"""Base-case decentralized multiloop PI controller, ported from temain_mod.f's
CONTRL1-CONTRL20 (Russell, Chiang & Braatz revision of the Downs & Vogel
benchmark). See constants.py for the source/license citation.

This is a genuine cascade: the "fast" loops (1-11, 16-18, executed every 3
simulated seconds) write directly to XMV; the "slow" composition/temperature
loops (13-15, 19, every 360 seconds; 20, every 900 seconds) don't touch XMV
at all — they adjust the SETPOINTS the fast loops track. The reference
implementation's call order within each tick group matters: a slow loop's
setpoint update doesn't affect its downstream fast loop until that fast
loop's *next* tick (one-tick lag), because Fortran executes the fast-loop
batch, in order, before the slow-loop batch on any tick where both are due.
BaseCaseController.compute() preserves that exact call order to reproduce
the same lag, and assumes it is being driven on a 1-second tick (matching
the reference — see REFERENCE_INTEGRATION_STEP_HOURS in constants.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import constants as c

N_LOOPS = 20  # loop "12" (index 11) has a SETPT slot but no active controller

INITIAL_SETPT = np.array(
    [
        3664.0, 4509.3, 0.25052, 9.3477, 26.902, 0.33712, 50.0, 50.0, 230.31, 94.599,
        22.949, 2633.7, 32.188, 6.8820, 18.776, 65.731, 75.000, 120.40, 13.823, 0.83570,
    ]
)

GAIN = np.array(
    [
        1.0, 1.0, 1.0, 1.0, -0.083, 1.22, -2.06, -1.62, 0.41, -0.156 * 10.0,
        1.09, 0.0, 18.0, 8.3, 2.37, 1.69 / 10.0, 11.1 / 10.0, 2.83 * 10.0, -83.2 / 5.0 / 3.0, -16.3 / 5.0,
    ]
)

# Reset time (hours); 0 for the pure-P loops (1-4, 6-9), which use no integral term.
TAUI = np.array(
    [
        0.0, 0.0, 0.0, 0.0, 1.0 / 3600.0, 0.0, 0.0, 0.0, 0.0, 1452.0 / 3600.0,
        2600.0 / 3600.0, 0.0, 3168.0 / 3600.0, 3168.0 / 3600.0, 5069.0 / 3600.0, 236.0 / 3600.0,
        3168.0 / 3600.0, 982.0 / 3600.0, 6336.0 / 3600.0, 12408.0 / 3600.0,
    ]
)

# Execution period in seconds, per loop (1-indexed loop number -> tick group).
PERIOD_SECONDS = {
    1: 3, 2: 3, 3: 3, 4: 3, 5: 3, 6: 3, 7: 3, 8: 3, 9: 3, 10: 3, 11: 3, 16: 3, 17: 3, 18: 3,
    13: 360, 14: 360, 15: 360, 19: 360,
    20: 900,
}


@dataclass
class ControllerState:
    setpt: np.ndarray = field(default_factory=lambda: INITIAL_SETPT.copy())
    errold: np.ndarray = field(default_factory=lambda: np.zeros(N_LOOPS))
    flag6: int = 0


class BaseCaseController:
    def __init__(self) -> None:
        self.state = ControllerState()

    def reset(self) -> None:
        self.state = ControllerState()

    def _p_loop(self, loop: int, xmeas: np.ndarray, xmv: np.ndarray, xmv_index: int, xmeas_index: int, span: float) -> None:
        i = loop - 1
        err = (self.state.setpt[i] - xmeas[xmeas_index]) * 100.0 / span
        dxmv = GAIN[i] * (err - self.state.errold[i])
        xmv[xmv_index] += dxmv
        self.state.errold[i] = err

    def _pi_loop_to_xmv(self, loop: int, xmeas: np.ndarray, xmv: np.ndarray, xmv_index: int, xmeas_index: int, span: float, dt_hours: float) -> None:
        i = loop - 1
        err = (self.state.setpt[i] - xmeas[xmeas_index]) * 100.0 / span
        period = PERIOD_SECONDS[loop]
        dxmv = GAIN[i] * ((err - self.state.errold[i]) + err * dt_hours * period / TAUI[i])
        xmv[xmv_index] += dxmv
        self.state.errold[i] = err

    def _pi_loop_to_setpt(self, loop: int, xmeas: np.ndarray, xmeas_index: int, span: float, dt_hours: float, target_loop: int, target_span: float) -> None:
        i = loop - 1
        err = (self.state.setpt[i] - xmeas[xmeas_index]) * 100.0 / span
        period = PERIOD_SECONDS[loop]
        dxmv = GAIN[i] * ((err - self.state.errold[i]) + err * dt_hours * period / TAUI[i])
        self.state.setpt[target_loop - 1] += dxmv * target_span / 100.0
        self.state.errold[i] = err

    def _contrl6(self, xmeas: np.ndarray, xmv: np.ndarray) -> None:
        s = self.state
        if xmeas[12] >= 2950.0:
            xmv[5] = 100.0
            s.flag6 = 1
        elif s.flag6 == 1 and xmeas[12] >= 2633.7:
            xmv[5] = 100.0
        elif s.flag6 == 1 and xmeas[12] <= 2633.7:
            xmv[5] = 40.060
            s.setpt[5] = 0.33712
            s.errold[5] = 0.0
            s.flag6 = 0
        elif xmeas[12] <= 2300.0:
            xmv[5] = 0.0
            s.flag6 = 2
        elif s.flag6 == 2 and xmeas[12] <= 2633.7:
            xmv[5] = 0.0
        elif s.flag6 == 2 and xmeas[12] >= 2633.7:
            xmv[5] = 40.060
            s.setpt[5] = 0.33712
            s.errold[5] = 0.0
            s.flag6 = 0
        else:
            s.flag6 = 0
            err6 = (s.setpt[5] - xmeas[9]) * 100.0 / 1.0
            dxmv = GAIN[5] * (err6 - s.errold[5])
            xmv[5] += dxmv
            s.errold[5] = err6

    def compute(self, xmeas: np.ndarray, xmv: np.ndarray, dt_hours: float, tick: int) -> np.ndarray:
        """`tick` = integer count of elapsed 1-second ticks since simulation
        start (i.e. round(t_hours * 3600)); drives the reference's MOD(I,3) /
        MOD(I,360) / MOD(I,900) execution schedule."""
        xmv = xmv.copy()

        if tick % 3 == 0:
            self._p_loop(1, xmeas, xmv, 0, 1, 5811.0)
            self._p_loop(2, xmeas, xmv, 1, 2, 8354.0)
            self._p_loop(3, xmeas, xmv, 2, 0, 1.017)
            self._p_loop(4, xmeas, xmv, 3, 3, 15.25)
            self._pi_loop_to_xmv(5, xmeas, xmv, 4, 4, 53.0, dt_hours)
            self._contrl6(xmeas, xmv)
            self._p_loop(7, xmeas, xmv, 6, 11, 70.0)
            self._p_loop(8, xmeas, xmv, 7, 14, 70.0)
            self._p_loop(9, xmeas, xmv, 8, 18, 460.0)
            self._pi_loop_to_xmv(10, xmeas, xmv, 9, 20, 150.0, dt_hours)
            self._pi_loop_to_xmv(11, xmeas, xmv, 10, 16, 46.0, dt_hours)
            self._pi_loop_to_setpt(16, xmeas, 17, 130.0, dt_hours, target_loop=9, target_span=460.0)
            self._pi_loop_to_setpt(17, xmeas, 7, 50.0, dt_hours, target_loop=4, target_span=15.25)
            self._pi_loop_to_setpt(18, xmeas, 8, 150.0, dt_hours, target_loop=10, target_span=150.0)

        if tick % 360 == 0:
            self._pi_loop_to_setpt(13, xmeas, 22, 100.0, dt_hours, target_loop=3, target_span=1.017)
            self._pi_loop_to_setpt(14, xmeas, 25, 100.0, dt_hours, target_loop=1, target_span=5811.0)
            self._pi_loop_to_setpt(15, xmeas, 26, 100.0, dt_hours, target_loop=2, target_span=8354.0)
            self._pi_loop_to_setpt(19, xmeas, 29, 26.0, dt_hours, target_loop=6, target_span=1.0)

        if tick % 900 == 0:
            self._pi_loop_to_setpt(20, xmeas, 37, 1.6, dt_hours, target_loop=16, target_span=130.0)

        xmv[0:11] = np.clip(xmv[0:11], 0.0, 100.0)  # CONSHAND: XMV(1..11); XMV(12)=agitator is left unclamped
        return xmv
