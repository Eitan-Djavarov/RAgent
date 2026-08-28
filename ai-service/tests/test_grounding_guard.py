from __future__ import annotations

import pytest

from app.agent.grounding_guard import GroundingGuard
from app.core.config import Settings
from app.models.schemas import SourceCitation


@pytest.fixture
def guard() -> GroundingGuard:
    settings = Settings(
        grounding_threshold=0.8,
        openai_api_key=None,
        ollama_base_url="http://127.0.0.1:9",
    )
    return GroundingGuard(settings, llm_timeout_seconds=0.05)


def test_heuristic_scores_supported_answer_as_grounded(guard: GroundingGuard) -> None:
    context = (
        "The AESA radar buffer overflow occurred during continuous target tracking "
        "when the track-file allocator exhausted heap memory under concurrent beam "
        "scheduling. Operators observed watchdog resets on the signal processor due "
        "to heap exhaustion. Increase track-file allocator capacity and add heap "
        "pressure monitoring."
    )
    answer = (
        "## Executive Summary\n"
        "The AESA radar buffer overflow occurred during continuous target tracking "
        "when the track-file allocator exhausted heap memory under concurrent beam scheduling.\n\n"
        "## Root Cause Analysis\n"
        "Operators observed watchdog resets on the signal processor due to heap exhaustion.\n\n"
        "## Recommended Mitigation / Corrective Actions\n"
        "Increase track-file allocator capacity and add heap pressure monitoring."
    )
    result = guard.evaluate_heuristic(answer=answer, context=context)
    assert result.faithfulness_score >= 0.8
    assert result.is_grounded is True
    assert result.unsupported_claims == []
    assert result.evaluation_mode == "heuristic"


def test_heuristic_flags_hallucinated_claims(guard: GroundingGuard) -> None:
    context = (
        "Coolant pump P-12 tripped on overcurrent after a bearing seizure. "
        "Maintenance replaced the bearing and restored flow within two hours."
    )
    answer = (
        "## Executive Summary\n"
        "A nuclear reactor meltdown was triggered by cosmic ray interference in the guidance computer.\n\n"
        "## Root Cause Analysis\n"
        "Sabotage by an unknown drone swarm disabled all redundant cooling loops simultaneously.\n\n"
        "## Recommended Mitigation / Corrective Actions\n"
        "Deploy orbital laser shields around every ground station immediately."
    )
    result = guard.evaluate_heuristic(answer=answer, context=context)
    assert result.faithfulness_score < 0.8
    assert result.is_grounded is False
    assert len(result.unsupported_claims) >= 1


@pytest.mark.asyncio
async def test_evaluate_falls_back_when_no_llm(guard: GroundingGuard) -> None:
    sources = [
        SourceCitation(
            document_id="doc-1",
            chunk_text=(
                "Hydraulic actuator lag exceeded 120ms after seal degradation on the "
                "left elevon control surface during high-G maneuvers. Seal degradation "
                "on the left elevon control surface caused the hydraulic actuator lag. "
                "Replace degraded seals and re-baseline actuator latency checks."
            ),
            score=0.91,
        )
    ]
    answer = (
        "## Executive Summary\n"
        "Hydraulic actuator lag exceeded 120ms after seal degradation on the left elevon "
        "control surface during high-G maneuvers.\n\n"
        "## Root Cause Analysis\n"
        "Seal degradation on the left elevon control surface caused the hydraulic actuator lag.\n\n"
        "## Recommended Mitigation / Corrective Actions\n"
        "Replace degraded seals and re-baseline actuator latency checks."
    )
    result = await guard.evaluate(
        query="What caused elevon actuator lag?",
        answer=answer,
        sources=sources,
    )
    assert result.faithfulness_score >= 0.8
    assert result.is_grounded is True
    assert result.evaluation_mode == "heuristic"


def test_extract_claims_skips_short_noise(guard: GroundingGuard) -> None:
    claims = GroundingGuard.extract_claims("Short.\nAlso short.\n")
    assert claims == []


def test_is_claim_supported_token_overlap(guard: GroundingGuard) -> None:
    context = "Fuel pump cavitation damaged impeller blades during climb-out."
    supported = "Fuel pump cavitation damaged impeller blades during climb-out operations."
    hallucinated = "The navigation star tracker was blinded by solar flares."
    assert GroundingGuard.is_claim_supported(supported, context) is True
    assert GroundingGuard.is_claim_supported(hallucinated, context) is False


def test_no_context_marks_all_claims_unsupported(guard: GroundingGuard) -> None:
    answer = (
        "## Executive Summary\n"
        "The propulsion controller entered a failsafe state after sensor disagreement."
    )
    result = guard.evaluate_heuristic(answer=answer, context="")
    assert result.faithfulness_score == 0.0
    assert result.is_grounded is False
    assert len(result.unsupported_claims) >= 1
