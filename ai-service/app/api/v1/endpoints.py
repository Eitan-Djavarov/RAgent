from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from app.agent.orchestrator import AgenticOrchestrator
from app.models.schemas import (
    AskIncidentRequest,
    CacheClearResponse,
    DocumentDeleteResponse,
    DocumentListResponse,
    FileIngestResponse,
    IngestRequest,
    IngestResponse,
    QueryRequest,
    QueryResponse,
    SessionClearResponse,
    StructuredIncidentAnalysis,
)
from app.cache.semantic_cache import SemanticCache
from app.cache.session_memory import SessionMemory
from app.rag.document_management import DocumentManagementService
from app.rag.file_ingestion import FileIngestionService
from app.rag.pipeline import RagPipeline
from app.security.deps import enforce_guardrails, extract_query_text

router = APIRouter(tags=["rag"])


def _get_pipeline(request: Request) -> RagPipeline:
    pipeline = getattr(request.app.state, "rag_pipeline", None)
    if pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG pipeline is not initialized.",
        )
    return pipeline


def _get_file_ingestion(request: Request) -> FileIngestionService:
    service = getattr(request.app.state, "file_ingestion", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="File ingestion service is not initialized.",
        )
    return service


def _get_orchestrator(request: Request) -> AgenticOrchestrator:
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agentic orchestrator is not initialized.",
        )
    return orchestrator


def _get_semantic_cache(request: Request) -> SemanticCache:
    cache = getattr(request.app.state, "semantic_cache", None)
    if cache is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Semantic cache is not initialized.",
        )
    return cache


def _get_session_memory(request: Request) -> SessionMemory:
    memory = getattr(request.app.state, "session_memory", None)
    if memory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session memory is not initialized.",
        )
    return memory


def _get_document_management(request: Request) -> DocumentManagementService:
    service = getattr(request.app.state, "document_management", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document management service is not initialized.",
        )
    return service


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]


@router.post(
    "/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_200_OK,
    summary="Ingest and index a document (dense + BM25)",
)
async def ingest_document(payload: IngestRequest, request: Request) -> IngestResponse:
    pipeline = _get_pipeline(request)
    try:
        result = await pipeline.ingest(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Document ingestion failed: {exc}",
        ) from exc

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.message,
        )
    return result


@router.post(
    "/ingest/file",
    response_model=FileIngestResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload PDF/TXT/MD, chunk, embed, index, and sync Postgres",
)
async def ingest_uploaded_file(
    request: Request,
    file: UploadFile = File(...),
    system: str = Form(...),
    severity: str = Form(...),
    subsystemTags: str = Form(""),
    title: str | None = Form(None),
) -> FileIngestResponse:
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must include a filename.",
        )

    file_bytes = await file.read()
    service = _get_file_ingestion(request)
    try:
        result = await service.ingest_file(
            filename=file.filename,
            file_bytes=file_bytes,
            title=title,
            system_name=system,
            severity=severity,
            subsystem_tags=_parse_tags(subsystemTags),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"File ingestion failed: {exc}",
        ) from exc

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.message,
        )
    return result


@router.post(
    "/query",
    response_model=QueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Agentic router over hybrid RAG and/or SQL metrics tools",
)
async def query_documents(payload: QueryRequest, request: Request) -> QueryResponse:
    enforce_guardrails(extract_query_text(payload), request)
    orchestrator = _get_orchestrator(request)
    try:
        return await orchestrator.ask(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"RAG query failed: {exc}",
        ) from exc


