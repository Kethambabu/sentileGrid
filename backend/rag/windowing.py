"""Dual fast(5)/slow(20) window construction over a simulation record stream,
per CLAUDE.md §7.3-7.4. Shared by two consumers: Phase 2's knowledge-base
authoring (pick one window pair at a chosen point in a labeled simulation
run, to pair with a hand-authored incident-stage narrative) and Phase 3+'s
live retrieval (slide across an incoming record stream). The sliding-window
math is identical for both, so it lives in one place rather than being
duplicated per consumer.

Windows are overlapping (slide by 1 record), not partitioned — this is
deliberate per CLAUDE.md §14: overlapping windows ensure a transition near a
boundary is still captured cleanly in at least one window.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..simulation.models import SimulationRecord

FAST_WINDOW_SIZE = 5
SLOW_WINDOW_SIZE = 20


@dataclass
class WindowPair:
    """A fast window, and (once enough records exist) a slow window, both
    ending at the same record. `has_slow_window=False` marks the fast-only
    phase (records 5-19 of a stream) where CLAUDE.md §7.5 requires capping
    reported confidence at 'moderate' even on a strong raw similarity score
    — that capping decision belongs to the Compound-Risk Agent (Phase 4),
    but this flag is what lets it know which phase a match came from."""

    end_record_index: int  # 0-indexed position of the last record in both windows
    fast_records: list[SimulationRecord]
    slow_records: list[SimulationRecord] | None

    @property
    def has_slow_window(self) -> bool:
        return self.slow_records is not None


def build_window_pairs(
    records: list[SimulationRecord], fast_size: int = FAST_WINDOW_SIZE, slow_size: int = SLOW_WINDOW_SIZE
) -> list[WindowPair]:
    """Every window pair obtainable by sliding across `records` one record at
    a time, starting once a fast window first becomes available (index
    fast_size-1) — mirrors CLAUDE.md §7.4's live retrieval sequence exactly."""
    if fast_size < 1 or slow_size < fast_size:
        raise ValueError("require 1 <= fast_size <= slow_size")

    pairs: list[WindowPair] = []
    for i in range(fast_size - 1, len(records)):
        fast_records = records[i - fast_size + 1 : i + 1]
        slow_records = records[i - slow_size + 1 : i + 1] if i >= slow_size - 1 else None
        pairs.append(WindowPair(end_record_index=i, fast_records=fast_records, slow_records=slow_records))
    return pairs


def window_pair_at(
    records: list[SimulationRecord], end_index: int, fast_size: int = FAST_WINDOW_SIZE, slow_size: int = SLOW_WINDOW_SIZE
) -> WindowPair:
    """The single window pair ending at `end_index` (0-indexed into
    `records`) — used when authoring a KB chunk for one incident stage at a
    specific, hand-picked point in a labeled simulation run."""
    if end_index < fast_size - 1:
        raise ValueError(f"end_index {end_index} too early: need at least {fast_size} records for a fast window")
    if end_index >= len(records):
        raise ValueError(f"end_index {end_index} out of range for {len(records)} records")

    fast_records = records[end_index - fast_size + 1 : end_index + 1]
    slow_records = records[end_index - slow_size + 1 : end_index + 1] if end_index >= slow_size - 1 else None
    return WindowPair(end_record_index=end_index, fast_records=fast_records, slow_records=slow_records)
