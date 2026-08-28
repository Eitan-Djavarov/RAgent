from __future__ import annotations

import re
from enum import Enum


class ExecutionStrategy(str, Enum):
    HYBRID_RAG = "HYBRID_RAG"
    SQL_METRICS = "SQL_METRICS"
    HYBRID_COMBINED = "HYBRID_COMBINED"


_SQL_HINTS = (
    r"\bhow many\b",
    r"\bcount\b",
    r"\btotal\b",
    r"\baggregat",
    r"\bbreakdown\b",
    r"\bstatistics\b",
    r"\bmetrics\b",
    r"\blist (all |the )?(incidents|reports)\b",
    r"\bgroup(ed)? by\b",
    r"\bby (system|hardware|component|severity)\b",
    r"\bnumber of\b",
)

_RAG_HINTS = (
    r"\bwhy\b",
    r"\bcause\b",
    r"\broot cause\b",
    r"\bmitigat",
    r"\bsymptom",
    r"\banaly[sz]e\b",
    r"\bexplain\b",
    r"\bwhat happened\b",
    r"\brecommend",
    r"\bfirmware\b",
    r"\btelemetry\b",
    r"\bjamming\b",
    r"\boverflow\b",
    r"\bdrift\b",
)


def classify_intent(query: str) -> ExecutionStrategy:
    """Rule-based intent router selecting the execution strategy."""
    text = query.strip().lower()
    sql_score = sum(1 for pattern in _SQL_HINTS if re.search(pattern, text))
    rag_score = sum(1 for pattern in _RAG_HINTS if re.search(pattern, text))

    if sql_score > 0 and rag_score > 0:
        return ExecutionStrategy.HYBRID_COMBINED
    if sql_score > 0 and rag_score == 0:
        return ExecutionStrategy.SQL_METRICS
    if rag_score > 0:
        return ExecutionStrategy.HYBRID_RAG
    if any(token in text for token in ("how many", "count", "list")):
        return ExecutionStrategy.SQL_METRICS
    return ExecutionStrategy.HYBRID_RAG
