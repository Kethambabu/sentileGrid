"""Phase 6 evaluation harness orchestrator (CLAUDE.md §10). Run:
    python -m backend.evaluation.run_eval
Every number in the resulting report comes from an actual run of this
script against real held-out data and real LLM calls — no placeholders.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..rag.retriever import LiveRetriever
from ..utils.llm_router import LLMRouter
from .collect_assessments import collect_holdout_assessments, load_manifest
from .groundedness_eval import evaluate_explanation_citation_completeness, evaluate_groundedness
from .judge_eval import evaluate_hallucination_rate
from .latency_eval import evaluate_latency
from .retrieval_eval import evaluate_retrieval, summarize as summarize_retrieval
from .risk_accuracy_eval import evaluate_risk_accuracy

REPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "evaluation" / "reports"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run_evaluation() -> dict:
    manifest = load_manifest()
    retriever = LiveRetriever()
    router = LLMRouter()

    logger.info("Running retrieval precision/recall over held-out runs (no LLM calls)...")
    retrieval_samples = evaluate_retrieval(retriever, manifest=manifest, sample_every=10)
    retrieval_summary = summarize_retrieval(retrieval_samples)

    logger.info("Collecting real agent-pipeline assessments over held-out checkpoints (real LLM calls)...")
    assessments = collect_holdout_assessments(llm_router=router, retriever=retriever, manifest=manifest)

    logger.info("Evaluating groundedness / citation validity...")
    groundedness = evaluate_groundedness(assessments)
    citation_completeness = evaluate_explanation_citation_completeness(assessments)

    logger.info("Evaluating hallucination rate via cross-tier LLM judge...")
    hallucination = evaluate_hallucination_rate(assessments)

    logger.info("Evaluating risk accuracy against authored ground truth...")
    risk_accuracy = evaluate_risk_accuracy(assessments)

    logger.info("Aggregating latency...")
    latency = evaluate_latency(assessments)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_holdout_runs": len(manifest),
        "n_assessment_samples": len(assessments),
        "retrieval": retrieval_summary,
        "groundedness": groundedness,
        "citation_completeness": citation_completeness,
        "hallucination": hallucination,
        "risk_accuracy": risk_accuracy,
        "latency": latency,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"eval_report_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info("Wrote report to %s", report_path)

    _print_summary(report)
    return report


def _print_summary(report: dict) -> None:
    print("\n=== SentinelGrid Evaluation Report ===")
    print(f"Holdout runs: {report['n_holdout_runs']}  |  Assessment samples: {report['n_assessment_samples']}")
    r = report["retrieval"]
    print(f"\nRetrieval - precision@1 (fault runs): {r.get('precision_at_1_fault_runs')}")
    print(f"Retrieval - recall@topK (fault runs): {r.get('recall_at_topk_fault_runs')}")
    print(f"Retrieval - false positive rate (negative control): {r.get('false_positive_rate_negative_control')}")
    print(f"\nGroundedness score: {report['groundedness']['groundedness_score']}")
    print(f"Citation completeness: {report['citation_completeness']['citation_completeness_score']}")
    h = report["hallucination"]
    print(f"\nHallucination rate (cross-tier judged): {h['hallucination_rate']}  ({h['n_judged']}/{h['n_samples']} judged, {h['n_unavailable_reasoning_service']} unavailable)")
    print(f"Cross-tier judging verified (no self-grading): {h['cross_tier_judging_verified']}")
    print(f"\nRisk accuracy: {report['risk_accuracy']['risk_accuracy']}")
    latency_means = {k: (v["mean_ms"] if v else None) for k, v in report["latency"].items()}
    print(f"\nLatency (mean ms): {json.dumps(latency_means, indent=2)}")


if __name__ == "__main__":
    run_evaluation()
