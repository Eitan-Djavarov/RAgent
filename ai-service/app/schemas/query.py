from typing import Any

from pydantic import Field

from app.schemas.base import ApiModel


class QueryRequest(ApiModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=3, ge=1, le=20)
    filter_metadata: dict[str, Any] | None = None
    structured: bool = True
    session_id: str | None = Field(default=None, max_length=128)


class SourceCitation(ApiModel):
    document_id: str
    chunk_text: str
    score: float = 0.0
    citation_index: int = Field(default=0, ge=0)
    doc_id: str | None = None
    parent_id: str | None = None
    system: str | None = None
    severity: str | None = None


class StructuredIncidentAnalysis(ApiModel):
    executive_summary: str
    root_cause_analysis: str
    recommended_mitigations: str
    source_citations: list[SourceCitation]


class SqlQueryResult(ApiModel):
    query: str
    row_count: int
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    interpretation: str = ""


class QueryResponse(ApiModel):
    answer: str
    sources: list[SourceCitation]
    latency_ms: float
    analysis: StructuredIncidentAnalysis | None = None
    retrieval_mode: str = "hybrid+rerank"
    tool_used: str = "HYBRID_RAG"
    sql_query_result: SqlQueryResult | None = None
    summary: str | None = None
    root_cause: str | None = None
    action_items: str | None = None
    citations: list[SourceCitation] | None = None
    cached: bool = False
    session_id: str | None = None
    original_query: str | None = None
    rewritten_query: str | None = None
    faithfulness_score: float | None = None
    is_grounded: bool | None = None
    unsupported_claims: list[str] | None = None


class AskIncidentRequest(ApiModel):
    """Alias schema aligned with backend AskIncidentQueryDto field names."""

    query_text: str = Field(min_length=1, max_length=4000, alias="queryText")
    top_k: int = Field(default=4, ge=1, le=20, alias="topK")
    system_name: str | None = Field(default=None, alias="systemName")
    min_severity: str | None = Field(default=None, alias="minSeverity")
    structured: bool = True
    session_id: str | None = Field(default=None, max_length=128, alias="sessionId")
