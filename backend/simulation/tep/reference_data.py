"""Ground-truth base-case operating point for the steady-state verification test.

Rather than hand-transcribing Downs & Vogel (1993) Table 3 from a secondary
source (risking a transcription error becoming an unchallenged "ground
truth"), this computes the base-case XMEAS directly: BASE_CASE_STATE (the
literal TEINIT initial condition — the literature operating point itself) is
fed through one noiseless, undisturbed TEFUNC evaluation at t=0, exactly as
TEINIT does before returning. This is self-consistent by construction: if the
port has a bug, this value will disagree with the process's own behavior
under closed-loop control (tested in test_steady_state.py), not merely with
an external table.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml

from . import constants as c
from .process_model import fresh_internal_state, tefunc

DEFAULT_TOLERANCE_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "tep_reference_steady_state.yaml"


def compute_base_case_xmeas() -> np.ndarray:
    """The 41-length XMEAS vector at the literature base case, noiseless."""
    state = fresh_internal_state()
    idv = np.zeros(c.N_IDV, dtype=int)
    _, xmeas, diverged, reason = tefunc(0.0, c.BASE_CASE_STATE, c.BASE_CASE_XMV, idv, state, noise_enabled=False)
    if diverged:
        raise RuntimeError(f"Base-case state diverged on evaluation: {reason} — this indicates a port bug.")
    return xmeas


def load_tolerance_config(path: Path | None = None) -> dict:
    """Loads per-field tolerance_pct + citation metadata (not target values —
    those are computed by compute_base_case_xmeas())."""
    path = path or DEFAULT_TOLERANCE_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
