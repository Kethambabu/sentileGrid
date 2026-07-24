"""LangGraph wiring: Sensor -> Trend -> Retrieval -> Compound-Risk ->
Compliance -> Explanation -> Emergency, matching CLAUDE.md §3's architecture
diagram exactly. Every LLM-agent node writes its result to the audit log
before returning — CLAUDE.md §2/§12: no shortcuts on the audit log, every
risk assessment/recommendation/decision gets logged, not just the ones that
end up mattering for a demo.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ..agents.compliance_agent import ComplianceAgent
from ..agents.compound_risk_agent import CompoundRiskAgent
from ..agents.emergency_agent import EmergencyAgent
from ..agents.explanation_agent import ExplanationAgent
from ..agents.retrieval_agent import RetrievalAgent
from ..agents.sensor_agent import SensorAgent
from ..agents.trend_agent import TrendAgent
from ..database.audit import AuditEntryInput, AuditWriteQueue, get_default_audit_queue
from .state import SentinelGridState


def build_graph(
    sensor_agent: SensorAgent | None = None,
    trend_agent: TrendAgent | None = None,
    retrieval_agent: RetrievalAgent | None = None,
    compound_risk_agent: CompoundRiskAgent | None = None,
    compliance_agent: ComplianceAgent | None = None,
    explanation_agent: ExplanationAgent | None = None,
    emergency_agent: EmergencyAgent | None = None,
    audit_queue: AuditWriteQueue | None = None,
):
    sensor_agent = sensor_agent or SensorAgent()
    trend_agent = trend_agent or TrendAgent()
    retrieval_agent = retrieval_agent or RetrievalAgent()
    compound_risk_agent = compound_risk_agent or CompoundRiskAgent()
    compliance_agent = compliance_agent or ComplianceAgent()
    explanation_agent = explanation_agent or ExplanationAgent()
    emergency_agent = emergency_agent or EmergencyAgent()
    audit_queue = audit_queue or get_default_audit_queue()

    def sensor_node(state: SentinelGridState) -> dict:
        return {"sensor_output": sensor_agent.process(state.records)}

    def trend_node(state: SentinelGridState) -> dict:
        cleaned = state.sensor_output.records if state.sensor_output else state.records
        return {"trend_output": trend_agent.compute(cleaned)}

    def retrieval_node(state: SentinelGridState) -> dict:
        cleaned = state.sensor_output.records if state.sensor_output else state.records
        return {"retrieval_outcome": retrieval_agent.retrieve(cleaned, equipment_zone=state.equipment_zone)}

    def _with_error(state: SentinelGridState, reasoning_unavailable: bool, agent_name: str, error_detail: str | None) -> list[str]:
        errors = list(state.errors)
        if reasoning_unavailable:
            suffix = f" — {error_detail}" if error_detail else ""
            errors.append(f"{agent_name}: reasoning service unavailable (both LLM tiers failed){suffix}")
        return errors

    def compound_risk_node(state: SentinelGridState) -> dict:
        risk = compound_risk_agent.assess(state.trend_output.features, state.retrieval_outcome, state.run_id)
        audit_queue.submit(
            AuditEntryInput(
                event_type="risk_assessment", agent_name="compound_risk_agent", run_id=state.run_id,
                payload={
                    "risk_score": risk.risk_score, "is_novel_condition": risk.is_novel_condition, "confidence": risk.confidence,
                    "contributing_factors": risk.contributing_factors, "recommended_action": risk.recommended_action,
                    "cited_chunk_ids": risk.cited_chunk_ids, "llm_tier_used": risk.llm_tier_used, "parse_error": risk.parse_error,
                    "reasoning_unavailable": risk.reasoning_unavailable, "error_detail": risk.error_detail,
                },
            )
        )
        return {"risk_assessment": risk, "errors": _with_error(state, risk.reasoning_unavailable, "compound_risk_agent", risk.error_detail)}

    def compliance_node(state: SentinelGridState) -> dict:
        result = compliance_agent.review(state.risk_assessment.recommended_action)
        audit_queue.submit(
            AuditEntryInput(
                event_type="compliance_check", agent_name="compliance_agent", run_id=state.run_id,
                payload={
                    "action_reviewed": result.action_reviewed, "approved": result.approved,
                    "cited_sop_chunk_ids": result.cited_sop_chunk_ids, "notes": result.notes, "llm_tier_used": result.llm_tier_used,
                    "reasoning_unavailable": result.reasoning_unavailable, "error_detail": result.error_detail,
                },
            )
        )
        return {"compliance_result": result, "errors": _with_error(state, result.reasoning_unavailable, "compliance_agent", result.error_detail)}

    def explanation_node(state: SentinelGridState) -> dict:
        explanation = explanation_agent.explain(state.risk_assessment, state.retrieval_outcome, state.compliance_result)
        audit_queue.submit(
            AuditEntryInput(
                event_type="explanation", agent_name="explanation_agent", run_id=state.run_id,
                payload={
                    "narrative": explanation.narrative, "cited_chunk_ids": explanation.cited_chunk_ids,
                    "llm_tier_used": explanation.llm_tier_used, "reasoning_unavailable": explanation.reasoning_unavailable,
                    "error_detail": explanation.error_detail,
                },
            )
        )
        return {"explanation": explanation, "errors": _with_error(state, explanation.reasoning_unavailable, "explanation_agent", explanation.error_detail)}

    def emergency_node(state: SentinelGridState) -> dict:
        recommendation = emergency_agent.maybe_escalate(state.risk_assessment, state.retrieval_outcome, state.run_id)
        if recommendation.triggered:
            audit_queue.submit(
                AuditEntryInput(
                    event_type="emergency_recommendation", agent_name="emergency_agent", run_id=state.run_id,
                    payload={
                        "recommended_interventions": recommendation.recommended_interventions,
                        "approval_id": recommendation.approval_id, "llm_tier_used": recommendation.llm_tier_used,
                        "reasoning_unavailable": recommendation.reasoning_unavailable, "error_detail": recommendation.error_detail,
                    },
                )
            )
        return {
            "emergency_recommendation": recommendation,
            "errors": _with_error(state, recommendation.reasoning_unavailable, "emergency_agent", recommendation.error_detail),
        }

    graph = StateGraph(SentinelGridState)
    graph.add_node("sensor", sensor_node)
    graph.add_node("trend", trend_node)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("compound_risk", compound_risk_node)
    graph.add_node("compliance", compliance_node)
    graph.add_node("explanation", explanation_node)
    graph.add_node("emergency", emergency_node)

    graph.add_edge(START, "sensor")
    graph.add_edge("sensor", "trend")
    graph.add_edge("trend", "retrieval")
    graph.add_edge("retrieval", "compound_risk")
    graph.add_edge("compound_risk", "compliance")
    graph.add_edge("compliance", "explanation")
    graph.add_edge("explanation", "emergency")
    graph.add_edge("emergency", END)

    return graph.compile()
