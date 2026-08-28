from __future__ import annotations

from app.agent.router import ExecutionStrategy, classify_intent


def test_classify_sql_metrics_for_count_queries() -> None:
    assert classify_intent("How many Critical incidents?") == ExecutionStrategy.SQL_METRICS
    assert classify_intent("List incidents by hardware component") == ExecutionStrategy.SQL_METRICS


def test_classify_hybrid_rag_for_analytical_queries() -> None:
    assert (
        classify_intent("What caused the buffer overflow in the AESA radar?")
        == ExecutionStrategy.HYBRID_RAG
    )


def test_classify_combined_when_metrics_and_analysis_present() -> None:
    assert (
        classify_intent("How many critical incidents and what caused the UAV jamming failures?")
        == ExecutionStrategy.HYBRID_COMBINED
    )
