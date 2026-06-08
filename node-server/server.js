const express = require("express");
const cors = require("cors");
const path = require("path");
const dotenv = require("dotenv");
const { Pool } = require("pg");

// Requer Node.js 18+ para usar fetch nativo.
dotenv.config({ path: path.join(__dirname, "..", ".env") });

const app = express();

const PORT = process.env.PORT || 3000;
const PYTHON_AI_URL = process.env.PYTHON_AI_URL || "http://localhost:8000/search";
const PYTHON_API_BASE =
  process.env.PYTHON_API_BASE || PYTHON_AI_URL.replace(/\/search$/, "");

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
});

app.use(cors());
app.use(express.json());

const frontendPath = path.join(__dirname, "..", "frontend");
app.use(express.static(frontendPath));

app.get("/api/health", async (req, res) => {
  res.json({
    status: "ok",
    node: true,
    python_ai_url: PYTHON_AI_URL,
    python_api_base: PYTHON_API_BASE,
  });
});

app.get("/api/stats", async (req, res) => {
  try {
    const filmes = await pool.query("SELECT COUNT(*)::int AS total FROM filmes");
    const series = await pool.query("SELECT COUNT(*)::int AS total FROM series");
    const pessoas = await pool.query("SELECT COUNT(*)::int AS total FROM pessoas");
    const generos = await pool.query("SELECT COUNT(*)::int AS total FROM generos");

    res.json({
      filmes: filmes.rows[0].total,
      series: series.rows[0].total,
      pessoas: pessoas.rows[0].total,
      generos: generos.rows[0].total,
    });
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: "Erro ao buscar estatísticas." });
  }
});

app.get("/api/popular", async (req, res) => {
  try {
    const result = await pool.query(`
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
          poster_path
        FROM filmes

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
          poster_path
        FROM series
      ) x
      ORDER BY popularidade_tmdb DESC NULLS LAST
      LIMIT 24;
    `);

    res.json({ results: result.rows });
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: "Erro ao buscar populares." });
  }
});

app.get("/api/search", async (req, res) => {
  const q = req.query.q;
  const tipo = req.query.tipo || "";
  const limit = req.query.limit || "12";

  if (!q) {
    return res.status(400).json({ error: "Digite uma busca." });
  }

  try {
    const url = new URL(PYTHON_AI_URL);
    url.searchParams.set("q", q);
    url.searchParams.set("limit", limit);

    if (tipo) {
      url.searchParams.set("tipo", tipo);
    }

    const response = await fetch(url.toString());

    if (!response.ok) {
      const text = await response.text();
      return res.status(500).json({
        error: "Erro na API Python.",
        detail: text,
      });
    }

    const data = await response.json();
    res.json(data);
  } catch (error) {
    console.error(error);
    res.status(500).json({
      error: "Erro ao conectar na API Python.",
      detail: error.message,
    });
  }
});

app.get("/api/person/:id", async (req, res) => {
  try {
    const response = await fetch(`${PYTHON_API_BASE}/person/${req.params.id}`);

    if (!response.ok) {
      const text = await response.text();
      return res.status(response.status).json({
        error: "Erro ao buscar pessoa.",
        detail: text,
      });
    }

    const data = await response.json();
    res.json(data);
  } catch (error) {
    console.error(error);
    res.status(500).json({
      error: "Erro ao conectar na API Python.",
      detail: error.message,
    });
  }
});

app.get("/api/movie/:id", async (req, res) => {
  try {
    const response = await fetch(`${PYTHON_API_BASE}/movie/${req.params.id}`);

    if (!response.ok) {
      const text = await response.text();
      return res.status(response.status).json({
        error: "Erro ao buscar filme.",
        detail: text,
      });
    }

    const data = await response.json();
    res.json(data);
  } catch (error) {
    console.error(error);
    res.status(500).json({
      error: "Erro ao conectar na API Python.",
      detail: error.message,
    });
  }
});

app.get("*", (req, res) => {
  res.sendFile(path.join(frontendPath, "index.html"));
});

app.listen(PORT, () => {
  console.log(`Node rodando em http://localhost:${PORT}`);
  console.log(`API Python Search: ${PYTHON_AI_URL}`);
  console.log(`API Python Base: ${PYTHON_API_BASE}`);
});