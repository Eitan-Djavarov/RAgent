# Tech-Doc-Intelligence

Dual-stack microservices platform for aerospace/defense **incident intelligence**: document ingestion, hierarchical RAG retrieval, agentic routing, grounded Q&A, and Streamlit investigation UX.

| Service | Stack | Port |
|---------|--------|------|
| `backend-core` | .NET 8 Web API (orchestration, Postgres) | 5000 |
| `ai-service` | FastAPI + LangChain + Qdrant + Redis | 8000 |
| `frontend-ui` | Streamlit Agentic Assistant | 8501 |
| `postgres` | PostgreSQL 16 | 5432 |
| `qdrant` | Vector store | 6333 |
| `redis` | Semantic cache + session memory + rate limits | 6379 |

---

## Architecture highlights

### Parent-Document (Small-to-Big) retrieval

1. **Hierarchical chunking** on ingest: large **parent** sections (~900 chars) and focused **child** sub-chunks (~200 chars).
2. **Qdrant indexes child embeddings** for fine-grained dense search; each child payload stores `parent_id` + `parent_text`.
3. **Hybrid search** (dense + BM25) runs on children, then **expands to parent text** and **deduplicates by `parent_id`** before LLM synthesis and grounding.

### Minimum similarity score fallback

- Configurable floor: `MIN_RETRIEVAL_SCORE=0.40`.
- If every hit after fusion/rerank is below the threshold, synthesis is **short-circuited** (no LLM call) with a deterministic message:  
  *"No sufficiently relevant incident context was found in the indexed documents."*

### Sentence-level inline citations

- Synthesis prompts require markers `[1]`, `[2]`, … after factual claims.
- Markers map 1-to-1 to the numbered citation list (`citationIndex`, `docId`, `system`, `severity`, `chunkText`).
- Streamlit Tab 1 renders matching numbered badges and expandable source cards.

### Faithfulness & grounding

- Post-synthesis grounding guard scores answer entailment against retrieved parents (`faithfulnessScore`, `isGrounded`, `unsupportedClaims`).
- UI shows a grounding badge and an expander for unsupported claims.

### Agentic orchestration

- Intent router: `HYBRID_RAG` | `SQL_METRICS` | `HYBRID_COMBINED`.
- Multi-turn session memory, query rewriting, Redis semantic cache, SSE token streaming, rate limiting, and input guardrails.

### Modular clean architecture

| Area | Layout |
|------|--------|
| **AI** | `app/schemas/`, `app/ingestion/` (chunker + Qdrant indexer), `app/retrieval/` (hybrid search + parent expansion), `app/rag/` (pipeline façade + LLM synthesis), `app/agent/` (orchestrator, grounding, SQL tool), `app/citations/`, `app/prompts/` |
| **.NET** | Controllers → Services → Clients; focused DTO files under `Models/DTOs/`; typed `HttpClient` to AI |
| **Contracts** | camelCase JSON; AI OpenAPI mirrored by .NET DTOs |

### CI/CD

GitHub Actions (`.github/workflows/ci.yml`) on `push` to `main` and all PRs:

| Job | What it runs |
|-----|----------------|
| `dotnet-tests` | Restore, build, `dotnet test` |
| `ai-service-tests` | Python 3.11 + `pytest` (**47** unit tests) |
| `docker-compose-lint` | `docker compose config` |

---

## Repository layout

```
backend-core/          .NET 8 API
backend-core.Tests/    .NET unit/integration tests
ai-service/            FastAPI RAG microservice + tests/
frontend-ui/           Streamlit UI
docker/                Dockerfiles and Postgres init
.github/workflows/     CI pipeline
docker-compose.yml     Full local stack
.env.example           Documented env overrides (no secrets)
```

---

## Prerequisites

- Docker + Docker Compose
- .NET 8 SDK (local backend development)
- Python 3.11+ (local AI service / tests)

---

## Quick start (full stack)

```bash
# From repo root — build and start all services in the background
docker compose up --build -d
```

| Surface | URL |
|---------|-----|
| Streamlit UI | http://localhost:8501 |
| Backend Swagger | http://localhost:5000/swagger |
| AI OpenAPI | http://localhost:8000/docs |
| Qdrant dashboard | http://localhost:6333/dashboard |

Optional LLM providers:

```bash
# PowerShell
$env:OPENAI_API_KEY="sk-..."
docker compose up --build -d

# or set OLLAMA_BASE_URL for local Ollama (compose defaults to host.docker.internal:11434)
```

