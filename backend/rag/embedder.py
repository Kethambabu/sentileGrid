"""Sentence-Transformers embedding wrapper (CLAUDE.md §5: bge-small/base,
not a paid embedding API). Lazily loads the model on first use so importing
this module (or anything that imports it transitively) doesn't pay the
model-load cost for code paths that never actually embed anything.
"""

from __future__ import annotations

DEFAULT_MODEL_NAME = "BAAI/bge-small-en-v1.5"


class Embedder:
    def __init__(self, model_name: str = DEFAULT_MODEL_NAME) -> None:
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return vectors.tolist()

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]
