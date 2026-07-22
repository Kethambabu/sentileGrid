"""Risk accuracy: does the predicted risk score's bucket (low/moderate/high)
match the ground truth for that checkpoint? Ground truth for fault-type
holdout runs is the seed incident's OWN authored risk_level at the
analogous stage (see collect_assessments.py) — a real domain judgment, not
an arbitrary heuristic. Baseline (no-fault) holdout checkpoints have no
authored stage, so ground truth is simply "low".
"""

from __future__ import annotations

from .collect_assessments import HoldoutAssessment

LOW_HIGH_BOUND = 40.0
MODERATE_HIGH_BOUND = 70.0


def _bucket(risk_score: float | None) -> str:
    if risk_score is None:
        return "novel"
    if risk_score < LOW_HIGH_BOUND:
        return "low"
    if risk_score < MODERATE_HIGH_BOUND:
        return "moderate"
    return "high"


def evaluate_risk_accuracy(assessments: list[HoldoutAssessment]) -> dict:
    details = []
    for a in assessments:
        expected = a.expected_risk_level or "low"  # baseline checkpoints: no authored stage -> expect low
        actual_bucket = _bucket(a.risk_assessment.risk_score)
        # A novel-condition call is treated as a defensible non-match, not
        # simply wrong — it means the system correctly declined to force a
        # score, which CLAUDE.md treats as the safe behavior, not a failure.
        correct = actual_bucket == expected
        details.append({
            "scenario_name": a.scenario_name, "seed": a.seed, "record_index": a.record_index,
            "expected_risk_level": expected, "actual_risk_score": a.risk_assessment.risk_score,
            "actual_bucket": actual_bucket, "correct": correct, "is_novel_condition": a.risk_assessment.is_novel_condition,
        })

    accuracy = sum(d["correct"] for d in details) / len(details) if details else None
    return {"risk_accuracy": accuracy, "n_samples": len(details), "details": details}
