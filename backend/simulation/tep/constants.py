"""Physical, thermodynamic, and numerical constants for the Tennessee Eastman Process model.

Transcribed from the reference Fortran implementation ``teprob.f`` / ``temain_mod.f``
(Downs & Vogel 1993 base model, modified by Russell, Chiang & Braatz, University of
Illinois Large Scale Systems Research Laboratory), redistributed under a permissive
BSD-style license that explicitly permits use/copy/modify/redistribute with attribution:
https://github.com/camaramm/tennessee-eastman-profBraatz (LICENSE file).

Citations (per that license's required attribution):
    J.J. Downs and E.F. Vogel, "A plant-wide industrial process control problem,"
    Computers and Chemical Engineering, 17:245-255 (1993).
    E.L. Russell, L.H. Chiang, and R.D. Braatz, Data-driven Techniques for Fault
    Detection and Diagnosis in Chemical Processes, Springer-Verlag, London, 2000.

All arrays below are 0-indexed (component 0 = A, ..., component 7 = H; stream
0 = stream 1, ..., stream 12 = stream 13), unlike the 1-indexed Fortran source.
"""

from __future__ import annotations

import numpy as np

N_COMPONENTS = 8  # A, B, C, D, E, F, G, H
N_STREAMS = 13
N_XMV = 12
N_XMEAS = 41
N_IDV = 20
N_STATES = 50
N_WALK_CHANNELS = 12

# Component molecular weights (g/mol), teprob.f TEINIT XMW(1..8).
MOLECULAR_WEIGHTS = np.array([2.0, 25.4, 28.0, 32.0, 46.0, 48.0, 62.0, 76.0])

# Vapor pressure correlation coefficients: VPR = exp(AVP + BVP / (T_C + CVP)).
# A, B, C (indices 0-2) are non-condensable, coefficients are zero (no liquid phase).
VAPOR_PRESSURE_A = np.array([0.0, 0.0, 0.0, 15.92, 16.35, 16.35, 16.43, 17.21])
VAPOR_PRESSURE_B = np.array([0.0, 0.0, 0.0, -1444.0, -2114.0, -2114.0, -2748.0, -3318.0])
VAPOR_PRESSURE_C = np.array([0.0, 0.0, 0.0, 259.0, 265.5, 265.5, 232.9, 249.6])

# Liquid molar volume correlation: v = XMW / (AD + (BD + CD*T)*T), used in density calc.
LIQUID_DENSITY_A = np.array([1.0, 1.0, 1.0, 23.3, 33.9, 32.8, 49.9, 50.5])
LIQUID_DENSITY_B = np.array([0.0, 0.0, 0.0, -0.0700, -0.0957, -0.0995, -0.0191, -0.0541])
LIQUID_DENSITY_C = np.array([0.0, 0.0, 0.0, -0.0002, -0.000152, -0.000233, -0.000425, -0.000150])

# Liquid enthalpy correlation coefficients (TESUB1 ITY=0 branch).
LIQUID_ENTHALPY_A = np.array([1.0e-6, 1.0e-6, 1.0e-6, 0.960e-6, 0.573e-6, 0.652e-6, 0.515e-6, 0.471e-6])
LIQUID_ENTHALPY_B = np.array([0.0, 0.0, 0.0, 8.70e-9, 2.41e-9, 2.18e-9, 5.65e-10, 8.70e-10])
LIQUID_ENTHALPY_C = np.array([0.0, 0.0, 0.0, 4.81e-11, 1.82e-11, 1.94e-11, 3.82e-12, 2.62e-12])

# Heat-of-vaporization additive term (TESUB1 ITY=1/2 branch).
VAPORIZATION_HEAT = np.array([1.0e-6, 1.0e-6, 1.0e-6, 86.7e-6, 160.0e-6, 160.0e-6, 225.0e-6, 209.0e-6])

# Vapor enthalpy correlation coefficients (TESUB1 ITY=1/2 branch).
VAPOR_ENTHALPY_A = np.array([3.411e-6, 0.3799e-6, 0.2491e-6, 0.3567e-6, 0.3463e-6, 0.3930e-6, 0.170e-6, 0.150e-6])
VAPOR_ENTHALPY_B = np.array([7.18e-10, 1.08e-9, 1.36e-11, 8.51e-10, 8.96e-10, 1.02e-9, 0.0, 0.0])
VAPOR_ENTHALPY_C = np.array([6.0e-13, -3.98e-13, -3.93e-14, -3.12e-13, -3.27e-13, -3.12e-13, 0.0, 0.0])

