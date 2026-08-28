from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg

from app.core.config import Settings
from app.models.schemas import FileIngestResponse, IngestRequest
from app.rag.document_parser import extract_text_from_bytes
from app.rag.pipeline import RagPipeline

logger = logging.getLogger(__name__)

_SEVERITY_CANONICAL = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "med": "Medium",
    "low": "Low",
}


class FileIngestionService:
    """Parse uploaded documents, index into Qdrant, and sync Postgres incidents."""

    def __init__(self, settings: Settings, pipeline: RagPipeline) -> None:
        self._settings = settings
        self._pipeline = pipeline
        self._dsn = (
            f"host={settings.postgres_host} "
            f"port={settings.postgres_port} "
            f"dbname={settings.postgres_db} "
            f"user={settings.postgres_user} "
            f"password={settings.postgres_password}"
        )

    async def ingest_file(
        self,
        *,
        filename: str,
        file_bytes: bytes,
        title: str | None,
        system_name: str,
        severity: str,
        subsystem_tags: list[str],
    ) -> FileIngestResponse:
        text = extract_text_from_bytes(filename, file_bytes)
        document_id = str(uuid.uuid4())
        resolved_title = (title or Path(filename).stem).strip() or "Uploaded Incident"
        canonical_severity = _SEVERITY_CANONICAL.get(severity.strip().lower(), "Medium")
        system = system_name.strip()

        metadata: dict[str, Any] = {
            "type": "incident",
            "systemName": system,
            "severity": canonical_severity,
            "sourceFilename": filename,
            "ingestionChannel": "file-upload",
        }
        if subsystem_tags:
            metadata["subsystemTags"] = ",".join(subsystem_tags)

        ingest_result = await self._pipeline.ingest(
            IngestRequest(
                document_id=document_id,
                title=resolved_title,
                content=text,
                metadata=metadata,
            )
        )
        if not ingest_result.success:
            return FileIngestResponse(
                success=False,
                document_id=document_id,
                chunk_count=0,
                status="failed",
                message=ingest_result.message,
                title=resolved_title,
                system_name=system,
                severity=canonical_severity,
            )

        await self._sync_postgres_incident(
            document_id=document_id,
            title=resolved_title,
            description=text,
            system_name=system,
            severity=canonical_severity,
            chunk_count=ingest_result.chunks_count,
            message=ingest_result.message,
        )

        return FileIngestResponse(
            success=True,
            document_id=document_id,
            chunk_count=ingest_result.chunks_count,
            status="indexed",
            message=ingest_result.message,
            title=resolved_title,
            system_name=system,
            severity=canonical_severity,
        )

    async def _sync_postgres_incident(
        self,
        *,
        document_id: str,
        title: str,
        description: str,
        system_name: str,
        severity: str,
        chunk_count: int,
        message: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        sql = """
            INSERT INTO incidents (
                id, title, description, system_name, severity,
                created_at, indexed_at, ingestion_message
            ) VALUES (
                %(id)s::uuid, %(title)s, %(description)s, %(system_name)s, %(severity)s,
                %(created_at)s, %(indexed_at)s, %(ingestion_message)s
            )
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                system_name = EXCLUDED.system_name,
                severity = EXCLUDED.severity,
                indexed_at = EXCLUDED.indexed_at,
                ingestion_message = EXCLUDED.ingestion_message
        """
        params = {
            "id": document_id,
            "title": title[:512],
            "description": description,
            "system_name": system_name[:256],
            "severity": severity,
            "created_at": now,
            "indexed_at": now,
            "ingestion_message": f"{message} chunks={chunk_count}"[:1024],
        }
        try:
            async with await psycopg.AsyncConnection.connect(self._dsn, autocommit=True) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql, params)
        except Exception:
            logger.exception("Failed to sync uploaded document %s into Postgres", document_id)
            raise
