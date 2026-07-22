"""Generates held-out evaluation runs — CLAUDE.md §9.3 / §14's highest-
priority requirement: "Train/test split by scenario run ID, not by window
... seeding the knowledge base and evaluating retrieval precision from the
same runs is invalid and must not happen."

The 3 runs used to seed the knowledge base (Phase 2) live in
data/simulation_runs/*_seed.csv and are referenced by name from
backend/knowledge/incidents/*.yaml. This script generates NEW runs of the
same scenario types (different random seeds — same fault, different
trajectory) plus a fault-free baseline, and writes them to
data/evaluation/holdout_runs/ — a directory seed_knowledge_base.py never
reads from and never will, so the split isn't just a convention, it's
architectural: nothing in the ingestion path can accidentally pick these up.

Run: python -m backend.evaluation.generate_holdout_runs
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..simulation.models import SimulationRunConfig
from ..simulation.run_simulation import flatten_record, load_scenario
from ..simulation.simulator import TEPSimulator

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
HOLDOUT_DIR = REPO_ROOT / "data" / "evaluation" / "holdout_runs"

# (scenario_name, holdout_seed, expected_incident_id_or_None)
# Seeds are deliberately different from each scenario YAML's own
# random_seed (1001/1002/1003 respectively) — same fault mechanism, an
# independent noise/trajectory realization.
HOLDOUT_SPECS = [
    ("reactor_kinetics_drift", 5001, "reactor_kinetics_drift"),
    ("reactor_cw_valve_stiction", 5002, "reactor_cw_valve_stiction"),
    ("reactor_a_feed_loss", 5003, "reactor_a_feed_loss"),
    ("baseline", 5004, None),  # negative control: no fault, nothing should match strongly
    ("compressor_feed_pressure_loss", 5005, "compressor_feed_pressure_loss"),
    ("separator_cooling_duty_loss", 5006, "separator_cooling_duty_loss"),
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def generate_holdout_runs() -> list[dict]:
    HOLDOUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []

    for scenario_name, seed, expected_incident_id in HOLDOUT_SPECS:
        scenario = load_scenario(scenario_name)
        config = SimulationRunConfig(
            scenario_name=scenario.name, duration_hours=scenario.duration_hours,
            idv_schedule=scenario.idv_schedule, noise_enabled=True, random_seed=float(seed),
        )
        logger.info("Generating holdout run: %s (seed=%d)", scenario_name, seed)
        result = TEPSimulator(config).run()

        out_path = HOLDOUT_DIR / f"{scenario_name}_holdout_{seed}.csv"
        df = pd.DataFrame([flatten_record(r) for r in result.records])
        df.to_csv(out_path, index=False)

        manifest.append({
            "scenario_name": scenario_name,
            "seed": seed,
            "expected_incident_id": expected_incident_id,
            "csv_path": str(out_path.relative_to(REPO_ROOT)),
            "n_records": len(result.records),
            "diverged": result.diverged,
        })
        logger.info("Wrote %s (%d records, diverged=%s)", out_path.name, len(result.records), result.diverged)

    manifest_path = HOLDOUT_DIR / "manifest.csv"
    pd.DataFrame(manifest).to_csv(manifest_path, index=False)
    logger.info("Wrote manifest: %s", manifest_path)
    return manifest


if __name__ == "__main__":
    generate_holdout_runs()
