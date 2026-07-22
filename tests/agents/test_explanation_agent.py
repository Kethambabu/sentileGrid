from backend.agents.explanation_agent import ExplanationAgent
from backend.agents.models import ComplianceResult, RiskAssessment
from backend.rag.retriever import ConfidenceLevel, RetrievalMatch, RetrievalOutcome, RetrievalPhase
from backend.utils.llm_router import LLMRouter, LLMTier
from tests.fakes import FakeLLMProvider


def _router(content: str) -> LLMRouter:
    hf = FakeLLMProvider(LLMTier.HUGGING_FACE, content=content)
    groq = FakeLLMProvider(LLMTier.GROQ, content=content)
    return LLMRouter(hf_provider=hf, groq_provider=groq, config={
        "huggingface": {"model": "m", "timeout_seconds": 5}, "groq": {"model": "m", "timeout_seconds": 5},
        "cache": {"ttl_seconds": 0}, "defaults": {"max_tokens": 500, "temperature": 0.7},
    })


def _risk():
    return RiskAssessment(
        risk_score=62.5, is_novel_condition=False, confidence="high", contributing_factors=["falling pressure"],
        recommended_action="increase cooling", cited_chunk_ids=["incident_x::critical"], reasoning="matches precedent",
        llm_tier_used="huggingface", latency_ms=10.0,
    )


def _outcome():
    match = RetrievalMatch(
        chunk_id="incident_x::critical", incident_id="incident_x", scenario_type="test", equipment_zone="reactor",
        risk_level="high", stage="critical", fast_similarity=0.9, slow_similarity=0.9, combined_similarity=0.9,
        narrative_text="Reactor pressure falling steadily.",
    )
    return RetrievalOutcome(phase=RetrievalPhase.FAST_AND_SLOW, is_novel_condition=False, confidence=ConfidenceLevel.HIGH, matches=[match])


def test_explanation_uses_llm_narrative_verbatim():
    agent = ExplanationAgent(router=_router("Reactor pressure is falling in a pattern matching [chunk_id=\"incident_x::critical\"]."))
    result = agent.explain(_risk(), _outcome())
    assert "falling" in result.narrative
    assert result.llm_tier_used == "huggingface"


def test_cited_chunks_include_ones_mentioned_in_narrative():
    agent = ExplanationAgent(router=_router("See [chunk_id=\"incident_x::critical\"] for precedent."))
    result = agent.explain(_risk(), _outcome())
    assert "incident_x::critical" in result.cited_chunk_ids


def test_cited_chunks_fall_back_to_risk_assessment_when_narrative_cites_nothing():
    agent = ExplanationAgent(router=_router("Plain narrative with no citations."))
    result = agent.explain(_risk(), _outcome())
    assert result.cited_chunk_ids == _risk().cited_chunk_ids


def test_explanation_accepts_optional_compliance_result():
    compliance = ComplianceResult(action_reviewed="increase cooling", approved=True, cited_sop_chunk_ids=["sop::part0"], notes="ok", llm_tier_used="groq", latency_ms=5.0)
    agent = ExplanationAgent(router=_router("Narrative mentioning compliance."))
    result = agent.explain(_risk(), _outcome(), compliance=compliance)
    assert result.narrative
