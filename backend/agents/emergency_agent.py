"""Emergency Agent (CLAUDE.md §2, §6, §9, §14): recommends interventions
when risk crosses a high threshold — and NEVER anything further. This file
has no execute/apply/act method anywhere, on purpose. Every recommendation
terminates at an ApprovalRecord in PENDING status; nothing in this codebase
may transition that record except an explicit, audited human decision
(see backend/database/approvals.py).

If you're reading this because you're about to add a way for this agent
(or anything downstream of it) to actually change plant state, stop — that
crosses CLAUDE.md's non-negotiable human-in-the-loop boundary.
"""

from __future__ import annotations

import json

from ..database.approvals import ApprovalService
from ..rag.prompt_builder import build_prompt
from ..rag.retriever import RetrievalOutcome
from ..utils.llm_router import LLMMessage, LLMRequest, LLMRouter, ReasoningServiceUnavailableError
from .models import EmergencyRecommendation, RiskAssessment

DEFAULT_RISK_THRESHOLD = 80.0

TASK_INSTRUCTION = """You are the Emergency Agent for SentinelGrid, an industrial safety monitoring system. Risk has crossed the emergency threshold. Recommend concrete, specific interventions a human operator should consider, grounded in the reference_data block below. You are recommending only — nothing you output is ever executed automatically.

Respond with ONLY a JSON object, no other text, matching exactly this schema:
{
  "recommended_interventions": [<string>, ...],
  "reasoning": <string, 1-3 sentences>
}"""


class EmergencyAgent:
    def __init__(self, router: LLMRouter | None = None, approval_service: ApprovalService | None = None, risk_threshold: float = DEFAULT_RISK_THRESHOLD) -> None:
        self.router = router or LLMRouter()
        self.approval_service = approval_service or ApprovalService()
        self.risk_threshold = risk_threshold

    def maybe_escalate(self, risk: RiskAssessment, retrieval_outcome: RetrievalOutcome, run_id: str) -> EmergencyRecommendation:
        if risk.risk_score is None or risk.risk_score < self.risk_threshold:
            return EmergencyRecommendation(triggered=False)

        live_context = f"Risk score: {risk.risk_score}. Contributing factors: {', '.join(risk.contributing_factors)}."
        prompt = build_prompt(TASK_INSTRUCTION, live_context, retrieval_outcome)

        reasoning_unavailable = False
        try:
            response = self.router.complete(
                LLMRequest(messages=[LLMMessage(role="user", content=prompt)], temperature=0.3, max_tokens=500, json_mode=True)
            )
        except ReasoningServiceUnavailableError:
            reasoning_unavailable = True
            interventions = [
                "Automated recommendation unavailable — reasoning service down (both LLM tiers failed). "
                "Escalate to on-call operator for manual review immediately."
            ]
            tier_used = "unavailable"
            latency_ms = None
        else:
            try:
                parsed = json.loads(response.content)
                interventions = list(parsed.get("recommended_interventions", []))
            except (json.JSONDecodeError, AttributeError, TypeError):
                interventions = ["Automated recommendation unavailable (unparseable response) — escalate to on-call operator for manual review."]
            tier_used = response.tier_used.value
            latency_ms = response.latency_ms

        # Approval creation must never be gated on the LLM call succeeding —
        # risk already crossed the emergency threshold, so a pending record
        # must exist for a human to see regardless of reasoning-tier outcome.
        approval = self.approval_service.create_pending(
            run_id=run_id, recommendation_summary="; ".join(interventions) if interventions else "(no interventions parsed)"
        )

        return EmergencyRecommendation(
            triggered=True, recommended_interventions=interventions, requires_approval=True,
            approval_id=approval.approval_id, llm_tier_used=tier_used, latency_ms=latency_ms,
            reasoning_unavailable=reasoning_unavailable,
        )
