"""IDV (process disturbance / fault) definitions and scheduling.

Descriptions for IDV1-15 are the published Downs & Vogel (1993) labels. IDV16-20
were left as "Unknown" in the original 1990/1993 papers (reserved for blind
testing) — the reference Fortran (teprob.f) does define concrete mechanisms for
them, which is what actually executes at runtime; those mechanisms are
documented below, transcribed from the source, not from the paper (which never
published them). See constants.py for the source/license citation.

CLAUDE.md §14 scope note: these 20 disturbance types are the full extent of
this benchmark's fault coverage — they do not represent every real-world
chemical-plant failure mode. The compound-risk labeling layer built on top of
this simulation (Phase 2+) is where broader scenario coverage is intended to
come from, not from adding ad hoc new IDVs to the physics layer itself.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import constants as c

IDV_DESCRIPTIONS: dict[int, str] = {
    1: "A/C Feed Ratio, B Composition Constant (Stream 4) — Step",
    2: "B Composition, A/C Ratio Constant (Stream 4) — Step",
    3: "D Feed Temperature (Stream 2) — Step",
    4: "Reactor Cooling Water Inlet Temperature — Step",
    5: "Condenser Cooling Water Inlet Temperature — Step",
    6: "A Feed Loss (Stream 1) — Step",
    7: "C Header Pressure Loss — Reduced Availability (Stream 4) — Step",
    8: "A, B, C Feed Composition (Stream 4) — Random Variation",
    9: "D Feed Temperature (Stream 2) — Random Variation",
    10: "C Feed Temperature (Stream 4) — Random Variation",
    11: "Reactor Cooling Water Inlet Temperature — Random Variation",
    12: "Condenser Cooling Water Inlet Temperature — Random Variation",
    13: "Reaction Kinetics — Slow Drift",
    14: "Reactor Cooling Water Valve — Sticking",
    15: "Condenser Cooling Water Valve — Sticking",
    16: (
        "Unknown in the original paper (reserved for blind testing). Reference-"
        "implementation mechanism: smooth random variation in the condenser "
        "cooling-water valve's effective heat-transfer coefficient (UAC), via "
        "the same continuous random-walk spline used for IDV8-13."
    ),
    17: (
        "Unknown in the original paper. Reference-implementation mechanism: an "
        "intermittent pulse-shaped reduction (rise/hold/decay) in reactor "
        "cooling duty (QUR), up to -35% at full pulse height."
    ),
    18: (
        "Unknown in the original paper. Reference-implementation mechanism: an "
        "intermittent pulse-shaped reduction in separator cooling duty (QUS), "
        "up to -25% at full pulse height."
    ),
    19: (
        "Unknown in the original paper. Reference-implementation mechanism: "
        "simultaneous valve sticking on FOUR valves at once — compressor "
        "recycle valve, separator liquid flow valve, stripper liquid flow "
        "valve, and stripper steam valve (the same stiction mechanism IDV14/15 "
        "apply to a single valve each)."
    ),
    20: (
        "Unknown in the original paper. Reference-implementation mechanism: an "
        "intermittent pulse-shaped reduction in reactor-to-separator transfer "
        "flow (FTM8), up to -25% at full pulse height."
    ),
}


@dataclass(frozen=True)
class IDVEvent:
    idv_number: int  # 1-20
    start_hour: float
    end_hour: float | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.idv_number <= c.N_IDV:
            raise ValueError(f"idv_number must be in [1, {c.N_IDV}], got {self.idv_number}")
        if self.start_hour < 0:
            raise ValueError("start_hour must be >= 0")
        if self.end_hour is not None and self.end_hour < self.start_hour:
            raise ValueError("end_hour must be >= start_hour")

    def is_active_at(self, t_hours: float) -> bool:
        if t_hours < self.start_hour:
            return False
        if self.end_hour is not None and t_hours >= self.end_hour:
            return False
        return True


def build_idv_vector(active: set[int]) -> np.ndarray:
    """0/1 vector of length 20 (index i = IDV i+1) from a set of active 1-indexed IDV numbers."""
    vec = np.zeros(c.N_IDV, dtype=int)
    for n in active:
        if not 1 <= n <= c.N_IDV:
            raise ValueError(f"IDV number must be in [1, {c.N_IDV}], got {n}")
        vec[n - 1] = 1
    return vec


def idv_vector_at(t_hours: float, schedule: list) -> np.ndarray:
    """Resolve a schedule of IDV events to the active IDV vector at time
    t_hours. Structural, not nominal, on the event type: accepts anything
    with idv_number/start_hour/end_hour attributes (IDVEvent, or the
    equivalent Pydantic IDVEventConfig used in SimulationRunConfig)."""
    active = set()
    for event in schedule:
        if t_hours < event.start_hour:
            continue
        if event.end_hour is not None and t_hours >= event.end_hour:
            continue
        active.add(event.idv_number)
    return build_idv_vector(active)
