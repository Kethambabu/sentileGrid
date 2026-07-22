from backend.agents.trend_agent import TrendAgent
from backend.simulation.models import SimulationRunConfig
from backend.simulation.simulator import TEPSimulator


def _records(n=6):
    config = SimulationRunConfig(scenario_name="trend_test", duration_hours=1, noise_enabled=False, record_interval_minutes=3)
    return TEPSimulator(config).run().records[:n]


def test_empty_or_single_record_produces_no_features():
    assert TrendAgent().compute([]).features == []
    assert TrendAgent().compute(_records(1)).features == []


def test_stable_baseline_reports_stable_direction():
    output = TrendAgent().compute(_records())
    reactor_pressure = next(f for f in output.features if f.field == "xmeas.reactor_pressure_kpa")
    assert reactor_pressure.direction == "stable"


def test_rising_field_is_classified_rising():
    records = _records()
    for i, r in enumerate(records):
        updated = r.model_copy(deep=True)
        updated.xmeas.reactor_pressure_kpa = 2700.0 + i * 50.0  # clear upward trend
        records[i] = updated

    output = TrendAgent().compute(records)
    feature = next(f for f in output.features if f.field == "xmeas.reactor_pressure_kpa")
    assert feature.direction == "rising"
    assert feature.delta > 0


def test_falling_field_is_classified_falling():
    records = _records()
    for i, r in enumerate(records):
        updated = r.model_copy(deep=True)
        updated.xmeas.reactor_pressure_kpa = 2900.0 - i * 50.0
        records[i] = updated

    output = TrendAgent().compute(records)
    feature = next(f for f in output.features if f.field == "xmeas.reactor_pressure_kpa")
    assert feature.direction == "falling"
    assert feature.delta < 0


def test_slope_is_per_minute_and_matches_duration():
    records = _records()
    updated_first = records[0].model_copy(deep=True)
    updated_first.xmeas.reactor_pressure_kpa = 2700.0
    updated_last = records[-1].model_copy(deep=True)
    updated_last.xmeas.reactor_pressure_kpa = 2700.0 + 15.0 * (records[-1].t_hours - records[0].t_hours) * 60.0
    records[0] = updated_first
    records[-1] = updated_last

    output = TrendAgent().compute(records)
    feature = next(f for f in output.features if f.field == "xmeas.reactor_pressure_kpa")
    assert abs(feature.slope_per_minute - 15.0) < 1e-6
