"""CLAUDE.md §9.3/§14, the highest-priority item in Phase 6: the runs used
to seed the knowledge base and the runs used to evaluate retrieval must
never be the same run IDs. This test verifies that split is real, not just
described — checking actual file paths and actual incident YAML references,
not trusting a comment.
"""

from __future__ import annotations

import pandas as pd

from backend.evaluation.generate_holdout_runs import HOLDOUT_DIR, HOLDOUT_SPECS
from backend.rag.loaders.incident_loader import load_incidents_from_dir
from backend.rag.loaders.simulation_run_loader import SIMULATION_RUNS_DIR
from backend.rag.seed_knowledge_base import INCIDENTS_DIR


def _seed_run_filenames() -> set[str]:
    return {i.source_simulation_run for i in load_incidents_from_dir(INCIDENTS_DIR)}


def test_holdout_manifest_exists():
    manifest_path = HOLDOUT_DIR / "manifest.csv"
    assert manifest_path.exists(), "Run `python -m backend.evaluation.generate_holdout_runs` first."


def test_holdout_runs_are_not_referenced_by_any_seed_incident():
    seed_filenames = _seed_run_filenames()
    manifest = pd.read_csv(HOLDOUT_DIR / "manifest.csv").to_dict("records")

    for row in manifest:
        holdout_filename = row["csv_path"].split("/")[-1].split("\\")[-1]
        assert holdout_filename not in seed_filenames, (
            f"Holdout run {holdout_filename} is also referenced as a KB-seeding source — this is exactly "
            "the leakage CLAUDE.md §9.3 forbids."
        )


def test_holdout_runs_live_in_a_directory_seed_knowledge_base_never_reads():
    import inspect

    from backend.rag import seed_knowledge_base

    source = inspect.getsource(seed_knowledge_base)
    assert "holdout" not in source.lower(), "seed_knowledge_base.py must never reference holdout runs by name or path."
    assert str(HOLDOUT_DIR) not in source


def test_holdout_seeds_differ_from_each_scenarios_own_seeding_seed():
    """Same fault mechanism as the seed run, but a genuinely different
    trajectory/noise realization — not literally the same run replayed."""
    from backend.rag.loaders.incident_loader import load_incidents_from_dir as _load
    from backend.simulation.scenario_definitions.base import ScenarioConfig
    import yaml

    scenario_dir = HOLDOUT_DIR.parents[2] / "backend" / "simulation" / "scenario_definitions"
    for scenario_name, holdout_seed, _expected in HOLDOUT_SPECS:
        path = scenario_dir / f"{scenario_name}.yaml"
        with open(path, "r", encoding="utf-8") as f:
            scenario = ScenarioConfig(**yaml.safe_load(f))
        if scenario.random_seed is not None:
            assert holdout_seed != scenario.random_seed


def test_manifest_expected_incident_ids_match_holdout_specs():
    manifest = pd.read_csv(HOLDOUT_DIR / "manifest.csv").to_dict("records")
    by_scenario = {row["scenario_name"]: row for row in manifest}
    for scenario_name, seed, expected_incident_id in HOLDOUT_SPECS:
        row = by_scenario[scenario_name]
        assert row["seed"] == seed
        if expected_incident_id is None:
            assert pd.isna(row["expected_incident_id"])
        else:
            assert row["expected_incident_id"] == expected_incident_id
