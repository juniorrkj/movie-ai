import os
import time
import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, Optional

import requests
import psycopg2
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(BASE_DIR, ".env"))

TMDB_API_KEY = os.getenv("TMDB_API_KEY")
TMDB_LANGUAGE = os.getenv("TMDB_LANGUAGE", "pt-BR")
TMDB_REGION = os.getenv("TMDB_REGION", "BR")
TMDB_SLEEP = float(os.getenv("TMDB_SLEEP", "0.20"))

YEAR_START = int(os.getenv("TMDB_YEAR_START", "1900"))
YEAR_END = int(os.getenv("TMDB_YEAR_END", str(datetime.now().year)))
TMDB_MAX_PAGES = int(os.getenv("TMDB_MAX_PAGES", "5"))
TMDB_MIN_VOTE_COUNT = int(os.getenv("TMDB_MIN_VOTE_COUNT", "1"))

IMPORT_MOVIES = os.getenv("IMPORT_MOVIES", "true").lower() == "true"
IMPORT_SERIES = os.getenv("IMPORT_SERIES", "false").lower() == "true"

MODEL_NAME = os.getenv("MODEL_NAME", "paraphrase-multilingual-MiniLM-L12-v2")
TMDB_BASE_URL = "https://api.themoviedb.org/3"


def connect_db():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL não encontrada no .env")
    return psycopg2.connect(database_url)


def clean_text(value):
    if value is None:
        return None
    value = str(value).strip()
    return value if value else None


def clean_date(value):
    if not value:
        return None
    value = str(value).strip()
    return value if value else None


def year_from_date(value):
    if not value:
        return None
    try:
        return int(value[:4])
    except Exception:
        return None


def slugify(text):
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:120] or "sem-genero"


def embedding_to_pgvector(embedding):
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


def tmdb_get(session: requests.Session, path: str, params: Optional[Dict[str, Any]] = None):
    if not TMDB_API_KEY or TMDB_API_KEY == "COLOQUE_SUA_CHAVE_AQUI":
        raise RuntimeError("Coloque sua TMDB_API_KEY correta no arquivo .env")

    params = params or {}
    params["api_key"] = TMDB_API_KEY
    url = f"{TMDB_BASE_URL}{path}"

    for attempt in range(6):
        response = session.get(url, params=params, timeout=30)

        if response.status_code == 200:
            time.sleep(TMDB_SLEEP)
            return response.json()

        if response.status_code == 429:
            wait = int(response.headers.get("Retry-After", "5"))
            print(f"[RATE LIMIT] Aguardando {wait}s...")
            time.sleep(wait)
            continue

        if response.status_code in [500, 502, 503, 504]:
            wait = 3 * (attempt + 1)
            print(f"[ERRO TMDB {response.status_code}] Tentando em {wait}s...")
            time.sleep(wait)
            continue

        raise RuntimeError(f"Erro TMDB {response.status_code}: {response.text}")

    raise RuntimeError(f"Falha após várias tentativas: {url}")


def upsert_genre(conn, genre):
    nome = clean_text(genre.get("name")) or f"Gênero {genre.get('id')}"
    slug = slugify(nome)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO generos (tmdb_id, nome, slug)
            VALUES (%s, %s, %s)
            ON CONFLICT (tmdb_id)
            DO UPDATE SET nome = EXCLUDED.nome, slug = EXCLUDED.slug
            RETURNING id;
            """,
            (genre.get("id"), nome, slug),
        )
        return cur.fetchone()[0]


def upsert_person(conn, person):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pessoas (
                tmdb_id, nome, nome_original, genero_tmdb,
                departamento_conhecido, popularidade_tmdb, profile_path
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tmdb_id)
            DO UPDATE SET
                nome = EXCLUDED.nome,
                nome_original = EXCLUDED.nome_original,
                genero_tmdb = EXCLUDED.genero_tmdb,
                departamento_conhecido = EXCLUDED.departamento_conhecido,
                popularidade_tmdb = EXCLUDED.popularidade_tmdb,
                profile_path = EXCLUDED.profile_path,
                updated_at = NOW()
            RETURNING id;
            """,
            (
                person.get("id"),
                clean_text(person.get("name")) or "Sem nome",
                clean_text(person.get("original_name")),
                person.get("gender"),
                clean_text(person.get("known_for_department")),
                person.get("popularity"),
                person.get("profile_path"),
            ),
        )
        return cur.fetchone()[0]


