"""Scenario configuration schema. Phase 1 only defines the schema and a single
no-fault baseline scenario (used by the steady-state verification test);
scenario authoring for the knowledge base and synthetic-sensor rule engine
are Phase 2 scope per CLAUDE.md §11/§6b.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..models import IDVEventConfig


class ScenarioConfig(BaseModel):
    name: str
    description: str
    duration_hours: float = Field(..., gt=0, le=200)
    idv_schedule: list[IDVEventConfig] = Field(default_factory=list)
    noise_enabled: bool = True
    random_seed: float | None = None
    synthetic_sensor_rules: dict = Field(
        default_factory=dict,
        description="Reserved for Phase 2's scenario-driven synthetic sensor rule engine (CLAUDE.md §6b). Unused in Phase 1.",
    )
