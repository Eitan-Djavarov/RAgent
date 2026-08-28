from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator

import httpx

from app.citations.indexing import attach_heuristic_markers
from app.core.config import Settings
from app.models.schemas import SourceCitation, StructuredIncidentAnalysis
from app.prompts.synthesis import STRUCTURED_SYSTEM_PROMPT
from app.retrieval.parent_expansion import low_relevance_answer


def chunk_text(text: str, size: int = 24) -> list[str]:
    if not text:
        return []
    return [text[index : index + size] for index in range(0, len(text), size)]


def build_context(sources: list[SourceCitation]) -> str:
    blocks: list[str] = []
    for index, source in enumerate(sources, start=1):
        citation_no = source.citation_index or index
        system = source.system or "n/a"
        severity = source.severity or "n/a"
        blocks.append(
            f"[{citation_no}] document_id={source.document_id} "
            f"system={system} severity={severity} "
            f"parent_id={source.parent_id or 'n/a'} confidence={source.score:.4f}\n"
            f"{source.chunk_text}"
        )
    return "\n\n".join(blocks)


def format_answer(analysis: StructuredIncidentAnalysis) -> str:
    citations = "\n".join(
        f"- [{c.citation_index or index}] document_id={c.document_id}; "
        f"system={c.system or 'n/a'}; severity={c.severity or 'n/a'}; "
        f"confidence={c.score:.4f}; "
        f"excerpt={c.chunk_text[:180].replace(chr(10), ' ')}"
        for index, c in enumerate(analysis.source_citations, start=1)
    )
    return (
        "## Executive Summary\n"
        f"{analysis.executive_summary}\n\n"
        "## Root Cause Analysis\n"
        f"{analysis.root_cause_analysis}\n\n"
        "## Recommended Mitigation / Corrective Actions\n"
        f"{analysis.recommended_mitigations}\n\n"
        "## Source Citations\n"
        f"{citations}"
    )


def empty_answer() -> str:
    return low_relevance_answer()


def heuristic_analysis(
    query: str,
    sources: list[SourceCitation],
) -> StructuredIncidentAnalysis:
    primary = sources[0]
    marker = primary.citation_index or 1
    joined = "\n".join(source.chunk_text for source in sources)
    root = extract_section(
        joined,
        markers=("root cause", "causal", "caused by", "primary causal"),
        fallback=primary.chunk_text[:500],
    )
    mitigation = extract_section(
        joined,
        markers=("mitigation", "corrective", "workaround", "recommended"),
        fallback="Review the cited reports and apply the listed field mitigations.",
    )
    summary = (
        f"Based on {len(sources)} re-ranked technical passages related to '{query}', "
        f"the strongest evidence points to issues described in document "
        f"{primary.document_id} (confidence {primary.score:.2f})."
    )
    return StructuredIncidentAnalysis(
        executive_summary=attach_heuristic_markers(summary, marker),
        root_cause_analysis=attach_heuristic_markers(root, marker),
        recommended_mitigations=attach_heuristic_markers(mitigation, marker),
        source_citations=sources,
    )


def extract_section(text: str, markers: tuple[str, ...], fallback: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    matched = [
        sentence.strip()
        for sentence in sentences
        if any(marker in sentence.lower() for marker in markers)
    ]
    if matched:
        return " ".join(matched[:4])
    return fallback


def parse_structured_output(
    raw: str,
    sources: list[SourceCitation],
) -> StructuredIncidentAnalysis:
    executive = section_between(raw, "Executive Summary", "Root Cause Analysis")
    root = section_between(raw, "Root Cause Analysis", "Recommended Mitigation")
    if not root:
        root = section_between(
            raw,
            "Root Cause Analysis",
            "Recommended Mitigation / Corrective Actions",
        )
    mitigation = section_between(
        raw,
        "Recommended Mitigation / Corrective Actions",
        "Source Citations",
    )
    if not mitigation:
        mitigation = section_between(raw, "Recommended Mitigation", "Source Citations")

    return StructuredIncidentAnalysis(
        executive_summary=executive or raw[:400],
        root_cause_analysis=root or "Insufficient grounded root-cause detail in model output.",
        recommended_mitigations=mitigation
        or "See source citations for reported mitigations.",
        source_citations=sources,
    )


def section_between(text: str, start: str, end: str) -> str:
    pattern = rf"##\s*{re.escape(start)}\s*(.*?)(?=##\s*{re.escape(end)}|$)"
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return match.group(1).strip()


async def complete_openai(settings: Settings, user_prompt: str) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    completion = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": STRUCTURED_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )
    message = completion.choices[0].message.content
    if not message:
        raise RuntimeError("OpenAI returned an empty completion.")
    return message.strip()


async def complete_ollama(settings: Settings, user_prompt: str) -> str:
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    payload = {
        "model": settings.ollama_model,
        "stream": False,
        "messages": [
            {"role": "system", "content": STRUCTURED_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "options": {"temperature": 0.2},
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

    message = data.get("message", {}).get("content")
    if not isinstance(message, str) or not message.strip():
        raise RuntimeError("Ollama returned an empty completion.")
    return message.strip()


async def stream_openai(settings: Settings, user_prompt: str) -> AsyncIterator[str]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    stream = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": STRUCTURED_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        stream=True,
    )
    async for event in stream:
        if not event.choices:
            continue
        delta = event.choices[0].delta.content
        if delta:
            yield delta


async def stream_ollama(settings: Settings, user_prompt: str) -> AsyncIterator[str]:
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    payload = {
        "model": settings.ollama_model,
        "stream": True,
        "messages": [
            {"role": "system", "content": STRUCTURED_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "options": {"temperature": 0.2},
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = data.get("message") or {}
                delta = message.get("content")
                if isinstance(delta, str) and delta:
                    yield delta
                if data.get("done") is True:
                    break
