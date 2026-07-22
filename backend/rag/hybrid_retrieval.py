"""Merges dense (ChromaDB embedding) search and BM25 keyword search via
reciprocal rank fusion — CLAUDE.md §7.6's "hybrid retrieval: dense + BM25
keyword, merged." Also implements CLAUDE.md §14's "filter by metadata
(zone, equipment type, scenario category) before vector search, not just
raw numeric similarity" — the `where` filter is applied to both the dense
query and, client-side, to BM25 candidates (BM25Okapi has no native
metadata filtering).
"""

from __future__ import annotations

from dataclasses import dataclass

from .bm25_index import BM25Index


@dataclass
class FusedResult:
    chunk_id: str
    fused_score: float
    dense_similarity: float | None  # cosine similarity in [-1, 1], derived from Chroma's L2 distance
    bm25_score: float | None
    text: str
    metadata: dict


def _matches_where(metadata: dict, where: dict | None) -> bool:
    if not where:
        return True
    return all(metadata.get(k) == v for k, v in where.items())


def _l2_distance_to_cosine_similarity(distance: float) -> float:
    """For unit-normalized embeddings, ||a-b||^2 = 2 - 2*cos(a,b)."""
    return 1.0 - distance / 2.0


def hybrid_query(
    collection,
    bm25_index: BM25Index,
    query_text: str,
    query_embedding: list[float],
    dense_top_k: int = 10,
    bm25_top_k: int = 10,
    rrf_k: int = 60,
    fused_top_k: int = 5,
    where: dict | None = None,
) -> list[FusedResult]:
    dense = collection.query(query_embeddings=[query_embedding], n_results=dense_top_k, where=where)
    dense_ids = dense["ids"][0] if dense["ids"] else []
    dense_ranks = {chunk_id: rank for rank, chunk_id in enumerate(dense_ids)}
    dense_texts = dict(zip(dense_ids, dense["documents"][0])) if dense_ids else {}
    dense_metas = dict(zip(dense_ids, dense["metadatas"][0])) if dense_ids else {}
    dense_similarities = {
        chunk_id: _l2_distance_to_cosine_similarity(dist)
        for chunk_id, dist in zip(dense_ids, dense["distances"][0])
    } if dense_ids else {}

    bm25_raw = bm25_index.query(query_text, top_k=bm25_top_k)
    bm25_scores = dict(bm25_raw)
    bm25_ranks = {chunk_id: rank for rank, (chunk_id, _score) in enumerate(bm25_raw)}

    # BM25 candidates need metadata/text fetched (not returned by BM25Index)
    # and filtered by `where`, since BM25Okapi has no native metadata filter.
    bm25_only_ids = [cid for cid in bm25_ranks if cid not in dense_ids]
    extra_texts: dict[str, str] = {}
    extra_metas: dict[str, dict] = {}
    if bm25_only_ids:
        fetched = collection.get(ids=bm25_only_ids)
        extra_texts = dict(zip(fetched["ids"], fetched["documents"]))
        extra_metas = dict(zip(fetched["ids"], fetched["metadatas"]))

    all_ids = set(dense_ranks) | set(bm25_ranks)
    fused: list[FusedResult] = []
    for chunk_id in all_ids:
        metadata = dense_metas.get(chunk_id) or extra_metas.get(chunk_id) or {}
        if not _matches_where(metadata, where):
            continue
        score = 0.0
        if chunk_id in dense_ranks:
            score += 1.0 / (rrf_k + dense_ranks[chunk_id] + 1)
        if chunk_id in bm25_ranks:
            score += 1.0 / (rrf_k + bm25_ranks[chunk_id] + 1)
        text = dense_texts.get(chunk_id) or extra_texts.get(chunk_id) or ""
        fused.append(
            FusedResult(
                chunk_id=chunk_id,
                fused_score=score,
                dense_similarity=dense_similarities.get(chunk_id),
                bm25_score=bm25_scores.get(chunk_id),
                text=text,
                metadata=metadata,
            )
        )

    fused.sort(key=lambda r: r.fused_score, reverse=True)
    return fused[:fused_top_k]
