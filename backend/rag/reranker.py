"""Cross-encoder reranking (CLAUDE.md §7.7: "re-rank top candidates with a
small cross-encoder before handing to the LLM"). Lazily loads the model on
first use, same rationale as embedder.py.
"""

from __future__ import annotations

from .hybrid_retrieval import FusedResult

DEFAULT_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class Reranker:
    def __init__(self, model_name: str = DEFAULT_MODEL_NAME) -> None:
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
        return self._model

    def rerank(self, query_text: str, candidates: list[FusedResult], top_n: int = 3) -> list[tuple[FusedResult, float]]:
        if not candidates:
            return []
        model = self._load()
        pairs = [(query_text, c.text) for c in candidates]
        scores = model.predict(pairs)
        ranked = sorted(zip(candidates, scores), key=lambda pair: pair[1], reverse=True)
        return [(candidate, float(score)) for candidate, score in ranked[:top_n]]
