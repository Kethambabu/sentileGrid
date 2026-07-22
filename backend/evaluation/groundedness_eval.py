"""Groundedness / citation-validity (CLAUDE.md §7.10, §10): every cited
chunk_id in a risk assessment must actually be one of the chunks that was
retrieved for it — a citation pointing at nothing retrieved is a fabricated
citation, independent of whether the surrounding text is otherwise sound.
"""

from __future__ import annotations

from .collect_assessments import HoldoutAssessment


def evaluate_groundedness(assessments: list[HoldoutAssessment]) -> dict:
    details = []
    for a in assessments:
        available = {m.chunk_id for m in a.retrieval_outcome.matches}
        cited = set(a.risk_assessment.cited_chunk_ids)
        if not cited:
            # No citation is only "grounded" if there was genuinely nothing
            # groundable — i.e. a novel condition — not merely convenient.
            grounded = a.risk_assessment.is_novel_condition
        else:
            grounded = cited.issubset(available)
        details.append({
            "scenario_name": a.scenario_name, "seed": a.seed, "record_index": a.record_index,
            "cited_chunk_ids": sorted(cited), "available_chunk_ids": sorted(available), "grounded": grounded,
        })

    score = sum(d["grounded"] for d in details) / len(details) if details else None
    return {"groundedness_score": score, "n_samples": len(details), "details": details}


def evaluate_explanation_citation_completeness(assessments: list[HoldoutAssessment]) -> dict:
    """CLAUDE.md §10 'explainability score (citation completeness)': for
    non-novel assessments with retrieved evidence available, does the
    Explanation Agent's narrative cite at least one of it?"""
    applicable = [a for a in assessments if not a.retrieval_outcome.is_novel_condition and a.retrieval_outcome.matches]
    cited_count = sum(1 for a in applicable if a.explanation.cited_chunk_ids)
    score = cited_count / len(applicable) if applicable else None
    return {"citation_completeness_score": score, "n_applicable": len(applicable), "n_cited": cited_count}
