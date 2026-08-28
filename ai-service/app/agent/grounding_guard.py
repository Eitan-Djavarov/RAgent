from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field

import httpx

from app.core.config import Settings
from app.models.schemas import SourceCitation

logger = logging.getLogger(__name__)

_STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "if",
    "then",
    "than",
    "that",
    "this",
    "these",
    "those",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "from",
    "by",
    "as",
    "at",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "it",
    "its",
    "into",
    "over",
    "under",
    "about",
    "after",
    "before",
    "during",
    "while",
    "not",
    "no",
    "yes",
    "can",
    "could",
    "should",
    "would",
    "may",
    "might",
    "will",
    "shall",
    "do",
    "does",
    "did",
    "have",
    "has",
    "had",
    "their",
    "there",
    "they",
    "them",
    "we",
    "our",
    "you",
    "your",
    "i",
    "see",
    "based",
    "using",
    "use",
    "used",
}

_GROUNDING_SYSTEM_PROMPT = """You evaluate factual faithfulness of an incident analysis answer against retrieved evidence.
Return ONLY compact JSON:
{"supported":["claim text that is entailed"],"unsupported":["claim text not entailed"]}
Do not invent claims. Only classify claims provided or clearly stated in the answer.
"""


@dataclass(slots=True)
class GroundingResult:
    faithfulness_score: float
    is_grounded: bool
    unsupported_claims: list[str] = field(default_factory=list)
    supported_claims: list[str] = field(default_factory=list)
    evaluation_mode: str = "heuristic"


