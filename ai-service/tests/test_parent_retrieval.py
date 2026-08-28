from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.config import Settings
from app.ingestion.hierarchical_chunker import HierarchicalChunker
from app.models.schemas import QueryRequest, SourceCitation
from app.rag.bm25_store import Bm25Store
from app.rag.pipeline import RagPipeline
from app.retrieval.parent_expansion import (
    LOW_RELEVANCE_MESSAGE,
    RetrievalHit,
    expand_and_dedupe_parents,
    filter_by_min_score,
    low_relevance_answer,
    meets_min_score_threshold,
)


def test_hierarchical_chunker_builds_parent_child_links() -> None:
    chunker = HierarchicalChunker(
        parent_chunk_size=220,
        parent_chunk_overlap=20,
        child_chunk_size=80,
        child_chunk_overlap=10,
    )
    # Two paragraph-ish sections so parents split cleanly.
    section_a = "AESA radar track allocator exhausted heap during multi-target tracking. " * 4
    section_b = "Operators observed watchdog resets on the signal processor under load. " * 4
    content = f"{section_a}\n\n{section_b}"
    result = chunker.split(content, document_id="doc-radar")

    assert result.parent_count >= 1
    assert result.child_count >= result.parent_count
    assert all(child.parent_id.startswith("doc-radar::parent::") for child in result.children)
    assert all(child.parent_text for child in result.children)
    assert all(len(child.text) <= 120 for child in result.children)
    # Every child parent_text must match a parent entry.
    parent_by_id = {parent.parent_id: parent.text for parent in result.parents}
    for child in result.children:
        assert parent_by_id[child.parent_id] == child.parent_text


def test_expand_and_dedupe_parents_keeps_best_score() -> None:
    hits = [
        RetrievalHit(
            document_id="doc-1",
            chunk_text="child-a1",
            score=0.92,
            parent_id="doc-1::parent::0",
            parent_text="Full parent paragraph A with rich context.",
        ),
        RetrievalHit(
            document_id="doc-1",
            chunk_text="child-a2",
            score=0.81,
            parent_id="doc-1::parent::0",
            parent_text="Full parent paragraph A with rich context.",
        ),
        RetrievalHit(
            document_id="doc-1",
            chunk_text="child-b1",
            score=0.77,
            parent_id="doc-1::parent::1",
            parent_text="Full parent paragraph B about mitigations.",
        ),
    ]
    expanded = expand_and_dedupe_parents(hits, top_n=5)
    assert len(expanded) == 2
    assert expanded[0].parent_id == "doc-1::parent::0"
    assert expanded[0].chunk_text.startswith("Full parent paragraph A")
    assert expanded[0].score == 0.92
    assert expanded[1].parent_id == "doc-1::parent::1"


def test_min_score_threshold_helpers() -> None:
    sources = [
        SourceCitation(document_id="a", chunk_text="x", score=0.35),
        SourceCitation(document_id="b", chunk_text="y", score=0.22),
    ]
    assert meets_min_score_threshold(sources, min_score=0.40) is False
    assert filter_by_min_score(sources, min_score=0.40) == []

    sources[0] = SourceCitation(document_id="a", chunk_text="x", score=0.55)
    assert meets_min_score_threshold(sources, min_score=0.40) is True
    kept = filter_by_min_score(sources, min_score=0.40)
    assert len(kept) == 1
    assert kept[0].document_id == "a"
    assert LOW_RELEVANCE_MESSAGE in low_relevance_answer()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        QDRANT_HOST="localhost",
        QDRANT_PORT=6333,
        COLLECTION_NAME="test_docs",
        EMBEDDING_MODEL="all-MiniLM-L6-v2",
        EMBEDDING_DIMENSION=3,
        PARENT_CHUNK_SIZE=300,
        PARENT_CHUNK_OVERLAP=40,
        CHILD_CHUNK_SIZE=100,
        CHILD_CHUNK_OVERLAP=20,
        MIN_RETRIEVAL_SCORE=0.40,
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