@router.post(
    "/ask",
    response_model=QueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Ask endpoint: intent router + tool calling (RAG / SQL / combined)",
)
async def ask_incidents(payload: AskIncidentRequest, request: Request) -> QueryResponse:
    enforce_guardrails(extract_query_text(payload), request)
    filter_metadata: dict[str, str] = {"type": "incident"}
    if payload.system_name:
        filter_metadata["systemName"] = payload.system_name
    if payload.min_severity:
        filter_metadata["severity"] = payload.min_severity

    query = QueryRequest(
        query=payload.query_text,
        top_k=payload.top_k,
        filter_metadata=filter_metadata,
        structured=payload.structured,
        session_id=payload.session_id,
    )
    orchestrator = _get_orchestrator(request)
    try:
        return await orchestrator.ask(query)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ask orchestration failed: {exc}",
        ) from exc


@router.post(
    "/ask/stream",
    status_code=status.HTTP_200_OK,
    summary="SSE token streaming ask with metadata then LLM deltas",
)
async def ask_incidents_stream(
    payload: QueryRequest,
    request: Request,
) -> StreamingResponse:
    """Accepts the shared QueryRequest contract used by the .NET streaming proxy."""
    enforce_guardrails(extract_query_text(payload), request)
    orchestrator = _get_orchestrator(request)

    async def event_generator() -> Any:
        try:
            async for frame in orchestrator.ask_stream(payload):
                yield frame
        except Exception as exc:  # noqa: BLE001
            yield f'data: {{"event": "error", "detail": {json.dumps(str(exc))}}}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/analyze",
    response_model=QueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Structured agentic incident analysis over hybrid-reranked evidence",
)
async def analyze_incidents(payload: QueryRequest, request: Request) -> QueryResponse:
    enforce_guardrails(extract_query_text(payload), request)
    orchestrator = _get_orchestrator(request)
    forced = payload.model_copy(update={"structured": True, "top_k": min(payload.top_k, 3)})
    try:
        result = await orchestrator.ask(forced)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Structured analysis failed: {exc}",
        ) from exc

    if result.analysis is None:
        result = result.model_copy(
            update={
                "analysis": StructuredIncidentAnalysis(
                    executive_summary=result.summary or "No analysis produced.",
                    root_cause_analysis=result.root_cause or "Insufficient evidence.",
                    recommended_mitigations=result.action_items
                    or "Ingest reports and retry.",
                    source_citations=result.sources,
                )
            }
        )
    return result


@router.get(
    "/documents",
    response_model=DocumentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List indexed incident documents with metadata",
)
async def list_documents(request: Request) -> DocumentListResponse:
    service = _get_document_management(request)
    try:
        documents = await service.list_documents()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to list documents: {exc}",
        ) from exc
    return DocumentListResponse(documents=documents, count=len(documents))


@router.delete(
    "/documents/{document_id}",
    response_model=DocumentDeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Cascade-delete a document from Qdrant, Postgres, and semantic cache",
)
async def delete_document(document_id: str, request: Request) -> DocumentDeleteResponse:
    service = _get_document_management(request)
    try:
        result = await service.delete_document(document_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to delete document: {exc}",
        ) from exc

    if result.status == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result.message,
        )
    return result


@router.delete(
    "/cache",
    response_model=CacheClearResponse,
    status_code=status.HTTP_200_OK,
    summary="Clear the Redis semantic query cache",
)
async def clear_semantic_cache(request: Request) -> CacheClearResponse:
    cache = _get_semantic_cache(request)
    try:
        deleted = await cache.clear()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to clear semantic cache: {exc}",
        ) from exc
    return CacheClearResponse(
        success=True,
        deleted_keys=deleted,
        message=f"Cleared {deleted} cache key(s).",
    )


@router.delete(
    "/sessions/{session_id}",
    response_model=SessionClearResponse,
    status_code=status.HTTP_200_OK,
    summary="Clear Redis conversational memory for a session",
)
async def clear_session_memory(session_id: str, request: Request) -> SessionClearResponse:
    memory = _get_session_memory(request)
    try:
        cleared = await memory.clear(session_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to clear session memory: {exc}",
        ) from exc
    return SessionClearResponse(
        success=True,
        session_id=session_id,
        message="Session cleared." if cleared else "Session had no stored history.",
    )
