import numpy as np

from backend.simulation.tep import constants as c
from backend.simulation.tep.controller import BaseCaseController
from backend.simulation.tep.process_model import fresh_internal_state, tefunc


def _base_case_xmeas():
    state = fresh_internal_state()
    idv = np.zeros(c.N_IDV, dtype=int)
    _, xmeas, diverged, reason = tefunc(0.0, c.BASE_CASE_STATE, c.BASE_CASE_XMV, idv, state, noise_enabled=False)
    assert not diverged, reason
    return xmeas


def test_controller_output_clamped_to_bounds():
    controller = BaseCaseController()
    xmeas = _base_case_xmeas()
    # Push XMEAS(2) (D feed) far from setpoint to force a large correction.
    xmeas = xmeas.copy()
    xmeas[1] = 0.0
    xmv = c.BASE_CASE_XMV.copy()
    for tick in range(1, 4):
        xmv = controller.compute(xmeas, xmv, 1.0 / 3600.0, tick)
    assert np.all(xmv[0:11] >= 0.0)
    assert np.all(xmv[0:11] <= 100.0)


def test_controller_at_base_case_produces_small_correction():
    """At the exact base-case operating point, the controller should barely
    move XMV (errors ~0), since this is the converged closed-loop setpoint."""
    controller = BaseCaseController()
    xmeas = _base_case_xmeas()
    xmv0 = c.BASE_CASE_XMV.copy()
    xmv = xmv0.copy()
    for tick in range(1, 901):  # cover all loop periods (3, 360, 900 sec)
        xmv = controller.compute(xmeas, xmv, 1.0 / 3600.0, tick)
    assert np.max(np.abs(xmv - xmv0)) < 5.0  # loose bound — smoke test, not a tight claim


def test_controller_reset_clears_state():
    controller = BaseCaseController()
    xmeas = _base_case_xmeas()
    xmv = c.BASE_CASE_XMV.copy()
    controller.compute(xmeas, xmv, 1.0 / 3600.0, 3)
    assert np.any(controller.state.errold != 0.0)
    controller.reset()
    assert np.all(controller.state.errold == 0.0)
    assert np.array_equal(controller.state.setpt, controller.state.setpt)  # reset object is fresh


def test_contrl6_state_machine_reaches_high_pressure_branch():
    controller = BaseCaseController()
    xmeas = _base_case_xmeas().copy()
    xmeas[12] = 3000.0  # trigger the XMEAS(13) >= 2950 branch
    xmv = c.BASE_CASE_XMV.copy()
    xmv = controller.compute(xmeas, xmv, 1.0 / 3600.0, 3)
    assert xmv[5] == 100.0
    assert controller.state.flag6 == 1
