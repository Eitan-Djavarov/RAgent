from __future__ import annotations

from app.cache.semantic_cache import SemanticCache


def test_response_references_document_by_citation() -> None:
    response = {
        "citations": [{"documentId": "abc-123", "chunkText": "x", "score": 0.9}],
        "sources": [],
    }
    assert SemanticCache._response_references_document(response, "abc-123")
    assert not SemanticCache._response_references_document(response, "other")


def test_response_references_document_in_analysis() -> None:
    response = {
        "analysis": {
            "sourceCitations": [{"documentId": "doc-9", "chunkText": "y", "score": 0.5}]
        }
    }
    assert SemanticCache._response_references_document(response, "doc-9")
