import numpy as np
import pytest

from backend.simulation.models import IDVEventConfig, SimulationRunConfig, SyntheticSensorRules
from backend.simulation.simulator import TEPSimulator


def test_simulator_run_produces_valid_result_with_correct_record_spacing():
    config = SimulationRunConfig(
        scenario_name="test_run",
        duration_hours=1,
        record_interval_minutes=3,
        noise_enabled=False,
    )
    result = TEPSimulator(config).run()

    assert not result.diverged
    assert len(result.records) == pytest.approx(60 / 3, abs=1)

    t_values = [r.t_hours for r in result.records]
    assert t_values == sorted(t_values)
    record_indices = [r.record_index for r in result.records]
    assert record_indices == list(range(len(result.records)))

    for r in result.records:
        assert r.sensor_fault == {}
        assert r.synthetic.is_stub is False  # CLAUDE.md §6b: rule-driven, not a stub


def test_simulator_run_with_idv_schedule_applies_fault():
    config = SimulationRunConfig(
        scenario_name="test_idv_run",
        duration_hours=2,
        noise_enabled=False,
        idv_schedule=[IDVEventConfig(idv_number=6, start_hour=0.5)],
    )
    result = TEPSimulator(config).run()

    pre_fault = [r for r in result.records if r.t_hours < 0.5]
    post_fault = [r for r in result.records if r.t_hours >= 0.5]
    assert any(not r.idv_active.idv_6 for r in pre_fault)
    assert any(r.idv_active.idv_6 for r in post_fault)


def test_simulator_run_schema_round_trips_to_array():
    config = SimulationRunConfig(scenario_name="roundtrip", duration_hours=1, noise_enabled=False)
    result = TEPSimulator(config).run()
    record = result.records[0]
    arr = record.xmeas.to_array()
    assert arr.shape == (41,)
    assert np.all(np.isfinite(arr))


def test_synthetic_sensor_rules_flow_through_from_config_to_records():
    """CLAUDE.md §6b: rules are scenario-driven, not hardcoded — confirms
    SimulationRunConfig.synthetic_sensor_rules actually reaches the layer
    computing each record's synthetic reading, end-to-end through the real
    simulator loop (not just unit-tested against SyntheticSensorLayer directly)."""
    rules = SyntheticSensorRules(
        vibration_watch_valves=["reactor_cw_flow_valve_pct"],
        vibration_mm_s_per_pct_std=5.0,
        valve_wear_baseline_pct_per_hour=1.0,
    )
    config = SimulationRunConfig(scenario_name="rules_flow", duration_hours=1, noise_enabled=False, synthetic_sensor_rules=rules)
    result = TEPSimulator(config).run()

    assert not result.diverged
    health_values = [r.synthetic.valve_health_pct for r in result.records]
    assert health_values == sorted(health_values, reverse=True)  # monotonically non-increasing
    assert health_values[-1] < 100.0  # baseline wear actually accumulated over the run
