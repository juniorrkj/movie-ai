import os
import re
import threading
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sentence_transformers import SentenceTransformer


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)


def env_int(name: str, default: int) -> int:
    value = os.getenv(name, str(default))

    try:
        return int(value)
    except ValueError:
        try:
            return int(float(value))
        except ValueError:
            return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name, str(default))

    try:
        return float(value)
    except ValueError:
        return default


DATABASE_URL = os.getenv("DATABASE_URL")
MODEL_NAME = os.getenv("MODEL_NAME", "paraphrase-multilingual-MiniLM-L12-v2")
PYTHON_AI_HOST = os.getenv("PYTHON_AI_HOST", "0.0.0.0")
PYTHON_AI_PORT = env_int("PYTHON_AI_PORT", 8000)

SEARCH_MIN_VOTES = env_int("SEARCH_MIN_VOTES", 20)
SEARCH_MIN_POPULARITY = env_float("SEARCH_MIN_POPULARITY", 1.0)

app = FastAPI(title="Movie AI Search API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

model = None
model_lock = threading.Lock()


def get_model():
    """
    Carrega o modelo apenas quando a primeira busca IA for feita.
    Isso evita crash/restart no Railway durante o boot.
    """
    global model

    if model is None:
        with model_lock:
            if model is None:
                print("Carregando modelo de IA...")
                model = SentenceTransformer(MODEL_NAME)

    return model


def connect_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL não encontrada. Confira o arquivo .env ou as Variables do Railway.")

    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def embedding_to_pgvector(embedding):
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


def encode_text(text: str):
    embedding = get_model().encode(text, normalize_embeddings=True)
    return embedding_to_pgvector(embedding)


def clean_context_from_person(query: str, person_name: str) -> str:
    text = query

    text = re.sub(re.escape(person_name), " ", text, flags=re.IGNORECASE)

    stop_words = [
        "filme", "filmes", "série", "series", "séries",
        "com", "do", "da", "de", "dos", "das",
        "no", "na", "nos", "nas",
        "um", "uma", "uns", "umas",
        "o", "a", "os", "as",
        "e", "em", "sobre", "para", "por",
        "ator", "atriz", "diretor", "dirigido", "dirigida"
    ]

    for word in stop_words:
        text = re.sub(rf"\b{word}\b", " ", text, flags=re.IGNORECASE)

    text = re.sub(r"\s+", " ", text).strip()
    return text


def find_person_inside_query(cur, q: str):
    cur.execute(
        """
        SELECT
            id,
            nome,
            nome_original,
            profile_path,
            departamento_conhecido,
            popularidade_tmdb
        FROM pessoas
        WHERE POSITION(LOWER(nome) IN LOWER(%s)) > 0
           OR LOWER(nome) = LOWER(%s)
           OR LOWER(nome) LIKE LOWER(%s)
        ORDER BY
            CASE
                WHEN LOWER(nome) = LOWER(%s) THEN 3
                WHEN POSITION(LOWER(nome) IN LOWER(%s)) > 0 THEN 2
                ELSE 1
            END DESC,
            LENGTH(nome) DESC,
            popularidade_tmdb DESC NULLS LAST
        LIMIT 1;
        """,
        (q, q, f"%{q}%", q, q),
    )

    return cur.fetchone()


def search_movies_by_person(cur, pessoa, q: str, limit: int):
    context = clean_context_from_person(q, pessoa["nome"])
    has_context = len(context) >= 3

    if has_context:
        context_vector = encode_text(context)

        cur.execute(
            """
            WITH pessoa_filmes AS (
                SELECT filme_id, MAX(role_score) AS role_score
                FROM (
                    SELECT
                        filme_id,
                        3.0 AS role_score
                    FROM elenco_filmes
                    WHERE pessoa_id = %s

                    UNION ALL

                    SELECT
                        filme_id,
                        CASE
                            WHEN POSITION('director' IN LOWER(COALESCE(funcao, ''))) > 0
                              OR POSITION('directing' IN LOWER(COALESCE(departamento, ''))) > 0
                            THEN 4.0
                            ELSE 2.0
                        END AS role_score
                    FROM equipe_filmes
                    WHERE pessoa_id = %s
                ) x
                GROUP BY filme_id
            )
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
                pf.role_score,
                el.personagens,
                eq.funcoes,
                (
                    (1 - (f.embedding <=> %s::vector)) * 0.80
                    + (pf.role_score / 4.0) * 0.10
                    + LEAST(COALESCE(f.popularidade_tmdb, 0) / 100.0, 1.0) * 0.10
                ) AS score
            FROM pessoa_filmes pf
            JOIN filmes f
                ON f.id = pf.filme_id
            LEFT JOIN LATERAL (
                SELECT string_agg(DISTINCT personagem, ', ') AS personagens
                FROM elenco_filmes
                WHERE filme_id = f.id
                  AND pessoa_id = %s
            ) el ON TRUE
            LEFT JOIN LATERAL (
                SELECT string_agg(DISTINCT funcao, ', ') AS funcoes
                FROM equipe_filmes
                WHERE filme_id = f.id
                  AND pessoa_id = %s
            ) eq ON TRUE
            WHERE f.embedding IS NOT NULL
            ORDER BY score DESC, f.popularidade_tmdb DESC NULLS LAST
            LIMIT %s;
            """,
            (
                pessoa["id"],
                pessoa["id"],
                context_vector,
                pessoa["id"],
                pessoa["id"],
                limit,
            ),
        )

    else:
        cur.execute(
            """
            WITH pessoa_filmes AS (
                SELECT filme_id, MAX(role_score) AS role_score
                FROM (
                    SELECT
                        filme_id,
                        3.0 AS role_score
                    FROM elenco_filmes
                    WHERE pessoa_id = %s

                    UNION ALL

                    SELECT
                        filme_id,
                        CASE
                            WHEN POSITION('director' IN LOWER(COALESCE(funcao, ''))) > 0
                              OR POSITION('directing' IN LOWER(COALESCE(departamento, ''))) > 0
                            THEN 4.0
                            ELSE 2.0
                        END AS role_score
                    FROM equipe_filmes
                    WHERE pessoa_id = %s
                ) x
                GROUP BY filme_id
            )
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
                pf.role_score,
                el.personagens,
                eq.funcoes,
                1.0 AS score
            FROM pessoa_filmes pf
            JOIN filmes f
                ON f.id = pf.filme_id
            LEFT JOIN LATERAL (
                SELECT string_agg(DISTINCT personagem, ', ') AS personagens
                FROM elenco_filmes
                WHERE filme_id = f.id
                  AND pessoa_id = %s
            ) el ON TRUE
            LEFT JOIN LATERAL (
                SELECT string_agg(DISTINCT funcao, ', ') AS funcoes
                FROM equipe_filmes
                WHERE filme_id = f.id
                  AND pessoa_id = %s
            ) eq ON TRUE
            ORDER BY
                pf.role_score DESC,
                f.popularidade_tmdb DESC NULLS LAST,
                f.votos_tmdb DESC NULLS LAST
            LIMIT %s;
            """,
            (
                pessoa["id"],
                pessoa["id"],
                pessoa["id"],
                pessoa["id"],
                limit,
            ),
        )

    return cur.fetchall(), context


def search_ai(cur, q: str, vector: str, tipo: Optional[str], limit: int):
    title_pattern = f"%{q}%"

    if tipo == "FILME":
        cur.execute(
            """
            SELECT
                'FILME' AS tipo,
                id,
                tmdb_id,
                titulo,
                titulo_original,
                sinopse,
                ano_lancamento,
                nota_tmdb,
                votos_tmdb,
                popularidade_tmdb,
                poster_path,
                (
                    (1 - (embedding <=> %s::vector))
                    + CASE
                        WHEN titulo ILIKE %s OR titulo_original ILIKE %s THEN 0.25
                        ELSE 0
                      END
                    + LEAST(COALESCE(popularidade_tmdb, 0) / 100.0, 1.0) * 0.05
                ) AS score
            FROM filmes
            WHERE embedding IS NOT NULL
              AND (
                    COALESCE(votos_tmdb, 0) >= %s
                    OR COALESCE(popularidade_tmdb, 0) >= %s
                  )
            ORDER BY score DESC, popularidade_tmdb DESC NULLS LAST
            LIMIT %s;
            """,
            (
                vector,
                title_pattern,
                title_pattern,
                SEARCH_MIN_VOTES,
                SEARCH_MIN_POPULARITY,
                limit,
            ),
        )

    elif tipo == "SERIE":
        cur.execute(
            """
            SELECT
                'SERIE' AS tipo,
                id,
                tmdb_id,
                titulo,
                titulo_original,
                sinopse,
                ano_lancamento,
                nota_tmdb,
                votos_tmdb,
                popularidade_tmdb,
                poster_path,
                (
                    (1 - (embedding <=> %s::vector))
                    + CASE
                        WHEN titulo ILIKE %s OR titulo_original ILIKE %s THEN 0.25
                        ELSE 0
                      END
                    + LEAST(COALESCE(popularidade_tmdb, 0) / 100.0, 1.0) * 0.05
                ) AS score
            FROM series
            WHERE embedding IS NOT NULL
              AND (
                    COALESCE(votos_tmdb, 0) >= %s
                    OR COALESCE(popularidade_tmdb, 0) >= %s
                  )
            ORDER BY score DESC, popularidade_tmdb DESC NULLS LAST
            LIMIT %s;
            """,
            (
                vector,
                title_pattern,
                title_pattern,
                SEARCH_MIN_VOTES,
                SEARCH_MIN_POPULARITY,
                limit,
            ),
        )

    else:
        cur.execute(
            """
            SELECT *
            FROM (
                SELECT
                    'FILME' AS tipo,
                    id,
                    tmdb_id,
                    titulo,
                    titulo_original,
                    sinopse,
                    ano_lancamento,
                    nota_tmdb,
                    votos_tmdb,
                    popularidade_tmdb,
                    poster_path,
                    (
                        (1 - (embedding <=> %s::vector))
                        + CASE
                            WHEN titulo ILIKE %s OR titulo_original ILIKE %s THEN 0.25
                            ELSE 0
                          END
                        + LEAST(COALESCE(popularidade_tmdb, 0) / 100.0, 1.0) * 0.05
                    ) AS score
                FROM filmes
                WHERE embedding IS NOT NULL
                  AND (
                        COALESCE(votos_tmdb, 0) >= %s
                        OR COALESCE(popularidade_tmdb, 0) >= %s
                      )

                UNION ALL

                SELECT
                    'SERIE' AS tipo,
                    id,
                    tmdb_id,
                    titulo,
                    titulo_original,
                    sinopse,
                    ano_lancamento,
                    nota_tmdb,
                    votos_tmdb,
                    popularidade_tmdb,
                    poster_path,
                    (
                        (1 - (embedding <=> %s::vector))
                        + CASE
                            WHEN titulo ILIKE %s OR titulo_original ILIKE %s THEN 0.25
                            ELSE 0
                          END
                        + LEAST(COALESCE(popularidade_tmdb, 0) / 100.0, 1.0) * 0.05
                    ) AS score
                FROM series
                WHERE embedding IS NOT NULL
                  AND (
                        COALESCE(votos_tmdb, 0) >= %s
                        OR COALESCE(popularidade_tmdb, 0) >= %s
                      )
            ) resultados
            ORDER BY score DESC, popularidade_tmdb DESC NULLS LAST
            LIMIT %s;
            """,
            (
                vector,
                title_pattern,
                title_pattern,
                SEARCH_MIN_VOTES,
                SEARCH_MIN_POPULARITY,
                vector,
                title_pattern,
                title_pattern,
                SEARCH_MIN_VOTES,
                SEARCH_MIN_POPULARITY,
                limit,
            ),
        )

    return cur.fetchall()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "database_url_configured": bool(DATABASE_URL),
        "model_loaded": model is not None,
        "search_min_votes": SEARCH_MIN_VOTES,
        "search_min_popularity": SEARCH_MIN_POPULARITY,
    }


