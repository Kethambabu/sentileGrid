"""CLAUDE.md §6b's synthetic sensor layer (methane_ppm, vibration_mm_s,
valve_health_pct — proxies for failure modes native TEP doesn't simulate).

Always calculated from real TEP variables + a scenario's SyntheticSensorRules
(backend/simulation/scenario_definitions/*.yaml), never random noise:

- methane_ppm rises with reactor pressure RISE RATE in excess of the
  scenario's normal-noise floor ("a leak often follows pressure buildup").
- vibration_mm_s rises with how erratically the scenario's watched valve(s)
  are moving relative to their own recent normal (a rolling stddev of
  tick-to-tick deltas, not raw position).
- valve_health_pct starts at 100 and only ever subtracts, wearing down
  faster under the same erraticness signal — monotonically non-increasing
  by construction, never guessed at.

Stateful across ticks (mirrors the TEPInternalState/WalkState pattern in
tep/process_model.py), because all three signals are inherently about
CHANGE over time — pressure rise rate, valve erraticness, cumulative wear —
none of which a single instantaneous reading can express.
"""

from __future__ import annotations

from pydantic import BaseModel

from .models import SyntheticSensorReading, SyntheticSensorRules, XMEASVector, XMVVector

_VALVE_HISTORY_LEN = 5


class SyntheticSensorBaseline(BaseModel):
    methane_ppm: float = 2.0
    vibration_mm_s: float = 0.8
    valve_health_pct: float = 100.0


class SyntheticSensorLayer:
    def __init__(self, rules: SyntheticSensorRules | None = None, baseline: SyntheticSensorBaseline | None = None) -> None:
        self.rules = rules or SyntheticSensorRules()
        self.baseline = baseline or SyntheticSensorBaseline()
        self._prev_t_hours: float | None = None
        self._prev_reactor_pressure_kpa: float | None = None
        self._prev_valve_values: dict[str, float] = {}
        self._valve_delta_history: dict[str, list[float]] = {name: [] for name in self.rules.vibration_watch_valves}
        self._valve_health_pct: float = self.baseline.valve_health_pct

    def _erraticness_std(self, xmv: XMVVector) -> float:
        """Population stddev of each watched valve's recent tick-to-tick
        deltas, maxed across valves — a rolling measure of how erratic (vs.
        smoothly controlled) recent valve movement has been. Zero until at
        least 2 deltas have been observed for a valve."""
        if not self.rules.vibration_watch_valves:
            return 0.0
        max_std = 0.0
        for name in self.rules.vibration_watch_valves:
            current = getattr(xmv, name)
            previous = self._prev_valve_values.get(name, current)
            delta = abs(current - previous)
            history = self._valve_delta_history.setdefault(name, [])
            history.append(delta)
            if len(history) > _VALVE_HISTORY_LEN:
                history.pop(0)
            if len(history) >= 2:
                mean = sum(history) / len(history)
                variance = sum((d - mean) ** 2 for d in history) / len(history)
                max_std = max(max_std, variance**0.5)
            self._prev_valve_values[name] = current
        return max_std

    def compute(self, xmeas: XMEASVector, xmv: XMVVector, t_hours: float) -> SyntheticSensorReading:
        dt_hours = None
        if self._prev_t_hours is not None:
            dt_hours = t_hours - self._prev_t_hours

        pressure_rise_rate = 0.0
        if dt_hours and dt_hours > 0 and self._prev_reactor_pressure_kpa is not None:
            pressure_rise_rate = (xmeas.reactor_pressure_kpa - self._prev_reactor_pressure_kpa) / dt_hours
        excess_rise = max(0.0, pressure_rise_rate - self.rules.methane_pressure_rise_baseline_kpa_per_hour)
        methane_ppm = self.baseline.methane_ppm + self.rules.methane_ppm_per_kpa_per_hour * excess_rise

        erraticness = self._erraticness_std(xmv)
        vibration_mm_s = self.baseline.vibration_mm_s + self.rules.vibration_mm_s_per_pct_std * erraticness

        if dt_hours and dt_hours > 0:
            wear = (self.rules.valve_wear_baseline_pct_per_hour + self.rules.valve_wear_pct_per_hour_per_pct_std * erraticness) * dt_hours
            self._valve_health_pct = max(0.0, self._valve_health_pct - wear)  # only ever subtracts

        self._prev_t_hours = t_hours
        self._prev_reactor_pressure_kpa = xmeas.reactor_pressure_kpa

        return SyntheticSensorReading(
            methane_ppm=methane_ppm,
            vibration_mm_s=vibration_mm_s,
            valve_health_pct=self._valve_health_pct,
            is_stub=False,
        )
