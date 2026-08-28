from __future__ import annotations

import json
import logging
import time
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_SESSION_PREFIX = "session:"


class SessionMemory:
    """Redis-backed multi-turn conversation memory keyed by session_id."""

    def __init__(self, redis_client: Redis, ttl_seconds: int = 3600) -> None:
        self._redis = redis_client
        self._ttl = ttl_seconds

    def _key(self, session_id: str) -> str:
        return f"{_SESSION_PREFIX}{session_id.strip()}"

    async def get_history(self, session_id: str) -> list[dict[str, Any]]:
        if not session_id or not session_id.strip():
            return []
        try:
            raw = await self._redis.get(self._key(session_id))
            if not raw:
                return []
            payload = json.loads(raw)
            turns = payload.get("turns")
            if not isinstance(turns, list):
                return []
            return [turn for turn in turns if isinstance(turn, dict)]
        except Exception:  # noqa: BLE001
            logger.exception("Failed to load session history for %s", session_id)
            return []

    async def append_turn(
        self,
        session_id: str,
        *,
        user_query: str,
        assistant_response: str,
        rewritten_query: str | None = None,
        tool_used: str | None = None,
    ) -> None:
        if not session_id or not session_id.strip():
            return

        turn: dict[str, Any] = {
            "role_user": user_query.strip(),
            "role_assistant": assistant_response.strip(),
            "rewritten_query": (rewritten_query or user_query).strip(),
            "tool_used": tool_used,
            "timestamp": time.time(),
        }
        try:
            history = await self.get_history(session_id)
            history.append(turn)
            # Cap memory growth while keeping recent context for rewriting.
            if len(history) > 40:
                history = history[-40:]
            payload = {"turns": history, "updated_at": time.time()}
            await self._redis.set(
                self._key(session_id),
                json.dumps(payload),
                ex=self._ttl,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to append turn for session %s", session_id)

    async def clear(self, session_id: str) -> bool:
        if not session_id or not session_id.strip():
            return False
        try:
            deleted = await self._redis.delete(self._key(session_id))
            return int(deleted) > 0
        except Exception:  # noqa: BLE001
            logger.exception("Failed to clear session %s", session_id)
            raise

    @staticmethod
    def format_history_for_prompt(history: list[dict[str, Any]], max_turns: int = 8) -> str:
        recent = history[-max_turns:]
        lines: list[str] = []
        for index, turn in enumerate(recent, start=1):
            user = str(turn.get("role_user") or "").strip()
            assistant = str(turn.get("role_assistant") or "").strip()
            if len(assistant) > 600:
                assistant = assistant[:600].rstrip() + "…"
            lines.append(f"Turn {index} User: {user}")
            lines.append(f"Turn {index} Assistant: {assistant}")
        return "\n".join(lines)