class GroundingGuard:
    """Faithfulness / grounding evaluation for RAG synthesis answers."""

    def __init__(
        self,
        settings: Settings,
        *,
        threshold: float | None = None,
        llm_timeout_seconds: float | None = None,
    ) -> None:
        self._settings = settings
        self._threshold = (
            threshold
            if threshold is not None
            else getattr(settings, "grounding_threshold", 0.8)
        )
        self._llm_timeout = (
            llm_timeout_seconds
            if llm_timeout_seconds is not None
            else getattr(settings, "grounding_llm_timeout_seconds", 8.0)
        )

    async def evaluate(
        self,
        *,
        query: str,
        answer: str,
        sources: list[SourceCitation],
    ) -> GroundingResult:
        context = self._build_context(sources)
        claims = self.extract_claims(answer)
        if not claims:
            # No factual claims extracted — treat as grounded when context exists.
            score = 1.0 if context.strip() else 0.0
            return GroundingResult(
                faithfulness_score=score,
                is_grounded=score >= self._threshold,
                unsupported_claims=[],
                supported_claims=[],
                evaluation_mode="empty-claims",
            )

        if not context.strip():
            return GroundingResult(
                faithfulness_score=0.0,
                is_grounded=False,
                unsupported_claims=claims,
                supported_claims=[],
                evaluation_mode="no-context",
            )

        try:
            llm_result = await asyncio.wait_for(
                self._evaluate_with_llm(query=query, answer=answer, context=context, claims=claims),
                timeout=self._llm_timeout,
            )
            if llm_result is not None:
                return llm_result
        except TimeoutError:
            logger.warning("Grounding LLM evaluation timed out; using heuristic")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Grounding LLM evaluation failed; using heuristic: %s", exc)

        return self.evaluate_heuristic(answer=answer, context=context, claims=claims)

    def evaluate_heuristic(
        self,
        *,
        answer: str,
        context: str,
        claims: list[str] | None = None,
    ) -> GroundingResult:
        resolved_claims = claims if claims is not None else self.extract_claims(answer)
        if not resolved_claims:
            score = 1.0 if context.strip() else 0.0
            return GroundingResult(
                faithfulness_score=score,
                is_grounded=score >= self._threshold,
                unsupported_claims=[],
                supported_claims=[],
                evaluation_mode="heuristic",
            )

        supported: list[str] = []
        unsupported: list[str] = []
        for claim in resolved_claims:
            if self.is_claim_supported(claim, context):
                supported.append(claim)
            else:
                unsupported.append(claim)

        score = len(supported) / max(len(resolved_claims), 1)
        return GroundingResult(
            faithfulness_score=round(score, 4),
            is_grounded=score >= self._threshold,
            unsupported_claims=unsupported,
            supported_claims=supported,
            evaluation_mode="heuristic",
        )

    @staticmethod
    def extract_claims(answer: str) -> list[str]:
        text = (answer or "").strip()
        if not text:
            return []

        # Prefer body text under known analysis headings.
        sections: list[str] = []
        for heading in (
            "Executive Summary",
            "Root Cause Analysis",
            "Recommended Mitigation / Corrective Actions",
            "Recommended Mitigation",
        ):
            section = GroundingGuard._section_between(text, heading)
            if section:
                sections.append(section)
        body = "\n".join(sections) if sections else text

        # Drop citation / SQL appendix noise.
        body = re.split(r"##\s*Source Citations", body, flags=re.IGNORECASE)[0]
        body = re.split(r"##\s*SQL Metrics", body, flags=re.IGNORECASE)[0]

        raw_sentences = re.split(r"(?<=[.!?])\s+|\n+", body)
        claims: list[str] = []
        for sentence in raw_sentences:
            cleaned = re.sub(r"^[\-\*\d\.\)\s]+", "", sentence).strip()
            cleaned = re.sub(r"\s+", " ", cleaned)
            if len(cleaned) < 25:
                continue
            if cleaned.lower().startswith(("see ", "not applicable", "insufficient")):
                continue
            claims.append(cleaned)
            if len(claims) >= 12:
                break
        return claims

    @staticmethod
    def is_claim_supported(claim: str, context: str, *, min_coverage: float = 0.45) -> bool:
        claim_tokens = GroundingGuard._content_tokens(claim)
        if not claim_tokens:
            return True
        context_tokens = set(GroundingGuard._content_tokens(context))
        if not context_tokens:
            return False

        overlap = sum(1 for token in claim_tokens if token in context_tokens)
        coverage = overlap / len(claim_tokens)

        # Strong exact-ish phrase support for short distinctive spans.
        lowered_context = context.lower()
        distinctive = [token for token in claim_tokens if len(token) >= 6][:4]
        phrase_hits = sum(1 for token in distinctive if token in lowered_context)
        if distinctive and phrase_hits >= max(1, len(distinctive) - 1):
            return True
        return coverage >= min_coverage

    async def _evaluate_with_llm(
        self,
        *,
        query: str,
        answer: str,
        context: str,
        claims: list[str],
    ) -> GroundingResult | None:
        user_prompt = (
            f"User query:\n{query}\n\n"
            f"Retrieved evidence:\n{context[:6000]}\n\n"
            f"Generated answer:\n{answer[:4000]}\n\n"
            f"Candidate claims:\n"
            + "\n".join(f"- {claim}" for claim in claims)
            + "\n\nClassify each claim as supported or unsupported by the evidence."
        )

        raw: str | None = None
        if self._settings.openai_api_key:
            try:
                raw = await self._openai_json(user_prompt)
            except Exception as exc:  # noqa: BLE001
                logger.warning("OpenAI grounding eval failed: %s", exc)

        if raw is None:
            try:
                raw = await self._ollama_json(user_prompt)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Ollama grounding eval failed: %s", exc)
                return None

        parsed = self._parse_llm_json(raw, fallback_claims=claims)
        if parsed is None:
            return None
        supported, unsupported = parsed
        total = max(len(supported) + len(unsupported), 1)
        score = len(supported) / total
        return GroundingResult(
            faithfulness_score=round(score, 4),
            is_grounded=score >= self._threshold,
            unsupported_claims=unsupported,
            supported_claims=supported,
            evaluation_mode="llm",
        )

    async def _openai_json(self, user_prompt: str) -> str:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._settings.openai_api_key)
        completion = await client.chat.completions.create(
            model=self._settings.openai_model,
            messages=[
                {"role": "system", "content": _GROUNDING_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=700,
        )
        message = completion.choices[0].message.content
        if not message:
            raise RuntimeError("OpenAI returned empty grounding evaluation.")
        return message.strip()

    async def _ollama_json(self, user_prompt: str) -> str:
        url = f"{self._settings.ollama_base_url.rstrip('/')}/api/chat"
        payload = {
            "model": self._settings.ollama_model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": _GROUNDING_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "options": {"temperature": 0.0},
        }
        async with httpx.AsyncClient(timeout=self._llm_timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        message = data.get("message", {}).get("content")
        if not isinstance(message, str) or not message.strip():
            raise RuntimeError("Ollama returned empty grounding evaluation.")
        return message.strip()

    @staticmethod
    def _parse_llm_json(
        raw: str,
        *,
        fallback_claims: list[str],
    ) -> tuple[list[str], list[str]] | None:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                return None
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None

        supported = [str(item).strip() for item in (payload.get("supported") or []) if str(item).strip()]
        unsupported = [
            str(item).strip() for item in (payload.get("unsupported") or []) if str(item).strip()
        ]
        if not supported and not unsupported:
            # If model returned nothing useful, fall back.
            return None
        # Keep unknown claims as unsupported for safety.
        classified = {item.lower() for item in supported + unsupported}
        for claim in fallback_claims:
            if claim.lower() not in classified:
                unsupported.append(claim)
        return supported, unsupported

    @staticmethod
    def _build_context(sources: list[SourceCitation]) -> str:
        return "\n\n".join(
            f"[{source.citation_index or index}] document_id={source.document_id}\n{source.chunk_text}"
            for index, source in enumerate(sources, start=1)
        )

    @staticmethod
    def _content_tokens(text: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9][a-z0-9\-/]{2,}", text.lower())
        return [token for token in tokens if token not in _STOPWORDS]

    @staticmethod
    def _section_between(text: str, start: str) -> str:
        pattern = rf"##\s*{re.escape(start)}\s*(.*?)(?=##\s|$)"
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else ""
