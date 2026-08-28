from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from qdrant_client.http import models as qmodels

from app.cache.semantic_cache import SemanticCache
from app.core.config import Settings
from app.models.schemas import DocumentDeleteResponse, DocumentListItem
from app.rag.pipeline import RagPipeline

logger = logging.getLogger(__name__)


class DocumentManagementService:
    """Synchronized document listing and cascade deletion across Qdrant, Postgres, and Redis."""

    def __init__(
        self,
        settings: Settings,
        pipeline: RagPipeline,
        semantic_cache: SemanticCache | None = None,
    ) -> None:
        self._settings = settings
        self._pipeline = pipeline
        self._cache = semantic_cache
        self._dsn = (
            f"host={settings.postgres_host} "
            f"port={settings.postgres_port} "
            f"dbname={settings.postgres_db} "
            f"user={settings.postgres_user} "
            f"password={settings.postgres_password}"
        )

    async def list_documents(self) -> list[DocumentListItem]:
        rows = await self._fetch_incidents()
        chunk_counts = await asyncio.to_thread(self._pipeline.count_chunks_by_document)
        documents: list[DocumentListItem] = []
        for row in rows:
            document_id = str(row["id"])
            created_at = row.get("created_at")
            if isinstance(created_at, datetime) and created_at.tzinfo is None:
                # Normalize naive timestamps from drivers.
                created_at = created_at.replace(tzinfo=None)
            documents.append(
                DocumentListItem(
                    document_id=document_id,
                    title=str(row.get("title") or ""),
                    system_name=str(row.get("system_name") or ""),
                    severity=str(row.get("severity") or ""),
                    chunk_count=int(chunk_counts.get(document_id, 0)),
                    created_at=created_at if isinstance(created_at, datetime) else datetime.now(timezone.utc),
                )
            )
        return documents

    async def delete_document(self, document_id: str) -> DocumentDeleteResponse:
        doc_id = document_id.strip()
        if not doc_id:
            raise ValueError("document_id is required.")

        vectors_deleted = await asyncio.to_thread(self._pipeline.delete_document, doc_id)
        postgres_deleted = await self._delete_postgres_incident(doc_id)
        cache_entries_invalidated = 0
        if self._cache is not None:
            cache_entries_invalidated = await self._cache.invalidate_document(doc_id)

        status = "deleted" if (vectors_deleted > 0 or postgres_deleted) else "not_found"
        message = (
            f"Cascade delete for {doc_id}: vectors={vectors_deleted}, "
            f"postgres={'yes' if postgres_deleted else 'no'}, "
            f"cacheEntries={cache_entries_invalidated}."
        )
        logger.info(message)
        return DocumentDeleteResponse(
            success=status == "deleted",
            document_id=doc_id,
            status=status,
            vectors_deleted=vectors_deleted,
            postgres_deleted=postgres_deleted,
            cache_entries_invalidated=cache_entries_invalidated,
            message=message,
        )

    async def _fetch_incidents(self) -> list[dict[str, Any]]:
        sql = """
            SELECT id, title, system_name, severity, created_at
            FROM incidents
            ORDER BY created_at DESC
            LIMIT 500
        """
        async with await psycopg.AsyncConnection.connect(
            self._dsn,
            row_factory=dict_row,
            autocommit=True,
        ) as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql)
                rows = await cur.fetchall()
        return list(rows)

    async def _delete_postgres_incident(self, document_id: str) -> bool:
        sql = "DELETE FROM incidents WHERE id = %(id)s::uuid RETURNING id"
        try:
            async with await psycopg.AsyncConnection.connect(self._dsn, autocommit=True) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql, {"id": document_id})
                    row = await cur.fetchone()
                    return row is not None
        except Exception:
            logger.exception("Failed deleting incident %s from Postgres", document_id)
            raise
