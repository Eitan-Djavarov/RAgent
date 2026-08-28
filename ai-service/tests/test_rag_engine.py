from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import Settings
from app.models.schemas import IngestRequest, QueryRequest
from app.rag.bm25_store import Bm25Store
from app.rag.pipeline import RagPipeline


@pytest.fixture
def settings() -> Settings:
    return Settings(
        QDRANT_HOST="localhost",
        QDRANT_PORT=6333,
        COLLECTION_NAME="test_docs",
        EMBEDDING_MODEL="all-MiniLM-L6-v2",
        EMBEDDING_DIMENSION=3,
        CHUNK_SIZE=500,
        CHUNK_OVERLAP=50,
        DEFAULT_TOP_K=3,
        RERANK_CANDIDATES=10,
        RERANK_TOP_N=3,
        ENABLE_RERANK=False,
        HYBRID_DENSE_TOP_K=10,
        HYBRID_BM25_TOP_K=10,
    )


@pytest.fixture
def fake_embeddings() -> MagicMock:
    embeddings = MagicMock()
    embeddings.embed_documents.side_effect = lambda texts: [[0.1, 0.2, 0.3] for _ in texts]
    embeddings.embed_query.return_value = [0.1, 0.2, 0.3]
    return embeddings


@pytest.fixture
def fake_qdrant() -> MagicMock:
    qdrant = MagicMock()
    collection = MagicMock()
    collection.name = "test_docs"
    qdrant.get_collections.return_value.collections = [collection]
    return qdrant


@pytest.fixture
def pipeline(settings: Settings, fake_embeddings: MagicMock, fake_qdrant: MagicMock) -> RagPipeline:
    return RagPipeline(
        settings=settings,
        embeddings=fake_embeddings,
        qdrant=fake_qdrant,
        bm25_store=Bm25Store(),
        reranker=MagicMock(),
    )


def test_settings_expose_required_env_aliases() -> None:
    cfg = Settings(
        QDRANT_HOST="qdrant",
        QDRANT_PORT=6333,
        COLLECTION_NAME="tech_docs",
        EMBEDDING_MODEL="all-MiniLM-L6-v2",
        OPENAI_API_KEY="sk-test",
        OLLAMA_BASE_URL="http://ollama:11434",
    )
    assert cfg.qdrant_host == "qdrant"
    assert cfg.qdrant_port == 6333
    assert cfg.collection_name == "tech_docs"
    assert cfg.embedding_model == "all-MiniLM-L6-v2"
    assert cfg.openai_api_key == "sk-test"
    assert cfg.ollama_base_url == "http://ollama:11434"
    assert cfg.qdrant_url == "http://qdrant:6333"


def test_schemas_serialize_camel_case() -> None:
    request = IngestRequest(
        document_id="doc-1",
        title="Guide",
        content="Hello world",
        metadata={"source": "wiki"},
    )
    payload = request.model_dump(by_alias=True)
    assert payload["documentId"] == "doc-1"
    assert payload["metadata"]["source"] == "wiki"


def test_recursive_splitter_defaults() -> None:
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    text = "word " * 200
    chunks = splitter.split_text(text)
    assert len(chunks) >= 2
    assert all(len(chunk) <= 500 + 20 for chunk in chunks)


@pytest.mark.asyncio
async def test_ingest_indexes_chunks(
    pipeline: RagPipeline,
    fake_embeddings: MagicMock,
    fake_qdrant: MagicMock,
) -> None:
    request = IngestRequest(
        document_id="doc-42",
        title="Architecture",
        content="Tech-Doc-Intelligence uses FastAPI for RAG. " * 20,
        metadata={"team": "platform"},
    )
    response = await pipeline.ingest(request)

    assert response.success is True
    assert response.document_id == "doc-42"
    assert response.chunks_count >= 1
    fake_embeddings.embed_documents.assert_called_once()
    fake_qdrant.upsert.assert_called_once()
    fake_qdrant.delete.assert_called_once()


