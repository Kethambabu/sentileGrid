"""Loader for near-miss incident definitions (backend/knowledge/incidents/).
CLAUDE.md §7.3: each incident is authored as multiple chunks along its own
progression (early-warning/mid-escalation/critical), each pointing at a
specific record in a real labeled simulation run — not invented numbers.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class IncidentStage(BaseModel):
    stage: str
    record_index: int = Field(..., ge=0)
    t_hours: float
    risk_level: str
    narrative: str


class IncidentDefinition(BaseModel):
    incident_id: str
    title: str
    scenario_type: str
    equipment_zone: str
    cause_category: str
    idv_reference: int
    idv_description: str
    source_simulation_run: str
    stages: list[IncidentStage]


def load_incident(path: Path) -> IncidentDefinition:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return IncidentDefinition(**data)


def load_incidents_from_dir(directory: Path) -> list[IncidentDefinition]:
    return [load_incident(p) for p in sorted(directory.glob("*.yaml"))]
