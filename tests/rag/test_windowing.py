import pytest

from backend.rag.windowing import FAST_WINDOW_SIZE, SLOW_WINDOW_SIZE, build_window_pairs, window_pair_at
from backend.simulation.models import SimulationRunConfig
from backend.simulation.simulator import TEPSimulator


def _records(n_hours: float = 2):
    config = SimulationRunConfig(scenario_name="windowing_test", duration_hours=n_hours, noise_enabled=False, record_interval_minutes=1)
    return TEPSimulator(config).run().records


def test_no_pairs_before_fast_window_size():
    records = _records()[: FAST_WINDOW_SIZE - 1]
    pairs = build_window_pairs(records)
    assert pairs == []


def test_first_pair_at_fast_window_size():
    records = _records()[:FAST_WINDOW_SIZE]
    pairs = build_window_pairs(records)
    assert len(pairs) == 1
    assert len(pairs[0].fast_records) == FAST_WINDOW_SIZE
    assert not pairs[0].has_slow_window


def test_slow_window_appears_at_slow_window_size():
    records = _records()[:SLOW_WINDOW_SIZE]
    pairs = build_window_pairs(records)
    assert not pairs[-2].has_slow_window  # record 19 (0-idx 18): fast only
    assert pairs[-1].has_slow_window      # record 20 (0-idx 19): fast + slow
    assert len(pairs[-1].slow_records) == SLOW_WINDOW_SIZE


def test_windows_slide_by_one_and_overlap():
    records = _records()[: SLOW_WINDOW_SIZE + 5]
    pairs = build_window_pairs(records)
    # consecutive fast windows share 4 of 5 records
    shared = set(id(r) for r in pairs[-1].fast_records) & set(id(r) for r in pairs[-2].fast_records)
    assert len(shared) == FAST_WINDOW_SIZE - 1


def test_window_pair_at_matches_build_window_pairs():
    records = _records()[: SLOW_WINDOW_SIZE + 10]
    all_pairs = build_window_pairs(records)
    single = window_pair_at(records, end_index=len(records) - 1)
    assert single.end_record_index == all_pairs[-1].end_record_index
    assert [r.record_index for r in single.fast_records] == [r.record_index for r in all_pairs[-1].fast_records]


def test_window_pair_at_rejects_too_early_index():
    records = _records()[:10]
    with pytest.raises(ValueError):
        window_pair_at(records, end_index=2)


def test_window_pair_at_rejects_out_of_range_index():
    records = _records()[:10]
    with pytest.raises(ValueError):
        window_pair_at(records, end_index=999)