# Ideal gas constant term used in TESUB1/TESUB3 ITY=2 (vapor-with-PV-work) branch.
IDEAL_GAS_R = 3.57696e-6

# Gas constant used for PV = nRT in the reactor/separator/V-vessel pressure calc (TEFUNC RG).
RG = 998.9

# --- Feed stream compositions/temperatures (teprob.f TEINIT XST(:,1..4), TST(1..4)) ---
# Streams 1-4 (0-indexed 0-3): A feed, D feed, E feed, A&C feed.
# Only stream 4's component A/B (indices 0,1) and TST(1) are perturbed at runtime
# (by IDV1/IDV2/random-walk and IDV3 respectively) — everything else here is a
# fixed physical feed composition, not a scratch/recomputed value.
FEED_STREAM_COMPOSITION = np.array(
    [
        [0.0, 0.0001, 0.0, 0.9999, 0.0, 0.0, 0.0, 0.0],  # stream 1: A feed
        [0.0, 0.0, 0.0, 0.0, 0.9999, 0.0001, 0.0, 0.0],  # stream 2: D feed
        [0.9999, 0.0001, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # stream 3: E feed
        [0.4850, 0.0050, 0.5100, 0.0, 0.0, 0.0, 0.0, 0.0],  # stream 4: A & C feed (init guess)
    ]
)
FEED_STREAM_TEMPERATURE_C = np.array([45.0, 45.0, 45.0, 45.0])

# --- Valve/actuator ranges (teprob.f TEINIT VRNG(1..12)); 0 where unused (5, 6, 12) ---
VALVE_RANGE = np.array([400.00, 400.00, 100.00, 1500.00, 0.0, 0.0, 1500.00, 1000.00, 0.03, 1000.0, 1200.0, 0.0])

# Valve position first-order lag time constants, seconds (teprob.f TEINIT VTAU(1..12)).
VALVE_TAU_SECONDS = np.array([8.0, 8.0, 6.0, 9.0, 7.0, 5.0, 5.0, 5.0, 120.0, 5.0, 5.0, 5.0])

# Valve stiction detection threshold magnitude, all 12 valves (teprob.f TEINIT VST(I)=2.0).
VALVE_STICTION_THRESHOLD = np.full(N_XMV, 2.0)

# --- Vessel volumes (ft^3) ---
REACTOR_VOLUME = 1300.0
SEPARATOR_VOLUME = 3500.0
STRIPPER_VOLUME = 156.5
VVESSEL_VOLUME = 5000.0

# Heats of reaction for reactions 1 and 2 (teprob.f TEINIT HTR(1), HTR(2)).
HEAT_OF_REACTION = np.array([0.06899381054, 0.05])

# Cooling water jacket holdups (reactor, separator/condenser).
REACTOR_JACKET_HOLDUP = 7060.0
SEPARATOR_JACKET_HOLDUP = 11138.0

# Initial (scratch) stripping-factor guesses; recomputed every TEFUNC call from
# process conditions, kept here only to seed TEINIT's first pass faithfully.
INITIAL_STRIPPING_FACTOR = np.array([0.99500, 0.99100, 0.99000, 0.91600, 0.93600, 0.93800, 5.80000e-02, 3.01000e-02])

# Compressor characteristic curve constants (teprob.f TEINIT CPFLMX, CPPRMX).
COMPRESSOR_MAX_FLOW = 280275.0
COMPRESSOR_MAX_PRESSURE_RATIO = 1.3

# --- Base-case initial state vector (teprob.f TEINIT YY(1..50)) ---
# This is the published Downs & Vogel operating point. It is NOT a hand-picked
# "close enough" steady state — it is the literal literature base case, and is
# used both to initialize TEProcess.reset() and (via a t=0 TEFUNC evaluation in
# reference_data.py) to derive the exact reference XMEAS values Phase 1's
# steady-state test asserts against.
BASE_CASE_STATE = np.array(
    [
        10.40491389, 4.363996017, 7.570059737, 0.4230042431, 24.15513437,
        2.942597645, 154.3770655, 159.1865960, 2.808522723, 63.75581199,
        26.74026066, 46.38532432, 0.2464521543, 15.20484404, 1.852266172,
        52.44639459, 41.20394008, 0.5699317760, 0.4306056376, 7.9906200783e-03,
        0.9056036089, 1.6054258216e-02, 0.7509759687, 8.8582855955e-02, 48.27726193,
        39.38459028, 0.3755297257, 107.7562698, 29.77250546, 88.32481135,
        23.03929507, 62.85848794, 5.546318688, 11.92244772, 5.555448243,
        0.9218489762, 94.59927549, 77.29698353, 63.05263039, 53.97970677,
        24.64355755, 61.30192144, 22.21000000, 40.06374673, 38.10034370,
        46.53415582, 47.44573456, 41.10581288, 18.11349055, 50.00000000,
    ]
)

# Base-case manipulated variables. teprob.f TEINIT sets XMV(I)=YY(I+38) directly
# (i.e. XMV *is* the valve-position tail of the state vector at t=0), so this
# is derived from BASE_CASE_STATE rather than re-transcribed from
# temain_mod.f's lower-precision XMV(1)=63.053-style literals, to avoid a
# spurious sub-0.001 mismatch between the two at t=0.
BASE_CASE_XMV = BASE_CASE_STATE[38:50].copy()

# --- Measurement noise standard deviations, XMEAS(1..41) (teprob.f TEINIT XNS(1..41)) ---
MEASUREMENT_NOISE_STD = np.array(
    [
        0.0012, 18.000, 22.000, 0.0500, 0.2000, 0.2100, 0.3000, 0.5000, 0.0100, 0.0017,
        0.0100, 1.0000, 0.3000, 0.1250, 1.0000, 0.3000, 0.1150, 0.0100, 1.1500, 0.2000,
        0.0100, 0.0100, 0.250, 0.100, 0.250, 0.100, 0.250, 0.025, 0.250, 0.100,
        0.250, 0.100, 0.250, 0.025, 0.050, 0.050, 0.010, 0.010, 0.010, 0.500,
        0.500,
    ]
)

# Analyzer dead-time/sample-time (hours), reactor-feed & purge (XMEAS 23-36) vs.
# product (XMEAS 37-41) analyzers — teprob.f TEINIT TGAS=0.1, TPROD=0.25.
REACTOR_FEED_PURGE_ANALYZER_INTERVAL_HOURS = 0.1
PRODUCT_ANALYZER_INTERVAL_HOURS = 0.25

# --- Random-walk disturbance spline parameters, 12 channels (teprob.f TEINIT WLK common) ---
# Channels 0-8 (9 channels) use the continuous cubic-spline walk (TESUB5); channels
# 9-11 (3 channels) use the threshold/pulse walk in TEFUNC's "DO 910" block.
# Channel -> IDV mapping (teprob.f TEFUNC IDVWLK assignment):
#   ch0,ch1 -> IDV8   ch2 -> IDV9   ch3 -> IDV10  ch4 -> IDV11  ch5 -> IDV12
#   ch6,ch7 -> IDV13  ch8 -> IDV16  ch9 -> IDV17  ch10 -> IDV18  ch11 -> IDV20
WALK_HSPAN = np.array([0.2, 0.7, 0.25, 0.7, 0.15, 0.15, 1.0, 1.0, 0.4, 1.5, 2.0, 1.5])
WALK_HZERO = np.array([0.5, 1.0, 0.5, 1.0, 0.25, 0.25, 2.0, 2.0, 0.5, 2.0, 3.0, 2.0])
WALK_SSPAN = np.array([0.03, 0.003, 10.0, 10.0, 10.0, 10.0, 0.25, 0.25, 0.25, 0.0, 0.0, 0.0])
WALK_SZERO = np.array([0.485, 0.005, 45.0, 45.0, 35.0, 40.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0])
WALK_SPSPAN = np.zeros(N_WALK_CHANNELS)

# IDVWLK source index per walk channel (which IDV[0-indexed] drives channel i's
# "on/off span" flag) — see mapping comment above.
WALK_CHANNEL_TO_IDV_INDEX = np.array([7, 7, 8, 9, 10, 11, 12, 12, 15, 16, 17, 19])

# LCG pseudo-random generator seed (teprob.f TEINIT G=4651207995.D0 — the active,
# uncommented default seed in the reference source; other commented values in the
# source are alternate scenario seeds used for generating distinct labeled datasets).
DEFAULT_RNG_SEED = 4651207995.0
LCG_MULTIPLIER = 9228907.0
LCG_MODULUS = 4294967296.0

# Reference control-loop integration step in the original benchmark (1 second).
REFERENCE_INTEGRATION_STEP_HOURS = 1.0 / 3600.0
