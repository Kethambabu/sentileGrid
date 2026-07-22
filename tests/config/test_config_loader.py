from backend.simulation.tep.reference_data import DEFAULT_TOLERANCE_CONFIG_PATH, load_tolerance_config
from backend.utils.config_loader import DEFAULT_SIMULATION_CONFIG_PATH, get_simulation_config


def test_simulation_config_loads_and_validates():
    config = get_simulation_config()
    assert config.integration.method == "euler"
    assert config.integration.substep_hours > 0
    assert config.sampling.record_interval_minutes > 0
    assert config.controller.fast_loop_period_seconds == 3


def test_simulation_config_path_exists():
    assert DEFAULT_SIMULATION_CONFIG_PATH.exists()


def test_tolerance_config_loads_and_has_expected_shape():
    data = load_tolerance_config()
    assert "tolerances_pct" in data
    assert "citation" in data
    assert all(isinstance(v, (int, float)) for v in data["tolerances_pct"].values())


def test_tolerance_config_path_exists():
    assert DEFAULT_TOLERANCE_CONFIG_PATH.exists()
