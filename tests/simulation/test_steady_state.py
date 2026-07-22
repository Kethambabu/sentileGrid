"""The core Phase 1 'verify realistic output' test: the closed-loop system,
started at the published Downs & Vogel base case with no faults, should hold
near that operating point for a multi-hour run — not drift or trip.
"""

import numpy as np

from backend.simulation.models import SimulationRunConfig
from backend.simulation.simulator import TEPSimulator
from backend.simulation.tep.reference_data import compute_base_case_xmeas, load_tolerance_config


def test_baseline_scenario_holds_steady_state_noiseless():
    reference_xmeas = compute_base_case_xmeas()
    tolerances = load_tolerance_config()["tolerances_pct"]

    config = SimulationRunConfig(
        scenario_name="baseline_noiseless_test",
        duration_hours=8,
        noise_enabled=False,
        idv_schedule=[],
    )
    result = TEPSimulator(config).run()

    assert not result.diverged, result.diverged_reason
    assert len(result.records) > 0

    from backend.simulation.models import XMEASVector

    reference_model = XMEASVector.from_array(reference_xmeas)
    final = result.records[-1].xmeas

    for field_name, tol_pct in tolerances.items():
        target = getattr(reference_model, field_name)
        actual = getattr(final, field_name)
        if abs(target) < 1e-9:
            assert abs(actual - target) < 1.0, f"{field_name}: {actual} vs {target}"
            continue
        rel_err_pct = abs(actual - target) / abs(target) * 100.0
        assert rel_err_pct <= tol_pct, f"{field_name}: {actual} vs {target} ({rel_err_pct:.2f}% > {tol_pct}%)"


def test_baseline_scenario_with_noise_stays_bounded_and_does_not_diverge():
    config = SimulationRunConfig(
        scenario_name="baseline_noisy_test",
        duration_hours=4,
        noise_enabled=True,
        idv_schedule=[],
        random_seed=4242.0,
    )
    result = TEPSimulator(config).run()

    assert not result.diverged, result.diverged_reason
    assert len(result.records) > 0

    reactor_pressures = np.array([r.xmeas.reactor_pressure_kpa for r in result.records])
    assert np.std(reactor_pressures) < 200.0  # plausible bounded variance, not an exact-match claim
    assert np.all(np.isfinite(reactor_pressures))
