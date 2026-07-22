"""Request/response schemas for the API surface (CLAUDE.md §12: type-hint
everything, Pydantic for all API request/response schemas)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .run_manager import DEFAULT_ASSESSMENT_INTERVAL_RECORDS, DEFAULT_TICK_SECONDS


class StartRunRequest(BaseModel):
    scenario_name: str
    duration_hours: float | None = None
    tick_seconds: float = Field(default=DEFAULT_TICK_SECONDS, gt=0)
    assessment_interval_records: int = Field(default=DEFAULT_ASSESSMENT_INTERVAL_RECORDS, ge=1)


class StartRunResponse(BaseModel):
    run_id: str


class ApprovalDecisionRequest(BaseModel):
    operator_id: str = Field(..., min_length=1)
    status: str  # "approved" | "rejected"
