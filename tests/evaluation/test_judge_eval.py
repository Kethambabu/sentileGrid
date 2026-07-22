"""CLAUDE.md §9.5: 'Evaluation judge model must differ from the model that
produced the original answer being judged — no self-grading.' This is a
mechanism test: it verifies the judge router structurally cannot reach the
tier it's supposed to be independent of, without needing a live API call.
"""

from backend.evaluation.judge_eval import _opposite_tier_router
from backend.utils.llm_router import GroqProvider, HuggingFaceProvider, LLMTier


def test_judging_a_huggingface_answer_uses_only_groq():
    router = _opposite_tier_router("huggingface")
    assert isinstance(router.hf_provider, GroqProvider)
    assert isinstance(router.groq_provider, GroqProvider)
    assert router.hf_provider is router.groq_provider  # same instance in both slots — no fallback path to HF


def test_judging_a_groq_answer_uses_only_huggingface():
    router = _opposite_tier_router("groq")
    assert isinstance(router.hf_provider, HuggingFaceProvider)
    assert isinstance(router.groq_provider, HuggingFaceProvider)
    assert router.hf_provider is router.groq_provider


def test_judge_router_cannot_fall_through_to_judged_tier(monkeypatch):
    """Even if the judge's sole provider fails, the router must not somehow
    reach the tier being judged — verify the two configured providers are
    identical and neither is the judged tier's class."""
    router = _opposite_tier_router("huggingface")
    assert router.hf_provider.tier == LLMTier.GROQ
    assert router.groq_provider.tier == LLMTier.GROQ
