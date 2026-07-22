"""CLI entrypoint: run a named scenario and write its record stream to CSV.

Usage:
    python -m backend.simulation.run_simulation --scenario baseline --hours 8
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd
import yaml

from .models import SimulationRunConfig
from .scenario_definitions.base import ScenarioConfig
from .simulator import TEPSimulator

SCENARIO_DIR = Path(__file__).resolve().parent / "scenario_definitions"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "simulation_runs"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def load_scenario(name: str) -> ScenarioConfig:
    path = SCENARIO_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No scenario definition at {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return ScenarioConfig(**data)


def flatten_record(record) -> dict:
    row = {"run_id": record.run_id, "record_index": record.record_index, "t_hours": record.t_hours}
    row.update({f"xmeas.{k}": v for k, v in record.xmeas.model_dump().items()})
    row.update({f"xmv.{k}": v for k, v in record.xmv.model_dump().items()})
    row.update({f"idv.{k}": v for k, v in record.idv_active.model_dump().items()})
    row.update({f"synthetic.{k}": v for k, v in record.synthetic.model_dump().items()})
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a TEP simulation scenario.")
    parser.add_argument("--scenario", required=True, help="Scenario name (matches scenario_definitions/<name>.yaml)")
    parser.add_argument("--hours", type=float, default=None, help="Override scenario duration_hours")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    scenario = load_scenario(args.scenario)
    duration_hours = args.hours if args.hours is not None else scenario.duration_hours

    config = SimulationRunConfig(
        scenario_name=scenario.name,
        duration_hours=duration_hours,
        idv_schedule=scenario.idv_schedule,
        noise_enabled=scenario.noise_enabled,
        random_seed=scenario.random_seed,
    )

    logger.info("Running scenario '%s' for %.2f hours", scenario.name, duration_hours)
    result = TEPSimulator(config).run()

    if result.diverged:
        logger.warning("Simulation diverged: %s (%d records captured before trip)", result.diverged_reason, len(result.records))
    else:
        logger.info("Simulation completed: %d records", len(result.records))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / f"{scenario.name}_{result.run_id[:8]}.csv"
    df = pd.DataFrame([flatten_record(r) for r in result.records])
    df.to_csv(out_path, index=False)
    logger.info("Wrote %s (%d rows)", out_path, len(df))


if __name__ == "__main__":
    main()
