from datetime import datetime, timezone
from typing import Any

from pydantic import Field

from app.schemas.base import ApiModel


class HealthResponse(ApiModel):
    status: str
    service: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: dict[str, Any] = Field(default_factory=dict)


class ProblemDetails(ApiModel):
    type: str
    title: str
    status: int
    detail: str
    trace_id: str | None = None
    error_code: str | None = None
    reason: str | None = None
