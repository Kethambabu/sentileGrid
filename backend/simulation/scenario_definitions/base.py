"""Scenario configuration schema (CLAUDE.md §6b/§11)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..models import IDVEventConfig, SyntheticSensorRules


class ScenarioConfig(BaseModel):
    name: str
    description: str
    duration_hours: float = Field(..., gt=0, le=200)
    idv_schedule: list[IDVEventConfig] = Field(default_factory=list)
    noise_enabled: bool = True
    random_seed: float | None = None
    synthetic_sensor_rules: SyntheticSensorRules = Field(
        default_factory=SyntheticSensorRules,
        description="Per-scenario synthetic sensor coefficients (CLAUDE.md §6b) — all-zero defaults mean 'no effect'.",
    )