@pytest.mark.asyncio
async def test_ingest_indexes_child_chunks_with_parent_payload(
    pipeline: RagPipeline,
    fake_qdrant: MagicMock,
) -> None:
    from app.models.schemas import IngestRequest

    content = (
        "Hydraulic actuator lag exceeded thresholds after seal degradation. " * 8
        + "\n\n"
        + "Maintenance replaced seals and re-baselined latency checks. " * 8
    )
    response = await pipeline.ingest(
        IngestRequest(
            document_id="doc-elevon",
            title="Elevon Actuator",
            content=content,
            metadata={"systemName": "FlightControls"},
        )
    )
    assert response.success is True
    assert response.chunks_count >= 2
    upsert_kwargs = fake_qdrant.upsert.call_args.kwargs
    points = upsert_kwargs["points"]
    assert points
    payload = points[0].payload
    assert payload["chunk_role"] == "child"
    assert payload["parent_id"]
    assert payload["parent_text"]
    assert payload["chunk_text"]
    assert len(payload["parent_text"]) >= len(payload["chunk_text"])


@pytest.mark.asyncio
async def test_retrieve_expands_parents_and_dedupes(
    pipeline: RagPipeline,
    fake_qdrant: MagicMock,
) -> None:
    parent_text = (
        "Coolant pump P-12 tripped on overcurrent after bearing seizure. "
        "Maintenance replaced the bearing and restored flow within two hours."
    )
    hit_a = MagicMock()
    hit_a.score = 0.88
    hit_a.payload = {
        "document_id": "doc-coolant",
        "chunk_text": "Coolant pump P-12 tripped on overcurrent",
        "parent_id": "doc-coolant::parent::0",
        "parent_text": parent_text,
    }
    hit_b = MagicMock()
    hit_b.score = 0.81
    hit_b.payload = {
        "document_id": "doc-coolant",
        "chunk_text": "bearing seizure. Maintenance replaced the bearing",
        "parent_id": "doc-coolant::parent::0",
        "parent_text": parent_text,
    }
    fake_qdrant.search.return_value = [hit_a, hit_b]

    sources = await pipeline.retrieve("coolant pump trip", top_n=3, filter_metadata=None)
    assert len(sources) == 1
    assert sources[0].parent_id == "doc-coolant::parent::0"
    assert sources[0].chunk_text == parent_text
    assert sources[0].score >= 0.40


@pytest.mark.asyncio
async def test_retrieve_short_circuits_below_min_score(
    pipeline: RagPipeline,
    fake_qdrant: MagicMock,
) -> None:
    hit = MagicMock()
    hit.score = 0.12
    hit.payload = {
        "document_id": "doc-noise",
        "chunk_text": "unrelated logistics warehouse barcode scanner glitch",
        "parent_id": "doc-noise::parent::0",
        "parent_text": "unrelated logistics warehouse barcode scanner glitch notes",
    }
    fake_qdrant.search.return_value = [hit]

    sources = await pipeline.retrieve("AESA radar buffer overflow", top_n=3, filter_metadata=None)
    assert sources == []


@pytest.mark.asyncio
async def test_query_skips_llm_when_below_threshold(
    pipeline: RagPipeline,
    fake_qdrant: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hit = MagicMock()
    hit.score = 0.05
    hit.payload = {
        "document_id": "doc-noise",
        "chunk_text": "office printer paper jam",
        "parent_id": "doc-noise::parent::0",
        "parent_text": "office printer paper jam advisory",
    }
    fake_qdrant.search.return_value = [hit]

    openai_mock = MagicMock()
    ollama_mock = MagicMock()
    monkeypatch.setattr(pipeline, "_answer_with_openai", openai_mock)
    monkeypatch.setattr(pipeline, "_answer_with_ollama", ollama_mock)

    result = await pipeline.query(QueryRequest(query="What caused AESA overflow?", top_k=3))
    assert result.sources == []
    assert LOW_RELEVANCE_MESSAGE in result.answer
    assert result.summary == LOW_RELEVANCE_MESSAGE
    openai_mock.assert_not_called()
    ollama_mock.assert_not_called()
