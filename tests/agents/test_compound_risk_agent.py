import json

from backend.agents.compound_risk_agent import CompoundRiskAgent
from backend.agents.models import TrendFeature
from backend.rag.retriever import ConfidenceLevel, RetrievalOutcome, RetrievalPhase
from backend.utils.llm_router import LLMRouter, LLMTier
from tests.fakes import FakeLLMProvider


def _trend_features():
    return [TrendFeature(field="xmeas.reactor_pressure_kpa", first_value=2705.0, last_value=2560.0, delta=-145.0, slope_per_minute=-2.0, direction="falling")]


def _outcome(is_novel: bool, confidence: ConfidenceLevel) -> RetrievalOutcome:
    return RetrievalOutcome(phase=RetrievalPhase.FAST_AND_SLOW, is_novel_condition=is_novel, confidence=confidence, matches=[])


def _router(content: str) -> LLMRouter:
    gemini = FakeLLMProvider(LLMTier.GEMINI, content=content)
    groq = FakeLLMProvider(LLMTier.GROQ, content=content)
    return LLMRouter(gemini_provider=gemini, groq_provider=groq, config={
        "gemini": {"model": "m", "timeout_seconds": 5}, "groq": {"model": "m", "timeout_seconds": 5},
        "cache": {"ttl_seconds": 0}, "defaults": {"max_tokens": 500, "temperature": 0.1},
    })


def test_normal_assessment_parses_llm_json():
    content = json.dumps({
        "risk_score": 62.5, "contributing_factors": ["falling reactor pressure", "recycle valve drift"],
        "recommended_action": "Increase reactor cooling water flow", "cited_chunk_ids": ["incident::stage"], "reasoning": "trend matches precedent",
    })
    agent = CompoundRiskAgent(router=_router(content))
    result = agent.assess(_trend_features(), _outcome(is_novel=False, confidence=ConfidenceLevel.HIGH), run_id="run-1")

    assert result.risk_score == 62.5
    assert result.is_novel_condition is False
    assert "falling reactor pressure" in result.contributing_factors
    assert result.parse_error is False


def test_novel_condition_forces_risk_score_none_even_if_llm_returns_a_number():
    """CLAUDE.md §9.2: code-level enforcement, not a prompt-level suggestion."""
    content = json.dumps({"risk_score": 95.0, "contributing_factors": ["should be ignored"], "recommended_action": "x", "cited_chunk_ids": [], "reasoning": "y"})
    agent = CompoundRiskAgent(router=_router(content))
    result = agent.assess(_trend_features(), _outcome(is_novel=True, confidence=ConfidenceLevel.NOVEL), run_id="run-1")

    assert result.risk_score is None
    assert result.is_novel_condition is True


def test_unparseable_llm_output_falls_back_conservatively():
    agent = CompoundRiskAgent(router=_router("not valid json at all"))
    result = agent.assess(_trend_features(), _outcome(is_novel=False, confidence=ConfidenceLevel.MODERATE), run_id="run-1")

    assert result.risk_score is None
    assert result.parse_error is True


def test_llm_tier_used_is_recorded():
    content = json.dumps({"risk_score": 10.0, "contributing_factors": [], "recommended_action": "x", "cited_chunk_ids": [], "reasoning": "y"})
    agent = CompoundRiskAgent(router=_router(content))
    result = agent.assess(_trend_features(), _outcome(is_novel=False, confidence=ConfidenceLevel.MODERATE), run_id="run-1")
    assert result.llm_tier_used == "gemini"


def test_reasoning_unavailable_when_both_tiers_fail():
    """CLAUDE.md §14: both LLM tiers down must produce a visible 'reasoning
    unavailable' result, never guess a risk score and never raise uncaught."""
    gemini = FakeLLMProvider(LLMTier.GEMINI, should_fail=True)
    groq = FakeLLMProvider(LLMTier.GROQ, should_fail=True)
    router = LLMRouter(gemini_provider=gemini, groq_provider=groq, config={
        "gemini": {"model": "m", "timeout_seconds": 5}, "groq": {"model": "m", "timeout_seconds": 5},
        "cache": {"ttl_seconds": 0}, "defaults": {"max_tokens": 500, "temperature": 0.1},
    })
    agent = CompoundRiskAgent(router=router)
    result = agent.assess(_trend_features(), _outcome(is_novel=False, confidence=ConfidenceLevel.MODERATE), run_id="run-1")

    assert result.risk_score is None
    assert result.reasoning_unavailable is True
    assert result.llm_tier_used == "unavailable"
    assert result.error_detail is not None and "fake provider configured to fail" in result.error_detail
