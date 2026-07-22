"""Latency per agent call (CLAUDE.md §10), aggregated from the same real
LLM-agent calls collect_assessments.py already made — not a synthetic
benchmark."""

from __future__ import annotations

import statistics

from .collect_assessments import HoldoutAssessment


def evaluate_latency(assessments: list[HoldoutAssessment]) -> dict:
    per_agent: dict[str, list[float]] = {"compound_risk": [], "compliance": [], "explanation": []}
    for a in assessments:
        per_agent["compound_risk"].append(a.risk_assessment.latency_ms)
        per_agent["compliance"].append(a.compliance_result.latency_ms)
        per_agent["explanation"].append(a.explanation.latency_ms)

    summary = {}
    for agent_name, latencies in per_agent.items():
        if not latencies:
            summary[agent_name] = None
            continue
        summary[agent_name] = {
            "n_calls": len(latencies), "mean_ms": statistics.mean(latencies),
            "median_ms": statistics.median(latencies), "max_ms": max(latencies), "min_ms": min(latencies),
        }
    return summary
