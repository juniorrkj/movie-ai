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

function profileUrl(path) {
  if (!path) return null;
  return `https://image.tmdb.org/t/p/w300${path}`;
}

function formatNumber(value) {
  if (value === null || value === undefined) return "0";
  return Number(value).toLocaleString("pt-BR");
}

function cardTemplate(item) {
  const img = posterUrl(item.poster_path);

  const poster = img
    ? `<img src="${img}" alt="${item.titulo || "Poster"}" loading="lazy" />`
    : `<div class="no-poster">Sem poster</div>`;

  const nota = item.nota_tmdb ? Number(item.nota_tmdb).toFixed(1) : "S/N";
  const ano = item.ano_lancamento || "Ano desconhecido";

  const detailsButton =
    item.tipo === "FILME"
      ? `
        <button class="details-button" data-movie-id="${item.id}">
          Ver detalhes
        </button>
      `
      : "";

  return `
    <article class="card">
      <div class="poster">
        ${poster}
      </div>

      <div class="card-body">
        <span class="badge">${item.tipo || "MÍDIA"}</span>

        <h3>${item.titulo || item.titulo_original || "Sem título"}</h3>

        <div class="meta">
          <span>${ano}</span>
          <span>⭐ ${nota}</span>
        </div>

        ${
          item.personagens
            ? `<p class="small-info"><strong>Personagem:</strong> ${item.personagens}</p>`
            : ""
        }

        ${
          item.funcoes
            ? `<p class="small-info"><strong>Função:</strong> ${item.funcoes}</p>`
            : ""
        }

        <p class="overview">
          ${item.sinopse || "Sem sinopse disponível."}
        </p>

        ${detailsButton}
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
  resultsEl.innerHTML = `<div class="error">${message}</div>`;
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

    if (!response.ok) {
      apiStatus.textContent = "API com erro";
      return;
    }

    apiStatus.textContent = "API online";
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

    if (data.matched_person) {
      sectionTitle.innerHTML = `
        Resultado para: "${query}"
        <button class="person-link" data-person-id="${data.matched_person.id}">
          ${data.matched_person.nome}
        </button>
      `;
    } else {
      sectionTitle.textContent = `Resultado para: "${query}"`;
    }

    renderResults(data.results);
  } catch (error) {
    console.error(error);
    renderError("Erro ao conectar na busca por IA. Verifique se o Python está rodando.");
  }
}

function personTemplate(data) {
  const person = data.person;
  const img = profileUrl(person.profile_path);

  const acting = data.acting || [];
  const crew = data.crew || [];

  return `
    <section class="detail-page">
      <button class="back-button" id="backToResults">← Voltar</button>

      <div class="person-detail">
        <div class="person-photo">
          ${
            img
              ? `<img src="${img}" alt="${person.nome}" />`
              : `<div class="no-poster">Sem foto</div>`
          }
        </div>

        <div>
          <h2>${person.nome}</h2>

          <p><strong>Nome original:</strong> ${person.nome_original || "Não informado"}</p>
          <p><strong>Departamento:</strong> ${person.departamento_conhecido || "Não informado"}</p>
          <p><strong>Nascimento:</strong> ${person.nascimento || "Não informado"}</p>
          <p><strong>Falecimento:</strong> ${person.falecimento || "Não informado"}</p>
          <p><strong>Local:</strong> ${person.local_nascimento || "Não informado"}</p>

          <p class="overview-full">
            ${person.biografia || "Sem biografia disponível."}
          </p>
        </div>
      </div>

      <h3>Filmes como ator/atriz</h3>
      <div class="mini-grid">
        ${
          acting.length > 0
            ? acting.map(cardTemplate).join("")
            : "<p>Nenhum filme encontrado.</p>"
        }
      </div>

      <h3>Equipe técnica / direção / roteiro</h3>
      <div class="mini-grid">
        ${
          crew.length > 0
            ? crew.map(cardTemplate).join("")
            : "<p>Nenhum filme encontrado.</p>"
        }
      </div>
    </section>
  `;
}

function movieDetailTemplate(data) {
  const movie = data.movie;
  const cast = data.cast || [];
  const crew = data.crew || [];
  const genres = data.genres || [];
  const companies = data.companies || [];

  const poster = posterUrl(movie.poster_path);

  return `
    <section class="detail-page">
      <button class="back-button" id="backToResults">← Voltar</button>

      <div class="movie-detail">
        <div class="detail-poster">
          ${
            poster
              ? `<img src="${poster}" alt="${movie.titulo}" />`
              : `<div class="no-poster">Sem poster</div>`
          }
        </div>

        <div>
          <span class="badge">FILME</span>

          <h2>${movie.titulo || movie.titulo_original || "Sem título"}</h2>

          <p><strong>Título original:</strong> ${movie.titulo_original || "Não informado"}</p>
          <p><strong>Ano:</strong> ${movie.ano_lancamento || "Não informado"}</p>
          <p><strong>Data de lançamento:</strong> ${movie.data_lancamento || "Não informado"}</p>
          <p><strong>Nota:</strong> ${movie.nota_tmdb || "Sem nota"}</p>
          <p><strong>Votos:</strong> ${movie.votos_tmdb || 0}</p>
          <p><strong>Duração:</strong> ${movie.duracao_min || "?"} min</p>
          <p><strong>Status:</strong> ${movie.status || "Não informado"}</p>

          <p>
            <strong>Gêneros:</strong>
            ${genres.map((g) => g.nome).join(", ") || "Não informado"}
          </p>

          <p class="overview-full">
            ${movie.sinopse || "Sem sinopse disponível."}
          </p>
        </div>
      </div>

      <h3>Direção / roteiro</h3>
      <div class="people-list">
        ${
          crew.length > 0
            ? crew
                .map(
                  (p) => `
                    <button class="person-chip" data-person-id="${p.id}">
                      ${p.nome}${p.funcao ? ` • ${p.funcao}` : ""}
                    </button>
                  `
                )
                .join("")
            : "<p>Nenhuma equipe encontrada.</p>"
        }
      </div>

      <h3>Elenco</h3>
      <div class="people-list">
        ${
          cast.length > 0
            ? cast
                .map(
                  (p) => `
                    <button class="person-chip" data-person-id="${p.id}">
                      ${p.nome}${p.personagem ? ` como ${p.personagem}` : ""}
                    </button>
                  `
                )
                .join("")
            : "<p>Nenhum elenco encontrado.</p>"
        }
      </div>

      <h3>Empresas de produção</h3>
      <p>${companies.map((c) => c.nome).join(", ") || "Não informado"}</p>
    </section>
  `;
}

async function loadPersonDetails(personId) {
  renderLoading();

  try {
    const response = await fetch(`${API_BASE}/api/person/${personId}`);
    const data = await response.json();

    if (!response.ok) {
      renderError(data.error || "Erro ao carregar pessoa.");
      return;
    }

    sectionTitle.textContent = "Detalhes da pessoa";
    resultsCount.textContent = "";
    resultsEl.innerHTML = personTemplate(data);
  } catch (error) {
    console.error(error);
    renderError("Erro ao carregar detalhes da pessoa.");
  }
}

async function loadMovieDetails(movieId) {
  renderLoading();

  try {
    const response = await fetch(`${API_BASE}/api/movie/${movieId}`);
    const data = await response.json();

    if (!response.ok) {
      renderError(data.error || "Erro ao carregar filme.");
      return;
    }

    sectionTitle.textContent = "Detalhes do filme";
    resultsCount.textContent = "";
    resultsEl.innerHTML = movieDetailTemplate(data);
  } catch (error) {
    console.error(error);
    renderError("Erro ao carregar detalhes do filme.");
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

document.addEventListener("click", (event) => {
  const personButton = event.target.closest("[data-person-id]");

  if (personButton) {
    loadPersonDetails(personButton.dataset.personId);
    return;
  }

  const movieButton = event.target.closest("[data-movie-id]");

  if (movieButton) {
    loadMovieDetails(movieButton.dataset.movieId);
    return;
  }

  if (event.target.id === "backToResults") {
    loadPopular();
  }
});

checkApi();
loadStats();
loadPopular();