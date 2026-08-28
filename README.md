# Tech-Doc-Intelligence

Dual-stack microservices system for technical document ingestion, embedding, retrieval, and Q&A.

| Service | Stack | Port |
|---------|--------|------|
| `backend-core` | .NET 8 Web API | 5000 |
| `ai-service` | FastAPI + LangChain + Qdrant | 8000 |
| `postgres` | PostgreSQL 16 | 5432 |
| `qdrant` | Qdrant | 6333 |

## Repository layout

```
backend-core/          .NET 8 API (Controllers, Models/DTOs, Services, Clients, Data)
ai-service/            FastAPI RAG microservice
docker/                Dockerfiles and Postgres init
docker-compose.yml     Full local stack
```

## Prerequisites

- Docker + Docker Compose
- .NET 8 SDK (local backend development)
- Python 3.11+ (local AI service development)

## Quick start (Docker)

```bash
docker compose up --build
```

- Backend Swagger: http://localhost:5000/swagger  
- AI OpenAPI docs: http://localhost:8000/docs  
- Qdrant dashboard: http://localhost:6333/dashboard  

Optional OpenAI answers (otherwise a heuristic answer is returned from retrieved chunks):

```bash
set OPENAI_API_KEY=sk-...
docker compose up --build
```

## Seed + verify

```bash
# corpus check only (no HTTP)
python -c "from scripts.seed_and_verify import validate_seed_corpus; validate_seed_corpus(); print('ok')"

# full flow against local backend
python scripts/seed_and_verify.py --base-url http://localhost:5000
```

HTTP scratchpad: `tests/incidents.http`

## Streamlit UI

```bash
# via compose (port 8501)
docker compose up --build frontend-ui

# or locally
cd frontend-ui
pip install -r requirements.txt
streamlit run app.py
```

Open http://localhost:8501




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

Set `QDRANT_URL=http://localhost:6333` (default) and ensure Qdrant is running.

## Core API flows

1. `POST /api/incidents` — persist an incident in PostgreSQL and ingest it via `POST /api/v1/ingest`.
2. `POST /api/incidents/ask` (alias: `/analyze`) — enriched RAG analysis with optional `systemName`, `minSeverity`, `topK`; returns `summary`, `rootCause`, `actionItems`, `citations`, `latencyMs`.
3. `GET /api/incidents/{id}` — fetch a persisted incident.
4. `GET /health` (AI) / `GET /api/health` (backend) — liveness checks.

## Configuration

| Variable | Service | Default |
|----------|---------|---------|
| `ConnectionStrings__DefaultConnection` | backend-core | Postgres on `postgres:5432` |
| `AiService__BaseUrl` | backend-core | `http://ai-service:8000` |
| `QDRANT_HOST` / `QDRANT_PORT` | ai-service | `qdrant` / `6333` |
| `COLLECTION_NAME` | ai-service | `tech_docs` |
| `EMBEDDING_MODEL` | ai-service | `all-MiniLM-L6-v2` |
| `OLLAMA_BASE_URL` | ai-service | `http://localhost:11434` |
| `OPENAI_API_KEY` | ai-service | empty (falls back to Ollama, then extractive) |

## License

Proprietary — internal use.
