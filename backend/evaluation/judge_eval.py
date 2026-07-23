"""LLM-judge hallucination scoring. CLAUDE.md §9.5: "Evaluation judge model
must differ from the model that produced the original answer being judged —
no self-grading." Implemented by forcing BOTH the judge router's primary and
fallback slots to the tier OPPOSITE whichever one actually answered — not by
convention, but structurally: the judge's LLMRouter physically cannot reach
the tier that produced the explanation it's judging.
"""

from __future__ import annotations

import json

from ..utils.llm_router import GeminiProvider, GroqProvider, LLMMessage, LLMRequest, LLMRouter, LLMTier, ReasoningServiceUnavailableError, load_llm_config
from .collect_assessments import HoldoutAssessment

JUDGE_TASK_INSTRUCTION = """You are an independent evaluator. You will be given a plain-language explanation an AI safety-monitoring agent produced, plus the reference data it was supposed to be grounded in. Judge whether the explanation's claims are actually supported by the reference data, or whether it states things not present in that data (hallucination).

Respond with ONLY a JSON object, no other text:
{
  "grounded": <true or false>,
  "hallucination_detected": <true or false>,
  "notes": <string, 1-2 sentences>
}"""


def _opposite_tier_router(original_tier: str) -> LLMRouter:
    config = load_llm_config()
    if original_tier == LLMTier.GEMINI.value:
        provider = GroqProvider(model=config["groq"]["model"], timeout_seconds=config["groq"]["timeout_seconds"])
    else:
        provider = GeminiProvider(model=config["gemini"]["model"], timeout_seconds=config["gemini"]["timeout_seconds"])
    # Both slots point at the SAME opposite-tier provider — the judge
    # physically cannot fall through to the tier being judged.
    return LLMRouter(gemini_provider=provider, groq_provider=provider, config=config)


def judge_assessment(assessment: HoldoutAssessment) -> dict:
    judge_router = _opposite_tier_router(assessment.explanation.llm_tier_used)

    reference_text = "\n".join(
        f'[chunk_id="{m.chunk_id}"] {m.narrative_text or ""}' for m in assessment.retrieval_outcome.matches
    ) or "(no reference data retrieved — novel condition)"

    prompt = (
        f"{JUDGE_TASK_INSTRUCTION}\n\n"
        f"--- EXPLANATION TO JUDGE ---\n{assessment.explanation.narrative}\n\n"
        f"--- REFERENCE DATA IT SHOULD BE GROUNDED IN ---\n{reference_text}"
    )

    base = {"scenario_name": assessment.scenario_name, "seed": assessment.seed, "record_index": assessment.record_index, "judged_tier": assessment.explanation.llm_tier_used}

    try:
        response = judge_router.complete(LLMRequest(messages=[LLMMessage(role="user", content=prompt)], temperature=0.0, max_tokens=300, json_mode=True))
    except ReasoningServiceUnavailableError as exc:
        # CLAUDE.md §14: fail visibly, not silently — and never fall back to
        # judging with the tier being judged just to avoid a gap in the
        # report. A missing judgment, clearly labeled as such, is honest;
        # a self-graded one would not be.
        return {**base, "judge_tier": None, "grounded": None, "hallucination_detected": None, "notes": f"Judge unavailable: {exc}", "parse_error": False, "unavailable": True}

    try:
        parsed = json.loads(response.content)
        grounded = bool(parsed.get("grounded", False))
        hallucination_detected = bool(parsed.get("hallucination_detected", True))
        notes = str(parsed.get("notes", ""))
        parse_error = False
    except (json.JSONDecodeError, AttributeError, TypeError):
        grounded, hallucination_detected, notes, parse_error = False, True, "Judge output unparseable.", True

    return {**base, "judge_tier": response.tier_used.value, "grounded": grounded, "hallucination_detected": hallucination_detected, "notes": notes, "parse_error": parse_error, "unavailable": False}


def evaluate_hallucination_rate(assessments: list[HoldoutAssessment]) -> dict:
    judgments = [judge_assessment(a) for a in assessments]
    available = [j for j in judgments if not j["unavailable"]]
    n_unavailable = len(judgments) - len(available)

    hallucination_rate = (sum(j["hallucination_detected"] for j in available) / len(available)) if available else None
    cross_tier_verified = all(j["judge_tier"] != j["judged_tier"] for j in available) if available else None

    return {
        "hallucination_rate": hallucination_rate, "n_samples": len(judgments), "n_judged": len(available),
        "n_unavailable_reasoning_service": n_unavailable, "cross_tier_judging_verified": cross_tier_verified,
        "judgments": judgments,
    }
