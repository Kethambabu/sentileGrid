from backend.rag.hybrid_retrieval import FusedResult
from backend.rag.reranker import Reranker


def _fused(chunk_id: str, text: str) -> FusedResult:
    return FusedResult(chunk_id=chunk_id, fused_score=0.0, dense_similarity=0.5, bm25_score=1.0, text=text, metadata={})


def test_rerank_orders_by_relevance_to_query():
    reranker = Reranker()
    candidates = [
        _fused("relevant", "The reactor cooling water valve is sticking and responding erratically to control commands."),
        _fused("irrelevant", "Quarterly parking pass renewal instructions for office staff."),
    ]
    ranked = reranker.rerank("cooling water valve sticking", candidates, top_n=2)
    assert ranked[0][0].chunk_id == "relevant"
    assert ranked[0][1] > ranked[1][1]


def test_rerank_respects_top_n():
    reranker = Reranker()
    candidates = [_fused(f"c{i}", f"document number {i} about reactor pressure") for i in range(5)]
    ranked = reranker.rerank("reactor pressure", candidates, top_n=2)
    assert len(ranked) == 2


def test_rerank_empty_candidates():
    reranker = Reranker()
    assert reranker.rerank("query", [], top_n=3) == []
