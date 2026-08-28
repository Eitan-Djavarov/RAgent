from __future__ import annotations

import logging
import uuid
from typing import Any

from langchain_community.embeddings import HuggingFaceEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.core.config import Settings
from app.ingestion.hierarchical_chunker import HierarchicalChunker
from app.models.schemas import IngestRequest, IngestResponse
from app.rag.bm25_store import Bm25Store

logger = logging.getLogger(__name__)


class QdrantIndexer:
    """Ensures the collection exists and indexes hierarchical child chunks."""

    def __init__(
        self,
        settings: Settings,
        embeddings: HuggingFaceEmbeddings,
        qdrant: QdrantClient,
        bm25_store: Bm25Store,
        chunker: HierarchicalChunker,
    ) -> None:
        self._settings = settings
        self._embeddings = embeddings
        self._qdrant = qdrant
        self._bm25 = bm25_store
        self._chunker = chunker

    def ensure_collection(self) -> None:
        collection = self._settings.collection_name
        existing = {c.name for c in self._qdrant.get_collections().collections}
        if collection in existing:
            return

        logger.info(
            "Creating Qdrant collection %s (dim=%s)",
            collection,
            self._settings.embedding_dimension,
        )
        self._qdrant.create_collection(
            collection_name=collection,
            vectors_config=qmodels.VectorParams(
                size=self._settings.embedding_dimension,
                distance=qmodels.Distance.COSINE,
            ),
        )
        self._qdrant.create_payload_index(
            collection_name=collection,
            field_name="document_id",
            field_schema=qmodels.PayloadSchemaType.KEYWORD,
        )
        try:
            self._qdrant.create_payload_index(
                collection_name=collection,
                field_name="parent_id",
                field_schema=qmodels.PayloadSchemaType.KEYWORD,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("parent_id payload index skipped/exists: %s", exc)

    def ingest(self, request: IngestRequest) -> IngestResponse:
        hierarchy = self._chunker.split(request.content, document_id=request.document_id)
        children = hierarchy.children
        if not children:
            return IngestResponse(
                success=False,
                document_id=request.document_id,
                chunks_count=0,
                message="No indexable chunks were produced from the document content.",
            )

        self.delete_vectors(request.document_id)
        self._bm25.remove_document(request.document_id)

        child_texts = [child.text for child in children]
        vectors = self._embeddings.embed_documents(child_texts)
        points: list[qmodels.PointStruct] = []
        point_ids: list[str] = []
        parent_ids: list[str | None] = []
        parent_texts: list[str | None] = []

        for index, (child, vector) in enumerate(zip(children, vectors, strict=True)):
            point_id = str(uuid.uuid4())
            point_ids.append(point_id)
            parent_ids.append(child.parent_id)
            parent_texts.append(child.parent_text)
            payload: dict[str, Any] = {
                "document_id": request.document_id,
                "title": request.title,
                "chunk_index": index,
                "chunk_text": child.text,
                "chunk_role": "child",
                "parent_id": child.parent_id,
                "parent_text": child.parent_text,
                "parent_index": child.parent_index,
                "child_index": child.child_index,
                "metadata": request.metadata,
            }
            for key, value in request.metadata.items():
                if isinstance(value, (str, int, float, bool)):
                    payload[f"meta_{key}"] = value

            points.append(
                qmodels.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            )

        self._qdrant.upsert(
            collection_name=self._settings.collection_name,
            points=points,
            wait=True,
        )
        self._bm25.add_chunks(
            document_id=request.document_id,
            title=request.title,
            point_ids=point_ids,
            chunk_texts=child_texts,
            parent_ids=parent_ids,
            parent_texts=parent_texts,
        )
        logger.info(
            "Ingested document %s (%s child chunks from %s parents)",
            request.document_id,
            len(points),
            hierarchy.parent_count,
        )
        return IngestResponse(
            success=True,
            document_id=request.document_id,
            chunks_count=len(points),
            message=(
                f"Indexed {len(points)} child chunks "
                f"({hierarchy.parent_count} parents) into collection "
                f"'{self._settings.collection_name}' (dense + BM25, small-to-big)."
            ),
        )

    def delete_vectors(self, document_id: str) -> None:
        self._qdrant.delete(
            collection_name=self._settings.collection_name,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="document_id",
                            match=qmodels.MatchValue(value=document_id),
                        )
                    ]
                )
            ),
        )

    def delete_document(self, document_id: str) -> int:
        before = self.count_document_chunks(document_id)
        self.delete_vectors(document_id)
        self._bm25.remove_document(document_id)
        return before

    def count_document_chunks(self, document_id: str) -> int:
        try:
            result = self._qdrant.count(
                collection_name=self._settings.collection_name,
                count_filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="document_id",
                            match=qmodels.MatchValue(value=document_id),
                        )
                    ]
                ),
                exact=True,
            )
            return int(result.count)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed counting chunks for %s: %s", document_id, exc)
            return 0

    def count_chunks_by_document(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        try:
            offset = None
            while True:
                points, offset = self._qdrant.scroll(
                    collection_name=self._settings.collection_name,
                    limit=256,
                    offset=offset,
                    with_payload=["document_id"],
                    with_vectors=False,
                )
                for point in points:
                    payload = point.payload or {}
                    document_id = str(payload.get("document_id") or "").strip()
                    if not document_id:
                        continue
                    counts[document_id] = counts.get(document_id, 0) + 1
                if offset is None:
                    break
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed aggregating chunk counts: %s", exc)
        return counts
