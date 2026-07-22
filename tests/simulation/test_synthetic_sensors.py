import numpy as np

from backend.simulation.models import XMEASVector, XMVVector
from backend.simulation.synthetic_sensors import SyntheticSensorBaseline, SyntheticSensorLayer
from backend.simulation.tep import constants as c


def test_synthetic_sensor_layer_returns_fixed_documented_baseline():
    layer = SyntheticSensorLayer()
    xmeas = XMEASVector.from_array(np.zeros(c.N_XMEAS))
    xmv = XMVVector.from_array(c.BASE_CASE_XMV)

    reading_a = layer.compute(xmeas, xmv, t_hours=0.0)
    reading_b = layer.compute(xmeas, xmv, t_hours=5.0)

    assert reading_a.is_stub is True
    assert reading_a == reading_b  # no randomness, no time-dependence in Phase 1
    assert reading_a.methane_ppm == SyntheticSensorBaseline().methane_ppm
    assert reading_a.vibration_mm_s == SyntheticSensorBaseline().vibration_mm_s
    assert reading_a.valve_health_pct == SyntheticSensorBaseline().valve_health_pct


def test_synthetic_sensor_valve_health_within_bounds():
    layer = SyntheticSensorLayer()
    xmeas = XMEASVector.from_array(np.zeros(c.N_XMEAS))
    xmv = XMVVector.from_array(c.BASE_CASE_XMV)
    reading = layer.compute(xmeas, xmv, t_hours=0.0)
    assert 0.0 <= reading.valve_health_pct <= 100.0