@app.get("/search")
def search(
    q: str = Query(..., min_length=1),
    limit: int = Query(12, ge=1, le=50),
    tipo: Optional[str] = Query(None),
):
    tipo = tipo.upper() if tipo else None

    conn = connect_db()

    try:
        with conn.cursor() as cur:
            pessoa = find_person_inside_query(cur, q)

            if pessoa:
                results, context = search_movies_by_person(cur, pessoa, q, limit)

                if results:
                    return {
                        "query": q,
                        "search_mode": "PERSON_HYBRID" if context else "PERSON",
                        "matched_person": {
                            "id": pessoa["id"],
                            "nome": pessoa["nome"],
                            "profile_path": pessoa["profile_path"],
                            "departamento_conhecido": pessoa["departamento_conhecido"],
                        },
                        "context": context,
                        "count": len(results),
                        "results": results,
                    }

            vector = encode_text(q)
            results = search_ai(cur, q, vector, tipo, limit)

            return {
                "query": q,
                "search_mode": "AI",
                "matched_person": None,
                "count": len(results),
                "results": results,
            }

    finally:
        conn.close()


@app.get("/person/{person_id}")
def person_detail(person_id: int):
    conn = connect_db()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    tmdb_id,
                    imdb_id,
                    nome,
                    nome_original,
                    genero_tmdb,
                    nascimento,
                    falecimento,
                    local_nascimento,
                    biografia,
                    departamento_conhecido,
                    popularidade_tmdb,
                    profile_path
                FROM pessoas
                WHERE id = %s;
                """,
                (person_id,),
            )

            person = cur.fetchone()

            if not person:
                raise HTTPException(status_code=404, detail="Pessoa não encontrada.")

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
                    ef.personagem,
                    ef.ordem_credito
                FROM elenco_filmes ef
                JOIN filmes f
                    ON f.id = ef.filme_id
                WHERE ef.pessoa_id = %s
                ORDER BY f.popularidade_tmdb DESC NULLS LAST, f.ano_lancamento DESC NULLS LAST
                LIMIT 50;
                """,
                (person_id,),
            )

            acting = cur.fetchall()

            cur.execute(
                """
                SELECT DISTINCT ON (f.id)
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
                    et.departamento,
                    et.funcao
                FROM equipe_filmes et
                JOIN filmes f
                    ON f.id = et.filme_id
                WHERE et.pessoa_id = %s
                ORDER BY f.id, f.popularidade_tmdb DESC NULLS LAST;
                """,
                (person_id,),
            )

            crew = cur.fetchall()

            return {
                "person": person,
                "acting": acting,
                "crew": crew,
            }

    finally:
        conn.close()


