"""Sensor Agent (CLAUDE.md §6, §6a, §9.6, §14): validates range/continuity
of raw readings BEFORE anything else touches them, tagging sensor_fault
separately so a broken sensor is never reasoned over as a real process
anomaly downstream. No LLM — this is deterministic validation.
"""

from __future__ import annotations

import math

from pydantic import BaseModel

from ..simulation.models import SimulationRecord

# Representative subset with known physical bounds — extending to every one
# of the 41+12+3 fields would be pure boilerplate for fields the rest of
# the pipeline doesn't reason about individually; these are the ones
# CLAUDE.md's own compound-risk narratives and trend features actually use.
PHYSICAL_RANGES: dict[str, tuple[float, float]] = {
    "xmeas.reactor_pressure_kpa": (0.0, 3500.0),
    "xmeas.reactor_level_pct": (-20.0, 120.0),
    "xmeas.reactor_temperature_c": (0.0, 250.0),
    "xmeas.separator_pressure_kpa": (0.0, 3500.0),
    "xmeas.stripper_level_pct": (-20.0, 120.0),
    "xmeas.compressor_work_kw": (0.0, 2000.0),
    "synthetic.valve_health_pct": (0.0, 100.0),
    "synthetic.methane_ppm": (0.0, 100000.0),
    "synthetic.vibration_mm_s": (0.0, 1000.0),
}

FLATLINE_FIELDS = ("xmeas.reactor_pressure_kpa", "xmeas.reactor_temperature_c", "xmeas.separator_pressure_kpa")
FLATLINE_WINDOW = 5


def _get_field(record: SimulationRecord, dotted_name: str) -> float:
    group, name = dotted_name.split(".", 1)
    return getattr(getattr(record, group), name)


class SensorAgentOutput(BaseModel):
    records: list[SimulationRecord]
    fault_count: int


class SensorAgent:
    def __init__(
        self, physical_ranges: dict[str, tuple[float, float]] | None = None,
        flatline_fields: tuple[str, ...] = FLATLINE_FIELDS, flatline_window: int = FLATLINE_WINDOW,
    ) -> None:
        self.physical_ranges = physical_ranges or PHYSICAL_RANGES
        self.flatline_fields = flatline_fields
        self.flatline_window = flatline_window

    def process(self, records: list[SimulationRecord]) -> SensorAgentOutput:
        cleaned: list[SimulationRecord] = []
        fault_count = 0

        for i, record in enumerate(records):
            faults: dict[str, bool] = {}

            for field_name, (lo, hi) in self.physical_ranges.items():
                value = _get_field(record, field_name)
                if not math.isfinite(value):
                    faults[f"{field_name}.nan"] = True
                elif value < lo or value > hi:
                    faults[f"{field_name}.out_of_range"] = True

            if i + 1 >= self.flatline_window:
                window = records[i + 1 - self.flatline_window : i + 1]
                for field_name in self.flatline_fields:
                    values = [_get_field(r, field_name) for r in window]
                    if len(set(values)) == 1:
                        faults[f"{field_name}.flatline"] = True

            if faults:
                fault_count += 1
                cleaned.append(record.model_copy(update={"sensor_fault": faults}))
            else:
                cleaned.append(record)

        return SensorAgentOutput(records=cleaned, fault_count=fault_count)
