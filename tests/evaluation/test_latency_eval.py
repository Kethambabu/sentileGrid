from backend.agents.models import ComplianceResult, ExplanationResult, RiskAssessment
from backend.evaluation.collect_assessments import HoldoutAssessment
from backend.evaluation.latency_eval import evaluate_latency
from backend.rag.retriever import ConfidenceLevel, RetrievalOutcome, RetrievalPhase


def _assessment(risk_latency, compliance_latency, explanation_latency):
    outcome = RetrievalOutcome(phase=RetrievalPhase.FAST_AND_SLOW, is_novel_condition=False, confidence=ConfidenceLevel.HIGH, matches=[])
    risk = RiskAssessment(
        risk_score=50.0, is_novel_condition=False, confidence="high", contributing_factors=[], recommended_action="x",
        cited_chunk_ids=[], reasoning="y", llm_tier_used="huggingface", latency_ms=risk_latency,
    )
    compliance = ComplianceResult(action_reviewed="x", approved=True, cited_sop_chunk_ids=[], notes="ok", llm_tier_used="huggingface", latency_ms=compliance_latency)
    explanation = ExplanationResult(narrative="x", cited_chunk_ids=[], llm_tier_used="huggingface", latency_ms=explanation_latency)
    return HoldoutAssessment(
        scenario_name="test", seed=1, record_index=10, total_records=100, t_hours=0.5, expected_incident_id="test",
        expected_risk_level="low", retrieval_outcome=outcome, risk_assessment=risk, compliance_result=compliance, explanation=explanation,
    )


def test_latency_aggregation_computes_stats_per_agent():
    assessments = [_assessment(100, 200, 300), _assessment(300, 400, 500)]
    result = evaluate_latency(assessments)
    assert result["compound_risk"]["mean_ms"] == 200
    assert result["compound_risk"]["n_calls"] == 2
    assert result["compliance"]["mean_ms"] == 300
    assert result["explanation"]["max_ms"] == 500
    assert result["explanation"]["min_ms"] == 300


def test_latency_empty_assessments_returns_none_per_agent():
    result = evaluate_latency([])
    assert result["compound_risk"] is None
    assert result["compliance"] is None
    assert result["explanation"] is None
