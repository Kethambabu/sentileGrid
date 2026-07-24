"""Compound-Risk Agent (CLAUDE.md §6, §9.2, §14): the core of the project's
thesis — detect danger that lives in the *combination and trend* of
readings, not any single reading. Uses the LLM router with low temperature
and constrained JSON output (CLAUDE.md §14: reserve creativity for the
Explanation Agent only).

Hard rule, enforced in code and not just requested in the prompt: if
retrieval confidence is "novel" (below the similarity threshold), risk_score
is forced to None regardless of what the LLM returns. CLAUDE.md §9.2 is
explicit that this must never be a soft, prompt-level suggestion the model
can ignore — it's a code-level guarantee.
"""

from __future__ import annotations

import json

from ..rag.prompt_builder import build_prompt
from ..rag.retriever import ConfidenceLevel, RetrievalOutcome
from ..utils.llm_router import LLMMessage, LLMRequest, LLMRouter, ReasoningServiceUnavailableError
from .models import RiskAssessment, TrendFeature

TASK_INSTRUCTION = """You are the Compound-Risk Agent for SentinelGrid, an industrial safety monitoring system for a chemical plant. Your job is to detect compound risk: situations where individual sensor readings look normal in isolation but their COMBINATION and TREND across time signal danger. You are given the current live trend features (rate of change per channel, below) and retrieved historical precedent (in the reference_data block).

Respond with ONLY a JSON object, no other text, matching exactly this schema:
{
  "risk_score": <float 0-100, or null if you cannot ground this in the retrieved reference data>,
  "contributing_factors": [<string>, ...],
  "recommended_action": <string: a single concrete first-line action>,
  "cited_chunk_ids": [<string chunk_id from reference_data that supports your assessment>, ...],
  "reasoning": <string, 1-3 sentences>
}

If retrieval confidence is "novel" or the reference_data block indicates a NOVEL CONDITION, you MUST set risk_score to null and explain what's unusual in reasoning instead of guessing a number."""


def format_trend_context(features: list[TrendFeature]) -> str:
    if not features:
        return "(Fewer than 2 records available — no trend features yet.)"
    lines = []
    for f in features:
        lines.append(f"{f.field}: {f.first_value:.3f} -> {f.last_value:.3f} ({f.direction}, slope {f.slope_per_minute:+.4f}/min)")
    return "\n".join(lines)


class CompoundRiskAgent:
    def __init__(self, router: LLMRouter | None = None) -> None:
        self.router = router or LLMRouter()

    def assess(self, trend_features: list[TrendFeature], retrieval_outcome: RetrievalOutcome, run_id: str) -> RiskAssessment:
        live_context = format_trend_context(trend_features)
        prompt = build_prompt(TASK_INSTRUCTION, live_context, retrieval_outcome)

        is_novel = retrieval_outcome.is_novel_condition or retrieval_outcome.confidence == ConfidenceLevel.NOVEL

        try:
            response = self.router.complete(
                LLMRequest(messages=[LLMMessage(role="user", content=prompt)], temperature=0.1, max_tokens=600, json_mode=True)
            )
        except ReasoningServiceUnavailableError as exc:
            return RiskAssessment(
                risk_score=None,
                is_novel_condition=is_novel,
                confidence=retrieval_outcome.confidence.value,
                contributing_factors=["Reasoning service unavailable — both LLM tiers failed"],
                recommended_action="Escalate for manual review — reasoning service unavailable.",
                cited_chunk_ids=[],
                reasoning="Both Gemini and Groq LLM tiers failed; refusing to guess a risk score.",
                llm_tier_used="unavailable",
                latency_ms=0.0,
                reasoning_unavailable=True,
                error_detail=str(exc),
            )

        parse_error = False
        try:
            parsed = json.loads(response.content)
            risk_score = parsed.get("risk_score")
            contributing_factors = list(parsed.get("contributing_factors", []))
            recommended_action = str(parsed.get("recommended_action", ""))
            cited_chunk_ids = list(parsed.get("cited_chunk_ids", []))
            reasoning = str(parsed.get("reasoning", ""))
        except (json.JSONDecodeError, AttributeError, TypeError):
            parse_error = True
            risk_score = None
            contributing_factors = ["LLM output could not be parsed as JSON"]
            recommended_action = "Escalate for manual review — automated assessment unavailable."
            cited_chunk_ids = []
            reasoning = "The reasoning-tier response was not valid JSON; refusing to guess a risk score."

        if is_novel:
            risk_score = None  # code-level enforcement, independent of what the LLM returned (CLAUDE.md §9.2)

        return RiskAssessment(
            risk_score=risk_score,
            is_novel_condition=is_novel,
            confidence=retrieval_outcome.confidence.value,
            contributing_factors=contributing_factors,
            recommended_action=recommended_action,
            cited_chunk_ids=cited_chunk_ids,
            reasoning=reasoning,
            llm_tier_used=response.tier_used.value,
            latency_ms=response.latency_ms,
            parse_error=parse_error,
        )
