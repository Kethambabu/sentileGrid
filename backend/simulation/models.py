"""Typed schemas for the TEP simulation layer (CLAUDE.md §12: type-hint
everything, Pydantic models for all agent/pipeline I/O — simulation output
included, even though the simulator itself isn't an "agent")."""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from .tep.faults import IDV_DESCRIPTIONS

# --- XMEAS: 41 process measurements (teprob.f header comment block) ---

_XMEAS_FIELDS = [
    ("a_feed_kscmh", "XMEAS(1) A Feed (stream 1), kscmh"),
    ("d_feed_kg_hr", "XMEAS(2) D Feed (stream 2), kg/hr"),
    ("e_feed_kg_hr", "XMEAS(3) E Feed (stream 3), kg/hr"),
    ("a_and_c_feed_kscmh", "XMEAS(4) A and C Feed (stream 4), kscmh"),
    ("recycle_flow_kscmh", "XMEAS(5) Recycle Flow (stream 8), kscmh"),
    ("reactor_feed_rate_kscmh", "XMEAS(6) Reactor Feed Rate (stream 6), kscmh"),
    ("reactor_pressure_kpa", "XMEAS(7) Reactor Pressure, kPa gauge"),
    ("reactor_level_pct", "XMEAS(8) Reactor Level, %"),
    ("reactor_temperature_c", "XMEAS(9) Reactor Temperature, deg C"),
    ("purge_rate_kscmh", "XMEAS(10) Purge Rate (stream 9), kscmh"),
    ("product_sep_temp_c", "XMEAS(11) Product Sep Temp, deg C"),
    ("product_sep_level_pct", "XMEAS(12) Product Sep Level, %"),
    ("separator_pressure_kpa", "XMEAS(13) Prod Sep Pressure, kPa gauge"),
    ("separator_underflow_m3_hr", "XMEAS(14) Prod Sep Underflow (stream 10), m3/hr"),
    ("stripper_level_pct", "XMEAS(15) Stripper Level, %"),
    ("stripper_pressure_kpa", "XMEAS(16) Stripper Pressure, kPa gauge"),
    ("stripper_underflow_m3_hr", "XMEAS(17) Stripper Underflow (stream 11), m3/hr"),
    ("stripper_temperature_c", "XMEAS(18) Stripper Temperature, deg C"),
    ("stripper_steam_flow_kg_hr", "XMEAS(19) Stripper Steam Flow, kg/hr"),
    ("compressor_work_kw", "XMEAS(20) Compressor Work, kW"),
    ("reactor_cw_outlet_temp_c", "XMEAS(21) Reactor Cooling Water Outlet Temp, deg C"),
    ("separator_cw_outlet_temp_c", "XMEAS(22) Separator Cooling Water Outlet Temp, deg C"),
    ("reactor_feed_a_mol_pct", "XMEAS(23) Reactor Feed Analysis, Component A, mole %"),
    ("reactor_feed_b_mol_pct", "XMEAS(24) Reactor Feed Analysis, Component B, mole %"),
    ("reactor_feed_c_mol_pct", "XMEAS(25) Reactor Feed Analysis, Component C, mole %"),
    ("reactor_feed_d_mol_pct", "XMEAS(26) Reactor Feed Analysis, Component D, mole %"),
    ("reactor_feed_e_mol_pct", "XMEAS(27) Reactor Feed Analysis, Component E, mole %"),
    ("reactor_feed_f_mol_pct", "XMEAS(28) Reactor Feed Analysis, Component F, mole %"),
    ("purge_a_mol_pct", "XMEAS(29) Purge Gas Analysis, Component A, mole %"),
    ("purge_b_mol_pct", "XMEAS(30) Purge Gas Analysis, Component B, mole %"),
    ("purge_c_mol_pct", "XMEAS(31) Purge Gas Analysis, Component C, mole %"),
    ("purge_d_mol_pct", "XMEAS(32) Purge Gas Analysis, Component D, mole %"),
    ("purge_e_mol_pct", "XMEAS(33) Purge Gas Analysis, Component E, mole %"),
    ("purge_f_mol_pct", "XMEAS(34) Purge Gas Analysis, Component F, mole %"),
    ("purge_g_mol_pct", "XMEAS(35) Purge Gas Analysis, Component G, mole %"),
    ("purge_h_mol_pct", "XMEAS(36) Purge Gas Analysis, Component H, mole %"),
    ("product_d_mol_pct", "XMEAS(37) Product Analysis, Component D, mole %"),
    ("product_e_mol_pct", "XMEAS(38) Product Analysis, Component E, mole %"),
    ("product_f_mol_pct", "XMEAS(39) Product Analysis, Component F, mole %"),
    ("product_g_mol_pct", "XMEAS(40) Product Analysis, Component G, mole %"),
    ("product_h_mol_pct", "XMEAS(41) Product Analysis, Component H, mole %"),
]

