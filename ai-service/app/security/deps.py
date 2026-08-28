from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.models.schemas import ProblemDetails
from app.security.guardrails import (
    InputSecurityGuardrails,
    RateLimitExceededError,
    SecurityViolationError,
)
from app.security.rate_limiter import SlidingWindowRateLimiter

logger = logging.getLogger(__name__)

_RATE_LIMITED_PATH_PREFIXES = (
    "/api/v1/ask",
    "/api/v1/query",
    "/api/v1/analyze",
    "/api/v1/ingest",
)


def resolve_client_key(request: Request, session_id: str | None = None) -> str:
    if session_id and session_id.strip():
        return f"session:{session_id.strip()}"

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return f"ip:{forwarded.split(',')[0].strip()}"

    if request.client and request.client.host:
        return f"ip:{request.client.host}"
    return "ip:unknown"


def extract_query_text(payload: Any) -> str:
    if payload is None:
        return ""
    if hasattr(payload, "query_text"):
        return str(getattr(payload, "query_text") or "")
    if hasattr(payload, "query"):
        return str(getattr(payload, "query") or "")
    if isinstance(payload, dict):
        return str(payload.get("queryText") or payload.get("query") or "")
    return ""


def extract_session_id(payload: Any, request: Request) -> str | None:
    header_session = request.headers.get("x-session-id")
    if header_session:
        return header_session.strip()
    if payload is None:
        return None
    if hasattr(payload, "session_id"):
        value = getattr(payload, "session_id")
        return str(value).strip() if value else None
    if isinstance(payload, dict):
        value = payload.get("sessionId") or payload.get("session_id")
        return str(value).strip() if value else None
    return None


async def enforce_rate_limit(request: Request, session_id: str | None = None) -> None:
    limiter: SlidingWindowRateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None or not limiter.enabled:
        return
    client_key = resolve_client_key(request, session_id)
    decision = await limiter.check(client_key)
    request.state.rate_limit = decision
    if not decision.allowed:
        raise RateLimitExceededError(
            limit=decision.limit,
            remaining=decision.remaining,
            retry_after_seconds=decision.retry_after_seconds,
            client_key=decision.client_key,
        )


def enforce_guardrails(text: str, request: Request | None = None) -> None:
    guardrails: InputSecurityGuardrails | None = None
    if request is not None:
        guardrails = getattr(request.app.state, "guardrails", None)
    if guardrails is None:
        guardrails = InputSecurityGuardrails()
    guardrails.assert_safe(text)


def security_problem(
    *,
    status_code: int,
    title: str,
    detail: str,
    error_code: str,
    reason: str | None = None,
    trace_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = ProblemDetails(
        type=f"https://httpstatuses.com/{status_code}",
        title=title,
        status=status_code,
        detail=detail,
        trace_id=trace_id,
    ).model_dump(by_alias=True)
    body["errorCode"] = error_code
    if reason:
        body["reason"] = reason
    if extra:
        body.update(extra)
    return body


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Applies sliding-window rate limits to selected AI API routes."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if not any(path.startswith(prefix) for prefix in _RATE_LIMITED_PATH_PREFIXES):
            return await call_next(request)

        limiter: SlidingWindowRateLimiter | None = getattr(request.app.state, "rate_limiter", None)
        if limiter is None or not limiter.enabled:
            return await call_next(request)

        session_hint = request.headers.get("x-session-id")
        try:
            await enforce_rate_limit(request, session_hint)
        except RateLimitExceededError as exc:
            headers = {
                "Retry-After": str(exc.retry_after_seconds),
                "X-RateLimit-Limit": str(exc.limit),
                "X-RateLimit-Remaining": str(exc.remaining),
            }
            return JSONResponse(
                status_code=429,
                content=security_problem(
                    status_code=429,
                    title="Rate limit exceeded",
                    detail=str(exc),
                    error_code="RATE_LIMITED",
                    reason="Too many requests for this client IP / session.",
                    trace_id=request.headers.get("x-correlation-id"),
                    extra={"retryAfterSeconds": exc.retry_after_seconds},
                ),
                headers=headers,
            )

        response = await call_next(request)
        decision = getattr(request.state, "rate_limit", None)
        if decision is not None:
            response.headers["X-RateLimit-Limit"] = str(decision.limit)
            response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        return response
