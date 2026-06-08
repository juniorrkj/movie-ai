const API_BASE = "";

const searchForm = document.getElementById("searchForm");
const searchInput = document.getElementById("searchInput");
const typeSelect = document.getElementById("typeSelect");
const resultsEl = document.getElementById("results");
const sectionTitle = document.getElementById("sectionTitle");
const resultsCount = document.getElementById("resultsCount");
const apiStatus = document.getElementById("apiStatus");

const statFilmes = document.getElementById("statFilmes");
const statSeries = document.getElementById("statSeries");
const statPessoas = document.getElementById("statPessoas");
const statGeneros = document.getElementById("statGeneros");

function posterUrl(path) {
  if (!path) return null;
  return `https://image.tmdb.org/t/p/w500${path}`;
}

function formatNumber(value) {
  if (value === null || value === undefined) return "0";
  return Number(value).toLocaleString("pt-BR");
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function cardTemplate(item) {
  const img = posterUrl(item.poster_path);

  const poster = img
    ? `<img src="${img}" alt="${escapeHtml(item.titulo || "Poster")}" loading="lazy" />`
    : `<div class="no-poster">Sem poster</div>`;

  const nota = item.nota_tmdb ? Number(item.nota_tmdb).toFixed(1) : "S/N";
  const ano = item.ano_lancamento || "Ano desconhecido";

  return `
    <article class="card">
      <div class="poster">${poster}</div>
      <div class="card-body">
        <span class="badge">${escapeHtml(item.tipo || "MÍDIA")}</span>
        <h3>${escapeHtml(item.titulo || item.titulo_original || "Sem título")}</h3>
        <div class="meta">
          <span>${escapeHtml(ano)}</span>
          <span>⭐ ${escapeHtml(nota)}</span>
        </div>
        <p class="overview">${escapeHtml(item.sinopse || "Sem sinopse disponível.")}</p>
      </div>
    </article>
  `;
}

function renderResults(items) {
  if (!items || items.length === 0) {
    resultsEl.innerHTML = `<div class="empty">Nenhum resultado encontrado.</div>`;
    resultsCount.textContent = "";
    return;
  }

  resultsEl.innerHTML = items.map(cardTemplate).join("");
  resultsCount.textContent = `${items.length} resultado(s)`;
}

function renderLoading() {
  resultsEl.innerHTML = `<div class="loading">Carregando...</div>`;
}

function renderError(message) {
  resultsEl.innerHTML = `<div class="error">${escapeHtml(message)}</div>`;
}

async function loadStats() {
  try {
    const response = await fetch(`${API_BASE}/api/stats`);
    const data = await response.json();

    statFilmes.textContent = formatNumber(data.filmes);
    statSeries.textContent = formatNumber(data.series);
    statPessoas.textContent = formatNumber(data.pessoas);
    statGeneros.textContent = formatNumber(data.generos);
  } catch (error) {
    console.error(error);
  }
}

async function checkApi() {
  try {
    const response = await fetch(`${API_BASE}/api/health`);
    apiStatus.textContent = response.ok ? "API online" : "API com erro";
  } catch (error) {
    apiStatus.textContent = "API offline";
  }
}

async function loadPopular() {
  renderLoading();

  try {
    const response = await fetch(`${API_BASE}/api/popular`);
    const data = await response.json();

    sectionTitle.textContent = "Populares no banco";
    renderResults(data.results);
  } catch (error) {
    console.error(error);
    renderError("Erro ao carregar populares.");
  }
}

async function searchMovies(query, tipo) {
  renderLoading();

  try {
    const params = new URLSearchParams();
    params.set("q", query);
    params.set("limit", "12");

    if (tipo) {
      params.set("tipo", tipo);
    }

    const response = await fetch(`${API_BASE}/api/search?${params.toString()}`);
    const data = await response.json();

    if (!response.ok) {
      renderError(data.error || "Erro na busca.");
      return;
    }

    sectionTitle.textContent = `Resultado para: "${query}"`;
    renderResults(data.results);
  } catch (error) {
    console.error(error);
    renderError("Erro ao conectar na busca por IA. Verifique se o Python está rodando.");
  }
}

searchForm.addEventListener("submit", (event) => {
  event.preventDefault();

  const query = searchInput.value.trim();
  const tipo = typeSelect.value;

  if (!query) {
    renderError("Digite algo para buscar.");
    return;
  }

  searchMovies(query, tipo);
});

document.querySelectorAll(".quick-searches button").forEach((button) => {
  button.addEventListener("click", () => {
    const query = button.dataset.query;
    searchInput.value = query;
    searchMovies(query, typeSelect.value);
  });
});

checkApi();
loadStats();
loadPopular();
