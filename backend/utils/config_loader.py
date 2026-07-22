"""Generic YAML config loading (CLAUDE.md §12: config lives in backend/config/,
never hardcoded inline). This is the only backend/utils/ module built in
Phase 1 — logging/schema-validation helpers wait until there's an audit
trail or agent I/O to serve (Phase 4/6)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SIMULATION_CONFIG_PATH = REPO_ROOT / "backend" / "config" / "simulation.yaml"


def load_yaml_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class IntegrationConfig(BaseModel):
    substep_hours: float
    method: str
    max_hours_per_run: float


class SamplingConfig(BaseModel):
    record_interval_minutes: float
    reactor_feed_purge_analyzer_interval_hours: float
    product_analyzer_interval_hours: float


class NoiseConfig(BaseModel):
    enabled: bool
    seed: float | None = None


class ControllerConfig(BaseModel):
    scheme: str
    fast_loop_period_seconds: int
    composition_loop_period_seconds: int
    slow_composition_loop_period_seconds: int


class PathsConfig(BaseModel):
    reference_steady_state: str
    scenario_dir: str
    output_dir: str


class SimulationConfig(BaseModel):
    integration: IntegrationConfig
    sampling: SamplingConfig
    noise: NoiseConfig
    controller: ControllerConfig
    paths: PathsConfig
    thresholds: dict


def get_simulation_config(path: Path = DEFAULT_SIMULATION_CONFIG_PATH) -> SimulationConfig:
    return SimulationConfig(**load_yaml_config(path))
