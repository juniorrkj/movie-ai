CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS generos (
    id SERIAL PRIMARY KEY,
    tmdb_id INTEGER UNIQUE,
    nome VARCHAR(120) NOT NULL,
    slug VARCHAR(120) UNIQUE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pessoas (
    id BIGSERIAL PRIMARY KEY,
    tmdb_id INTEGER UNIQUE,
    imdb_id VARCHAR(30) UNIQUE,

    nome VARCHAR(300) NOT NULL,
    nome_original VARCHAR(300),
    genero_tmdb SMALLINT,

    nascimento DATE,
    falecimento DATE,
    local_nascimento VARCHAR(500),
    biografia TEXT,

    departamento_conhecido VARCHAR(120),
    popularidade_tmdb NUMERIC(12,4),
    profile_path VARCHAR(255),

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS filmes (
    id BIGSERIAL PRIMARY KEY,
    tmdb_id INTEGER UNIQUE,
    imdb_id VARCHAR(30) UNIQUE,

    titulo VARCHAR(500),
    titulo_original VARCHAR(500),
    sinopse TEXT,
    tagline VARCHAR(500),

    idioma_original VARCHAR(20),
    status VARCHAR(100),

    data_lancamento DATE,
    ano_lancamento INTEGER,

    duracao_min INTEGER,
    orcamento BIGINT,
    receita BIGINT,

    popularidade_tmdb NUMERIC(12,4),
    nota_tmdb NUMERIC(4,2),
    votos_tmdb INTEGER,

    poster_path VARCHAR(255),
    backdrop_path VARCHAR(255),

    adulto BOOLEAN DEFAULT FALSE,

    embedding vector(384),

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS series (
    id BIGSERIAL PRIMARY KEY,
    tmdb_id INTEGER UNIQUE,
    imdb_id VARCHAR(30) UNIQUE,

    titulo VARCHAR(500),
    titulo_original VARCHAR(500),
    sinopse TEXT,
    tagline VARCHAR(500),

    idioma_original VARCHAR(20),
    pais_origem VARCHAR(50),
    status VARCHAR(100),

    data_primeiro_ep DATE,
    data_ultimo_ep DATE,
    ano_lancamento INTEGER,

    numero_temporadas INTEGER,
    numero_episodios INTEGER,
    em_producao BOOLEAN,
    tipo_serie VARCHAR(100),

    popularidade_tmdb NUMERIC(12,4),
    nota_tmdb NUMERIC(4,2),
    votos_tmdb INTEGER,

    poster_path VARCHAR(255),
    backdrop_path VARCHAR(255),

    embedding vector(384),

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS temporadas (
    id BIGSERIAL PRIMARY KEY,
    serie_id BIGINT NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    tmdb_id INTEGER UNIQUE,
    numero_temporada INTEGER NOT NULL,
    nome VARCHAR(500),
    sinopse TEXT,
    data_lancamento DATE,
    poster_path VARCHAR(255),
    quantidade_episodios INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (serie_id, numero_temporada)
);

CREATE TABLE IF NOT EXISTS episodios (
    id BIGSERIAL PRIMARY KEY,
    serie_id BIGINT NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    temporada_id BIGINT REFERENCES temporadas(id) ON DELETE SET NULL,
    tmdb_id INTEGER UNIQUE,
    imdb_id VARCHAR(30) UNIQUE,
    numero_temporada INTEGER,
    numero_episodio INTEGER,
    titulo VARCHAR(500),
    titulo_original VARCHAR(500),
    sinopse TEXT,
    data_exibicao DATE,
    duracao_min INTEGER,
    nota_tmdb NUMERIC(4,2),
    votos_tmdb INTEGER,
    still_path VARCHAR(255),
    embedding vector(384),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (serie_id, numero_temporada, numero_episodio)
);

CREATE TABLE IF NOT EXISTS filme_generos (
    filme_id BIGINT NOT NULL REFERENCES filmes(id) ON DELETE CASCADE,
    genero_id INTEGER NOT NULL REFERENCES generos(id) ON DELETE CASCADE,
    PRIMARY KEY (filme_id, genero_id)
);

CREATE TABLE IF NOT EXISTS serie_generos (
    serie_id BIGINT NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    genero_id INTEGER NOT NULL REFERENCES generos(id) ON DELETE CASCADE,
    PRIMARY KEY (serie_id, genero_id)
);

CREATE TABLE IF NOT EXISTS elenco_filmes (
    id BIGSERIAL PRIMARY KEY,
    filme_id BIGINT NOT NULL REFERENCES filmes(id) ON DELETE CASCADE,
    pessoa_id BIGINT NOT NULL REFERENCES pessoas(id) ON DELETE CASCADE,
    personagem VARCHAR(300),
    ordem_credito INTEGER,
    credit_id_tmdb VARCHAR(100) UNIQUE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (filme_id, pessoa_id, personagem)
);

CREATE TABLE IF NOT EXISTS elenco_series (
    id BIGSERIAL PRIMARY KEY,
    serie_id BIGINT NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    pessoa_id BIGINT NOT NULL REFERENCES pessoas(id) ON DELETE CASCADE,
    personagem VARCHAR(300),
    ordem_credito INTEGER,
    credit_id_tmdb VARCHAR(100) UNIQUE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (serie_id, pessoa_id, personagem)
);

CREATE TABLE IF NOT EXISTS equipe_filmes (
    id BIGSERIAL PRIMARY KEY,
    filme_id BIGINT NOT NULL REFERENCES filmes(id) ON DELETE CASCADE,
    pessoa_id BIGINT NOT NULL REFERENCES pessoas(id) ON DELETE CASCADE,
    departamento VARCHAR(120),
    funcao VARCHAR(180),
    credit_id_tmdb VARCHAR(100) UNIQUE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (filme_id, pessoa_id, departamento, funcao)
);

CREATE TABLE IF NOT EXISTS equipe_series (
    id BIGSERIAL PRIMARY KEY,
    serie_id BIGINT NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    pessoa_id BIGINT NOT NULL REFERENCES pessoas(id) ON DELETE CASCADE,
    departamento VARCHAR(120),
    funcao VARCHAR(180),
    credit_id_tmdb VARCHAR(100) UNIQUE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (serie_id, pessoa_id, departamento, funcao)
);

CREATE TABLE IF NOT EXISTS traducoes_filmes (
    id BIGSERIAL PRIMARY KEY,
    filme_id BIGINT NOT NULL REFERENCES filmes(id) ON DELETE CASCADE,
    idioma VARCHAR(20) NOT NULL,
    titulo VARCHAR(500),
    sinopse TEXT,
    tagline VARCHAR(500),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (filme_id, idioma)
);

CREATE TABLE IF NOT EXISTS traducoes_series (
    id BIGSERIAL PRIMARY KEY,
    serie_id BIGINT NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    idioma VARCHAR(20) NOT NULL,
    titulo VARCHAR(500),
    sinopse TEXT,
    tagline VARCHAR(500),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (serie_id, idioma)
);

CREATE TABLE IF NOT EXISTS empresas_producao (
    id BIGSERIAL PRIMARY KEY,
    tmdb_id INTEGER UNIQUE,
    nome VARCHAR(300) NOT NULL,
    pais_origem VARCHAR(20),
    logo_path VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS filme_empresas (
    filme_id BIGINT NOT NULL REFERENCES filmes(id) ON DELETE CASCADE,
    empresa_id BIGINT NOT NULL REFERENCES empresas_producao(id) ON DELETE CASCADE,
    PRIMARY KEY (filme_id, empresa_id)
);

CREATE TABLE IF NOT EXISTS serie_empresas (
    serie_id BIGINT NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    empresa_id BIGINT NOT NULL REFERENCES empresas_producao(id) ON DELETE CASCADE,
    PRIMARY KEY (serie_id, empresa_id)
);

CREATE TABLE IF NOT EXISTS import_logs (
    id BIGSERIAL PRIMARY KEY,
    fonte VARCHAR(50) NOT NULL,
    tipo_entidade VARCHAR(50) NOT NULL,
    external_id VARCHAR(100),
    status VARCHAR(20) NOT NULL,
    mensagem TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_filmes_titulo_trgm ON filmes USING gin (titulo gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_filmes_titulo_original_trgm ON filmes USING gin (titulo_original gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_series_titulo_trgm ON series USING gin (titulo gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_pessoas_nome_trgm ON pessoas USING gin (nome gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_filmes_ano ON filmes (ano_lancamento);
CREATE INDEX IF NOT EXISTS idx_series_ano ON series (ano_lancamento);
CREATE INDEX IF NOT EXISTS idx_filmes_tmdb ON filmes (tmdb_id);
CREATE INDEX IF NOT EXISTS idx_series_tmdb ON series (tmdb_id);
CREATE INDEX IF NOT EXISTS idx_pessoas_tmdb ON pessoas (tmdb_id);
CREATE INDEX IF NOT EXISTS idx_elenco_filmes_filme ON elenco_filmes (filme_id);
CREATE INDEX IF NOT EXISTS idx_elenco_filmes_pessoa ON elenco_filmes (pessoa_id);
CREATE INDEX IF NOT EXISTS idx_equipe_filmes_filme ON equipe_filmes (filme_id);
CREATE INDEX IF NOT EXISTS idx_equipe_filmes_pessoa ON equipe_filmes (pessoa_id);