@pytest.mark.asyncio
async def test_query_hybrid_retrieve_and_heuristic_structured_answer(
    pipeline: RagPipeline,
    fake_qdrant: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hit = MagicMock()
    hit.score = 0.91
    hit.payload = {
        "document_id": "doc-42",
        "chunk_text": (
            "Root cause was RF jamming on UAV-Link-X. "
            "Mitigation steps include enabling anti-jam hop profile PROFILE_AJ_B."
        ),
    }
    fake_qdrant.search.return_value = [hit]

    monkeypatch.setattr(
        pipeline,
        "_answer_with_openai",
        AsyncMock(side_effect=RuntimeError("no key")),
    )
    monkeypatch.setattr(
        pipeline,
        "_answer_with_ollama",
        AsyncMock(side_effect=RuntimeError("ollama down")),
    )

    result = await pipeline.query(QueryRequest(query="What caused telemetry drops?", top_k=3))
    assert result.latency_ms >= 0
    assert len(result.sources) == 1
    assert result.sources[0].document_id == "doc-42"
    assert result.analysis is not None
    assert "Executive Summary" in result.answer
    assert "Root Cause" in result.answer
    assert "Mitigation" in result.answer
    assert "RF jamming" in result.analysis.root_cause_analysis


def test_bm25_store_ranks_keyword_matches() -> None:
    store = Bm25Store()
    store.add_chunks(
        document_id="a",
        title="UAV Link",
        point_ids=["1"],
        chunk_texts=["UAV telemetry dropped during RF jamming near WP-17"],
    )
    store.add_chunks(
        document_id="b",
        title="Thermal",
        point_ids=["2"],
        chunk_texts=["Mission computer thermal throttling under SAR ATR load"],
    )
    hits = store.search("RF jamming telemetry", top_k=2)
    assert hits
    assert hits[0][0].document_id == "a"


@pytest.mark.asyncio
async def test_health_and_endpoints_with_test_client(
    settings: Settings,
    fake_embeddings: MagicMock,
    fake_qdrant: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.rag.pipeline import RagPipeline as RealPipeline

    def _fake_get_pipeline() -> RealPipeline:
        pipe = RealPipeline(
            settings=settings,
            embeddings=fake_embeddings,
            qdrant=fake_qdrant,
            bm25_store=Bm25Store(),
            reranker=MagicMock(),
        )
        monkeypatch.setattr(
            pipe,
            "_answer_with_openai",
            AsyncMock(side_effect=RuntimeError("no key")),
        )
        monkeypatch.setattr(
            pipe,
            "_answer_with_ollama",
            AsyncMock(side_effect=RuntimeError("ollama down")),
        )
        return pipe

    monkeypatch.setattr("app.main.get_rag_pipeline", _fake_get_pipeline)

    hit = MagicMock()
    hit.score = 0.88
    hit.payload = {
        "document_id": "doc-1",
        "chunk_text": (
            "Hybrid RAG combines dense and BM25 signals. "
            "Root cause analysis uses retrieved reports. Mitigation: enable reranking."
        ),
    }
    fake_qdrant.search.return_value = [hit]

    app = create_app()
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["service"] == "ai-service"

        ingest = client.post(
            "/api/v1/ingest",
            json={
                "documentId": "doc-1",
                "title": "RAG Notes",
                "content": "Hybrid RAG combines dense and BM25 signals. " * 15,
                "metadata": {"source": "test"},
            },
        )
        assert ingest.status_code == 200
        body: dict[str, Any] = ingest.json()
        assert body["success"] is True
        assert body["chunksCount"] >= 1

        query = client.post(
            "/api/v1/query",
            json={"query": "What is hybrid RAG?", "topK": 3, "structured": True},
        )
        assert query.status_code == 200
        query_body = query.json()
        assert "answer" in query_body
        assert isinstance(query_body["sources"], list)
        assert "latencyMs" in query_body
        assert query_body["analysis"] is not None
        assert query_body.get("toolUsed") in {"HYBRID_RAG", "HYBRID_COMBINED", "SQL_METRICS"}
        assert "summary" in query_body

        analyze = client.post(
            "/api/v1/analyze",
            json={"query": "Summarize root causes", "topK": 3},
        )
        assert analyze.status_code == 200
        assert analyze.json()["analysis"]["executiveSummary"]
        assert analyze.json().get("toolUsed")
