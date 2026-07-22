"""Retrieval Agent (CLAUDE.md §6): thin wrapper around the Phase 3
LiveRetriever. No chat-LLM call — ranking comes from embeddings + the
cross-encoder reranker, not a generative model.
"""

from __future__ import annotations

from ..rag.retriever import LiveRetriever, RetrievalOutcome
from ..simulation.models import SimulationRecord


class RetrievalAgent:
    def __init__(self, retriever: LiveRetriever | None = None) -> None:
        self.retriever = retriever or LiveRetriever()

    def retrieve(self, records: list[SimulationRecord], equipment_zone: str | None = None) -> RetrievalOutcome:
        where = {"equipment_zone": equipment_zone} if equipment_zone else None
        return self.retriever.retrieve(records, where=where)