Copy `.env.example` to `.env` for local overrides. Never commit real secrets.

Stop / tear down:

```bash
docker compose down
```

---

## Seed + verify

```bash
# corpus check only (no HTTP)
python -c "from scripts.seed_and_verify import validate_seed_corpus; validate_seed_corpus(); print('ok')"

# full flow against local backend
python scripts/seed_and_verify.py --base-url http://localhost:5000
```

HTTP scratchpad: `tests/incidents.http`

---

## Local development

### Streamlit UI

```bash
docker compose up --build frontend-ui
# or
cd frontend-ui
pip install -r requirements.txt
streamlit run app.py
```

### Backend

```bash
cd backend-core
dotnet restore
dotnet run
```

Configure `ConnectionStrings:DefaultConnection` and `AiService:BaseUrl` in `appsettings.Development.json`.

### AI service

```bash
cd ai-service
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Ensure Postgres, Redis, and Qdrant are reachable (via compose or local installs).

### Tests

```bash
# AI
cd ai-service
pytest -q

# .NET
dotnet test TechDocIntelligence.sln
```

---

## Core API flows

1. `POST /api/incidents` — persist incident in PostgreSQL and ingest via `POST /api/v1/ingest`.
2. `POST /api/incidents/upload` — multipart PDF/TXT/MD ingest (cascade into Qdrant + Postgres).
3. `POST /api/incidents/ask` (alias `/analyze`) — agentic RAG/SQL analysis; returns summary, root cause, action items, citations, faithfulness, latency.
4. `POST /api/incidents/ask/stream` — SSE proxy of AI token stream.
5. `DELETE /api/incidents/{id}` — cascade delete (Postgres + Qdrant + cache invalidation).
6. `GET /health` (AI) / `GET /api/health` (backend) — liveness / dependency checks.

AI equivalents: `POST /api/v1/query`, `POST /api/v1/ask`, `POST /api/v1/ask/stream`, ingest/document management under `/api/v1/...`.

---

## Configuration

| Variable | Service | Default | Notes |
|----------|---------|---------|-------|
| `ConnectionStrings__DefaultConnection` | backend-core | Postgres on `postgres:5432` | |
| `AiService__BaseUrl` | backend-core | `http://ai-service:8000` | |
| `QDRANT_HOST` / `QDRANT_PORT` | ai-service | `qdrant` / `6333` | |
| `COLLECTION_NAME` | ai-service | `tech_docs` | |
| `EMBEDDING_MODEL` | ai-service | `all-MiniLM-L6-v2` | |
| `PARENT_CHUNK_SIZE` | ai-service | `900` | Parent section size (chars) |
| `PARENT_CHUNK_OVERLAP` | ai-service | `100` | |
| `CHILD_CHUNK_SIZE` | ai-service | `200` | Indexed child size (chars) |
| `CHILD_CHUNK_OVERLAP` | ai-service | `40` | |
| `MIN_RETRIEVAL_SCORE` | ai-service | `0.40` | Min relevance before synthesis |
| `GROUNDING_ENABLED` | ai-service | `true` | Faithfulness guard |
| `GROUNDING_THRESHOLD` | ai-service | `0.8` | `isGrounded` cutoff |
| `GROUNDING_LLM_TIMEOUT_SECONDS` | ai-service | `8` | Heuristic fallback on timeout |
| `REDIS_HOST` / `REDIS_PORT` | ai-service | `redis` / `6379` | Cache + sessions + rate limit |
| `SEMANTIC_CACHE_ENABLED` | ai-service | `true` | |
| `SEMANTIC_CACHE_SIMILARITY_THRESHOLD` | ai-service | `0.92` | |
| `SESSION_MEMORY_TTL_SECONDS` | ai-service | `3600` | |
| `RATE_LIMIT_ENABLED` | ai-service | `true` | |
| `RATE_LIMIT_REQUESTS` | ai-service | `30` | Per window |
| `RATE_LIMIT_WINDOW_SECONDS` | ai-service | `60` | |
| `OLLAMA_BASE_URL` | ai-service | `http://localhost:11434` | Local LLM fallback |
| `OPENAI_API_KEY` | ai-service | empty | Prefer OpenAI when set |

See `.env.example` for a ready-to-copy template.

---

## License

Proprietary — internal use.
