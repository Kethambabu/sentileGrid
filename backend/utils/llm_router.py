"""Shared LLM fallback router (CLAUDE.md §5): every LLM-calling agent goes
through this, not a hardcoded provider. Two-tier fallback, in order —
Gemini (Google AI Studio), then Groq — no third/offline tier. These two are
fully independent backends/companies, so a genuine fallback, not fake
redundancy.

HISTORY (2026-07-23): the original primary tier was Hugging Face's free
"Serverless Inference API" (api-inference.huggingface.co). That endpoint
was retired entirely (DNS-dead); its replacement (router.huggingface.co,
"Inference Providers") is metered pay-as-you-go — free accounts get only
$0.10/month credit, exhausted almost immediately at real usage. Cerebras
was evaluated as an alternative and rejected: despite blog claims of a
card-free ongoing free tier, its actual current policy (verified directly
against a real account, not just docs) requires a payment method before
any API access works at all, even to unlock the $5/30-day trial credit —
confirmed live with a real 402 Payment Required. Google AI Studio's Gemini
API was verified live (real 200 OK, real content, no billing setup) as a
genuinely free, card-free, ongoing tier — that's what's wired in below.
HF is left implemented but unused or removed here entirely by design; see
git history if it needs to be reinstated.

KNOWN LIMIT (verified live via a real 429 response body, not docs/blogs):
gemini-2.5-flash's free tier caps at 20 requests/day per project+model
(quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier) — exhausts
after roughly 5 real assessment cycles (3-4 Gemini calls each). Accepted
as a known constraint rather than reordering tiers: Groq's real quota
comfortably covers the rest of the day once Gemini is exhausted, and the
two-tier fallback already handles this correctly with no code changes
needed.

MODEL NAME IS ACCOUNT-DEPENDENT (2026-07-24): a second, newer Google
account got a real 404 on the exact same "gemini-2.5-flash" name — "no
longer available to new users." gemini-2.0-flash/lite 429'd (quota) and
gemini-3.5-flash 503'd (overloaded) on that account. The "-latest" alias
(gemini-flash-latest) worked live on both accounts, so config uses that
instead of a pinned dated version — see backend/config/llm.yaml.

CONFIRMED (2026-07-24): the 20/day quota does reset daily (a fresh key/day
produces real successful calls again), it's just tight enough that casual
testing exhausts it in a handful of requests. See GeminiProvider's
docstring for the thinkingConfig JSON-truncation fix, since verified live.

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

import requests
from dotenv import load_dotenv
from pydantic import BaseModel

from .config_loader import load_yaml_config

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LLM_CONFIG_PATH = REPO_ROOT / "backend" / "config" / "llm.yaml"

load_dotenv(REPO_ROOT / ".env")


class LLMTier(str, Enum):
    GEMINI = "gemini"
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

    def __init__(self, gemini_error: Exception | None, groq_error: Exception | None) -> None:
        super().__init__(
            f"Reasoning service unavailable — both LLM tiers failed. "
            f"Gemini error: {gemini_error!r}. Groq error: {groq_error!r}."
        )
        self.gemini_error = gemini_error
        self.groq_error = groq_error


class LLMProvider(ABC):
    tier: LLMTier

    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse: ...


class GeminiProvider(LLMProvider):
    """Google AI Studio's Gemini API — verified live 2026-07-23 as a
    genuinely free, card-free, ongoing tier (real 200 OK response, no
    billing setup), unlike Hugging Face's now-metered Inference Providers
    or Cerebras' payment-method-gated trial (see module docstring). Uses
    plain `requests` rather than a new SDK dependency, to avoid pulling in
    another native/compiled package after this project's earlier torch/
    chromadb DLL-compatibility issues on this machine.

    `gemini-2.0-flash` was found to have a free-tier quota of 0 on this
    account (immediate 429) — `gemini-2.5-flash` is the one with real free
    quota available. Re-verify if switching models.

    The current model (resolved via the "-latest" alias, see llm.yaml) is a
    "thinking" model: it spends part of `max_tokens` on internal reasoning
    before visible output, reported separately as `thoughtsTokenCount`. At
    very small `max_tokens` (verified live at 10) it can spend the entire
    budget thinking and return `finishReason: MAX_TOKENS` with an empty
    `content` (no `parts` key at all) — handled explicitly below rather
    than left as a raw KeyError.

    CORRECTION — this is NOT only a small-max_tokens problem: the same
    thinking-budget mechanism was also observed producing truncated,
    malformed JSON (missing even the leading '{') at this project's real
    production size (compliance_agent's actual max_tokens=400 call, a real
    live run, not a synthetic test) — thinking apparently consumed enough
    of the budget that the visible JSON output itself got cut off mid-token,
    not just reduced to empty. `thinkingConfig` below is the fix.

    VERIFIED LIVE 2026-07-24 (after an earlier attempt was blocked by quota
    exhaustion on every available key): a real production-sized call
    (emergency_agent's actual max_tokens=500, json_mode=True) through the
    full API — not a synthetic script — returned clean, correctly-parsed
    JSON with two coherent interventions, not the "unparseable response"
    fallback text. Confirms thinkingConfig closes the truncation gap at
    real agent token budgets.
    """

    tier = LLMTier.GEMINI
    _BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, model: str, timeout_seconds: float, api_key: str | None = None) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY")

    def complete(self, request: LLMRequest) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")

        system_parts = [m.content for m in request.messages if m.role == "system"]
        contents = [
            {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
            for m in request.messages if m.role != "system"
        ]
        generation_config: dict = {
            "temperature": request.temperature, "maxOutputTokens": request.max_tokens,
            # VERIFIED LIVE 2026-07-24: a real production-sized call
            # (emergency_agent's actual max_tokens=500, json_mode=True,
            # through the full API) returned clean, correctly-parsed JSON —
            # confirmed this closes the truncation gap. Root cause this
            # addresses: the resolved model (gemini-flash-latest -> gemini-3.6-flash, a
            # "thinking" model) was observed spending its entire max_tokens
            # budget on invisible reasoning, leaving too little for the
            # actual JSON output and producing truncated/malformed JSON
            # (missing the leading '{') even at this project's real 400-600
            # token budgets — reproduced live in compliance_agent's actual
            # production call, not just a synthetic test. "low" is the
            # documented value for Gemini 3.x's thinkingLevel (2.5-series
            # models use a different thinkingBudget=0 field instead, per
            # https://ai.google.dev/gemini-api/docs/generate-content/thinking
            # — re-check which applies if the "-latest" alias ever resolves
            # to a 2.5-series model again).
            "thinkingConfig": {"thinkingLevel": "low"},
        }
        if request.json_mode:
            generation_config["responseMimeType"] = "application/json"
        payload: dict = {"contents": contents, "generationConfig": generation_config}
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n".join(system_parts)}]}

        start = time.monotonic()
        resp = requests.post(
            f"{self._BASE_URL}/{self.model}:generateContent",
            params={"key": self.api_key},
            json=payload,
            timeout=self.timeout_seconds,
        )
        latency_ms = (time.monotonic() - start) * 1000.0
        resp.raise_for_status()
        data = resp.json()
        candidate = data["candidates"][0]
        parts = candidate.get("content", {}).get("parts")
        if not parts:
            raise RuntimeError(
                f"Gemini returned no output text (finishReason={candidate.get('finishReason')!r}) — "
                f"likely spent the entire max_tokens budget on internal reasoning "
                f"(thoughtsTokenCount={data.get('usageMetadata', {}).get('thoughtsTokenCount')!r})"
            )
        content = parts[0]["text"]
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
        gemini_provider: LLMProvider | None = None,
        groq_provider: LLMProvider | None = None,
        config: dict | None = None,
        on_response: Callable[[LLMRequest, LLMResponse], None] | None = None,
    ) -> None:
        self.config = config or load_llm_config()
        self.gemini_provider = gemini_provider or GeminiProvider(
            model=self.config["gemini"]["model"], timeout_seconds=self.config["gemini"]["timeout_seconds"],
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

        gemini_error: Exception | None = None
        try:
            response = self.gemini_provider.complete(request)
            self.active_tier = LLMTier.GEMINI
        except Exception as exc:  # noqa: BLE001 — deliberately broad: any Gemini failure triggers fallback
            gemini_error = exc
            try:
                response = self.groq_provider.complete(request)
                self.active_tier = LLMTier.GROQ
            except Exception as groq_exc:  # noqa: BLE001
                self.active_tier = LLMTier.UNAVAILABLE
                raise ReasoningServiceUnavailableError(gemini_error, groq_exc) from groq_exc

        self._store_cache(cache_key, response)
        if self.on_response is not None:
            self.on_response(request, response)
        return response
