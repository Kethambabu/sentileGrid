"""Explanation Agent (CLAUDE.md §6, §14): plain-language narrative weaving
together the risk assessment, retrieved evidence, and compliance result.
Higher temperature than Compound-Risk — CLAUDE.md §14 explicitly reserves
creativity for this agent, not the risk-scoring one.
"""

from __future__ import annotations

from ..rag.prompt_builder import build_prompt
from ..rag.retriever import RetrievalOutcome
from ..utils.llm_router import LLMMessage, LLMRequest, LLMRouter
from .models import ComplianceResult, ExplanationResult, RiskAssessment

TASK_INSTRUCTION = """You are the Explanation Agent for SentinelGrid, an industrial safety monitoring system. Write a short, plain-language narrative (3-6 sentences) for a plant operator explaining the current risk assessment below, citing the reference_data chunk_ids that support each claim inline like [chunk_id="..."]. Be concrete about WHICH readings are involved and HOW they relate — this system's whole point is that danger lives in the combination of readings, not any one of them. Do not invent facts not present in the risk assessment, compliance result, or reference_data below. Respond with plain text only, not JSON."""


def _format_context(risk: RiskAssessment, compliance: ComplianceResult | None) -> str:
    lines = [
        f"Risk score: {risk.risk_score if risk.risk_score is not None else 'N/A (novel condition)'}",
        f"Confidence: {risk.confidence}",
        f"Contributing factors: {', '.join(risk.contributing_factors) or 'none listed'}",
        f"Recommended action: {risk.recommended_action}",
    ]
    if compliance is not None:
        lines.append(f"Compliance review: {'APPROVED' if compliance.approved else 'NOT APPROVED'} — {compliance.notes}")
    return "\n".join(lines)


class ExplanationAgent:
    def __init__(self, router: LLMRouter | None = None) -> None:
        self.router = router or LLMRouter()

    def explain(self, risk: RiskAssessment, retrieval_outcome: RetrievalOutcome, compliance: ComplianceResult | None = None) -> ExplanationResult:
        live_context = _format_context(risk, compliance)
        prompt = build_prompt(TASK_INSTRUCTION, live_context, retrieval_outcome)

        response = self.router.complete(
            LLMRequest(messages=[LLMMessage(role="user", content=prompt)], temperature=0.7, max_tokens=500, json_mode=False)
        )

        cited = [m.chunk_id for m in retrieval_outcome.matches if m.chunk_id in response.content] or risk.cited_chunk_ids

        return ExplanationResult(
            narrative=response.content, cited_chunk_ids=cited, llm_tier_used=response.tier_used.value, latency_ms=response.latency_ms,
        )
