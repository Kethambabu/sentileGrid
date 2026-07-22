"""Retrieval precision/recall, evaluated ONLY on held-out runs (CLAUDE.md
§9.3/§10/§14) — never the runs used to seed the knowledge base. See
generate_holdout_runs.py's docstring for why this split is structural, not
just a convention.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..rag.loaders.simulation_run_loader import load_simulation_records
from ..rag.retriever import LiveRetriever
from ..rag.windowing import FAST_WINDOW_SIZE
from .generate_holdout_runs import HOLDOUT_DIR

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class RetrievalEvalSample:
    scenario_name: str
    seed: int
    record_index: int
    t_hours: float
    expected_incident_id: str | None
    phase: str
    is_novel_condition: bool
    top_match_incident_id: str | None
    top_match_similarity: float | None
    correct_top1: bool
    expected_in_topk: bool


def load_manifest() -> list[dict]:
    manifest_path = HOLDOUT_DIR / "manifest.csv"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"No holdout manifest at {manifest_path} — run "
            "`python -m backend.evaluation.generate_holdout_runs` first."
        )
    return pd.read_csv(manifest_path).to_dict("records")


def evaluate_retrieval(retriever: LiveRetriever, manifest: list[dict] | None = None, sample_every: int = 10) -> list[RetrievalEvalSample]:
    manifest = manifest if manifest is not None else load_manifest()
    samples: list[RetrievalEvalSample] = []

    for spec in manifest:
        expected_incident_id = spec["expected_incident_id"]
        if pd.isna(expected_incident_id):
            expected_incident_id = None
        csv_path = REPO_ROOT / spec["csv_path"]
        records = load_simulation_records(csv_path)

        for end_index in range(FAST_WINDOW_SIZE - 1, len(records), sample_every):
            window_records = records[: end_index + 1]
            outcome = retriever.retrieve(window_records)

            top_match = outcome.matches[0] if outcome.matches else None
            if expected_incident_id is None:
                # Negative control (no-fault run): "correct" means we did NOT
                # confidently pin this to some unrelated incident.
                correct_top1 = outcome.is_novel_condition or top_match is None
                expected_in_topk = correct_top1
            else:
                correct_top1 = top_match is not None and top_match.incident_id == expected_incident_id
                expected_in_topk = any(m.incident_id == expected_incident_id for m in outcome.matches)

            samples.append(
                RetrievalEvalSample(
                    scenario_name=spec["scenario_name"], seed=int(spec["seed"]), record_index=end_index,
                    t_hours=window_records[-1].t_hours, expected_incident_id=expected_incident_id,
                    phase=outcome.phase.value, is_novel_condition=outcome.is_novel_condition,
                    top_match_incident_id=top_match.incident_id if top_match else None,
                    top_match_similarity=top_match.combined_similarity if top_match else None,
                    correct_top1=correct_top1, expected_in_topk=expected_in_topk,
                )
            )
    return samples


def summarize(samples: list[RetrievalEvalSample]) -> dict:
    if not samples:
        return {"n_samples": 0}

    fault_samples = [s for s in samples if s.expected_incident_id is not None]
    negative_samples = [s for s in samples if s.expected_incident_id is None]

    by_scenario: dict[str, dict] = {}
    for scenario_name in sorted({s.scenario_name for s in samples}):
        scenario_samples = [s for s in samples if s.scenario_name == scenario_name]
        by_scenario[scenario_name] = {
            "n_samples": len(scenario_samples),
            "precision_at_1": sum(s.correct_top1 for s in scenario_samples) / len(scenario_samples),
        }

    return {
        "n_samples": len(samples),
        "precision_at_1_overall": sum(s.correct_top1 for s in samples) / len(samples),
        "precision_at_1_fault_runs": (sum(s.correct_top1 for s in fault_samples) / len(fault_samples)) if fault_samples else None,
        "recall_at_topk_fault_runs": (sum(s.expected_in_topk for s in fault_samples) / len(fault_samples)) if fault_samples else None,
        "false_positive_rate_negative_control": (1 - sum(s.correct_top1 for s in negative_samples) / len(negative_samples)) if negative_samples else None,
        "by_scenario": by_scenario,
    }
