
import os
import re
import threading
import unicodedata
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sentence_transformers import SentenceTransformer


# =====================================================
# CONFIGURAÇÃO
# =====================================================

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


# =====================================================
# MODELO IA SOB DEMANDA
# =====================================================

model = None
model_lock = threading.Lock()


def get_model():
    """
    Carrega o modelo apenas quando a primeira busca semântica for feita.
    Isso evita crash/restart no Railway durante o boot.
    """
    global model

    if model is None:
        with model_lock:
            if model is None:
                print("Carregando modelo de IA...")
                model = SentenceTransformer(MODEL_NAME)

    return model


# =====================================================
# UTILITÁRIOS
# =====================================================

STOP_WORDS = {
    "filme", "filmes", "serie", "series", "série", "séries",
    "com", "do", "da", "de", "dos", "das",
    "no", "na", "nos", "nas",
    "um", "uma", "uns", "umas",
    "o", "a", "os", "as",
    "e", "em", "sobre", "para", "por",
    "ator", "atriz", "diretor", "diretora", "dirigido", "dirigida",
    "quero", "assistir", "ver", "procurar", "buscar",
    "que", "tem", "onde", "quando", "tipo"
}

# Termos comuns de busca. Eles NÃO devem ser interpretados como nome de pessoa.
GENERIC_SEARCH_TERMS = {
    "acao", "aventura", "animacao", "anime", "comedia", "crime", "documentario",
    "drama", "familia", "fantasia", "historia", "terror", "horror", "musica",
    "misterio", "romance", "ficcao", "cientifica", "suspense", "thriller",
    "guerra", "faroeste", "carro", "carros", "corrida", "corridas", "velocidade",
    "piloto", "pilotos", "psicologico", "psicologica", "sombrio", "sombria",
    "assustador", "assustadora", "palhaco", "palhaço", "zumbi", "zumbis",
    "alien", "aliens", "espaco", "espaço", "vinganca", "vingança", "luta",
    "lutas", "amor", "amizade", "familia", "familía", "policial", "investigacao",
    "investigação", "medo", "monstro", "monstros", "sobrenatural"
}

# Mapa de intenção: ajuda a IA a entender linguagem humana em português.
# A busca final combina semântica + gênero + texto + popularidade.
INTENT_RULES = [
    {
        "keys": {"terror", "horror", "assustador", "assustadora", "medo", "sobrenatural", "monstro", "monstros"},
        "genres": {"terror", "thriller", "misterio"},
        "terms": {"terror", "horror", "medo", "assustador", "assustadora", "sobrenatural", "monstro", "monstros", "assombrado", "assombrada"}
    },
    {
        "keys": {"psicologico", "psicologica", "mente", "paranoia", "obsessao", "obsessão", "trauma"},
        "genres": {"thriller", "misterio", "drama", "terror"},
        "terms": {"psicologico", "psicológico", "psicologica", "psicológica", "mente", "paranoia", "obsessao", "obsessão", "trauma", "surto"}
    },
    {
        "keys": {"suspense", "thriller", "investigacao", "investigação", "misterio", "mistério"},
        "genres": {"thriller", "misterio", "crime"},
        "terms": {"suspense", "thriller", "investigacao", "investigação", "misterio", "mistério", "detetive", "crime", "assassinato"}
    },
    {
        "keys": {"carro", "carros", "corrida", "corridas", "velocidade", "piloto", "pilotos", "motorista"},
        "genres": {"acao", "aventura", "crime"},
        "terms": {"carro", "carros", "corrida", "corridas", "velocidade", "piloto", "pilotos", "motorista", "automovel", "automóvel", "veiculo", "veículo"}
    },
    {
        "keys": {"acao", "ação", "luta", "lutas", "tiro", "explosao", "explosão", "vinganca", "vingança"},
        "genres": {"acao", "aventura", "crime", "thriller"},
        "terms": {"acao", "ação", "luta", "lutas", "tiro", "explosao", "explosão", "vinganca", "vingança", "perseguicao", "perseguição"}
    },
    {
        "keys": {"espaco", "espaço", "alien", "aliens", "futuro", "robo", "robô", "robos", "robôs"},
        "genres": {"ficcao cientifica", "aventura", "acao"},
        "terms": {"espaco", "espaço", "alien", "aliens", "futuro", "robo", "robô", "robos", "robôs", "planeta", "galaxia", "galáxia"}
    },
    {
        "keys": {"romance", "amor", "casal", "namoro", "apaixonado", "apaixonada"},
        "genres": {"romance", "drama", "comedia"},
        "terms": {"romance", "amor", "casal", "namoro", "apaixonado", "apaixonada", "relacionamento"}
    },
    {
        "keys": {"engracado", "engraçado", "comedia", "comédia", "rir", "humor"},
        "genres": {"comedia"},
        "terms": {"engracado", "engraçado", "comedia", "comédia", "rir", "humor", "divertido", "divertida"}
    },
    {
        "keys": {"crianca", "criança", "criancas", "crianças", "familia", "família", "infantil"},
        "genres": {"familia", "animacao", "aventura", "fantasia"},
        "terms": {"crianca", "criança", "criancas", "crianças", "familia", "família", "infantil", "animação", "animacao"}
    },
    {
        "keys": {"guerra", "soldado", "soldados", "militar", "exercito", "exército"},
        "genres": {"guerra", "drama", "historia", "acao"},
        "terms": {"guerra", "soldado", "soldados", "militar", "exercito", "exército", "batalha"}
    },
]