@app.get("/movie/{movie_id}")
def movie_detail(movie_id: int):
    conn = connect_db()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    'FILME' AS tipo,
                    id,
                    tmdb_id,
                    imdb_id,
                    titulo,
                    titulo_original,
                    sinopse,
                    tagline,
                    idioma_original,
                    status,
                    data_lancamento,
                    ano_lancamento,
                    duracao_min,
                    orcamento,
                    receita,
                    popularidade_tmdb,
                    nota_tmdb,
                    votos_tmdb,
                    poster_path,
                    backdrop_path,
                    adulto
                FROM filmes
                WHERE id = %s;
                """,
                (movie_id,),
            )

            movie = cur.fetchone()

            if not movie:
                raise HTTPException(status_code=404, detail="Filme não encontrado.")

            cur.execute(
                """
                SELECT g.id, g.nome, g.slug
                FROM filme_generos fg
                JOIN generos g
                    ON g.id = fg.genero_id
                WHERE fg.filme_id = %s
                ORDER BY g.nome;
                """,
                (movie_id,),
            )

            genres = cur.fetchall()

            cur.execute(
                """
                SELECT
                    p.id,
                    p.nome,
                    p.profile_path,
                    ef.personagem,
                    ef.ordem_credito
                FROM elenco_filmes ef
                JOIN pessoas p
                    ON p.id = ef.pessoa_id
                WHERE ef.filme_id = %s
                ORDER BY ef.ordem_credito ASC NULLS LAST
                LIMIT 30;
                """,
                (movie_id,),
            )

            cast = cur.fetchall()

            cur.execute(
                """
                SELECT
                    p.id,
                    p.nome,
                    p.profile_path,
                    et.departamento,
                    et.funcao
                FROM equipe_filmes et
                JOIN pessoas p
                    ON p.id = et.pessoa_id
                WHERE et.filme_id = %s
                  AND (
                        POSITION('director' IN LOWER(COALESCE(et.funcao, ''))) > 0
                        OR POSITION('writer' IN LOWER(COALESCE(et.funcao, ''))) > 0
                        OR POSITION('screenplay' IN LOWER(COALESCE(et.funcao, ''))) > 0
                        OR LOWER(COALESCE(et.departamento, '')) IN ('directing', 'writing')
                      )
                ORDER BY
                    CASE
                        WHEN POSITION('director' IN LOWER(COALESCE(et.funcao, ''))) > 0 THEN 1
                        WHEN LOWER(COALESCE(et.departamento, '')) = 'directing' THEN 2
                        WHEN POSITION('writer' IN LOWER(COALESCE(et.funcao, ''))) > 0 THEN 3
                        ELSE 4
                    END,
                    p.nome
                LIMIT 30;
                """,
                (movie_id,),
            )

            crew = cur.fetchall()

            cur.execute(
                """
                SELECT ep.id, ep.nome, ep.pais_origem, ep.logo_path
                FROM filme_empresas fe
                JOIN empresas_producao ep
                    ON ep.id = fe.empresa_id
                WHERE fe.filme_id = %s
                ORDER BY ep.nome;
                """,
                (movie_id,),
            )

            companies = cur.fetchall()

            return {
                "movie": movie,
                "genres": genres,
                "cast": cast,
                "crew": crew,
                "companies": companies,
            }

    finally:
        conn.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=PYTHON_AI_HOST,
        port=PYTHON_AI_PORT,
        reload=False,
    )