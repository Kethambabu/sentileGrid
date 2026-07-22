"""Typed I/O for every agent (CLAUDE.md §12: Pydantic models for all agent
inputs/outputs). One file, shared across agents, since these types compose
into the orchestrator's state schema (backend/orchestrator/state.py).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TrendFeature(BaseModel):
    field: str
    first_value: float
    last_value: float
    delta: float
    slope_per_minute: float
    direction: str  # "rising" | "falling" | "stable"


class RiskAssessment(BaseModel):
    risk_score: float | None = Field(None, ge=0, le=100, description="None when is_novel_condition is True — never a forced/guessed score (CLAUDE.md §9.2)")
    is_novel_condition: bool
    confidence: str
    contributing_factors: list[str] = Field(default_factory=list)
    recommended_action: str
    cited_chunk_ids: list[str] = Field(default_factory=list)
    reasoning: str
    llm_tier_used: str
    latency_ms: float
    parse_error: bool = False


class ComplianceResult(BaseModel):
    action_reviewed: str
    approved: bool
    cited_sop_chunk_ids: list[str] = Field(default_factory=list)
    notes: str
    llm_tier_used: str
    latency_ms: float
    parse_error: bool = False


class ExplanationResult(BaseModel):
    narrative: str
    cited_chunk_ids: list[str] = Field(default_factory=list)
    llm_tier_used: str
    latency_ms: float


class EmergencyRecommendation(BaseModel):
    triggered: bool
    recommended_interventions: list[str] = Field(default_factory=list)
    requires_approval: bool = True
    approval_id: str | None = None
    llm_tier_used: str | None = None
    latency_ms: float | None = None
