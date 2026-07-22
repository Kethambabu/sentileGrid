"""Phase-1 stub for CLAUDE.md §6b's synthetic sensor layer (methane_ppm,
vibration_mm_s, valve_health_pct — proxies for failure modes native TEP
doesn't simulate).

Always returns a fixed, documented baseline, never random noise standing in
for real values — the scenario-driven rules (methane tracking pressure-rise-
rate, vibration tracking motor/valve erraticness, valve wear monotonically
increasing under stress) require Phase 2's scenario/labeling layer to mean
anything and are deliberately deferred, not guessed at here.
"""

from __future__ import annotations

from pydantic import BaseModel

from .models import SyntheticSensorReading, XMEASVector, XMVVector


class SyntheticSensorBaseline(BaseModel):
    methane_ppm: float = 2.0
    vibration_mm_s: float = 0.8
    valve_health_pct: float = 100.0


class SyntheticSensorLayer:
    def __init__(self, baseline: SyntheticSensorBaseline | None = None) -> None:
        self.baseline = baseline or SyntheticSensorBaseline()

    def compute(self, xmeas: XMEASVector, xmv: XMVVector, t_hours: float) -> SyntheticSensorReading:
        return SyntheticSensorReading(
            methane_ppm=self.baseline.methane_ppm,
            vibration_mm_s=self.baseline.vibration_mm_s,
            valve_health_pct=self.baseline.valve_health_pct,
            is_stub=True,
        )
