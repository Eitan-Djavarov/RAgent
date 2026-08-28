from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int
    client_key: str


class SlidingWindowRateLimiter:
    """Redis sorted-set sliding window rate limiter."""

    def __init__(
        self,
        redis_client: Redis,
        *,
        limit: int = 30,
        window_seconds: int = 60,
        key_prefix: str = "ratelimit",
        enabled: bool = True,
    ) -> None:
        self._redis = redis_client
        self._limit = max(1, limit)
        self._window = max(1, window_seconds)
        self._prefix = key_prefix
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def limit(self) -> int:
        return self._limit

    async def check(self, client_key: str) -> RateLimitDecision:
        if not self._enabled:
            return RateLimitDecision(
                allowed=True,
                limit=self._limit,
                remaining=self._limit,
                retry_after_seconds=0,
                client_key=client_key,
            )

        now = time.time()
        key = f"{self._prefix}:{client_key}"
        member = f"{now:.6f}:{time.time_ns()}"
        try:
            pipe = self._redis.pipeline(transaction=True)
            pipe.zremrangebyscore(key, 0, now - self._window)
            pipe.zadd(key, {member: now})
            pipe.zcard(key)
            pipe.expire(key, self._window)
            results = await pipe.execute()
            count = int(results[2])
        except Exception:  # noqa: BLE001
            logger.exception("Rate limiter Redis failure; allowing request")
            return RateLimitDecision(
                allowed=True,
                limit=self._limit,
                remaining=self._limit,
                retry_after_seconds=0,
                client_key=client_key,
            )

        remaining = max(0, self._limit - count)
        allowed = count <= self._limit
        retry_after = 0 if allowed else self._window
        if not allowed:
            # Best-effort: remove the just-added member so denied requests don't keep filling the window.
            try:
                await self._redis.zrem(key, member)
                remaining = 0
            except Exception:  # noqa: BLE001
                remaining = 0
        return RateLimitDecision(
            allowed=allowed,
            limit=self._limit,
            remaining=remaining,
            retry_after_seconds=retry_after,
            client_key=client_key,
        )