def make_embedding_text(title, original_title, overview, genres, year):
    genre_names = ", ".join([g.get("name", "") for g in genres or []])
    return "\n".join(
        [
            f"Título: {title or ''}",
            f"Título original: {original_title or ''}",
            f"Ano: {year or ''}",
            f"Gêneros: {genre_names}",
            f"Sinopse: {overview or ''}",
        ]
    )


def save_production_companies(conn, content_id, companies, content_type):
    if content_type not in ["filme", "serie"]:
        return

    link_table = "filme_empresas" if content_type == "filme" else "serie_empresas"
    id_column = "filme_id" if content_type == "filme" else "serie_id"

    for company in companies or []:
        name = clean_text(company.get("name"))
        if not name:
            continue

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO empresas_producao (tmdb_id, nome, pais_origem, logo_path)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (tmdb_id)
                DO UPDATE SET
                    nome = EXCLUDED.nome,
                    pais_origem = EXCLUDED.pais_origem,
                    logo_path = EXCLUDED.logo_path,
                    updated_at = NOW()
                RETURNING id;
                """,
                (company.get("id"), name, clean_text(company.get("origin_country")), company.get("logo_path")),
            )
            company_id = cur.fetchone()[0]
            cur.execute(
                f"INSERT INTO {link_table} ({id_column}, empresa_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
                (content_id, company_id),
            )


def save_translations(conn, content_id, translations, content_type):
    if content_type not in ["filme", "serie"]:
        return

    table = "traducoes_filmes" if content_type == "filme" else "traducoes_series"
    id_column = "filme_id" if content_type == "filme" else "serie_id"

    for item in (translations or {}).get("translations", []) or []:
        iso_639_1 = item.get("iso_639_1")
        iso_3166_1 = item.get("iso_3166_1")
        data = item.get("data") or {}
        if not iso_639_1:
            continue

        idioma = f"{iso_639_1}-{iso_3166_1}" if iso_3166_1 else iso_639_1

        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {table} ({id_column}, idioma, titulo, sinopse, tagline)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT ({id_column}, idioma)
                DO UPDATE SET
                    titulo = EXCLUDED.titulo,
                    sinopse = EXCLUDED.sinopse,
                    tagline = EXCLUDED.tagline,
                    updated_at = NOW();
                """,
                (
                    content_id,
                    idioma,
                    clean_text(data.get("title") or data.get("name")),
                    clean_text(data.get("overview")),
                    clean_text(data.get("tagline")),
                ),
            )