def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s']", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize(text: str):
    normalized = normalize_text(text)
    return re.findall(r"[a-z0-9']+", normalized)


def meaningful_tokens(text: str):
    return [
        token
        for token in tokenize(text)
        if len(token) >= 3 and token not in STOP_WORDS
    ]


def build_query_profile(q: str):
    """
    Transforma a frase do usuário em sinais de busca.

    Exemplo:
    "terror psicológico" vira:
    - tokens: terror, psicologico
    - gêneros prováveis: Terror, Thriller, Mistério, Drama
    - termos expandidos: medo, paranoia, trauma, sobrenatural...
    """
    tokens = meaningful_tokens(q)
    token_set = set(tokens)

    inferred_genres = set()
    expanded_terms = set(tokens)

    for rule in INTENT_RULES:
        if token_set.intersection({normalize_text(k) for k in rule["keys"]}):
            inferred_genres.update({normalize_text(g) for g in rule["genres"]})
            expanded_terms.update({normalize_text(t) for t in rule["terms"]})

    # Para não virar uma busca gigante e lenta.
    expanded_terms = {term for term in expanded_terms if len(term) >= 3}

    return {
        "tokens": tokens,
        "expanded_terms": sorted(expanded_terms),
        "inferred_genres": sorted(inferred_genres),
    }


def make_like_patterns(values):
    cleaned = []

    for value in values:
        value = normalize_text(value)
        if value and len(value) >= 3:
            cleaned.append(f"%{value}%")

    return cleaned or ["%__never_match__%"]


def connect_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL não encontrada. Confira o arquivo .env ou as Variables do Railway.")

    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def embedding_to_pgvector(embedding):
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


def encode_text(text: str):
    embedding = get_model().encode(text, normalize_embeddings=True)
    return embedding_to_pgvector(embedding)


# =====================================================
# DETECÇÃO DE PESSOA
# =====================================================

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
        "ator", "atriz", "diretor", "diretora", "dirigido", "dirigida"
    ]

    for word in stop_words:
        text = re.sub(rf"\b{word}\b", " ", text, flags=re.IGNORECASE)

    text = re.sub(r"\s+", " ", text).strip()
    return text


