from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.agent.orchestrator import AgenticOrchestrator
from app.agent.sql_tool import ReadOnlyIncidentSqlTool
from app.cache.semantic_cache import SemanticCache
from app.cache.session_memory import SessionMemory
from app.agent.grounding_guard import GroundingGuard
from app.agent.query_rewriter import QueryRewriter
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.models.schemas import HealthResponse, ProblemDetails
from app.rag.file_ingestion import FileIngestionService
from app.rag.document_management import DocumentManagementService
from app.rag.pipeline import get_rag_pipeline
from app.security.deps import RateLimitMiddleware, security_problem
from app.security.guardrails import (
    InputSecurityGuardrails,
    RateLimitExceededError,
    SecurityViolationError,
)
from app.security.rate_limiter import SlidingWindowRateLimiter


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    pipeline = get_rag_pipeline()
    redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    semantic_cache = SemanticCache(
        settings=settings,
        redis_client=redis_client,
        embed_query=pipeline.embed_query,
    )
    session_memory = SessionMemory(
        redis_client=redis_client,
        ttl_seconds=settings.session_memory_ttl_seconds,
    )
    rate_limiter = SlidingWindowRateLimiter(
        redis_client,
        limit=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
        enabled=settings.rate_limit_enabled,
    )
    query_rewriter = QueryRewriter(settings)
    grounding_guard = GroundingGuard(settings) if settings.grounding_enabled else None
    app.state.rag_pipeline = pipeline
    app.state.redis = redis_client
    app.state.semantic_cache = semantic_cache
    app.state.session_memory = session_memory
    app.state.rate_limiter = rate_limiter
    app.state.guardrails = InputSecurityGuardrails()
    app.state.file_ingestion = FileIngestionService(settings, pipeline)
    app.state.document_management = DocumentManagementService(
        settings=settings,
        pipeline=pipeline,
        semantic_cache=semantic_cache,
    )
    app.state.orchestrator = AgenticOrchestrator(
        rag_pipeline=pipeline,
        sql_tool=ReadOnlyIncidentSqlTool(settings),
        semantic_cache=semantic_cache,
        session_memory=session_memory,
        query_rewriter=query_rewriter,
        grounding_guard=grounding_guard,
    )
    yield
    app.state.rag_pipeline = None
    app.state.file_ingestion = None
    app.state.document_management = None
    app.state.orchestrator = None
    app.state.semantic_cache = None
    app.state.session_memory = None
    app.state.rate_limiter = None
    app.state.guardrails = None
    await redis_client.aclose()
    app.state.redis = None


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    application.add_middleware(RateLimitMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.exception_handler(RateLimitExceededError)
    async def rate_limit_handler(
        request: Request,
        exc: RateLimitExceededError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=security_problem(
                status_code=429,
                title="Rate limit exceeded",
                detail=str(exc),
                error_code="RATE_LIMITED",
                reason="Too many requests for this client IP / session.",
                trace_id=request.headers.get("x-correlation-id"),
                extra={"retryAfterSeconds": exc.retry_after_seconds},
            ),
            headers={
                "Retry-After": str(exc.retry_after_seconds),
                "X-RateLimit-Limit": str(exc.limit),
                "X-RateLimit-Remaining": str(exc.remaining),
            },
        )

    @application.exception_handler(SecurityViolationError)
    async def security_violation_handler(
        request: Request,
        exc: SecurityViolationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=security_problem(
                status_code=400,
                title="Security guardrail violation",
                detail=exc.reason,
                error_code="SECURITY_VIOLATION",
                reason=exc.category,
                trace_id=request.headers.get("x-correlation-id"),
                extra={"matched": exc.matched} if exc.matched else None,
            ),
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        detail = exc.detail
        error_code = None
        reason = None
        if isinstance(detail, dict):
            error_code = detail.get("errorCode") or detail.get("error_code")
            reason = detail.get("reason")
            detail_text = str(detail.get("detail") or detail)
        else:
            detail_text = str(detail)
        body = ProblemDetails(
            type=f"https://httpstatuses.com/{exc.status_code}",
            title="Request failed",
            status=exc.status_code,
            detail=detail_text,
            trace_id=request.headers.get("x-correlation-id"),
            error_code=error_code,
            reason=reason,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=body.model_dump(by_alias=True),
        )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        body = ProblemDetails(
            type="https://tools.ietf.org/html/rfc7807",
            title="Validation failed",
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc.errors()),
            trace_id=request.headers.get("x-correlation-id"),
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=body.model_dump(by_alias=True),
        )

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        body = ProblemDetails(
            type="https://httpstatuses.com/500",
            title="Internal server error",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
            trace_id=request.headers.get("x-correlation-id"),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=body.model_dump(by_alias=True),
        )

    @application.get("/health", response_model=HealthResponse, tags=["health"])
    async def health(request: Request) -> HealthResponse:
        pipeline = getattr(request.app.state, "rag_pipeline", None)
        cache = getattr(request.app.state, "semantic_cache", None)
        qdrant_ok = False
        detail = "unavailable"
        if pipeline is not None:
            qdrant_ok, detail = pipeline.is_ready()

        redis_ok = False
        if cache is not None:
            redis_ok = await cache.ping()

        healthy = qdrant_ok and (redis_ok or not settings.semantic_cache_enabled)
        return HealthResponse(
            status="Healthy" if healthy else "Degraded",
            service="ai-service",
            details={
                "qdrant": detail,
                "redis": "up" if redis_ok else "down",
                "semanticCacheEnabled": settings.semantic_cache_enabled,
                "semanticCacheTtlSeconds": settings.semantic_cache_ttl_seconds,
                "semanticCacheThreshold": settings.semantic_cache_similarity_threshold,
                "rateLimitEnabled": settings.rate_limit_enabled,
                "rateLimitRequests": settings.rate_limit_requests,
                "rateLimitWindowSeconds": settings.rate_limit_window_seconds,
                "collection": settings.collection_name,
                "embeddingModel": settings.embedding_model,
                "environment": settings.environment,
            },
        )

    application.include_router(api_router)
    return application


app = create_app()
