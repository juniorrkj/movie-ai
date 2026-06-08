# Movie AI Search Zero Base

Projeto base completo com:

- PostgreSQL + pgvector
- Seed TMDB para popular o banco
- FastAPI para busca semântica com IA
- Node/Express para servir o frontend e fazer ponte com a API Python
- Frontend HTML + CSS + JS

## 1. Criar o .env

Copie o arquivo `.env.example` e renomeie para `.env`.

No Windows CMD:

```bash
copy .env.example .env
```

Depois abra:

```bash
notepad .env
```

Troque:

```env
TMDB_API_KEY=COLOQUE_SUA_CHAVE_AQUI
```

pela sua chave real do TMDB.

## 2. Subir o PostgreSQL

Na raiz do projeto:

```bash
docker compose up -d
```

Teste:

```bash
docker exec -it movie_ai_postgres psql -U postgres -d movie_ai -c "\dt"
```

## 3. Instalar dependências Python

```bash
cd python-ai
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cd ..
```

## 4. Popular o banco

```bash
cd python-ai
.venv\Scripts\activate
python scrapers\seed_tmdb.py
cd ..
```

A configuração inicial no `.env` está assim:

```env
TMDB_YEAR_START=1900
TMDB_YEAR_END=2026
TMDB_MAX_PAGES=5
IMPORT_MOVIES=true
IMPORT_SERIES=false
```

Isso busca filmes de 1900 até 2026, com até 5 páginas por ano.

## 5. Conferir quantidade no banco

```bash
docker exec -it movie_ai_postgres psql -U postgres -d movie_ai -c "SELECT COUNT(*) FROM filmes;"
```

```bash
docker exec -it movie_ai_postgres psql -U postgres -d movie_ai -c "SELECT COUNT(*) FROM pessoas;"
```

## 6. Subir API Python

```bash
cd python-ai
.venv\Scripts\activate
python app.py
```

Abra:

```txt
http://localhost:8000/health
```

## 7. Instalar e subir Node

Em outro terminal:

```bash
cd node-server
npm install
npm start
```

Abra:

```txt
http://localhost:3000
```

## 8. Scripts prontos

Depois de instalar tudo uma vez, você pode usar os arquivos da pasta `scripts`:

- `reset-db.bat`: apaga e recria o banco
- `run-seed.bat`: popula o banco
- `start-python.bat`: inicia a API Python
- `start-node.bat`: inicia o Node/frontend

## Observações

- O `.env` não deve ir para o GitHub.
- A primeira execução do Python pode demorar porque baixa o modelo de IA.
- Para aumentar a quantidade de filmes, aumente `TMDB_MAX_PAGES` no `.env`.
- Evite começar com `TMDB_MAX_PAGES=50`, porque pode levar muitas horas.
