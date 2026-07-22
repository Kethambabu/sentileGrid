import math

from backend.agents.sensor_agent import SensorAgent
from backend.simulation.models import SimulationRunConfig
from backend.simulation.simulator import TEPSimulator


def _clean_records(n=10):
    config = SimulationRunConfig(scenario_name="sensor_test", duration_hours=1, noise_enabled=False, record_interval_minutes=3)
    return TEPSimulator(config).run().records[:n]


def test_clean_records_produce_no_faults():
    records = _clean_records()
    output = SensorAgent().process(records)
    assert output.fault_count == 0
    assert all(r.sensor_fault == {} for r in output.records)


def test_nan_reading_is_flagged():
    records = _clean_records()
    corrupted = records[3].model_copy(deep=True)
    corrupted.xmeas.reactor_pressure_kpa = math.nan
    records[3] = corrupted

    output = SensorAgent().process(records)
    assert output.fault_count == 1
    assert output.records[3].sensor_fault.get("xmeas.reactor_pressure_kpa.nan") is True


def test_out_of_range_reading_is_flagged():
    records = _clean_records()
    corrupted = records[2].model_copy(deep=True)
    corrupted.xmeas.reactor_temperature_c = 9999.0
    records[2] = corrupted

    output = SensorAgent().process(records)
    assert output.records[2].sensor_fault.get("xmeas.reactor_temperature_c.out_of_range") is True


def test_flatline_is_flagged_when_value_never_changes():
    records = _clean_records(n=8)
    frozen_value = records[0].xmeas.reactor_pressure_kpa
    for i in range(8):
        r = records[i].model_copy(deep=True)
        r.xmeas.reactor_pressure_kpa = frozen_value
        records[i] = r

    output = SensorAgent().process(records)
    assert output.records[4].sensor_fault.get("xmeas.reactor_pressure_kpa.flatline") is True


def test_flatline_not_flagged_before_window_fills():
    records = _clean_records(n=3)
    frozen_value = records[0].xmeas.reactor_pressure_kpa
    for i in range(3):
        r = records[i].model_copy(deep=True)
        r.xmeas.reactor_pressure_kpa = frozen_value
        records[i] = r

    output = SensorAgent().process(records)  # only 3 records, flatline window is 5
    assert all("xmeas.reactor_pressure_kpa.flatline" not in r.sensor_fault for r in output.records)


def test_faulty_reading_does_not_mutate_original_record_list():
    records = _clean_records()
    original = records[3]
    SensorAgent().process(records)
    assert records[3] is original  # process() returns new objects, doesn't mutate input
