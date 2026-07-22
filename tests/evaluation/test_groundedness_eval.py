from backend.agents.models import ComplianceResult, ExplanationResult, RiskAssessment
from backend.evaluation.collect_assessments import HoldoutAssessment
from backend.evaluation.groundedness_eval import evaluate_explanation_citation_completeness, evaluate_groundedness
from backend.rag.retriever import ConfidenceLevel, RetrievalMatch, RetrievalOutcome, RetrievalPhase


def _match(chunk_id):
    return RetrievalMatch(
        chunk_id=chunk_id, incident_id="x", scenario_type="s", equipment_zone="reactor", risk_level="high",
        stage="critical", fast_similarity=0.9, slow_similarity=0.9, combined_similarity=0.9, narrative_text="text",
    )


def _assessment(cited_chunk_ids, available_chunk_ids, is_novel=False, explanation_cited=None):
    outcome = RetrievalOutcome(
        phase=RetrievalPhase.FAST_AND_SLOW, is_novel_condition=is_novel,
        confidence=ConfidenceLevel.NOVEL if is_novel else ConfidenceLevel.HIGH,
        matches=[_match(c) for c in available_chunk_ids],
    )
    risk = RiskAssessment(
        risk_score=None if is_novel else 60.0, is_novel_condition=is_novel, confidence="high", contributing_factors=[],
        recommended_action="x", cited_chunk_ids=cited_chunk_ids, reasoning="y", llm_tier_used="huggingface", latency_ms=1.0,
    )
    compliance = ComplianceResult(action_reviewed="x", approved=True, cited_sop_chunk_ids=[], notes="ok", llm_tier_used="huggingface", latency_ms=1.0)
    explanation = ExplanationResult(
        narrative="text", cited_chunk_ids=explanation_cited if explanation_cited is not None else cited_chunk_ids,
        llm_tier_used="huggingface", latency_ms=1.0,
    )
    return HoldoutAssessment(
        scenario_name="test", seed=1, record_index=10, total_records=100, t_hours=0.5, expected_incident_id="x",
        expected_risk_level="high", retrieval_outcome=outcome, risk_assessment=risk, compliance_result=compliance, explanation=explanation,
    )


def test_citation_within_retrieved_chunks_is_grounded():
    assessment = _assessment(cited_chunk_ids=["a"], available_chunk_ids=["a", "b"])
    result = evaluate_groundedness([assessment])
    assert result["groundedness_score"] == 1.0


def test_fabricated_citation_not_in_retrieved_chunks_is_ungrounded():
    assessment = _assessment(cited_chunk_ids=["fabricated"], available_chunk_ids=["a", "b"])
    result = evaluate_groundedness([assessment])
    assert result["groundedness_score"] == 0.0
    assert result["details"][0]["grounded"] is False


def test_no_citation_on_novel_condition_is_grounded():
    assessment = _assessment(cited_chunk_ids=[], available_chunk_ids=[], is_novel=True)
    result = evaluate_groundedness([assessment])
    assert result["groundedness_score"] == 1.0


def test_no_citation_when_not_novel_is_ungrounded():
    assessment = _assessment(cited_chunk_ids=[], available_chunk_ids=["a"], is_novel=False)
    result = evaluate_groundedness([assessment])
    assert result["groundedness_score"] == 0.0


def test_empty_assessments_returns_none_score():
    result = evaluate_groundedness([])
    assert result["groundedness_score"] is None
    assert result["n_samples"] == 0


def test_citation_completeness_counts_only_applicable_assessments():
    cited = _assessment(cited_chunk_ids=["a"], available_chunk_ids=["a"], explanation_cited=["a"])
    not_cited = _assessment(cited_chunk_ids=["a"], available_chunk_ids=["a"], explanation_cited=[])
    novel = _assessment(cited_chunk_ids=[], available_chunk_ids=[], is_novel=True, explanation_cited=[])

    result = evaluate_explanation_citation_completeness([cited, not_cited, novel])
    assert result["n_applicable"] == 2  # novel condition isn't "applicable" (nothing to cite)
    assert result["n_cited"] == 1
    assert result["citation_completeness_score"] == 0.5
