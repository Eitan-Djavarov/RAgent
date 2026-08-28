from __future__ import annotations

from app.agent.query_rewriter import QueryRewriter
from app.cache.session_memory import SessionMemory


def test_format_history_for_prompt() -> None:
    history = [
        {
            "role_user": "What caused AESA overflow?",
            "role_assistant": "Buffer overflow in track processor.",
        },
        {
            "role_user": "What about mitigations?",
            "role_assistant": "Add RSS governor.",
        },
    ]
    text = SessionMemory.format_history_for_prompt(history)
    assert "AESA overflow" in text
    assert "mitigations" in text


def test_heuristic_rewrite_expands_follow_up() -> None:
    rewriter = QueryRewriter.__new__(QueryRewriter)
    history = [
        {
            "role_user": "What caused AESA radar buffer overflow?",
            "role_assistant": "Scratch arena leak under TWS load.",
            "rewritten_query": "What caused AESA radar buffer overflow?",
        }
    ]
    rewritten = QueryRewriter._heuristic_rewrite("What about mitigations for it?", history)
    assert "AESA" in rewritten or "context:" in rewritten.lower()


def test_sanitize_strips_labels() -> None:
    cleaned = QueryRewriter._sanitize(
        'Rewritten query: How many Critical incidents?',
        fallback="fallback",
    )
    assert cleaned == "How many Critical incidents?"
