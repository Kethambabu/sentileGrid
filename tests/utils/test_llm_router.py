import pytest

from backend.utils.llm_router import LLMMessage, LLMRequest, LLMRouter, LLMTier, ReasoningServiceUnavailableError
from tests.fakes import FakeLLMProvider


def _config():
    return {
        "gemini": {"model": "fake-gemini-model", "timeout_seconds": 5},
        "groq": {"model": "fake-groq-model", "timeout_seconds": 5},
        "cache": {"ttl_seconds": 5},
        "defaults": {"max_tokens": 512, "temperature": 0.5},
    }


def _request():
    return LLMRequest(messages=[LLMMessage(role="user", content="hello")], temperature=0.1, max_tokens=100)


def test_primary_tier_success_does_not_touch_fallback():
    gemini = FakeLLMProvider(LLMTier.GEMINI, content="gemini response")
    groq = FakeLLMProvider(LLMTier.GROQ, content="groq response")
    router = LLMRouter(gemini_provider=gemini, groq_provider=groq, config=_config())

    response = router.complete(_request())
    assert response.tier_used == LLMTier.GEMINI
    assert response.content == "gemini response"
    assert len(gemini.calls) == 1
    assert len(groq.calls) == 0
    assert router.active_tier == LLMTier.GEMINI


def test_primary_failure_falls_back_to_groq():
    gemini = FakeLLMProvider(LLMTier.GEMINI, should_fail=True)
    groq = FakeLLMProvider(LLMTier.GROQ, content="groq response")
    router = LLMRouter(gemini_provider=gemini, groq_provider=groq, config=_config())

    response = router.complete(_request())
    assert response.tier_used == LLMTier.GROQ
    assert response.content == "groq response"
    assert router.active_tier == LLMTier.GROQ


def test_both_tiers_failing_raises_visibly():
    gemini = FakeLLMProvider(LLMTier.GEMINI, should_fail=True)
    groq = FakeLLMProvider(LLMTier.GROQ, should_fail=True)
    router = LLMRouter(gemini_provider=gemini, groq_provider=groq, config=_config())

    with pytest.raises(ReasoningServiceUnavailableError):
        router.complete(_request())
    assert router.active_tier == LLMTier.UNAVAILABLE


def test_identical_requests_are_cached_within_ttl():
    gemini = FakeLLMProvider(LLMTier.GEMINI, content="gemini response")
    groq = FakeLLMProvider(LLMTier.GROQ, content="groq response")
    router = LLMRouter(gemini_provider=gemini, groq_provider=groq, config=_config())

    r1 = router.complete(_request())
    r2 = router.complete(_request())
    assert r1.cached is False
    assert r2.cached is True
    assert len(gemini.calls) == 1  # second call served from cache, not a real request


def test_different_requests_are_not_cached_together():
    gemini = FakeLLMProvider(LLMTier.GEMINI, content="gemini response")
    groq = FakeLLMProvider(LLMTier.GROQ, content="groq response")
    router = LLMRouter(gemini_provider=gemini, groq_provider=groq, config=_config())

    router.complete(_request())
    router.complete(LLMRequest(messages=[LLMMessage(role="user", content="different")], temperature=0.1, max_tokens=100))
    assert len(gemini.calls) == 2


def test_on_response_callback_invoked_on_success():
    calls = []
    gemini = FakeLLMProvider(LLMTier.GEMINI, content="gemini response")
    groq = FakeLLMProvider(LLMTier.GROQ, content="groq response")
    router = LLMRouter(gemini_provider=gemini, groq_provider=groq, config=_config(), on_response=lambda req, resp: calls.append((req, resp)))

    router.complete(_request())
    assert len(calls) == 1
    assert calls[0][1].tier_used == LLMTier.GEMINI
