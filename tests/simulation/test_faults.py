import numpy as np
import pytest

from backend.simulation.tep import constants as c
from backend.simulation.tep.faults import (
    IDV_DESCRIPTIONS,
    IDVEvent,
    build_idv_vector,
    idv_vector_at,
)
from backend.simulation.tep.process_model import ProcessDivergedError, TEProcess


def test_all_20_idvs_documented():
    assert set(IDV_DESCRIPTIONS.keys()) == set(range(1, 21))
    assert all(isinstance(v, str) and v for v in IDV_DESCRIPTIONS.values())


def test_build_idv_vector():
    vec = build_idv_vector({1, 6, 20})
    assert vec.shape == (20,)
    assert vec[0] == 1 and vec[5] == 1 and vec[19] == 1
    assert vec.sum() == 3


def test_build_idv_vector_rejects_out_of_range():
    with pytest.raises(ValueError):
        build_idv_vector({21})
    with pytest.raises(ValueError):
        build_idv_vector({0})


def test_idv_event_scheduling():
    schedule = [IDVEvent(idv_number=4, start_hour=1.0, end_hour=2.0)]
    assert idv_vector_at(0.5, schedule)[3] == 0
    assert idv_vector_at(1.5, schedule)[3] == 1
    assert idv_vector_at(2.5, schedule)[3] == 0


@pytest.mark.parametrize("idv_number", range(1, 21))
def test_each_idv_perturbs_output_without_crashing(idv_number):
    process = TEProcess()
    idv = np.zeros(c.N_IDV, dtype=int)
    idv[idv_number - 1] = 1
    xmeas_start = None
    xmeas_end = None
    diverged = False
    try:
        for i in range(7200):  # 2 simulated hours
            xmeas = process.step(1.0 / 3600.0, c.BASE_CASE_XMV, idv, noise_enabled=False)
            if xmeas_start is None:
                xmeas_start = xmeas.copy()
            xmeas_end = xmeas
    except ProcessDivergedError:
        diverged = True

    # Every IDV should either measurably move at least one XMEAS, or trip the
    # plant outright — this guards against an IDV being silently a no-op.
    assert diverged or not np.allclose(xmeas_start, xmeas_end, atol=1e-6)
