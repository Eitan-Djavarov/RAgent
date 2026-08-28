from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import Any, Callable

import numpy as np
from redis.asyncio import Redis

from app.core.config import Settings
from app.models.schemas import QueryRequest, QueryResponse

logger = logging.getLogger(__name__)

_INDEX_KEY = "semantic_cache:index"
_EXACT_PREFIX = "semantic_cache:exact:"
_ENTRY_PREFIX = "semantic_cache:entry:"


def cosine_similarity(left: list[float] | np.ndarray, right: list[float] | np.ndarray) -> float:
    a = np.asarray(left, dtype=np.float32)
    b = np.asarray(right, dtype=np.float32)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom <= 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def normalize_query_text(query: str) -> str:
    return " ".join(query.strip().lower().split())


class SemanticCache:
    """Redis-backed semantic cache for ask/query responses."""

    def __init__(
        self,
        settings: Settings,
        redis_client: Redis,
        embed_query: Callable[[str], list[float]],
    ) -> None:
        self._settings = settings
        self._redis = redis_client
        self._embed_query = embed_query
        self._ttl = settings.semantic_cache_ttl_seconds
        self._threshold = settings.semantic_cache_similarity_threshold
        self._enabled = settings.semantic_cache_enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def ping(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except Exception:  # noqa: BLE001
            return False

    async def lookup(self, request: QueryRequest) -> QueryResponse | None:
        if not self._enabled:
            return None

        started = time.perf_counter()
        try:
            exact = await self._lookup_exact(request)
            if exact is not None:
                latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
                return exact.model_copy(update={"cached": True, "latency_ms": latency_ms})

            semantic = await self._lookup_semantic(request)
            if semantic is not None:
                latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
                return semantic.model_copy(update={"cached": True, "latency_ms": latency_ms})
        except Exception:  # noqa: BLE001
            logger.exception("Semantic cache lookup failed; continuing without cache")
        return None

    async def store(self, request: QueryRequest, response: QueryResponse) -> None:
        if not self._enabled:
            return

        try:
            embedding = await self._embed(request.query)
            entry_id = str(uuid.uuid4())
            payload = {
                "id": entry_id,
                "query_text": request.query,
                "normalized_query": normalize_query_text(request.query),
                "context_key": self._context_key(request),
                "exact_key": self._exact_key(request),
                "embedding": embedding,
                "response": response.model_copy(update={"cached": False}).model_dump(
                    by_alias=True,
                    mode="json",
                ),
                "created_at": time.time(),
            }
            raw = json.dumps(payload)
            pipe = self._redis.pipeline(transaction=True)
            pipe.set(f"{_ENTRY_PREFIX}{entry_id}", raw, ex=self._ttl)
            pipe.set(self._exact_key(request), raw, ex=self._ttl)
            pipe.sadd(_INDEX_KEY, entry_id)
            pipe.expire(_INDEX_KEY, self._ttl)
            await pipe.execute()
        except Exception:  # noqa: BLE001
            logger.exception("Semantic cache store failed; response still returned")

    async def clear(self) -> int:
        deleted = 0
        try:
            entry_ids = await self._redis.smembers(_INDEX_KEY)
            keys: list[str] = [_INDEX_KEY]
            for entry_id in entry_ids:
                entry_key = f"{_ENTRY_PREFIX}{entry_id}"
                keys.append(entry_key)
                raw = await self._redis.get(entry_key)
                if raw:
                    try:
                        payload = json.loads(raw)
                        exact_key = payload.get("exact_key")
                        if exact_key:
                            keys.append(str(exact_key))
                    except json.JSONDecodeError:
                        pass

            # Also sweep any leftover exact keys via pattern
            async for key in self._redis.scan_iter(match=f"{_EXACT_PREFIX}*", count=200):
                keys.append(key)
            async for key in self._redis.scan_iter(match=f"{_ENTRY_PREFIX}*", count=200):
                keys.append(key)

            unique_keys = list(dict.fromkeys(keys))
            if unique_keys:
                deleted = int(await self._redis.delete(*unique_keys))
        except Exception:  # noqa: BLE001
            logger.exception("Semantic cache clear failed")
            raise
        return deleted

    async def _lookup_exact(self, request: QueryRequest) -> QueryResponse | None:
        raw = await self._redis.get(self._exact_key(request))
        if not raw:
            return None
        payload = json.loads(raw)
        return QueryResponse.model_validate(payload["response"])

    async def _lookup_semantic(self, request: QueryRequest) -> QueryResponse | None:
        query_embedding = await self._embed(request.query)
        context_key = self._context_key(request)
        entry_ids = await self._redis.smembers(_INDEX_KEY)
        best_score = -1.0
        best_response: QueryResponse | None = None

        for entry_id in entry_ids:
            raw = await self._redis.get(f"{_ENTRY_PREFIX}{entry_id}")
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if payload.get("context_key") != context_key:
                continue
            stored = payload.get("embedding") or []
            if not stored:
                continue
            score = cosine_similarity(query_embedding, stored)
            if score >= self._threshold and score > best_score:
                best_score = score
                best_response = QueryResponse.model_validate(payload["response"])

        if best_response is not None:
            logger.info(
                "Semantic cache hit similarity=%.4f threshold=%.2f",
                best_score,
                self._threshold,
            )
        return best_response

    async def _embed(self, query: str) -> list[float]:
        # HuggingFaceEmbeddings is sync; keep event loop responsive.
        import asyncio

        return await asyncio.to_thread(self._embed_query, query)

    def _exact_key(self, request: QueryRequest) -> str:
        digest = hashlib.sha256(
            self._fingerprint_material(request, include_query=True).encode("utf-8")
        ).hexdigest()
        return f"{_EXACT_PREFIX}{digest}"

    def _context_key(self, request: QueryRequest) -> str:
        return hashlib.sha256(
            self._fingerprint_material(request, include_query=False).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _fingerprint_material(request: QueryRequest, *, include_query: bool) -> str:
        filters = request.filter_metadata or {}
        normalized_filters = {
            str(key): "" if value is None else str(value)
            for key, value in sorted(filters.items(), key=lambda item: str(item[0]))
        }
        payload: dict[str, Any] = {
            "top_k": request.top_k,
            "structured": request.structured,
            "filters": normalized_filters,
        }
        if include_query:
            payload["query"] = normalize_query_text(request.query)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))