_XMV_FIELDS = [
    ("d_feed_flow_valve_pct", "XMV(1) D Feed Flow (stream 2)"),
    ("e_feed_flow_valve_pct", "XMV(2) E Feed Flow (stream 3)"),
    ("a_feed_flow_valve_pct", "XMV(3) A Feed Flow (stream 1)"),
    ("a_and_c_feed_flow_valve_pct", "XMV(4) A and C Feed Flow (stream 4)"),
    ("compressor_recycle_valve_pct", "XMV(5) Compressor Recycle Valve"),
    ("purge_valve_pct", "XMV(6) Purge Valve (stream 9)"),
    ("separator_liquid_flow_valve_pct", "XMV(7) Separator Pot Liquid Flow (stream 10)"),
    ("stripper_liquid_flow_valve_pct", "XMV(8) Stripper Liquid Product Flow (stream 11)"),
    ("stripper_steam_valve_pct", "XMV(9) Stripper Steam Valve"),
    ("reactor_cw_flow_valve_pct", "XMV(10) Reactor Cooling Water Flow"),
    ("condenser_cw_flow_valve_pct", "XMV(11) Condenser Cooling Water Flow"),
    ("agitator_speed_pct", "XMV(12) Agitator Speed"),
]


def _make_vector_model(name: str, fields: list[tuple[str, str]]):
    annotations = {field_name: float for field_name, _ in fields}
    namespace: dict = {"__annotations__": annotations}
    for field_name, description in fields:
        namespace[field_name] = Field(..., description=description)

    def from_array(cls, arr: np.ndarray):
        if len(arr) != len(fields):
            raise ValueError(f"{name}.from_array expected length {len(fields)}, got {len(arr)}")
        return cls(**{field_name: float(v) for (field_name, _), v in zip(fields, arr)})

    def to_array(self) -> np.ndarray:
        return np.array([getattr(self, field_name) for field_name, _ in fields])

    namespace["from_array"] = classmethod(from_array)
    namespace["to_array"] = to_array
    return type(name, (BaseModel,), namespace)


XMEASVector = _make_vector_model("XMEASVector", _XMEAS_FIELDS)
XMVVector = _make_vector_model("XMVVector", _XMV_FIELDS)


class IDVVector(BaseModel):
    """20 process-disturbance flags. Field order matches teprob.f's IDV(1..20)."""

    idv_1: bool = Field(False, description=IDV_DESCRIPTIONS[1])
    idv_2: bool = Field(False, description=IDV_DESCRIPTIONS[2])
    idv_3: bool = Field(False, description=IDV_DESCRIPTIONS[3])
    idv_4: bool = Field(False, description=IDV_DESCRIPTIONS[4])
    idv_5: bool = Field(False, description=IDV_DESCRIPTIONS[5])
    idv_6: bool = Field(False, description=IDV_DESCRIPTIONS[6])
    idv_7: bool = Field(False, description=IDV_DESCRIPTIONS[7])
    idv_8: bool = Field(False, description=IDV_DESCRIPTIONS[8])
    idv_9: bool = Field(False, description=IDV_DESCRIPTIONS[9])
    idv_10: bool = Field(False, description=IDV_DESCRIPTIONS[10])
    idv_11: bool = Field(False, description=IDV_DESCRIPTIONS[11])
    idv_12: bool = Field(False, description=IDV_DESCRIPTIONS[12])
    idv_13: bool = Field(False, description=IDV_DESCRIPTIONS[13])
    idv_14: bool = Field(False, description=IDV_DESCRIPTIONS[14])
    idv_15: bool = Field(False, description=IDV_DESCRIPTIONS[15])
    idv_16: bool = Field(False, description=IDV_DESCRIPTIONS[16])
    idv_17: bool = Field(False, description=IDV_DESCRIPTIONS[17])
    idv_18: bool = Field(False, description=IDV_DESCRIPTIONS[18])
    idv_19: bool = Field(False, description=IDV_DESCRIPTIONS[19])
    idv_20: bool = Field(False, description=IDV_DESCRIPTIONS[20])

    @classmethod
    def from_array(cls, arr: np.ndarray) -> "IDVVector":
        names = list(cls.model_fields.keys())
        return cls(**{n: bool(v) for n, v in zip(names, arr)})

    def to_array(self) -> np.ndarray:
        return np.array([int(v) for v in self.model_dump().values()])


class IDVEventConfig(BaseModel):
    idv_number: int = Field(..., ge=1, le=20)
    start_hour: float = Field(..., ge=0)
    end_hour: float | None = None


class SimulationRunConfig(BaseModel):
    scenario_name: str
    duration_hours: float = Field(..., gt=0, le=200)
    integration_substep_hours: float = Field(default=1.0 / 3600.0, gt=0)
    record_interval_minutes: float = Field(default=3.0, gt=0)
    idv_schedule: list[IDVEventConfig] = Field(default_factory=list)
    noise_enabled: bool = True
    random_seed: float | None = None


class SyntheticSensorReading(BaseModel):
    """CLAUDE.md §6b: synthetic proxies for failure modes native TEP doesn't
    simulate. Phase 1 always returns the documented baseline (is_stub=True) —
    scenario-driven calculation is Phase 2 scope; see synthetic_sensors.py."""

    methane_ppm: float
    vibration_mm_s: float
    valve_health_pct: float = Field(..., ge=0, le=100)
    is_stub: bool = True


class SimulationRecord(BaseModel):
    run_id: str
    record_index: int
    t_hours: float
    xmeas: XMEASVector
    xmv: XMVVector
    idv_active: IDVVector
    synthetic: SyntheticSensorReading
    sensor_fault: dict[str, bool] = Field(
        default_factory=dict,
        description="Reserved for the Sensor Agent (Phase 4). Always empty in Phase 1.",
    )


class SimulationResult(BaseModel):
    run_id: str
    config: SimulationRunConfig
    records: list[SimulationRecord]
    diverged: bool = False
    diverged_reason: str | None = None
