from backend.agents.models import ComplianceResult, ExplanationResult, RiskAssessment
from backend.evaluation.collect_assessments import HoldoutAssessment
from backend.evaluation.risk_accuracy_eval import evaluate_risk_accuracy
from backend.rag.retriever import ConfidenceLevel, RetrievalOutcome, RetrievalPhase


def _assessment(risk_score, expected_risk_level, is_novel=False):
    outcome = RetrievalOutcome(phase=RetrievalPhase.FAST_AND_SLOW, is_novel_condition=is_novel, confidence=ConfidenceLevel.HIGH, matches=[])
    risk = RiskAssessment(
        risk_score=risk_score, is_novel_condition=is_novel, confidence="high", contributing_factors=[],
        recommended_action="x", cited_chunk_ids=[], reasoning="y", llm_tier_used="huggingface", latency_ms=1.0,
    )
    compliance = ComplianceResult(action_reviewed="x", approved=True, cited_sop_chunk_ids=[], notes="ok", llm_tier_used="huggingface", latency_ms=1.0)
    explanation = ExplanationResult(narrative="x", cited_chunk_ids=[], llm_tier_used="huggingface", latency_ms=1.0)
    return HoldoutAssessment(
        scenario_name="test", seed=1, record_index=10, total_records=100, t_hours=0.5, expected_incident_id="test",
        expected_risk_level=expected_risk_level, retrieval_outcome=outcome, risk_assessment=risk,
        compliance_result=compliance, explanation=explanation,
    )


def test_low_score_matches_low_expected():
    result = evaluate_risk_accuracy([_assessment(20.0, "low")])
    assert result["risk_accuracy"] == 1.0
    assert result["details"][0]["actual_bucket"] == "low"


def test_high_score_does_not_match_low_expected():
    result = evaluate_risk_accuracy([_assessment(90.0, "low")])
    assert result["risk_accuracy"] == 0.0
    assert result["details"][0]["actual_bucket"] == "high"


def test_moderate_bucket_boundaries():
    result = evaluate_risk_accuracy([_assessment(55.0, "moderate")])
    assert result["details"][0]["actual_bucket"] == "moderate"
    assert result["risk_accuracy"] == 1.0


def test_novel_condition_bucket():
    result = evaluate_risk_accuracy([_assessment(None, "low", is_novel=True)])
    assert result["details"][0]["actual_bucket"] == "novel"
    assert result["details"][0]["correct"] is False  # "novel" never equals an expected low/moderate/high label


def test_baseline_checkpoint_with_no_authored_stage_expects_low():
    outcome = RetrievalOutcome(phase=RetrievalPhase.FAST_AND_SLOW, is_novel_condition=False, confidence=ConfidenceLevel.HIGH, matches=[])
    risk = RiskAssessment(
        risk_score=20.0, is_novel_condition=False, confidence="high", contributing_factors=[], recommended_action="x",
        cited_chunk_ids=[], reasoning="y", llm_tier_used="huggingface", latency_ms=1.0,
    )
    compliance = ComplianceResult(action_reviewed="x", approved=True, cited_sop_chunk_ids=[], notes="ok", llm_tier_used="huggingface", latency_ms=1.0)
    explanation = ExplanationResult(narrative="x", cited_chunk_ids=[], llm_tier_used="huggingface", latency_ms=1.0)
    assessment = HoldoutAssessment(
        scenario_name="baseline", seed=1, record_index=10, total_records=100, t_hours=0.5, expected_incident_id=None,
        expected_risk_level=None, retrieval_outcome=outcome, risk_assessment=risk, compliance_result=compliance, explanation=explanation,
    )
    result = evaluate_risk_accuracy([assessment])
    assert result["details"][0]["expected_risk_level"] == "low"
    assert result["risk_accuracy"] == 1.0


def test_empty_assessments():
    result = evaluate_risk_accuracy([])
    assert result["risk_accuracy"] is None
    assert result["n_samples"] == 0