def find_person_inside_query(cur, q: str):
    """
    Busca pessoa de forma inteligente e segura.

    Não aceita falso positivo dentro de palavra:
    - "terror psicológico" NÃO vira "Logic"
    - "carro" NÃO vira "Carroll"

    Aceita:
    - "adam sandler"
    - "adam sandler casa no campo"
    - "christopher nolan filme espacial"
    - "zendaya filme"
    - "sandler"
    """
    query_tokens = meaningful_tokens(q)

    if not query_tokens:
        return None

    # Se a busca for só tema/gênero, não tente achar pessoa.
    # Ex: "terror psicológico", "carro", "corrida", "palhaço".
    if all(token in GENERIC_SEARCH_TERMS for token in query_tokens):
        return None

    cur.execute(
        """
        WITH candidatos AS (
            SELECT
                p.id,
                p.nome,
                p.nome_original,
                p.profile_path,
                p.departamento_conhecido,
                p.popularidade_tmdb,
                array_remove(
                    regexp_split_to_array(
                        lower(unaccent(COALESCE(p.nome, ''))),
                        '[^a-z0-9]+'
                    ),
                    ''
                ) AS nome_tokens,
                array_remove(
                    regexp_split_to_array(
                        lower(unaccent(COALESCE(p.nome_original, ''))),
                        '[^a-z0-9]+'
                    ),
                    ''
                ) AS nome_original_tokens
            FROM pessoas p
            WHERE COALESCE(p.popularidade_tmdb, 0) >= 1
        )
        SELECT
            id,
            nome,
            nome_original,
            profile_path,
            departamento_conhecido,
            popularidade_tmdb,
            nome_tokens,
            nome_original_tokens
        FROM candidatos
        WHERE
            (
                array_length(nome_tokens, 1) >= 2
                AND nome_tokens <@ %s::text[]
            )
            OR
            (
                array_length(nome_original_tokens, 1) >= 2
                AND nome_original_tokens <@ %s::text[]
            )
            OR
            (
                array_length(nome_tokens, 1) = 1
                AND nome_tokens[1] = ANY(%s::text[])
                AND nome_tokens[1] <> ALL(%s::text[])
                AND COALESCE(popularidade_tmdb, 0) >= 5
            )
            OR
            (
                array_length(nome_original_tokens, 1) = 1
                AND nome_original_tokens[1] = ANY(%s::text[])
                AND nome_original_tokens[1] <> ALL(%s::text[])
                AND COALESCE(popularidade_tmdb, 0) >= 5
            )
        ORDER BY
            CASE
                WHEN array_length(nome_tokens, 1) >= 2 AND nome_tokens <@ %s::text[] THEN 4
                WHEN array_length(nome_original_tokens, 1) >= 2 AND nome_original_tokens <@ %s::text[] THEN 3
                ELSE 1
            END DESC,
            array_length(nome_tokens, 1) DESC,
            popularidade_tmdb DESC NULLS LAST
        LIMIT 1;
        """,
        (
            query_tokens,
            query_tokens,
            query_tokens,
            list(GENERIC_SEARCH_TERMS),
            query_tokens,
            list(GENERIC_SEARCH_TERMS),
            query_tokens,
            query_tokens,
        ),
    )

    person = cur.fetchone()

    if not person:
        return None

    # Remove campos auxiliares para não poluir o retorno.
    person.pop("nome_tokens", None)
    person.pop("nome_original_tokens", None)
    return person


# =====================================================
# BUSCA POR PESSOA
# =====================================================

def search_movies_by_person(cur, pessoa, q: str, limit: int):
    context = clean_context_from_person(q, pessoa["nome"])
    has_context = len(context) >= 3

    if has_context:
        try:
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
                        (1 - (f.embedding <=> %s::vector)) * 0.75
                        + (pf.role_score / 4.0) * 0.15
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

            return cur.fetchall(), context, "PERSON_HYBRID"

        except Exception as error:
            print("Erro na busca híbrida por pessoa. Usando popularidade:", error)

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

    return cur.fetchall(), context, "PERSON"


# =====================================================
# BUSCA GERAL INTELIGENTE
# =====================================================

