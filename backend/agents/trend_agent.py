"""Trend Agent (CLAUDE.md §6, §7.11): rate-of-change/directional features
over the live window sequence. No LLM. This is also the only signal
available for the first 4 live records, before the Retrieval Agent's first
fast window exists (CLAUDE.md §7.11's documented startup-gap trade-off).

Reuses rag.chunker.WINDOW_SUMMARY_FIELDS so the Trend Agent and the
knowledge-base window-text serializer reason about the same channels —
deliberately not re-deriving a separate channel list.
"""

from __future__ import annotations

from pydantic import BaseModel

from ..rag.chunker import WINDOW_SUMMARY_FIELDS
from ..simulation.models import SimulationRecord
from .models import TrendFeature

STABLE_RELATIVE_THRESHOLD = 0.005  # 0.5% of |first_value| per record, below which direction is "stable"
STABLE_ABSOLUTE_FLOOR = 0.01  # for near-zero fields, avoid dividing by ~0


class TrendAgentOutput(BaseModel):
    features: list[TrendFeature]


class TrendAgent:
    def compute(self, records: list[SimulationRecord]) -> TrendAgentOutput:
        if len(records) < 2:
            return TrendAgentOutput(features=[])

        first, last = records[0], records[-1]
        duration_min = (last.t_hours - first.t_hours) * 60.0
        features: list[TrendFeature] = []

        for group, name, _unit in WINDOW_SUMMARY_FIELDS:
            v0 = getattr(getattr(first, group), name)
            v1 = getattr(getattr(last, group), name)
            delta = v1 - v0
            slope = delta / duration_min if duration_min > 0 else 0.0

            threshold = max(abs(v0) * STABLE_RELATIVE_THRESHOLD, STABLE_ABSOLUTE_FLOOR)
            if abs(delta) < threshold:
                direction = "stable"
            else:
                direction = "rising" if delta > 0 else "falling"

            features.append(
                TrendFeature(field=f"{group}.{name}", first_value=v0, last_value=v1, delta=delta, slope_per_minute=slope, direction=direction)
            )

        return TrendAgentOutput(features=features)
