from __future__ import annotations

from app.rag.pipeline import RagPipeline


def test_chunk_text_splits_deterministically() -> None:
    chunks = RagPipeline._chunk_text("abcdefghij", size=4)
    assert chunks == ["abcd", "efgh", "ij"]


def test_chunk_text_empty() -> None:
    assert RagPipeline._chunk_text("") == []
