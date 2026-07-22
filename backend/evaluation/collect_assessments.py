"""Runs the real agent pipeline (Trend -> Retrieval -> Compound-Risk ->
Compliance -> Explanation) over held-out runs at checkpoints matched to
each seed incident's own authored stage progression, producing samples that
groundedness_eval.py, judge_eval.py, risk_accuracy_eval.py, and
latency_eval.py all consume — one real LLM-call pass shared across every
metric that needs one, not a separate pass per metric.

Checkpoint selection: for a fault-type holdout run, the checkpoints are the
SAME fractional positions (record_index / total_records) as the seed
incident's own authored early_warning/mid_escalation/critical stages,
applied to the holdout run's own length — so risk_accuracy_eval can use the
incident author's own risk_level judgment as ground truth at an analogous
point in an unrelated (held-out) trajectory of the same fault.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..agents.compliance_agent import ComplianceAgent
from ..agents.compound_risk_agent import CompoundRiskAgent
from ..agents.explanation_agent import ExplanationAgent
from ..agents.models import ComplianceResult, ExplanationResult, RiskAssessment
from ..agents.retrieval_agent import RetrievalAgent
from ..agents.trend_agent import TrendAgent
from ..rag.loaders.incident_loader import load_incidents_from_dir
from ..rag.loaders.simulation_run_loader import SIMULATION_RUNS_DIR, load_simulation_records
from ..rag.retriever import LiveRetriever, RetrievalOutcome
from ..rag.seed_knowledge_base import INCIDENTS_DIR
from ..rag.windowing import FAST_WINDOW_SIZE
from ..utils.llm_router import LLMRouter, ReasoningServiceUnavailableError
from .generate_holdout_runs import HOLDOUT_DIR

REPO_ROOT = Path(__file__).resolve().parents[2]

BASELINE_CHECKPOINT_FRACTIONS = (0.5, 0.9)

logger = logging.getLogger(__name__)


@dataclass
class HoldoutAssessment:
    scenario_name: str
    seed: int
    record_index: int
    total_records: int
    t_hours: float
    expected_incident_id: str | None
    expected_risk_level: str | None  # from the seed incident's own authored stage label; None for baseline
    retrieval_outcome: RetrievalOutcome
    risk_assessment: RiskAssessment
    compliance_result: ComplianceResult
    explanation: ExplanationResult


def _stage_checkpoints(scenario_name: str, holdout_total_records: int) -> list[tuple[int, str | None]]:
    incidents = {i.incident_id: i for i in load_incidents_from_dir(INCIDENTS_DIR)}
    incident = incidents.get(scenario_name)
    if incident is None:
        return [(max(FAST_WINDOW_SIZE - 1, int(round(f * (holdout_total_records - 1)))), None) for f in BASELINE_CHECKPOINT_FRACTIONS]

    seed_records = load_simulation_records(SIMULATION_RUNS_DIR / incident.source_simulation_run)
    seed_total = len(seed_records)
    checkpoints = []
    for stage in incident.stages:
        fraction = stage.record_index / (seed_total - 1)
        holdout_index = min(max(FAST_WINDOW_SIZE - 1, int(round(fraction * (holdout_total_records - 1)))), holdout_total_records - 1)
        checkpoints.append((holdout_index, stage.risk_level))
    return checkpoints


def load_manifest() -> list[dict]:
    manifest_path = HOLDOUT_DIR / "manifest.csv"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No holdout manifest at {manifest_path} — run generate_holdout_runs.py first.")
    return pd.read_csv(manifest_path).to_dict("records")


def collect_holdout_assessments(llm_router: LLMRouter | None = None, retriever: LiveRetriever | None = None, manifest: list[dict] | None = None) -> list[HoldoutAssessment]:
    manifest = manifest if manifest is not None else load_manifest()
    router = llm_router or LLMRouter()
    live_retriever = retriever or LiveRetriever()

    trend_agent = TrendAgent()
    retrieval_agent = RetrievalAgent(retriever=live_retriever)
    compound_risk_agent = CompoundRiskAgent(router=router)
    compliance_agent = ComplianceAgent(router=router, client=live_retriever.client)
    explanation_agent = ExplanationAgent(router=router)

    results: list[HoldoutAssessment] = []
    for spec in manifest:
        expected_incident_id = spec["expected_incident_id"]
        if pd.isna(expected_incident_id):
            expected_incident_id = None
        records = load_simulation_records(REPO_ROOT / spec["csv_path"])
        checkpoints = _stage_checkpoints(spec["scenario_name"], len(records))

        for end_index, expected_risk_level in checkpoints:
            window = records[: end_index + 1]
            trend = trend_agent.compute(window)
            outcome = retrieval_agent.retrieve(window)
            run_id = f"eval-{spec['scenario_name']}-{spec['seed']}-{end_index}"

            try:
                risk = compound_risk_agent.assess(trend.features, outcome, run_id=run_id)
                compliance = compliance_agent.review(risk.recommended_action)
                explanation = explanation_agent.explain(risk, outcome, compliance)
            except ReasoningServiceUnavailableError as exc:
                # CLAUDE.md §14: fail visibly, not silently — but one
                # checkpoint hitting exhausted free-tier quota shouldn't
                # discard every other real sample already collected. Skip
                # this checkpoint, log it clearly, keep going.
                logger.warning("Skipping checkpoint %s: reasoning service unavailable: %s", run_id, exc)
                continue

            results.append(
                HoldoutAssessment(
                    scenario_name=spec["scenario_name"], seed=int(spec["seed"]), record_index=end_index,
                    total_records=len(records), t_hours=window[-1].t_hours, expected_incident_id=expected_incident_id,
                    expected_risk_level=expected_risk_level, retrieval_outcome=outcome, risk_assessment=risk,
                    compliance_result=compliance, explanation=explanation,
                )
            )
    return results
