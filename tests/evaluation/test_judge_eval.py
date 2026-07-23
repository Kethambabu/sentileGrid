"""CLAUDE.md §9.5: 'Evaluation judge model must differ from the model that
produced the original answer being judged — no self-grading.' This is a
mechanism test: it verifies the judge router structurally cannot reach the
tier it's supposed to be independent of, without needing a live API call.
"""

from backend.evaluation.judge_eval import _opposite_tier_router
from backend.utils.llm_router import GeminiProvider, GroqProvider, LLMTier


def test_judging_a_gemini_answer_uses_only_groq():
    router = _opposite_tier_router("gemini")
    assert isinstance(router.gemini_provider, GroqProvider)
    assert isinstance(router.groq_provider, GroqProvider)
    assert router.gemini_provider is router.groq_provider  # same instance in both slots — no fallback path to Gemini


def test_judging_a_groq_answer_uses_only_gemini():
    router = _opposite_tier_router("groq")
    assert isinstance(router.gemini_provider, GeminiProvider)
    assert isinstance(router.groq_provider, GeminiProvider)
    assert router.gemini_provider is router.groq_provider


def test_judge_router_cannot_fall_through_to_judged_tier(monkeypatch):
    """Even if the judge's sole provider fails, the router must not somehow
    reach the tier being judged — verify the two configured providers are
    identical and neither is the judged tier's class."""
    router = _opposite_tier_router("gemini")
    assert router.gemini_provider.tier == LLMTier.GROQ
    assert router.groq_provider.tier == LLMTier.GROQ
