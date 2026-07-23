import numpy as np

from backend.simulation.models import SyntheticSensorRules, XMEASVector, XMVVector
from backend.simulation.synthetic_sensors import SyntheticSensorBaseline, SyntheticSensorLayer
from backend.simulation.tep import constants as c


def _xmeas_with_pressure(pressure_kpa: float) -> XMEASVector:
    arr = np.zeros(c.N_XMEAS)
    xmeas = XMEASVector.from_array(arr)
    return xmeas.model_copy(update={"reactor_pressure_kpa": pressure_kpa})


def test_zero_rules_stays_at_flat_baseline():
    """CLAUDE.md §6b: a scenario with no rules (e.g. `baseline`) must
    produce the documented constant baseline, not drift or vary."""
    layer = SyntheticSensorLayer()
    xmv = XMVVector.from_array(c.BASE_CASE_XMV)

    reading_a = layer.compute(_xmeas_with_pressure(2700.0), xmv, t_hours=0.0)
    reading_b = layer.compute(_xmeas_with_pressure(2700.0), xmv, t_hours=1.0)

    assert reading_a.is_stub is False
    assert reading_a.methane_ppm == SyntheticSensorBaseline().methane_ppm
    assert reading_b.methane_ppm == SyntheticSensorBaseline().methane_ppm
    assert reading_a.vibration_mm_s == SyntheticSensorBaseline().vibration_mm_s
    assert reading_b.valve_health_pct == SyntheticSensorBaseline().valve_health_pct


def test_methane_rises_with_excess_pressure_rise_rate():
    """CLAUDE.md §6b: methane_ppm increases when pressure rises MORE than
    normal — a rise below the configured baseline-rise floor has no effect."""
    rules = SyntheticSensorRules(methane_ppm_per_kpa_per_hour=1.0, methane_pressure_rise_baseline_kpa_per_hour=5.0)
    layer = SyntheticSensorLayer(rules=rules)
    xmv = XMVVector.from_array(c.BASE_CASE_XMV)

    layer.compute(_xmeas_with_pressure(2700.0), xmv, t_hours=0.0)
    # Rise of 2 kPa over 1 hour = 2 kPa/hr, below the 5 kPa/hr floor -> no effect
    below_floor = layer.compute(_xmeas_with_pressure(2702.0), xmv, t_hours=1.0)
    assert below_floor.methane_ppm == SyntheticSensorBaseline().methane_ppm

    # Rise of 20 kPa over 1 hour = 20 kPa/hr, 15 kPa/hr excess over the floor
    above_floor = layer.compute(_xmeas_with_pressure(2722.0), xmv, t_hours=2.0)
    assert above_floor.methane_ppm == SyntheticSensorBaseline().methane_ppm + 15.0


def test_vibration_rises_with_watched_valve_erraticness():
    """CLAUDE.md §6b: vibration_mm_s increases when a watched valve moves
    more erratically than its own recent normal — smooth constant movement
    (normal control-loop behavior) must not trigger it."""
    rules = SyntheticSensorRules(vibration_watch_valves=["reactor_cw_flow_valve_pct"], vibration_mm_s_per_pct_std=2.0)
    layer = SyntheticSensorLayer(rules=rules)
    xmeas = _xmeas_with_pressure(2700.0)

    smooth_positions = [40.0, 41.0, 42.0, 43.0, 44.0, 45.0]
    smooth_reading = None
    for i, pos in enumerate(smooth_positions):
        xmv = XMVVector.from_array(c.BASE_CASE_XMV).model_copy(update={"reactor_cw_flow_valve_pct": pos})
        smooth_reading = layer.compute(xmeas, xmv, t_hours=float(i))
    assert smooth_reading.vibration_mm_s == SyntheticSensorBaseline().vibration_mm_s  # constant deltas -> zero stddev

    erratic_layer = SyntheticSensorLayer(rules=rules)
    erratic_positions = [40.0, 60.0, 20.0, 70.0, 10.0, 65.0]
    erratic_reading = None
    for i, pos in enumerate(erratic_positions):
        xmv = XMVVector.from_array(c.BASE_CASE_XMV).model_copy(update={"reactor_cw_flow_valve_pct": pos})
        erratic_reading = layer.compute(xmeas, xmv, t_hours=float(i))
    assert erratic_reading.vibration_mm_s > SyntheticSensorBaseline().vibration_mm_s


def test_valve_health_never_increases_and_stays_in_bounds():
    """CLAUDE.md §6b: valve_health_pct starts at 100 and only ever
    decreases, regardless of how erratic or calm the input sequence is."""
    rules = SyntheticSensorRules(
        vibration_watch_valves=["reactor_cw_flow_valve_pct"],
        valve_wear_baseline_pct_per_hour=0.05,
        valve_wear_pct_per_hour_per_pct_std=0.1,
    )
    layer = SyntheticSensorLayer(rules=rules)
    xmeas = _xmeas_with_pressure(2700.0)
    rng = np.random.default_rng(42)

    previous = 100.0
    for i in range(30):
        pos = float(rng.uniform(0.0, 100.0))
        xmv = XMVVector.from_array(c.BASE_CASE_XMV).model_copy(update={"reactor_cw_flow_valve_pct": pos})
        reading = layer.compute(xmeas, xmv, t_hours=float(i) * 0.5)
        assert reading.valve_health_pct <= previous
        assert 0.0 <= reading.valve_health_pct <= 100.0
        previous = reading.valve_health_pct

    assert previous < 100.0  # some wear actually accumulated over the run