def search_general_semantic(cur, q: str, vector: str, tipo: Optional[str], limit: int):
    profile = build_query_profile(q)

    expanded_terms = profile["expanded_terms"]
    inferred_genres = profile["inferred_genres"]

    patterns = make_like_patterns(expanded_terms)
    genre_norms = inferred_genres or ["__never_match__"]

    if tipo == "FILME":
        cur.execute(
            """
            WITH filmes_com_generos AS (
                SELECT
                    f.*,
                    COALESCE(string_agg(DISTINCT g.nome, ' '), '') AS generos_texto,
                    COALESCE(
                        array_agg(DISTINCT lower(unaccent(g.nome))) FILTER (WHERE g.nome IS NOT NULL),
                        ARRAY[]::text[]
                    ) AS generos_norm
                FROM filmes f
                LEFT JOIN filme_generos fg ON fg.filme_id = f.id
                LEFT JOIN generos g ON g.id = fg.genero_id
                GROUP BY f.id
            )
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
                    (1 - (embedding <=> %s::vector)) * 0.60
                    + CASE
                        WHEN lower(unaccent(COALESCE(titulo, ''))) LIKE ANY(%s::text[])
                          OR lower(unaccent(COALESCE(titulo_original, ''))) LIKE ANY(%s::text[])
                        THEN 0.25 ELSE 0 END
                    + CASE
                        WHEN lower(unaccent(COALESCE(sinopse, ''))) LIKE ANY(%s::text[])
                        THEN 0.15 ELSE 0 END
                    + CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM unnest(generos_norm) AS genero
                            WHERE genero = ANY(%s::text[])
                        )
                        THEN 0.30 ELSE 0 END
                    + LEAST(COALESCE(popularidade_tmdb, 0) / 100.0, 1.0) * 0.08
                    + LEAST(COALESCE(votos_tmdb, 0) / 5000.0, 1.0) * 0.05
                ) AS score
            FROM filmes_com_generos
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
                patterns,
                patterns,
                patterns,
                genre_norms,
                SEARCH_MIN_VOTES,
                SEARCH_MIN_POPULARITY,
                limit,
            ),
        )

    elif tipo == "SERIE":
        cur.execute(
            """
            WITH series_com_generos AS (
                SELECT
                    s.*,
                    COALESCE(string_agg(DISTINCT g.nome, ' '), '') AS generos_texto,
                    COALESCE(
                        array_agg(DISTINCT lower(unaccent(g.nome))) FILTER (WHERE g.nome IS NOT NULL),
                        ARRAY[]::text[]
                    ) AS generos_norm
                FROM series s
                LEFT JOIN serie_generos sg ON sg.serie_id = s.id
                LEFT JOIN generos g ON g.id = sg.genero_id
                GROUP BY s.id
            )
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
                    (1 - (embedding <=> %s::vector)) * 0.60
                    + CASE
                        WHEN lower(unaccent(COALESCE(titulo, ''))) LIKE ANY(%s::text[])
                          OR lower(unaccent(COALESCE(titulo_original, ''))) LIKE ANY(%s::text[])
                        THEN 0.25 ELSE 0 END
                    + CASE
                        WHEN lower(unaccent(COALESCE(sinopse, ''))) LIKE ANY(%s::text[])
                        THEN 0.15 ELSE 0 END
                    + CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM unnest(generos_norm) AS genero
                            WHERE genero = ANY(%s::text[])
                        )
                        THEN 0.30 ELSE 0 END
                    + LEAST(COALESCE(popularidade_tmdb, 0) / 100.0, 1.0) * 0.08
                    + LEAST(COALESCE(votos_tmdb, 0) / 5000.0, 1.0) * 0.05
                ) AS score
            FROM series_com_generos
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
                patterns,
                patterns,
                patterns,
                genre_norms,
                SEARCH_MIN_VOTES,
                SEARCH_MIN_POPULARITY,
                limit,
            ),
        )

    else:
        cur.execute(
            """
            WITH filmes_com_generos AS (
                SELECT
                    f.*,
                    COALESCE(string_agg(DISTINCT g.nome, ' '), '') AS generos_texto,
                    COALESCE(
                        array_agg(DISTINCT lower(unaccent(g.nome))) FILTER (WHERE g.nome IS NOT NULL),
                        ARRAY[]::text[]
                    ) AS generos_norm
                FROM filmes f
                LEFT JOIN filme_generos fg ON fg.filme_id = f.id
                LEFT JOIN generos g ON g.id = fg.genero_id
                GROUP BY f.id
            ),
            series_com_generos AS (
                SELECT
                    s.*,
                    COALESCE(string_agg(DISTINCT g.nome, ' '), '') AS generos_texto,
                    COALESCE(
                        array_agg(DISTINCT lower(unaccent(g.nome))) FILTER (WHERE g.nome IS NOT NULL),
                        ARRAY[]::text[]
                    ) AS generos_norm
                FROM series s
                LEFT JOIN serie_generos sg ON sg.serie_id = s.id
                LEFT JOIN generos g ON g.id = sg.genero_id
                GROUP BY s.id
            )
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
                        (1 - (embedding <=> %s::vector)) * 0.60
                        + CASE
                            WHEN lower(unaccent(COALESCE(titulo, ''))) LIKE ANY(%s::text[])
                              OR lower(unaccent(COALESCE(titulo_original, ''))) LIKE ANY(%s::text[])
                            THEN 0.25 ELSE 0 END
                        + CASE
                            WHEN lower(unaccent(COALESCE(sinopse, ''))) LIKE ANY(%s::text[])
                            THEN 0.15 ELSE 0 END
                        + CASE
                            WHEN EXISTS (
                                SELECT 1
                                FROM unnest(generos_norm) AS genero
                                WHERE genero = ANY(%s::text[])
                            )
                            THEN 0.30 ELSE 0 END
                        + LEAST(COALESCE(popularidade_tmdb, 0) / 100.0, 1.0) * 0.08
                        + LEAST(COALESCE(votos_tmdb, 0) / 5000.0, 1.0) * 0.05
                    ) AS score
                FROM filmes_com_generos
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
                        (1 - (embedding <=> %s::vector)) * 0.60
                        + CASE
                            WHEN lower(unaccent(COALESCE(titulo, ''))) LIKE ANY(%s::text[])
                              OR lower(unaccent(COALESCE(titulo_original, ''))) LIKE ANY(%s::text[])
                            THEN 0.25 ELSE 0 END
                        + CASE
                            WHEN lower(unaccent(COALESCE(sinopse, ''))) LIKE ANY(%s::text[])
                            THEN 0.15 ELSE 0 END
                        + CASE
                            WHEN EXISTS (
                                SELECT 1
                                FROM unnest(generos_norm) AS genero
                                WHERE genero = ANY(%s::text[])
                            )
                            THEN 0.30 ELSE 0 END
                        + LEAST(COALESCE(popularidade_tmdb, 0) / 100.0, 1.0) * 0.08
                        + LEAST(COALESCE(votos_tmdb, 0) / 5000.0, 1.0) * 0.05
                    ) AS score
                FROM series_com_generos
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
                patterns,
                patterns,
                patterns,
                genre_norms,
                SEARCH_MIN_VOTES,
                SEARCH_MIN_POPULARITY,
                vector,
                patterns,
                patterns,
                patterns,
                genre_norms,
                SEARCH_MIN_VOTES,
                SEARCH_MIN_POPULARITY,
                limit,
            ),
        )

    return cur.fetchall(), profile


def search_general_textual(cur, q: str, tipo: Optional[str], limit: int):
    profile = build_query_profile(q)

    expanded_terms = profile["expanded_terms"]
    inferred_genres = profile["inferred_genres"]

    patterns = make_like_patterns(expanded_terms)
    genre_norms = inferred_genres or ["__never_match__"]

    if tipo == "FILME":
        cur.execute(
            """
            WITH filmes_com_generos AS (
                SELECT
                    f.*,
                    COALESCE(string_agg(DISTINCT g.nome, ' '), '') AS generos_texto,
                    COALESCE(
                        array_agg(DISTINCT lower(unaccent(g.nome))) FILTER (WHERE g.nome IS NOT NULL),
                        ARRAY[]::text[]
                    ) AS generos_norm
                FROM filmes f
                LEFT JOIN filme_generos fg ON fg.filme_id = f.id
                LEFT JOIN generos g ON g.id = fg.genero_id
                GROUP BY f.id
            )
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
                    CASE
                        WHEN lower(unaccent(COALESCE(titulo, ''))) LIKE ANY(%s::text[])
                          OR lower(unaccent(COALESCE(titulo_original, ''))) LIKE ANY(%s::text[])
                        THEN 0.35 ELSE 0 END
                    + CASE
                        WHEN lower(unaccent(COALESCE(sinopse, ''))) LIKE ANY(%s::text[])
                        THEN 0.25 ELSE 0 END
                    + CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM unnest(generos_norm) AS genero
                            WHERE genero = ANY(%s::text[])
                        )
                        THEN 0.45 ELSE 0 END
                    + LEAST(COALESCE(popularidade_tmdb, 0) / 100.0, 1.0) * 0.08
                    + LEAST(COALESCE(votos_tmdb, 0) / 5000.0, 1.0) * 0.05
                ) AS score
            FROM filmes_com_generos
            WHERE
                lower(unaccent(COALESCE(titulo, ''))) LIKE ANY(%s::text[])
                OR lower(unaccent(COALESCE(titulo_original, ''))) LIKE ANY(%s::text[])
                OR lower(unaccent(COALESCE(sinopse, ''))) LIKE ANY(%s::text[])
                OR EXISTS (
                    SELECT 1
                    FROM unnest(generos_norm) AS genero
                    WHERE genero = ANY(%s::text[])
                )
            ORDER BY score DESC, popularidade_tmdb DESC NULLS LAST
            LIMIT %s;
            """,
            (
                patterns,
                patterns,
                patterns,
                genre_norms,
                patterns,
                patterns,
                patterns,
                genre_norms,
                limit,
            ),
        )

    elif tipo == "SERIE":
        cur.execute(
            """
            WITH series_com_generos AS (
                SELECT
                    s.*,
                    COALESCE(string_agg(DISTINCT g.nome, ' '), '') AS generos_texto,
                    COALESCE(
                        array_agg(DISTINCT lower(unaccent(g.nome))) FILTER (WHERE g.nome IS NOT NULL),
                        ARRAY[]::text[]
                    ) AS generos_norm
                FROM series s
                LEFT JOIN serie_generos sg ON sg.serie_id = s.id
                LEFT JOIN generos g ON g.id = sg.genero_id
                GROUP BY s.id
            )
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
                    CASE
                        WHEN lower(unaccent(COALESCE(titulo, ''))) LIKE ANY(%s::text[])
                          OR lower(unaccent(COALESCE(titulo_original, ''))) LIKE ANY(%s::text[])
                        THEN 0.35 ELSE 0 END
                    + CASE
                        WHEN lower(unaccent(COALESCE(sinopse, ''))) LIKE ANY(%s::text[])
                        THEN 0.25 ELSE 0 END
                    + CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM unnest(generos_norm) AS genero
                            WHERE genero = ANY(%s::text[])
                        )
                        THEN 0.45 ELSE 0 END
                    + LEAST(COALESCE(popularidade_tmdb, 0) / 100.0, 1.0) * 0.08
                    + LEAST(COALESCE(votos_tmdb, 0) / 5000.0, 1.0) * 0.05
                ) AS score
            FROM series_com_generos
            WHERE
                lower(unaccent(COALESCE(titulo, ''))) LIKE ANY(%s::text[])
                OR lower(unaccent(COALESCE(titulo_original, ''))) LIKE ANY(%s::text[])
                OR lower(unaccent(COALESCE(sinopse, ''))) LIKE ANY(%s::text[])
                OR EXISTS (
                    SELECT 1
                    FROM unnest(generos_norm) AS genero
                    WHERE genero = ANY(%s::text[])
                )
            ORDER BY score DESC, popularidade_tmdb DESC NULLS LAST
            LIMIT %s;
            """,
            (
                patterns,
                patterns,
                patterns,
                genre_norms,
                patterns,
                patterns,
                patterns,
                genre_norms,
                limit,
            ),
        )

    else:
        cur.execute(
            """
            WITH filmes_com_generos AS (
                SELECT
                    f.*,
                    COALESCE(string_agg(DISTINCT g.nome, ' '), '') AS generos_texto,
                    COALESCE(
                        array_agg(DISTINCT lower(unaccent(g.nome))) FILTER (WHERE g.nome IS NOT NULL),
                        ARRAY[]::text[]
                    ) AS generos_norm
                FROM filmes f
                LEFT JOIN filme_generos fg ON fg.filme_id = f.id
                LEFT JOIN generos g ON g.id = fg.genero_id
                GROUP BY f.id
            ),
            series_com_generos AS (
                SELECT
                    s.*,
                    COALESCE(string_agg(DISTINCT g.nome, ' '), '') AS generos_texto,
                    COALESCE(
                        array_agg(DISTINCT lower(unaccent(g.nome))) FILTER (WHERE g.nome IS NOT NULL),
                        ARRAY[]::text[]
                    ) AS generos_norm
                FROM series s
                LEFT JOIN serie_generos sg ON sg.serie_id = s.id
                LEFT JOIN generos g ON g.id = sg.genero_id
                GROUP BY s.id
            )
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
                        CASE
                            WHEN lower(unaccent(COALESCE(titulo, ''))) LIKE ANY(%s::text[])
                              OR lower(unaccent(COALESCE(titulo_original, ''))) LIKE ANY(%s::text[])
                            THEN 0.35 ELSE 0 END
                        + CASE
                            WHEN lower(unaccent(COALESCE(sinopse, ''))) LIKE ANY(%s::text[])
                            THEN 0.25 ELSE 0 END
                        + CASE
                            WHEN EXISTS (
                                SELECT 1
                                FROM unnest(generos_norm) AS genero
                                WHERE genero = ANY(%s::text[])
                            )
                            THEN 0.45 ELSE 0 END
                        + LEAST(COALESCE(popularidade_tmdb, 0) / 100.0, 1.0) * 0.08
                        + LEAST(COALESCE(votos_tmdb, 0) / 5000.0, 1.0) * 0.05
                    ) AS score
                FROM filmes_com_generos
                WHERE
                    lower(unaccent(COALESCE(titulo, ''))) LIKE ANY(%s::text[])
                    OR lower(unaccent(COALESCE(titulo_original, ''))) LIKE ANY(%s::text[])
                    OR lower(unaccent(COALESCE(sinopse, ''))) LIKE ANY(%s::text[])
                    OR EXISTS (
                        SELECT 1
                        FROM unnest(generos_norm) AS genero
                        WHERE genero = ANY(%s::text[])
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
                        CASE
                            WHEN lower(unaccent(COALESCE(titulo, ''))) LIKE ANY(%s::text[])
                              OR lower(unaccent(COALESCE(titulo_original, ''))) LIKE ANY(%s::text[])
                            THEN 0.35 ELSE 0 END
                        + CASE
                            WHEN lower(unaccent(COALESCE(sinopse, ''))) LIKE ANY(%s::text[])
                            THEN 0.25 ELSE 0 END
                        + CASE
                            WHEN EXISTS (
                                SELECT 1
                                FROM unnest(generos_norm) AS genero
                                WHERE genero = ANY(%s::text[])
                            )
                            THEN 0.45 ELSE 0 END
                        + LEAST(COALESCE(popularidade_tmdb, 0) / 100.0, 1.0) * 0.08
                        + LEAST(COALESCE(votos_tmdb, 0) / 5000.0, 1.0) * 0.05
                    ) AS score
                FROM series_com_generos
                WHERE
                    lower(unaccent(COALESCE(titulo, ''))) LIKE ANY(%s::text[])
                    OR lower(unaccent(COALESCE(titulo_original, ''))) LIKE ANY(%s::text[])
                    OR lower(unaccent(COALESCE(sinopse, ''))) LIKE ANY(%s::text[])
                    OR EXISTS (
                        SELECT 1
                        FROM unnest(generos_norm) AS genero
                        WHERE genero = ANY(%s::text[])
                    )
            ) resultados
            ORDER BY score DESC, popularidade_tmdb DESC NULLS LAST
            LIMIT %s;
            """,
            (
                patterns,
                patterns,
                patterns,
                genre_norms,
                patterns,
                patterns,
                patterns,
                genre_norms,
                patterns,
                patterns,
                patterns,
                genre_norms,
                patterns,
                patterns,
                patterns,
                genre_norms,
                limit,
            ),
        )

    return cur.fetchall(), profile


def search_general(cur, q: str, tipo: Optional[str], limit: int):
    """
    Busca inteligente:
    1. tenta IA semântica + regras de intenção;
    2. se a IA falhar ou ficar indisponível, usa busca textual/por gênero;
    3. não derruba a API.
    """
    try:
        vector = encode_text(q)
        results, profile = search_general_semantic(cur, q, vector, tipo, limit)

        if results:
            return results, profile, "AI_SMART"

    except Exception as error:
        print("Erro na busca semântica. Usando fallback inteligente:", error)

    results, profile = search_general_textual(cur, q, tipo, limit)

    return results, profile, "TEXT_SMART_FALLBACK"


# =====================================================
# ROTAS
# =====================================================

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
                results, context, person_mode = search_movies_by_person(cur, pessoa, q, limit)

                if results:
                    return {
                        "query": q,
                        "search_mode": person_mode,
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

            results, profile, mode = search_general(cur, q, tipo, limit)

            return {
                "query": q,
                "search_mode": mode,
                "matched_person": None,
                "profile": profile,
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
