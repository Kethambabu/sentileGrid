"""BM25 keyword index, the sparse half of CLAUDE.md §7.6's hybrid retrieval
(dense embeddings + BM25 keyword, merged). One index per ChromaDB
collection's contents — built from the same (id, text) pairs stored there,
so dense and sparse search always operate over an identical candidate set.
"""

from __future__ import annotations

import re

from rank_bm25 import BM25Okapi

_TOKEN_RE = re.compile(r"[a-z]+|\d+\.\d+|\d+")


def tokenize(text: str) -> list[str]:
    """Word tokens, plus decimal numbers kept whole (not split at '.') —
    "2942.076" tokenizes as one token, not "2942" + "076". Matters
    specifically for the RAG window-matching corpus (see chunker.py's
    window_to_text), where splitting decimals turned every number into a
    near-unique fragment that almost never coincided between independent
    noise realizations of the same trend."""
    return _TOKEN_RE.findall(text.lower())


class BM25Index:
    def __init__(self, ids: list[str], texts: list[str]) -> None:
        if len(ids) != len(texts):
            raise ValueError("ids and texts must be the same length")
        self.ids = ids
        self._tokenized = [tokenize(t) for t in texts]
        self._bm25 = BM25Okapi(self._tokenized) if texts else None

    def query(self, text: str, top_k: int = 10) -> list[tuple[str, float]]:
        if self._bm25 is None:
            return []
        scores = self._bm25.get_scores(tokenize(text))
        ranked = sorted(zip(self.ids, scores), key=lambda pair: pair[1], reverse=True)
        return [(chunk_id, score) for chunk_id, score in ranked[:top_k] if score > 0]

    @classmethod
    def from_collection(cls, collection) -> "BM25Index":
        """Build directly from a ChromaDB collection's current contents."""
        data = collection.get()
        return cls(ids=data["ids"], texts=data["documents"])