def upsert_movie(conn, movie, model):
    external_ids = movie.get("external_ids") or {}
    release_date = clean_date(movie.get("release_date"))
    year = year_from_date(release_date)

    text_for_embedding = make_embedding_text(
        movie.get("title"),
        movie.get("original_title"),
        movie.get("overview"),
        movie.get("genres"),
        year,
    )
    embedding = model.encode(text_for_embedding, normalize_embeddings=True)
    embedding_vector = embedding_to_pgvector(embedding)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO filmes (
                tmdb_id, imdb_id,
                titulo, titulo_original, sinopse, tagline,
                idioma_original, status,
                data_lancamento, ano_lancamento,
                duracao_min, orcamento, receita,
                popularidade_tmdb, nota_tmdb, votos_tmdb,
                poster_path, backdrop_path, adulto,
                embedding
            )
            VALUES (
                %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s::vector
            )
            ON CONFLICT (tmdb_id)
            DO UPDATE SET
                imdb_id = EXCLUDED.imdb_id,
                titulo = EXCLUDED.titulo,
                titulo_original = EXCLUDED.titulo_original,
                sinopse = EXCLUDED.sinopse,
                tagline = EXCLUDED.tagline,
                idioma_original = EXCLUDED.idioma_original,
                status = EXCLUDED.status,
                data_lancamento = EXCLUDED.data_lancamento,
                ano_lancamento = EXCLUDED.ano_lancamento,
                duracao_min = EXCLUDED.duracao_min,
                orcamento = EXCLUDED.orcamento,
                receita = EXCLUDED.receita,
                popularidade_tmdb = EXCLUDED.popularidade_tmdb,
                nota_tmdb = EXCLUDED.nota_tmdb,
                votos_tmdb = EXCLUDED.votos_tmdb,
                poster_path = EXCLUDED.poster_path,
                backdrop_path = EXCLUDED.backdrop_path,
                adulto = EXCLUDED.adulto,
                embedding = EXCLUDED.embedding,
                updated_at = NOW()
            RETURNING id;
            """,
            (
                movie.get("id"),
                external_ids.get("imdb_id") or movie.get("imdb_id"),
                clean_text(movie.get("title")),
                clean_text(movie.get("original_title")),
                clean_text(movie.get("overview")),
                clean_text(movie.get("tagline")),
                clean_text(movie.get("original_language")),
                clean_text(movie.get("status")),
                release_date,
                year,
                movie.get("runtime"),
                movie.get("budget"),
                movie.get("revenue"),
                movie.get("popularity"),
                movie.get("vote_average"),
                movie.get("vote_count"),
                movie.get("poster_path"),
                movie.get("backdrop_path"),
                bool(movie.get("adult", False)),
                embedding_vector,
            ),
        )
        filme_id = cur.fetchone()[0]

    for genre in movie.get("genres") or []:
        genero_id = upsert_genre(conn, genre)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO filme_generos (filme_id, genero_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
                (filme_id, genero_id),
            )

    credits = movie.get("credits") or {}

    for cast in credits.get("cast") or []:
        pessoa_id = upsert_person(conn, cast)
        if cast.get("credit_id"):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO elenco_filmes (filme_id, pessoa_id, personagem, ordem_credito, credit_id_tmdb)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (credit_id_tmdb)
                    DO UPDATE SET personagem = EXCLUDED.personagem, ordem_credito = EXCLUDED.ordem_credito;
                    """,
                    (filme_id, pessoa_id, clean_text(cast.get("character")), cast.get("order"), cast.get("credit_id")),
                )

    for crew in credits.get("crew") or []:
        pessoa_id = upsert_person(conn, crew)
        if crew.get("credit_id"):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO equipe_filmes (filme_id, pessoa_id, departamento, funcao, credit_id_tmdb)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (credit_id_tmdb)
                    DO UPDATE SET departamento = EXCLUDED.departamento, funcao = EXCLUDED.funcao;
                    """,
                    (filme_id, pessoa_id, clean_text(crew.get("department")), clean_text(crew.get("job")), crew.get("credit_id")),
                )

    save_production_companies(conn, filme_id, movie.get("production_companies") or [], "filme")
    save_translations(conn, filme_id, movie.get("translations") or {}, "filme")


def upsert_series(conn, tv, model):
    external_ids = tv.get("external_ids") or {}
    first_air_date = clean_date(tv.get("first_air_date"))
    last_air_date = clean_date(tv.get("last_air_date"))
    year = year_from_date(first_air_date)
    origin_country = tv.get("origin_country") or []
    pais_origem = ",".join(origin_country) if origin_country else None

    text_for_embedding = make_embedding_text(tv.get("name"), tv.get("original_name"), tv.get("overview"), tv.get("genres"), year)
    embedding = model.encode(text_for_embedding, normalize_embeddings=True)
    embedding_vector = embedding_to_pgvector(embedding)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO series (
                tmdb_id, imdb_id,
                titulo, titulo_original, sinopse, tagline,
                idioma_original, pais_origem, status,
                data_primeiro_ep, data_ultimo_ep, ano_lancamento,
                numero_temporadas, numero_episodios, em_producao, tipo_serie,
                popularidade_tmdb, nota_tmdb, votos_tmdb,
                poster_path, backdrop_path,
                embedding
            )
            VALUES (
                %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s::vector
            )
            ON CONFLICT (tmdb_id)
            DO UPDATE SET
                imdb_id = EXCLUDED.imdb_id,
                titulo = EXCLUDED.titulo,
                titulo_original = EXCLUDED.titulo_original,
                sinopse = EXCLUDED.sinopse,
                tagline = EXCLUDED.tagline,
                idioma_original = EXCLUDED.idioma_original,
                pais_origem = EXCLUDED.pais_origem,
                status = EXCLUDED.status,
                data_primeiro_ep = EXCLUDED.data_primeiro_ep,
                data_ultimo_ep = EXCLUDED.data_ultimo_ep,
                ano_lancamento = EXCLUDED.ano_lancamento,
                numero_temporadas = EXCLUDED.numero_temporadas,
                numero_episodios = EXCLUDED.numero_episodios,
                em_producao = EXCLUDED.em_producao,
                tipo_serie = EXCLUDED.tipo_serie,
                popularidade_tmdb = EXCLUDED.popularidade_tmdb,
                nota_tmdb = EXCLUDED.nota_tmdb,
                votos_tmdb = EXCLUDED.votos_tmdb,
                poster_path = EXCLUDED.poster_path,
                backdrop_path = EXCLUDED.backdrop_path,
                embedding = EXCLUDED.embedding,
                updated_at = NOW()
            RETURNING id;
            """,
            (
                tv.get("id"),
                external_ids.get("imdb_id"),
                clean_text(tv.get("name")),
                clean_text(tv.get("original_name")),
                clean_text(tv.get("overview")),
                clean_text(tv.get("tagline")),
                clean_text(tv.get("original_language")),
                pais_origem,
                clean_text(tv.get("status")),
                first_air_date,
                last_air_date,
                year,
                tv.get("number_of_seasons"),
                tv.get("number_of_episodes"),
                tv.get("in_production"),
                clean_text(tv.get("type")),
                tv.get("popularity"),
                tv.get("vote_average"),
                tv.get("vote_count"),
                tv.get("poster_path"),
                tv.get("backdrop_path"),
                embedding_vector,
            ),
        )
        serie_id = cur.fetchone()[0]

    for genre in tv.get("genres") or []:
        genero_id = upsert_genre(conn, genre)
        with conn.cursor() as cur:
            cur.execute("INSERT INTO serie_generos (serie_id, genero_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;", (serie_id, genero_id))

    credits = tv.get("credits") or {}

    for cast in credits.get("cast") or []:
        pessoa_id = upsert_person(conn, cast)
        if cast.get("credit_id"):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO elenco_series (serie_id, pessoa_id, personagem, ordem_credito, credit_id_tmdb)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (credit_id_tmdb)
                    DO UPDATE SET personagem = EXCLUDED.personagem, ordem_credito = EXCLUDED.ordem_credito;
                    """,
                    (serie_id, pessoa_id, clean_text(cast.get("character")), cast.get("order"), cast.get("credit_id")),
                )

    for crew in credits.get("crew") or []:
        pessoa_id = upsert_person(conn, crew)
        if crew.get("credit_id"):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO equipe_series (serie_id, pessoa_id, departamento, funcao, credit_id_tmdb)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (credit_id_tmdb)
                    DO UPDATE SET departamento = EXCLUDED.departamento, funcao = EXCLUDED.funcao;
                    """,
                    (serie_id, pessoa_id, clean_text(crew.get("department")), clean_text(crew.get("job")), crew.get("credit_id")),
                )

    save_production_companies(conn, serie_id, tv.get("production_companies") or [], "serie")
    save_translations(conn, serie_id, tv.get("translations") or {}, "serie")


