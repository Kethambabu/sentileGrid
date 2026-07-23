"""Shared LLM fallback router (CLAUDE.md §5): every LLM-calling agent goes
through this, not a hardcoded provider. Two-tier fallback, in order —
Hugging Face Serverless Inference API, then Groq — no third/offline tier,
no HF Inference Providers routing as the "second" tier (that can silently
route to Groq under the hood, which isn't real redundancy with a direct
Groq call).

Deliberately does NOT import backend.database: this module sits below the
agent/orchestrator layer and must not depend upward on it. Callers that
want responses written to the audit trail pass an `on_response` callback;
llm_router has no opinion on how or whether that happens.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from pydantic import BaseModel

from .config_loader import load_yaml_config

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LLM_CONFIG_PATH = REPO_ROOT / "backend" / "config" / "llm.yaml"

load_dotenv(REPO_ROOT / ".env")


class LLMTier(str, Enum):
    HUGGING_FACE = "huggingface"
    GROQ = "groq"
    UNAVAILABLE = "unavailable"


class LLMMessage(BaseModel):
    role: str  # "system" | "user" | "assistant"
    content: str


class LLMRequest(BaseModel):
    messages: list[LLMMessage]
    temperature: float = 0.7
    max_tokens: int = 1024
    json_mode: bool = False


class LLMResponse(BaseModel):
    content: str
    tier_used: LLMTier
    model_name: str
    latency_ms: float
    cached: bool = False


class ReasoningServiceUnavailableError(RuntimeError):
    """Both tiers failed. CLAUDE.md §14: fail visibly, never hang or
    silently retry forever."""

    def __init__(self, hf_error: Exception | None, groq_error: Exception | None) -> None:
        super().__init__(
            f"Reasoning service unavailable — both LLM tiers failed. "
            f"HF error: {hf_error!r}. Groq error: {groq_error!r}."
        )
        self.hf_error = hf_error
        self.groq_error = groq_error


class LLMProvider(ABC):
    tier: LLMTier

    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse: ...


class HuggingFaceProvider(LLMProvider):
    """Hugging Face's old free "Serverless Inference API"
    (api-inference.huggingface.co) was retired — it now 404/DNS-fails
    entirely. The replacement (router.huggingface.co, the "Inference
    Providers" router) is a metered, pay-as-you-go service: free accounts
    get $0.10/month credit, then billing kicks in. This is a real change to
    CLAUDE.md §2's "zero paid resources" constraint that we cannot code our
    way around — flagged explicitly rather than silently absorbed.

    `provider` MUST be pinned to a specific backend (never "auto") and MUST
    NOT be a provider Groq also resolves to — otherwise "tier 1 fails, fall
    back to tier 2 Groq" can silently mean "call Groq twice," which is not
    real redundancy (CLAUDE.md §5's exact concern about Inference Providers
    routing). Verified 2026-07-23: the configured model
    (Qwen/Qwen2.5-72B-Instruct) is served by featherless-ai/novita/deepinfra
    — none of which are Groq — so pinning to one of those is safe. The HF
    account token also needs the "Make calls to Inference Providers"
    permission explicitly granted (not on by default for fine-grained
    tokens) — without it every call 403s regardless of model/provider choice.
    """

    tier = LLMTier.HUGGING_FACE

    def __init__(self, model: str, timeout_seconds: float, provider: str = "featherless-ai", api_token: str | None = None) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.provider = provider
        self.api_token = api_token if api_token is not None else os.environ.get("HF_API_TOKEN")

    def complete(self, request: LLMRequest) -> LLMResponse:
        if not self.api_token:
            raise RuntimeError("HF_API_TOKEN is not set")
        from huggingface_hub import InferenceClient

        client = InferenceClient(model=self.model, provider=self.provider, token=self.api_token, timeout=self.timeout_seconds)
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        start = time.monotonic()
        result = client.chat_completion(messages=messages, temperature=request.temperature, max_tokens=request.max_tokens)
        latency_ms = (time.monotonic() - start) * 1000.0
        content = result.choices[0].message.content
        return LLMResponse(content=content, tier_used=self.tier, model_name=self.model, latency_ms=latency_ms)


class GroqProvider(LLMProvider):
    tier = LLMTier.GROQ

    def __init__(self, model: str, timeout_seconds: float, api_key: str | None = None) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.api_key = api_key if api_key is not None else os.environ.get("GROQ_API_KEY")

    def complete(self, request: LLMRequest) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        from groq import Groq

        client = Groq(api_key=self.api_key, timeout=self.timeout_seconds)
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        kwargs = {}
        if request.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        start = time.monotonic()
        result = client.chat.completions.create(
            model=self.model, messages=messages, temperature=request.temperature, max_tokens=request.max_tokens, **kwargs
        )
        latency_ms = (time.monotonic() - start) * 1000.0
        content = result.choices[0].message.content
        return LLMResponse(content=content, tier_used=self.tier, model_name=self.model, latency_ms=latency_ms)


def _request_cache_key(request: LLMRequest) -> str:
    payload = json.dumps(
        {"messages": [m.model_dump() for m in request.messages], "temperature": request.temperature,
         "max_tokens": request.max_tokens, "json_mode": request.json_mode},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class _CacheEntry:
    response: LLMResponse
    expires_at: float


def load_llm_config(path: Path = DEFAULT_LLM_CONFIG_PATH) -> dict:
    return load_yaml_config(path)


class LLMRouter:
    def __init__(
        self,
        hf_provider: LLMProvider | None = None,
        groq_provider: LLMProvider | None = None,
        config: dict | None = None,
        on_response: Callable[[LLMRequest, LLMResponse], None] | None = None,
    ) -> None:
        self.config = config or load_llm_config()
        self.hf_provider = hf_provider or HuggingFaceProvider(
            model=self.config["huggingface"]["model"], timeout_seconds=self.config["huggingface"]["timeout_seconds"],
            provider=self.config["huggingface"].get("provider", "featherless-ai"),
        )
        self.groq_provider = groq_provider or GroqProvider(
            model=self.config["groq"]["model"], timeout_seconds=self.config["groq"]["timeout_seconds"]
        )
        self.cache_ttl_seconds: float = self.config["cache"]["ttl_seconds"]
        self.on_response = on_response
        self.active_tier: LLMTier | None = None  # exposed for the frontend "active tier" indicator (Phase 5)
        self._cache: dict[str, _CacheEntry] = {}

    def _check_cache(self, key: str) -> LLMResponse | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        if time.monotonic() >= entry.expires_at:
            del self._cache[key]
            return None
        cached = entry.response.model_copy(update={"cached": True})
        return cached

    def _store_cache(self, key: str, response: LLMResponse) -> None:
        self._cache[key] = _CacheEntry(response=response, expires_at=time.monotonic() + self.cache_ttl_seconds)

    def complete(self, request: LLMRequest) -> LLMResponse:
        cache_key = _request_cache_key(request)
        cached = self._check_cache(cache_key)
        if cached is not None:
            return cached

        hf_error: Exception | None = None
        try:
            response = self.hf_provider.complete(request)
            self.active_tier = LLMTier.HUGGING_FACE
        except Exception as exc:  # noqa: BLE001 — deliberately broad: any HF failure triggers fallback
            hf_error = exc
            try:
                response = self.groq_provider.complete(request)
                self.active_tier = LLMTier.GROQ
            except Exception as groq_exc:  # noqa: BLE001
                self.active_tier = LLMTier.UNAVAILABLE
                raise ReasoningServiceUnavailableError(hf_error, groq_exc) from groq_exc

        self._store_cache(cache_key, response)
        if self.on_response is not None:
            self.on_response(request, response)
        return response
