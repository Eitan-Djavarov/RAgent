from __future__ import annotations

from app.citations.indexing import (
    attach_heuristic_markers,
    extract_citation_markers,
    index_citations,
    markers_are_valid,
)
from app.models.schemas import SourceCitation
from app.prompts.synthesis import STRUCTURED_SYSTEM_PROMPT, build_synthesis_user_prompt


def test_index_citations_assigns_one_based_indices_and_doc_id() -> None:
    sources = [
        SourceCitation(
            document_id="doc-a",
            chunk_text="parent A text",
            score=0.91,
            system="Radar-APG",
            severity="High",
        ),
        SourceCitation(
            document_id="doc-b",
            chunk_text="parent B text",
            score=0.77,
            system="EO/IR",
            severity="Medium",
        ),
    ]
    indexed = index_citations(sources)
    assert [item.citation_index for item in indexed] == [1, 2]
    assert indexed[0].doc_id == "doc-a"
    assert indexed[1].doc_id == "doc-b"
    payload = indexed[0].model_dump(by_alias=True)
    assert payload["citationIndex"] == 1
    assert payload["docId"] == "doc-a"
    assert payload["system"] == "Radar-APG"
    assert payload["severity"] == "High"
    assert payload["chunkText"] == "parent A text"
    assert payload["documentId"] == "doc-a"


def test_synthesis_prompt_requires_inline_markers() -> None:
    assert "[1]" in STRUCTURED_SYSTEM_PROMPT
    assert "every factual sentence" in STRUCTURED_SYSTEM_PROMPT.lower() or (
        "EVERY factual sentence" in STRUCTURED_SYSTEM_PROMPT
    )
    prompt = build_synthesis_user_prompt(
        query="What caused the AESA overflow?",
        context="[1] document_id=doc-1\nHeap exhaustion under multi-target load.",
    )
    assert "exact [n] markers" in prompt
    assert "[1] document_id=doc-1" in prompt


def test_extract_and_validate_citation_markers() -> None:
    text = (
        "Heap exhaustion caused watchdog resets [1]. "
        "Anti-jam profile PROFILE_AJ_B mitigated RF interference [2][1]."
    )
    assert extract_citation_markers(text) == [1, 2]
    citations = index_citations(
        [
            SourceCitation(document_id="a", chunk_text="x", score=0.9),
            SourceCitation(document_id="b", chunk_text="y", score=0.8),
        ]
    )
    assert markers_are_valid(text, citations) is True
    assert markers_are_valid("Unsupported claim [9].", citations) is False
    assert markers_are_valid("No markers here.", citations) is False


def test_attach_heuristic_markers() -> None:
    assert attach_heuristic_markers("Primary causal factor was RF jamming.", 1).endswith("[1].")
    already = "Already cited [2]."
    assert attach_heuristic_markers(already, 1) == already
