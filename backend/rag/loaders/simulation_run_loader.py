"""Loader that reconstructs typed SimulationRecords from a flattened CSV
written by backend/simulation/run_simulation.py — the reverse of that
module's flatten_record(). Used to source real labeled window data for
knowledge-base incident authoring (CLAUDE.md §7.3) rather than inventing
numbers by hand.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ...simulation.models import (
    IDVVector,
    SimulationRecord,
    SyntheticSensorReading,
    XMEASVector,
    XMVVector,
)

SIMULATION_RUNS_DIR = Path(__file__).resolve().parents[3] / "data" / "simulation_runs"


def _extract_prefixed(row: pd.Series, prefix: str) -> dict:
    plen = len(prefix) + 1
    return {col[plen:]: row[col] for col in row.index if col.startswith(prefix + ".")}


def load_simulation_records(csv_path: Path) -> list[SimulationRecord]:
    df = pd.read_csv(csv_path)
    records: list[SimulationRecord] = []
    for _, row in df.iterrows():
        records.append(
            SimulationRecord(
                run_id=row["run_id"],
                record_index=int(row["record_index"]),
                t_hours=float(row["t_hours"]),
                xmeas=XMEASVector(**_extract_prefixed(row, "xmeas")),
                xmv=XMVVector(**_extract_prefixed(row, "xmv")),
                idv_active=IDVVector(**{k: bool(v) for k, v in _extract_prefixed(row, "idv").items()}),
                synthetic=SyntheticSensorReading(**_extract_prefixed(row, "synthetic")),
                sensor_fault={},
            )
        )
    return records
