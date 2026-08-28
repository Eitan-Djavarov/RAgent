from __future__ import annotations

import logging
import re

import httpx

from app.cache.session_memory import SessionMemory
from app.core.config import Settings

logger = logging.getLogger(__name__)

REWRITE_SYSTEM_PROMPT = """You are a query rewriting assistant for an aerospace / defense incident intelligence system.
Given prior conversation turns and the latest user message, rewrite the latest message into a single
self-contained search / analytics question that preserves all necessary context from history.

Rules:
- Output ONLY the rewritten standalone query text.
- Do not answer the question.
- Do not add markdown, quotes, or explanations.
- Keep named systems, severities, components, and incident details from earlier turns when referenced by pronouns like "it", "that", "the same system".
- If the latest message is already fully self-contained, return it unchanged (lightly cleaned).
"""


class QueryRewriter:
    """LLM-backed contextual query rewriter with heuristic fallback."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def rewrite(
        self,
        *,
        current_query: str,
        history: list[dict[str, object]],
    ) -> str:
        cleaned = current_query.strip()
        if not history:
            return cleaned

        history_block = SessionMemory.format_history_for_prompt(history)
        user_prompt = (
            f"Conversation history:\n{history_block}\n\n"
            f"Latest user message:\n{cleaned}\n\n"
            "Standalone rewritten query:"
        )

        rewritten: str | None = None
        if self._settings.openai_api_key:
            try:
                rewritten = await self._rewrite_openai(user_prompt)
            except Exception as exc:  # noqa: BLE001
                logger.warning("OpenAI query rewrite failed, trying Ollama: %s", exc)

        if rewritten is None:
            try:
                rewritten = await self._rewrite_ollama(user_prompt)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Ollama query rewrite failed, using heuristic: %s", exc)
                rewritten = self._heuristic_rewrite(cleaned, history)

        return self._sanitize(rewritten, fallback=cleaned)

    async def _rewrite_openai(self, user_prompt: str) -> str:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._settings.openai_api_key)
        completion = await client.chat.completions.create(
            model=self._settings.openai_model,
            messages=[
                {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=256,
        )
        message = completion.choices[0].message.content
        if not message:
            raise RuntimeError("OpenAI returned an empty rewrite.")
        return message.strip()

    async def _rewrite_ollama(self, user_prompt: str) -> str:
        url = f"{self._settings.ollama_base_url.rstrip('/')}/api/chat"
        payload = {
            "model": self._settings.ollama_model,
            "stream": False,
            "messages": [
                {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "options": {"temperature": 0.0},
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        message = data.get("message", {}).get("content")
        if not isinstance(message, str) or not message.strip():
            raise RuntimeError("Ollama returned an empty rewrite.")
        return message.strip()

    @staticmethod
    def _heuristic_rewrite(current_query: str, history: list[dict[str, object]]) -> str:
        """Lightweight pronoun / follow-up expansion when LLMs are unavailable."""
        last_user = ""
        last_assistant = ""
        if history:
            last = history[-1]
            last_user = str(last.get("role_user") or "")
            last_assistant = str(last.get("role_assistant") or "")

        lowered = current_query.lower()
        follow_up_markers = (
            "it",
            "that",
            "this",
            "those",
            "them",
            "the same",
            "what about",
            "and the",
            "how many of",
            "why did that",
            "root cause",
            "mitigation",
            "more detail",
            "same system",
            "same incident",
        )
        needs_context = any(
            marker in lowered for marker in follow_up_markers
        ) or len(current_query.split()) <= 6

        if not needs_context:
            return current_query

        # Prefer the previous rewritten/standalone query if present.
        prior_focus = ""
        if history:
            prior_focus = str(history[-1].get("rewritten_query") or last_user)

        entity = QueryRewriter._extract_entity(f"{prior_focus}\n{last_assistant}")
        if entity and entity.lower() not in lowered:
            return f"{current_query.rstrip('?.!')} regarding {entity}?"
        if prior_focus:
            return f"{current_query.rstrip('?.!')} (context: {prior_focus})"
        return current_query

    @staticmethod
    def _extract_entity(text: str) -> str:
        patterns = [
            r"\b(AESA(?:\s+Radar)?)\b",
            r"\b(EO/?IR(?:\s+gimbal)?)\b",
            r"\b(UAV(?:\s+SATCOM)?)\b",
            r"\b(Radar[\w\-]*)\b",
            r"\b(Critical|High|Medium|Low)\s+incidents?\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(0)
        return ""

    @staticmethod
    def _sanitize(rewritten: str, *, fallback: str) -> str:
        text = rewritten.strip().strip('"').strip("'")
        text = re.sub(r"^(standalone rewritten query|rewritten query)\s*:\s*", "", text, flags=re.I)
        text = text.splitlines()[0].strip() if text else fallback
        if len(text) < 2:
            return fallback
        return text[:4000]