def import_movies(conn, session, model):
    print("==== Importando filmes ====")
    for year in range(YEAR_START, YEAR_END + 1):
        first_page = tmdb_get(
            session,
            "/discover/movie",
            {
                "language": TMDB_LANGUAGE,
                "region": TMDB_REGION,
                "include_adult": "false",
                "include_video": "false",
                "sort_by": "popularity.desc",
                "primary_release_year": year,
                "vote_count.gte": TMDB_MIN_VOTE_COUNT,
                "page": 1,
            },
        )
        total_pages = min(first_page.get("total_pages", 1), TMDB_MAX_PAGES)
        for page in range(1, total_pages + 1):
            data = first_page if page == 1 else tmdb_get(
                session,
                "/discover/movie",
                {
                    "language": TMDB_LANGUAGE,
                    "region": TMDB_REGION,
                    "include_adult": "false",
                    "include_video": "false",
                    "sort_by": "popularity.desc",
                    "primary_release_year": year,
                    "vote_count.gte": TMDB_MIN_VOTE_COUNT,
                    "page": page,
                },
            )
            print(f"[FILMES] Ano {year} | Página {page}/{total_pages}")
            for item in data.get("results") or []:
                tmdb_id = item.get("id")
                if not tmdb_id:
                    continue
                try:
                    movie = tmdb_get(
                        session,
                        f"/movie/{tmdb_id}",
                        {"language": TMDB_LANGUAGE, "append_to_response": "credits,external_ids,translations"},
                    )
                    upsert_movie(conn, movie, model)
                    conn.commit()
                    print(f"OK filme: {movie.get('title')}")
                except Exception as exc:
                    conn.rollback()
                    print(f"ERRO filme {tmdb_id}: {exc}")


