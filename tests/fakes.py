"""Shared test doubles, used across tests/agents/, tests/utils/, and
tests/orchestrator/. Not itself a mirror of a backend/ module — a small,
deliberate exception to the tests/ mirrors backend/ convention, same as any
project's conftest/helpers module.
"""

from __future__ import annotations

from backend.utils.llm_router import LLMProvider, LLMRequest, LLMResponse, LLMTier


class FakeLLMProvider(LLMProvider):
    def __init__(self, tier: LLMTier, content: str = "{}", should_fail: bool = False, latency_ms: float = 5.0) -> None:
        self.tier = tier
        self.content = content
        self.should_fail = should_fail
        self.latency_ms = latency_ms
        self.calls: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if self.should_fail:
            raise RuntimeError("fake provider configured to fail")
        return LLMResponse(content=self.content, tier_used=self.tier, model_name="fake-model", latency_ms=self.latency_ms)


class ScriptedLLMProvider(LLMProvider):
    """Returns different canned content depending on a keyword found in the
    prompt — needed when one fake provider stands in for several agents at
    once (e.g. RunManager shares a single LLMRouter across all 4 LLM
    agents), each expecting a differently-shaped response."""

    def __init__(self, tier: LLMTier, rules: list[tuple[str, str]], default_content: str = "{}", latency_ms: float = 5.0) -> None:
        self.tier = tier
        self.rules = rules
        self.default_content = default_content
        self.latency_ms = latency_ms
        self.calls: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        text = request.messages[-1].content if request.messages else ""
        for keyword, content in self.rules:
            if keyword in text:
                return LLMResponse(content=content, tier_used=self.tier, model_name="fake-model", latency_ms=self.latency_ms)
        return LLMResponse(content=self.default_content, tier_used=self.tier, model_name="fake-model", latency_ms=self.latency_ms)
