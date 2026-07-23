"""TEPSimulator: drives TEProcess + BaseCaseController + SyntheticSensorLayer
through a configured run, emitting evenly-spaced typed SimulationRecords.

Per-tick ordering mirrors temain_mod.f's main loop exactly: controllers run
first (reading the previous tick's XMEAS, writing a new XMV), then the
process is stepped forward using that XMV (producing the XMEAS the *next*
tick's controllers will read). See controller.py's docstring for why this
ordering matters (it reproduces the reference's one-tick cascade lag).
"""

from __future__ import annotations

import uuid

import numpy as np

from .models import (
    IDVVector,
    SimulationRecord,
    SimulationResult,
    SimulationRunConfig,
    XMEASVector,
    XMVVector,
)
from .synthetic_sensors import SyntheticSensorLayer
from .tep import constants as c
from .tep.controller import BaseCaseController
from .tep.faults import idv_vector_at
from .tep.process_model import ProcessDivergedError, TEProcess


class TEPSimulator:
    def __init__(self, config: SimulationRunConfig) -> None:
        self.config = config
        seed = config.random_seed if config.random_seed is not None else c.DEFAULT_RNG_SEED
        self.process = TEProcess(rng_seed=seed)
        self.controller = BaseCaseController()
        self.synthetic = SyntheticSensorLayer(rules=config.synthetic_sensor_rules)

    def run(self) -> SimulationResult:
        run_id = str(uuid.uuid4())
        dt_hours = self.config.integration_substep_hours
        n_steps = round(self.config.duration_hours / dt_hours)
        record_interval_ticks = max(
            1, round((self.config.record_interval_minutes * 60.0) / (dt_hours * 3600.0))
        )

        xmv = c.BASE_CASE_XMV.copy()
        idv0 = idv_vector_at(self.process.t_hours, self.config.idv_schedule)
        xmeas = self.process.peek_xmeas(xmv, idv0, noise_enabled=self.config.noise_enabled)

        records: list[SimulationRecord] = []
        diverged = False
        diverged_reason: str | None = None
        record_index = 0

        for tick in range(1, n_steps + 1):
            xmv = self.controller.compute(xmeas, xmv, dt_hours, tick)
            idv = idv_vector_at(self.process.t_hours, self.config.idv_schedule)

            try:
                xmeas = self.process.step(dt_hours, xmv, idv, noise_enabled=self.config.noise_enabled)
            except ProcessDivergedError as exc:
                diverged = True
                diverged_reason = str(exc)
                break

            if tick % record_interval_ticks == 0:
                xmeas_model = XMEASVector.from_array(xmeas)
                xmv_model = XMVVector.from_array(xmv)
                idv_model = IDVVector.from_array(idv)
                synthetic = self.synthetic.compute(xmeas_model, xmv_model, self.process.t_hours)
                records.append(
                    SimulationRecord(
                        run_id=run_id,
                        record_index=record_index,
                        t_hours=self.process.t_hours,
                        xmeas=xmeas_model,
                        xmv=xmv_model,
                        idv_active=idv_model,
                        synthetic=synthetic,
                        sensor_fault={},
                    )
                )
                record_index += 1

        return SimulationResult(
            run_id=run_id,
            config=self.config,
            records=records,
            diverged=diverged,
            diverged_reason=diverged_reason,
        )