def import_series(conn, session, model):
    print("==== Importando séries ====")
    for year in range(YEAR_START, YEAR_END + 1):
        first_page = tmdb_get(
            session,
            "/discover/tv",
            {
                "language": TMDB_LANGUAGE,
                "sort_by": "popularity.desc",
                "first_air_date_year": year,
                "vote_count.gte": TMDB_MIN_VOTE_COUNT,
                "page": 1,
            },
        )
        total_pages = min(first_page.get("total_pages", 1), TMDB_MAX_PAGES)
        for page in range(1, total_pages + 1):
            data = first_page if page == 1 else tmdb_get(
                session,
                "/discover/tv",
                {
                    "language": TMDB_LANGUAGE,
                    "sort_by": "popularity.desc",
                    "first_air_date_year": year,
                    "vote_count.gte": TMDB_MIN_VOTE_COUNT,
                    "page": page,
                },
            )
            print(f"[SÉRIES] Ano {year} | Página {page}/{total_pages}")
            for item in data.get("results") or []:
                tmdb_id = item.get("id")
                if not tmdb_id:
                    continue
                try:
                    tv = tmdb_get(
                        session,
                        f"/tv/{tmdb_id}",
                        {"language": TMDB_LANGUAGE, "append_to_response": "credits,external_ids,translations"},
                    )
                    upsert_series(conn, tv, model)
                    conn.commit()
                    print(f"OK série: {tv.get('name')}")
                except Exception as exc:
                    conn.rollback()
                    print(f"ERRO série {tmdb_id}: {exc}")


def main():
    print("Carregando modelo de embeddings...")
    model = SentenceTransformer(MODEL_NAME)
    print("Conectando ao banco...")
    conn = connect_db()
    session = requests.Session()
    session.headers.update({"Accept": "application/json", "User-Agent": "movie-ai-search-zero/1.0"})
    try:
        if IMPORT_MOVIES:
            import_movies(conn, session, model)
        if IMPORT_SERIES:
            import_series(conn, session, model)
    finally:
        conn.close()
    print("Importação finalizada.")


if __name__ == "__main__":
    main()
