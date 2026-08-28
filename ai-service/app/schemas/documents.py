from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.base import ApiModel


class IngestRequest(ApiModel):
    document_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestResponse(ApiModel):
    success: bool
    document_id: str
    chunks_count: int
    message: str


class FileIngestResponse(ApiModel):
    success: bool
    document_id: str
    chunk_count: int
    status: str
    message: str
    title: str | None = None
    system_name: str | None = None
    severity: str | None = None


class DocumentListItem(ApiModel):
    document_id: str
    title: str
    system_name: str
    severity: str
    chunk_count: int
    created_at: datetime


class DocumentListResponse(ApiModel):
    documents: list[DocumentListItem]
    count: int


class DocumentDeleteResponse(ApiModel):
    success: bool
    document_id: str
    status: str
    vectors_deleted: int
    postgres_deleted: bool
    cache_entries_invalidated: int
    message: str
