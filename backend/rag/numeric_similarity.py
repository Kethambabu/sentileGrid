"""Numeric feature-vector similarity — the supplementary channel named in
backend/config/retrieval.yaml's documented retrieval-generalization-gap
finding: text-embedding cosine similarity on templated window text doesn't
discriminate a real match from a wrong one (scores compress into a ~1%-wide
band near 1.0 regardless of correctness), so the novel-condition/confidence
gate needs a signal that attacks the root cause instead of working around it.

Vectors here are chunker.compute_feature_vector's threshold-normalized
deviation-from-baseline values, not raw embeddings — RMS distance (not
cosine) is used because these vectors are legitimately near-zero for
baseline/normal windows, where cosine similarity is undefined or unstable.
"""

from __future__ import annotations


def vector_similarity(a: list[float], b: list[float]) -> float:
    """1.0 for identical vectors, decreasing smoothly as RMS distance grows.
    Never negative, never undefined for a zero vector (unlike cosine)."""
    if len(a) != len(b):
        raise ValueError(f"vector_similarity expected equal-length vectors, got {len(a)} and {len(b)}")
    if not a:
        return 1.0
    mean_sq_diff = sum((x - y) ** 2 for x, y in zip(a, b)) / len(a)
    rms_distance = mean_sq_diff**0.5
    return 1.0 / (1.0 + rms_distance)
