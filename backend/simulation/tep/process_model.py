"""Tennessee Eastman Process physics: a term-by-term Python port of teprob.f's
TEFUNC (derivative evaluator) and its TESUB1-TESUB8 utility routines.

This is intentionally NOT idiomatic "clean" Python in variable naming — array
names (ftm, fcm, xst, ppr, crxr, ...) mirror the Fortran COMMON block names
1:1, and streams/components are addressed by position exactly as the source
does (0-indexed here vs. 1-indexed there). This is a deliberate correctness
choice: for a 50-state benchmark port with dozens of cross-referenced indices,
staying structurally close to the cited reference is far easier to verify
line-by-line than a renamed "pythonic" rewrite would be. See constants.py for
the source/license citation.

Persistent cross-call state (the parts of teprob.f's COMMON blocks that are
NOT simply recomputed from the state vector each call — the random-walk
disturbance splines, the analyzer dead-time buffer, valve stiction memory,
and the LCG noise generator seed) lives in TEPInternalState. A fresh
TEPInternalState's zero-valued arrays are only valid for a simulation that
starts its first tefunc() call at t=0.0 exactly — that first call's `if t==0`
branches (matching the Fortran's `IF(TIME.EQ.0.D0)` blocks) perform the real
initialization, exactly as TEINIT relies on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import constants as c


class ProcessDivergedError(RuntimeError):
    """Raised when the process hits a trip condition (teprob.f ISD flag)."""

    def __init__(self, reason: str, t_hours: float) -> None:
        super().__init__(f"TEP process tripped at t={t_hours:.4f}h: {reason}")
        self.reason = reason
        self.t_hours = t_hours


@dataclass
class WalkState:
    adist: np.ndarray = field(default_factory=lambda: np.zeros(c.N_WALK_CHANNELS))
    bdist: np.ndarray = field(default_factory=lambda: np.zeros(c.N_WALK_CHANNELS))
    cdist: np.ndarray = field(default_factory=lambda: np.zeros(c.N_WALK_CHANNELS))
    ddist: np.ndarray = field(default_factory=lambda: np.zeros(c.N_WALK_CHANNELS))
    tlast: np.ndarray = field(default_factory=lambda: np.zeros(c.N_WALK_CHANNELS))
    tnext: np.ndarray = field(default_factory=lambda: np.zeros(c.N_WALK_CHANNELS))


@dataclass
class TEPInternalState:
    """Persistent state carried between tefunc() calls (teprob.f COMMON/WLK/,
    /RANDSD/, and the analyzer/valve-stiction scratch variables)."""

    walk: WalkState = field(default_factory=WalkState)
    xdel: np.ndarray = field(default_factory=lambda: np.zeros(c.N_XMEAS))
    tgas: float = 0.0
    tprod: float = 0.0
    vcv: np.ndarray = field(default_factory=lambda: np.zeros(c.N_XMV))
    rng_seed: float = c.DEFAULT_RNG_SEED
    temperature_guess: np.ndarray = field(default_factory=lambda: np.full(4, 100.0))
    # teprob.f's XMEAS is a persistent COMMON variable: indices 22-40 (0-idx,
    # XMEAS 23-41) are only overwritten at analyzer refresh ticks and hold
    # their prior value in between. xmeas is a fresh local array each call
    # here, so that hold behavior must be carried explicitly via this buffer
    # (see tefunc's XMEAS(23-41) block) — without it, those fields read as
    # zero on every non-refresh tick instead of holding, corrupting every
    # composition-based control loop (13-15, 19, 20).
    xmeas_hold: np.ndarray = field(default_factory=lambda: np.zeros(c.N_XMEAS))


def fresh_internal_state(seed: float = c.DEFAULT_RNG_SEED) -> TEPInternalState:
    """A blank internal state, valid only if the caller's first tefunc() call
    uses t_hours=0.0 (its `if t==0` branches perform the real initialization)."""
    return TEPInternalState(rng_seed=seed)


# --------------------------------------------------------------------------
# TESUB1-4: thermodynamic property routines
# --------------------------------------------------------------------------


def _tesub1(z: np.ndarray, t: float, ity: int) -> float:
    """Mixture enthalpy (liquid if ity==0, vapor if ity in (1, 2))."""
    if ity == 0:
        hi = t * (c.LIQUID_ENTHALPY_A + c.LIQUID_ENTHALPY_B * t / 2.0 + c.LIQUID_ENTHALPY_C * t**2 / 3.0)
        hi = 1.8 * hi
    else:
        hi = t * (c.VAPOR_ENTHALPY_A + c.VAPOR_ENTHALPY_B * t / 2.0 + c.VAPOR_ENTHALPY_C * t**2 / 3.0)
        hi = 1.8 * hi + c.VAPORIZATION_HEAT
    h = float(np.sum(z * c.MOLECULAR_WEIGHTS * hi))
    if ity == 2:
        h -= c.IDEAL_GAS_R * (t + 273.15)
    return h


def _tesub3(z: np.ndarray, t: float, ity: int) -> float:
    """d(enthalpy)/dT, used by the TESUB2 Newton solve."""
    if ity == 0:
        dhi = c.LIQUID_ENTHALPY_A + c.LIQUID_ENTHALPY_B * t + c.LIQUID_ENTHALPY_C * t**2
        dhi = 1.8 * dhi
    else:
        dhi = c.VAPOR_ENTHALPY_A + c.VAPOR_ENTHALPY_B * t + c.VAPOR_ENTHALPY_C * t**2
        dhi = 1.8 * dhi
    dh = float(np.sum(z * c.MOLECULAR_WEIGHTS * dhi))
    if ity == 2:
        dh -= c.IDEAL_GAS_R
    return dh


def _tesub2(z: np.ndarray, t_guess: float, h: float, ity: int) -> float:
    """Newton solve for temperature given target enthalpy h."""
    t = t_guess
    for _ in range(100):
        err = _tesub1(z, t, ity) - h
        dh = _tesub3(z, t, ity)
        dt = -err / dh
        t += dt
        if abs(dt) < 1e-12:
            return t
    return t_guess


def _tesub4(x: np.ndarray, t: float) -> float:
    """Liquid mixture density."""
    v = float(np.sum(x * c.MOLECULAR_WEIGHTS / (c.LIQUID_DENSITY_A + (c.LIQUID_DENSITY_B + c.LIQUID_DENSITY_C * t) * t)))
    return 1.0 / v


# --------------------------------------------------------------------------
# TESUB5-8: random-walk disturbance generator + LCG noise source
# --------------------------------------------------------------------------


def _lcg_advance(seed: float) -> float:
    return (seed * c.LCG_MULTIPLIER) % c.LCG_MODULUS


def _tesub7(seed: float, signed: bool) -> tuple[float, float]:
    new_seed = _lcg_advance(seed)
    value = (2.0 * new_seed / c.LCG_MODULUS - 1.0) if signed else (new_seed / c.LCG_MODULUS)
    return new_seed, value


def _tesub6(std: float, seed: float) -> tuple[float, float]:
    """Irwin-Hall(12) approximate-Gaussian noise draw, mean 0, ~std stdev."""
    total = 0.0
    for _ in range(12):
        seed, v = _tesub7(seed, signed=False)
        total += v
    return seed, (total - 6.0) * std


def _tesub5(
    s_val: float, sp_val: float, hspan: float, hzero: float, sspan: float, szero: float,
    spspan: float, idvflag: int, tlast: float, seed: float,
) -> tuple[float, float, float, float, float, float]:
    """Generate a new Hermite cubic spline segment (continuity-matched at its
    start) targeting a randomized (or, if idvflag==0, fixed-baseline) endpoint."""
    seed, r1 = _tesub7(seed, signed=True)
    h = hspan * r1 + hzero
    seed, r2 = _tesub7(seed, signed=True)
    s1 = sspan * r2 * idvflag + szero
    seed, r3 = _tesub7(seed, signed=True)
    s1p = spspan * r3 * idvflag
    adist = s_val
    bdist = sp_val
    cdist = (3.0 * (s1 - s_val) - h * (s1p + 2.0 * sp_val)) / h**2
    ddist = (2.0 * (s_val - s1) + h * (s1p + sp_val)) / h**3
    tnext = tlast + h
    return seed, adist, bdist, cdist, ddist, tnext


def _tesub8_eval(walk: WalkState, i: int, t: float) -> float:
    h = t - walk.tlast[i]
    return walk.adist[i] + h * (walk.bdist[i] + h * (walk.cdist[i] + h * walk.ddist[i]))


def _update_walk(walk: WalkState, idvwlk: np.ndarray, t: float, rng_seed: float) -> float:
    """Advance the 12-channel disturbance spline state to cover time t.
    Mirrors teprob.f's DO 900 (channels 0-8, continuous spline) and DO 910
    (channels 9-11, rise/hold/decay pulse) blocks. Mutates `walk` in place,
    returns the updated RNG seed."""
    for i in range(9):
        if t >= walk.tnext[i]:
            hwlk = walk.tnext[i] - walk.tlast[i]
            swlk = walk.adist[i] + hwlk * (walk.bdist[i] + hwlk * (walk.cdist[i] + hwlk * walk.ddist[i]))
            spwlk = walk.bdist[i] + hwlk * (2.0 * walk.cdist[i] + 3.0 * hwlk * walk.ddist[i])
            walk.tlast[i] = walk.tnext[i]
            rng_seed, a, b, cc, d, tn = _tesub5(
                swlk, spwlk, c.WALK_HSPAN[i], c.WALK_HZERO[i], c.WALK_SSPAN[i],
                c.WALK_SZERO[i], c.WALK_SPSPAN[i], int(idvwlk[i]), walk.tlast[i], rng_seed,
            )
            walk.adist[i], walk.bdist[i], walk.cdist[i], walk.ddist[i], walk.tnext[i] = a, b, cc, d, tn

    for i in range(9, 12):
        if t >= walk.tnext[i]:
            hwlk = walk.tnext[i] - walk.tlast[i]
            swlk = walk.adist[i] + hwlk * (walk.bdist[i] + hwlk * (walk.cdist[i] + hwlk * walk.ddist[i]))
            spwlk = walk.bdist[i] + hwlk * (2.0 * walk.cdist[i] + 3.0 * hwlk * walk.ddist[i])
            walk.tlast[i] = walk.tnext[i]
            if swlk > 0.1:
                walk.adist[i] = swlk
                walk.bdist[i] = spwlk
                walk.cdist[i] = -(3.0 * swlk + 0.2 * spwlk) / 0.01
                walk.ddist[i] = (2.0 * swlk + 0.1 * spwlk) / 0.001
                walk.tnext[i] = walk.tlast[i] + 0.1
            else:
                rng_seed, r = _tesub7(rng_seed, signed=True)
                hwlk2 = c.WALK_HSPAN[i] * r + c.WALK_HZERO[i]
                walk.adist[i] = 0.0
                walk.bdist[i] = 0.0
                walk.cdist[i] = float(idvwlk[i]) / hwlk2**2
                walk.ddist[i] = 0.0
                walk.tnext[i] = walk.tlast[i] + hwlk2
    return rng_seed


# --------------------------------------------------------------------------
# TEFUNC
# --------------------------------------------------------------------------


def tefunc(
    t_hours: float,
    y: np.ndarray,
    xmv: np.ndarray,
    idv: np.ndarray,
    state: TEPInternalState,
    noise_enabled: bool = True,
) -> tuple[np.ndarray, np.ndarray, bool, str]:
    """One derivative evaluation. Mutates `state` in place (walk splines,
    analyzer dead-time buffer, valve stiction memory, RNG seed) exactly as
    teprob.f's COMMON blocks persist across calls.

    Returns (dydt[50], xmeas[41], diverged, diverged_reason).
    """
    idv = (np.asarray(idv) > 0).astype(int)
    idvwlk = idv[c.WALK_CHANNEL_TO_IDV_INDEX]

    if t_hours == 0.0:
        state.walk = WalkState(
            adist=c.WALK_SZERO.copy(),
            bdist=np.zeros(c.N_WALK_CHANNELS),
            cdist=np.zeros(c.N_WALK_CHANNELS),
            ddist=np.zeros(c.N_WALK_CHANNELS),
            tlast=np.zeros(c.N_WALK_CHANNELS),
            tnext=np.full(c.N_WALK_CHANNELS, 0.1),
        )

    state.rng_seed = _update_walk(state.walk, idvwlk, t_hours, state.rng_seed)

    def w(i: int) -> float:
        return _tesub8_eval(state.walk, i, t_hours)

    xst4_a = w(0) - idv[0] * 0.03 - idv[1] * 2.43719e-3
    xst4_b = w(1) + idv[1] * 0.005
    xst4_c = 1.0 - xst4_a - xst4_b
    tst1 = w(2) + idv[2] * 5.0
    tst4 = w(3)
    tcwr = w(4) + idv[3] * 5.0
    tcws = w(5) + idv[4] * 5.0
    r1f = w(6)
    r2f = w(7)

    xst = np.zeros((c.N_COMPONENTS, c.N_STREAMS))
    xst[:, 0] = c.FEED_STREAM_COMPOSITION[0]
    xst[:, 1] = c.FEED_STREAM_COMPOSITION[1]
    xst[:, 2] = c.FEED_STREAM_COMPOSITION[2]
    xst[:, 3] = c.FEED_STREAM_COMPOSITION[3]
    xst[0, 3], xst[1, 3], xst[2, 3] = xst4_a, xst4_b, xst4_c
    tst = np.zeros(c.N_STREAMS)
    tst[0], tst[1], tst[2], tst[3] = tst1, c.FEED_STREAM_TEMPERATURE_C[1], c.FEED_STREAM_TEMPERATURE_C[2], tst4

    # --- unpack state vector (teprob.f lines 1010-1040) ---
    ucvr = np.zeros(8)
    ucvs = np.zeros(8)
    uclr = np.zeros(8)
    ucls = np.zeros(8)
    ucvr[0:3] = y[0:3]
    ucvs[0:3] = y[9:12]
    uclr[3:8] = y[3:8]
    ucls[3:8] = y[12:17]
    uclc = y[18:26].copy()
    ucvv = y[27:35].copy()
    etr, ets, etc_, etv = y[8], y[17], y[26], y[35]
    twr, tws = y[36], y[37]
    vpos = y[38:50].copy()

    utlr, utls, utlc, utvv = uclr.sum(), ucls.sum(), uclc.sum(), ucvv.sum()
    xlr, xls, xlc, xvv = uclr / utlr, ucls / utls, uclc / utlc, ucvv / utvv
    esr, ess, esc, esv = etr / utlr, ets / utls, etc_ / utlc, etv / utvv

    tcr = _tesub2(xlr, state.temperature_guess[0], esr, 0)
    tkr = tcr + 273.15
    tcs = _tesub2(xls, state.temperature_guess[1], ess, 0)
    tks = tcs + 273.15
    tcc = _tesub2(xlc, state.temperature_guess[2], esc, 0)
    tcv = _tesub2(xvv, state.temperature_guess[3], esv, 2)
    tkv = tcv + 273.15
    state.temperature_guess = np.array([tcr, tcs, tcc, tcv])

    dlr = _tesub4(xlr, tcr)
    dls = _tesub4(xls, tcs)
    dlc = _tesub4(xlc, tcc)
    vlr, vls, vlc = utlr / dlr, utls / dls, utlc / dlc
    vvr, vvs = c.REACTOR_VOLUME - vlr, c.SEPARATOR_VOLUME - vls

    ppr = np.zeros(8)
    pps = np.zeros(8)
    ppr[0:3] = ucvr[0:3] * c.RG * tkr / vvr
    pps[0:3] = ucvs[0:3] * c.RG * tks / vvs
    vpr_r = np.exp(c.VAPOR_PRESSURE_A[3:8] + c.VAPOR_PRESSURE_B[3:8] / (tcr + c.VAPOR_PRESSURE_C[3:8]))
    vpr_s = np.exp(c.VAPOR_PRESSURE_A[3:8] + c.VAPOR_PRESSURE_B[3:8] / (tcs + c.VAPOR_PRESSURE_C[3:8]))
    ppr[3:8] = vpr_r * xlr[3:8]
    pps[3:8] = vpr_s * xls[3:8]
    ptr, pts = float(ppr.sum()), float(pps.sum())
    ptv = utvv * c.RG * tkv / c.VVESSEL_VOLUME

    xvr, xvs = ppr / ptr, pps / pts
    utvr, utvs = ptr * vvr / c.RG / tkr, pts * vvs / c.RG / tks
    ucvr[3:8] = utvr * xvr[3:8]
    ucvs[3:8] = utvs * xvs[3:8]

    rr = np.zeros(4)
    rr[0] = np.exp(31.5859536 - 40000.0 / 1.987 / tkr) * r1f
    rr[1] = np.exp(3.00094014 - 20000.0 / 1.987 / tkr) * r2f
    rr[2] = np.exp(53.4060443 - 60000.0 / 1.987 / tkr)
    rr[3] = rr[2] * 0.767488334
    if ppr[0] > 0.0 and ppr[2] > 0.0:
        r1f2 = ppr[0] ** 1.1544
        r2f2 = ppr[2] ** 0.3735
        rr[0] = rr[0] * r1f2 * r2f2 * ppr[3]
        rr[1] = rr[1] * r1f2 * r2f2 * ppr[4]
    else:
        rr[0] = 0.0
        rr[1] = 0.0
    rr[2] = rr[2] * ppr[0] * ppr[4]
    rr[3] = rr[3] * ppr[0] * ppr[3]
    rr = rr * vvr

    crxr = np.zeros(8)
    crxr[0] = -rr[0] - rr[1] - rr[2]
    crxr[2] = -rr[0] - rr[1]
    crxr[3] = -rr[0] - 1.5 * rr[3]
    crxr[4] = -rr[1] - rr[2]
    crxr[5] = rr[2] + rr[3]
    crxr[6] = rr[0]
    crxr[7] = rr[1]
    rh = rr[0] * c.HEAT_OF_REACTION[0] + rr[1] * c.HEAT_OF_REACTION[1]

    xst[:, 5] = xvv
    xst[:, 7] = xvr
    xst[:, 8] = xvs
    xst[:, 9] = xvs
    xst[:, 10] = xls
    xst[:, 12] = xlc

    xmws = np.zeros(c.N_STREAMS)
    xmws[0] = float(np.sum(xst[:, 0] * c.MOLECULAR_WEIGHTS))
    xmws[1] = float(np.sum(xst[:, 1] * c.MOLECULAR_WEIGHTS))
    xmws[5] = float(np.sum(xst[:, 5] * c.MOLECULAR_WEIGHTS))
    xmws[7] = float(np.sum(xst[:, 7] * c.MOLECULAR_WEIGHTS))
    xmws[8] = float(np.sum(xst[:, 8] * c.MOLECULAR_WEIGHTS))
    xmws[9] = float(np.sum(xst[:, 9] * c.MOLECULAR_WEIGHTS))

    tst[5] = tcv
    tst[7] = tcr
    tst[8] = tcs
    tst[9] = tcs
    tst[10] = tcs
    tst[12] = tcc

    hst = np.zeros(c.N_STREAMS)
    hst[0] = _tesub1(xst[:, 0], tst[0], 1)
    hst[1] = _tesub1(xst[:, 1], tst[1], 1)
    hst[2] = _tesub1(xst[:, 2], tst[2], 1)
    hst[3] = _tesub1(xst[:, 3], tst[3], 1)
    hst[5] = _tesub1(xst[:, 5], tst[5], 1)
    hst[7] = _tesub1(xst[:, 7], tst[7], 1)
    hst[8] = _tesub1(xst[:, 8], tst[8], 1)
    hst[9] = hst[8]
    hst[10] = _tesub1(xst[:, 10], tst[10], 0)
    hst[12] = _tesub1(xst[:, 12], tst[12], 0)

    ftm = np.zeros(c.N_STREAMS)
    ftm[0] = vpos[0] * c.VALVE_RANGE[0] / 100.0
    ftm[1] = vpos[1] * c.VALVE_RANGE[1] / 100.0
    ftm[2] = vpos[2] * (1.0 - idv[5]) * c.VALVE_RANGE[2] / 100.0
    ftm[3] = vpos[3] * (1.0 - idv[6] * 0.2) * c.VALVE_RANGE[3] / 100.0 + 1.0e-10
    ftm[10] = vpos[6] * c.VALVE_RANGE[6] / 100.0
    ftm[12] = vpos[7] * c.VALVE_RANGE[7] / 100.0
    uac = vpos[8] * c.VALVE_RANGE[8] * (1.0 + w(8)) / 100.0
    fwr = vpos[9] * c.VALVE_RANGE[9] / 100.0
    fws = vpos[10] * c.VALVE_RANGE[10] / 100.0
    agsp = (vpos[11] + 150.0) / 100.0

    dlp = max(ptv - ptr, 0.0)
    flms = 1937.6 * np.sqrt(dlp)
    ftm[5] = flms / xmws[5]

    dlp = max(ptr - pts, 0.0)
    flms = 4574.21 * np.sqrt(dlp) * (1.0 - 0.25 * w(11))
    ftm[7] = flms / xmws[7]

    dlp = max(pts - 760.0, 0.0)
    flms = vpos[5] * 0.151169 * np.sqrt(dlp)
    ftm[9] = flms / xmws[9]

    pr = min(max(ptv / pts, 1.0), c.COMPRESSOR_MAX_PRESSURE_RATIO)
    flcoef = c.COMPRESSOR_MAX_FLOW / 1.197
    flms = c.COMPRESSOR_MAX_FLOW + flcoef * (1.0 - pr**3)
    cpdh = flms * (tcs + 273.15) * 1.8e-6 * 1.9872 * (ptv - pts) / (xmws[8] * pts)
    dlp = max(ptv - pts, 0.0)
    flms = flms - vpos[4] * 53.349 * np.sqrt(dlp)
    flms = max(flms, 1.0e-3)
    ftm[8] = flms / xmws[8]
    hst[8] = hst[8] + cpdh / ftm[8]

    fcm = np.zeros((c.N_COMPONENTS, c.N_STREAMS))
    for k in (0, 1, 2, 3, 5, 7, 8, 9, 10, 12):
        fcm[:, k] = xst[:, k] * ftm[k]

    if ftm[10] > 0.1:
        if tcc > 170.0:
            tmpfac = tcc - 120.262
        elif tcc < 5.292:
            tmpfac = 0.1
        else:
            tmpfac = 363.744 / (177.0 - tcc) - 2.22579488
        vovrl = ftm[3] / ftm[10] * tmpfac
        sfr = np.array(
            [
                c.INITIAL_STRIPPING_FACTOR[0],
                c.INITIAL_STRIPPING_FACTOR[1],
                c.INITIAL_STRIPPING_FACTOR[2],
                8.5010 * vovrl / (1.0 + 8.5010 * vovrl),
                11.402 * vovrl / (1.0 + 11.402 * vovrl),
                11.795 * vovrl / (1.0 + 11.795 * vovrl),
                0.0480 * vovrl / (1.0 + 0.0480 * vovrl),
                0.0242 * vovrl / (1.0 + 0.0242 * vovrl),
            ]
        )
    else:
        sfr = np.array(
            [c.INITIAL_STRIPPING_FACTOR[0], c.INITIAL_STRIPPING_FACTOR[1], c.INITIAL_STRIPPING_FACTOR[2],
             0.9999, 0.999, 0.999, 0.99, 0.98]
        )

    fin = fcm[:, 3] + fcm[:, 10]
    fcm[:, 4] = sfr * fin
    fcm[:, 11] = fin - fcm[:, 4]
    ftm[4] = float(fcm[:, 4].sum())
    ftm[11] = float(fcm[:, 11].sum())
    xst[:, 4] = fcm[:, 4] / ftm[4]
    xst[:, 11] = fcm[:, 11] / ftm[11]
    tst[4] = tcc
    tst[11] = tcc
    hst[4] = _tesub1(xst[:, 4], tst[4], 1)
    hst[11] = _tesub1(xst[:, 11], tst[11], 0)

    ftm[6] = ftm[5]
    hst[6] = hst[5]
    tst[6] = tst[5]
    xst[:, 6] = xst[:, 5]
    fcm[:, 6] = fcm[:, 5]

    vlr_ratio = vlr / 7.8
    if vlr_ratio > 50.0:
        uarlev = 1.0
    elif vlr_ratio < 10.0:
        uarlev = 0.0
    else:
        uarlev = 0.025 * vlr_ratio - 0.25
    uar = uarlev * (-0.5 * agsp**2 + 2.75 * agsp - 2.5) * 855490.0e-6
    qur = uar * (twr - tcr) * (1.0 - 0.35 * w(9))
    uas = 0.404655 * (1.0 - 1.0 / (1.0 + (ftm[7] / 3528.73) ** 4))
    qus = uas * (tws - tst[7]) * (1.0 - 0.25 * w(10))
    quc = uac * (100.0 - tcc) if tcc < 100.0 else 0.0

    xmeas = np.zeros(c.N_XMEAS)
    xmeas[0] = ftm[2] * 0.359 / 35.3145
    xmeas[1] = ftm[0] * xmws[0] * 0.454
    xmeas[2] = ftm[1] * xmws[1] * 0.454
    xmeas[3] = ftm[3] * 0.359 / 35.3145
    xmeas[4] = ftm[8] * 0.359 / 35.3145
    xmeas[5] = ftm[5] * 0.359 / 35.3145
    xmeas[6] = (ptr - 760.0) / 760.0 * 101.325
    xmeas[7] = (vlr - 84.6) / 666.7 * 100.0
    xmeas[8] = tcr
    xmeas[9] = ftm[9] * 0.359 / 35.3145
    xmeas[10] = tcs
    xmeas[11] = (vls - 27.5) / 290.0 * 100.0
    xmeas[12] = (pts - 760.0) / 760.0 * 101.325
    xmeas[13] = ftm[10] / dls / 35.3145
    xmeas[14] = (vlc - 78.25) / c.STRIPPER_VOLUME * 100.0
    xmeas[15] = (ptv - 760.0) / 760.0 * 101.325
    xmeas[16] = ftm[12] / dlc / 35.3145
    xmeas[17] = tcc
    xmeas[18] = quc * 1.04e3 * 0.454
    xmeas[19] = cpdh * 0.29307e3
    xmeas[20] = twr
    xmeas[21] = tws

    diverged = False
    diverged_reason = ""
    checks = [
        (xmeas[6] > 3000.0, "reactor pressure exceeded 3000 kPa gauge"),
        (vlr / 35.3145 > 24.0, "reactor level exceeded upper bound"),
        (vlr / 35.3145 < 2.0, "reactor level below lower bound"),
        (xmeas[8] > 175.0, "reactor temperature exceeded 175 C"),
        (vls / 35.3145 > 12.0, "separator level exceeded upper bound"),
        (vls / 35.3145 < 1.0, "separator level below lower bound"),
        (vlc / 35.3145 > 8.0, "stripper level exceeded upper bound"),
        (vlc / 35.3145 < 1.0, "stripper level below lower bound"),
    ]
    for condition, reason in checks:
        if condition:
            diverged = True
            diverged_reason = reason
            break

    if noise_enabled and t_hours > 0.0 and not diverged:
        for i in range(22):
            state.rng_seed, noise = _tesub6(c.MEASUREMENT_NOISE_STD[i], state.rng_seed)
            xmeas[i] += noise

    # XMEAS(23-41) hold their previous value by default (persistent COMMON in
    # the reference); only overwritten below on an analyzer refresh tick.
    xmeas[22:41] = state.xmeas_hold[22:41]

    xcmp = np.zeros(c.N_XMEAS)
    xcmp[22:28] = xst[0:6, 6] * 100.0
    xcmp[28:36] = xst[0:8, 9] * 100.0
    xcmp[36:41] = xst[3:8, 12] * 100.0

    if t_hours == 0.0:
        state.xdel[22:41] = xcmp[22:41]
        xmeas[22:41] = xcmp[22:41]
        state.tgas = 0.1
        state.tprod = 0.25

    if t_hours >= state.tgas:
        for i in range(22, 36):
            xmeas[i] = state.xdel[i]
            if noise_enabled:
                state.rng_seed, noise = _tesub6(c.MEASUREMENT_NOISE_STD[i], state.rng_seed)
                xmeas[i] += noise
            state.xdel[i] = xcmp[i]
        state.tgas += 0.1

    if t_hours >= state.tprod:
        for i in range(36, 41):
            xmeas[i] = state.xdel[i]
            if noise_enabled:
                state.rng_seed, noise = _tesub6(c.MEASUREMENT_NOISE_STD[i], state.rng_seed)
                xmeas[i] += noise
            state.xdel[i] = xcmp[i]
        state.tprod += 0.25

    state.xmeas_hold[22:41] = xmeas[22:41]

    dydt = np.zeros(c.N_STATES)
    for i in range(8):
        dydt[i] = fcm[i, 6] - fcm[i, 7] + crxr[i]
        dydt[i + 9] = fcm[i, 7] - fcm[i, 8] - fcm[i, 9] - fcm[i, 10]
        dydt[i + 18] = fcm[i, 11] - fcm[i, 12]
        dydt[i + 27] = fcm[i, 0] + fcm[i, 1] + fcm[i, 2] + fcm[i, 4] + fcm[i, 8] - fcm[i, 5]

    dydt[8] = hst[6] * ftm[6] - hst[7] * ftm[7] + rh + qur
    dydt[17] = hst[7] * ftm[7] - hst[8] * ftm[8] - hst[9] * ftm[9] - hst[10] * ftm[10] + qus
    dydt[26] = hst[3] * ftm[3] + hst[10] * ftm[10] - hst[4] * ftm[4] - hst[12] * ftm[12] + quc
    dydt[35] = hst[0] * ftm[0] + hst[1] * ftm[1] + hst[2] * ftm[2] + hst[4] * ftm[4] + hst[8] * ftm[8] - hst[5] * ftm[5]
    dydt[36] = (fwr * 500.53 * (tcwr - twr) - qur * 1.0e6 / 1.8) / c.REACTOR_JACKET_HOLDUP
    dydt[37] = (fws * 500.53 * (tcws - tws) - qus * 1.0e6 / 1.8) / c.SEPARATOR_JACKET_HOLDUP

    ivst = np.zeros(c.N_XMV, dtype=int)
    ivst[9] = idv[13]
    ivst[10] = idv[14]
    ivst[4] = idv[18]
    ivst[6] = idv[18]
    ivst[7] = idv[18]
    ivst[8] = idv[18]

    valve_tau_hours = c.VALVE_TAU_SECONDS / 3600.0
    for i in range(c.N_XMV):
        if t_hours == 0.0 or abs(state.vcv[i] - xmv[i]) > c.VALVE_STICTION_THRESHOLD[i] * ivst[i]:
            state.vcv[i] = xmv[i]
        state.vcv[i] = min(max(state.vcv[i], 0.0), 100.0)
        dydt[38 + i] = (state.vcv[i] - vpos[i]) / valve_tau_hours[i]

    if diverged:
        dydt[:] = 0.0

    return dydt, xmeas, diverged, diverged_reason


class TEProcess:
    """Stateful wrapper: owns the 50-state vector and the persistent
    TEPInternalState, advances via single-evaluation fixed-step Euler
    integration — the same scheme teprob.f's own INTGTR uses.

    Deliberately NOT RK4/an adaptive solver: TEFUNC is not a pure function of
    (t, y). Each call has real side effects tied to time progression (the
    random-walk disturbance splines regenerate when t crosses a breakpoint,
    the analyzer dead-time buffer advances, and measurement noise is drawn
    from a stateful LCG). Evaluating it at RK4's intermediate sub-stage
    points would trigger those side effects multiple times per real
    timestep, corrupting the disturbance/noise state. Single-evaluation
    Euler at the reference's 1-second step avoids this by construction, and
    matches every published TEP fault-detection dataset's own integration
    scheme, so it is also the more literature-faithful choice, not just a
    workaround."""

    def __init__(self, rng_seed: float = c.DEFAULT_RNG_SEED) -> None:
        self._rng_seed_init = rng_seed
        self.y: np.ndarray = c.BASE_CASE_STATE.copy()
        self.t_hours: float = 0.0
        self.internal = fresh_internal_state(rng_seed)

    def reset(self) -> np.ndarray:
        self.y = c.BASE_CASE_STATE.copy()
        self.t_hours = 0.0
        self.internal = fresh_internal_state(self._rng_seed_init)
        return self.y

    def peek_xmeas(self, xmv: np.ndarray, idv: np.ndarray, noise_enabled: bool = True) -> np.ndarray:
        """Evaluate XMEAS at the current (t, y) WITHOUT advancing time/state.
        Used once, before the control loop starts, to prime the first XMEAS
        reading — matching TEINIT's own priming TEFUNC call in the
        reference, which runs before its main loop's first controller call."""
        _, xmeas, diverged, reason = tefunc(self.t_hours, self.y, xmv, idv, self.internal, noise_enabled)
        if diverged:
            raise ProcessDivergedError(reason, self.t_hours)
        return xmeas

    def step(self, dt_hours: float, xmv: np.ndarray, idv: np.ndarray, noise_enabled: bool = True) -> np.ndarray:
        """Advance one Euler step. Returns the 41-length XMEAS vector
        evaluated at the pre-advance state (matching temain_mod.f, which
        records OUTPUT before calling INTGTR each loop iteration). Raises
        ProcessDivergedError on a trip condition."""
        dydt, xmeas, diverged, reason = tefunc(self.t_hours, self.y, xmv, idv, self.internal, noise_enabled)
        if diverged:
            raise ProcessDivergedError(reason, self.t_hours)
        self.t_hours += dt_hours
        self.y = self.y + dydt * dt_hours
        return xmeas
