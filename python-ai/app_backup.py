import os
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sentence_transformers import SentenceTransformer

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")
MODEL_NAME = os.getenv("MODEL_NAME", "paraphrase-multilingual-MiniLM-L12-v2")
PYTHON_AI_HOST = os.getenv("PYTHON_AI_HOST", "0.0.0.0")
PYTHON_AI_PORT = int(os.getenv("PYTHON_AI_PORT", "8000"))

app = FastAPI(title="Movie AI Search API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print("Carregando modelo de IA...")
model = SentenceTransformer(MODEL_NAME)


def connect_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL não encontrada. Confira o arquivo .env na raiz do projeto.")
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def embedding_to_pgvector(embedding):
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/search")
def search(
    q: str = Query(..., min_length=1),
    limit: int = Query(12, ge=1, le=50),
    tipo: Optional[str] = Query(None),
):
    query_embedding = model.encode(q, normalize_embeddings=True)
    vector = embedding_to_pgvector(query_embedding)
    tipo = tipo.upper() if tipo else None

    conn = connect_db()

    try:
        with conn.cursor() as cur:

            # =====================================
            # BUSCA POR PESSOA (ATOR / DIRETOR)
            # =====================================

            cur.execute(
                """
                SELECT id, nome
                FROM pessoas
                WHERE LOWER(nome) LIKE LOWER(%s)
                ORDER BY popularidade_tmdb DESC NULLS LAST
                LIMIT 1
                """,
                (f"%{q}%",)
            )

            pessoa = cur.fetchone()

            if pessoa:
                cur.execute(
                    """
                    SELECT
                        'FILME' AS tipo,
                        f.id,
                        f.tmdb_id,
                        f.titulo,
                        f.titulo_original,
                        f.sinopse,
                        f.ano_lancamento,
                        f.nota_tmdb,
                        f.votos_tmdb,
                        f.popularidade_tmdb,
                        f.poster_path,
                        1.0 AS score
                    FROM filmes f
                    INNER JOIN elenco_filmes ef
                        ON ef.filme_id = f.id
                    WHERE ef.pessoa_id = %s
                    ORDER BY f.popularidade_tmdb DESC NULLS LAST
                    LIMIT %s
                    """,
                    (pessoa["id"], limit)
                )

                filmes = cur.fetchall()

                if filmes:
                    return {
                        "query": q,
                        "tipo": "PESSOA",
                        "pessoa": pessoa["nome"],
                        "count": len(filmes),
                        "results": filmes
                    }

            # =====================================
            # BUSCA VETORIAL (IA)
            # =====================================

            if tipo == "FILME":
                cur.execute(
                    """
                    SELECT
                        'FILME' AS tipo,
                        id, tmdb_id, titulo, titulo_original, sinopse,
                        ano_lancamento, nota_tmdb, votos_tmdb,
                        popularidade_tmdb, poster_path,
                        1 - (embedding <=> %s::vector) AS score
                    FROM filmes
                    WHERE embedding IS NOT NULL
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s;
                    """,
                    (vector, vector, limit),
                )

            elif tipo == "SERIE":
                cur.execute(
                    """
                    SELECT
                        'SERIE' AS tipo,
                        id, tmdb_id, titulo, titulo_original, sinopse,
                        ano_lancamento, nota_tmdb, votos_tmdb,
                        popularidade_tmdb, poster_path,
                        1 - (embedding <=> %s::vector) AS score
                    FROM series
                    WHERE embedding IS NOT NULL
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s;
                    """,
                    (vector, vector, limit),
                )

            else:
                cur.execute(
                    """
                    SELECT *
                    FROM (
                        SELECT
                            'FILME' AS tipo,
                            id, tmdb_id, titulo, titulo_original, sinopse,
                            ano_lancamento, nota_tmdb, votos_tmdb,
                            popularidade_tmdb, poster_path,
                            1 - (embedding <=> %s::vector) AS score
                        FROM filmes
                        WHERE embedding IS NOT NULL

                        UNION ALL

                        SELECT
                            'SERIE' AS tipo,
                            id, tmdb_id, titulo, titulo_original, sinopse,
                            ano_lancamento, nota_tmdb, votos_tmdb,
                            popularidade_tmdb, poster_path,
                            1 - (embedding <=> %s::vector) AS score
                        FROM series
                        WHERE embedding IS NOT NULL
                    ) resultados
                    ORDER BY score DESC
                    LIMIT %s;
                    """,
                    (vector, vector, limit),
                )

            results = cur.fetchall()

            return {
                "query": q,
                "count": len(results),
                "results": results
            }

    finally:
        conn.close()