"""Live retrieval driver implementing CLAUDE.md §7.4's exact sequence:

- Records 1-4: not enough for a fast window — no retrieval.
- Record 5 onward (until 20): fast-window-only comparison against every
  chunk's fast window, via the fast_windows collection's ANN index.
- Record 20 onward: fast+slow combined — a chunk counts as a strong match
  only when BOTH windows line up well (§7.4), so a match must appear in
  both the fast_windows and slow_windows top results to be reported at all.
- §7.5: confidence is capped at "moderate" during the fast-only phase, even
  on a high raw similarity score, since less context is available.
- §9.2/§14: below the novelty threshold, report "novel condition" rather
  than forcing a match — this retriever surfaces that as
  RetrievalOutcome.is_novel_condition; it is the Compound-Risk Agent's job
  (Phase 4) to refuse to guess a risk score when this is set, not this
  module's, but the flag has to originate here where the similarity score
  is actually known.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from ..database.vector_store import get_client, get_or_create_collections
from ..simulation.models import SimulationRecord
from ..utils.config_loader import load_yaml_config
from .bm25_index import BM25Index
from .chunker import window_to_text
from .embedder import Embedder
from .hybrid_retrieval import FusedResult, hybrid_query
from .reranker import Reranker
from .windowing import FAST_WINDOW_SIZE, SLOW_WINDOW_SIZE, window_pair_at

DEFAULT_RETRIEVAL_CONFIG_PATH = None  # resolved lazily below to avoid a hard import-time file dependency


def _config_path():
    from pathlib import Path

    return Path(__file__).resolve().parents[2] / "backend" / "config" / "retrieval.yaml"


def load_retrieval_config() -> dict:
    return load_yaml_config(_config_path())


class RetrievalPhase(str, Enum):
    NO_RETRIEVAL = "no_retrieval"
    FAST_ONLY = "fast_only"
    FAST_AND_SLOW = "fast_and_slow"


class ConfidenceLevel(str, Enum):
    NONE = "none"
    NOVEL = "novel"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class RetrievalMatch(BaseModel):
    chunk_id: str
    incident_id: str | None = None
    scenario_type: str | None = None
    equipment_zone: str | None = None
    risk_level: str | None = None
    stage: str | None = None
    fast_similarity: float | None = None
    slow_similarity: float | None = None
    combined_similarity: float
    narrative_text: str | None = None


class RetrievalOutcome(BaseModel):
    phase: RetrievalPhase
    is_novel_condition: bool
    confidence: ConfidenceLevel
    matches: list[RetrievalMatch]


def _match_from_fused(result: FusedResult, fast_sim: float | None, slow_sim: float | None, combined: float) -> RetrievalMatch:
    meta = result.metadata
    return RetrievalMatch(
        chunk_id=result.chunk_id,
        incident_id=meta.get("incident_id"),
        scenario_type=meta.get("scenario_type"),
        equipment_zone=meta.get("equipment_zone"),
        risk_level=meta.get("risk_level"),
        stage=meta.get("stage"),
        fast_similarity=fast_sim,
        slow_similarity=slow_sim,
        combined_similarity=combined,
    )


class LiveRetriever:
    def __init__(self, client=None, embedder: Embedder | None = None, reranker: Reranker | None = None, config: dict | None = None) -> None:
        self.client = client or get_client()
        self.collections = get_or_create_collections(self.client)
        self.embedder = embedder or Embedder()
        self.reranker = reranker or Reranker()
        self.config = config or load_retrieval_config()
        self._fast_bm25 = BM25Index.from_collection(self.collections["fast_windows"])
        self._slow_bm25 = BM25Index.from_collection(self.collections["slow_windows"])

    def refresh_bm25_indexes(self) -> None:
        """Call after re-seeding the vector store within the same process —
        the BM25 indexes are built once at construction and don't auto-track
        collection changes."""
        self._fast_bm25 = BM25Index.from_collection(self.collections["fast_windows"])
        self._slow_bm25 = BM25Index.from_collection(self.collections["slow_windows"])

    def _hybrid(self, collection, bm25_index: BM25Index, query_text: str, where: dict | None) -> list[FusedResult]:
        hybrid_cfg = self.config["hybrid"]
        embedding = self.embedder.embed_one(query_text)
        return hybrid_query(
            collection, bm25_index, query_text, embedding,
            dense_top_k=hybrid_cfg["dense_top_k"], bm25_top_k=hybrid_cfg["bm25_top_k"],
            rrf_k=hybrid_cfg["rrf_k"], fused_top_k=hybrid_cfg["fused_top_k"], where=where,
        )

    def _narrative_text(self, incident_id: str, stage: str) -> str | None:
        if not incident_id or not stage:
            return None
        where = {"$and": [{"incident_id": incident_id}, {"stage": stage}]}
        result = self.collections["documents"].get(where=where)
        if not result["ids"]:
            return None
        ordered = sorted(zip(result["ids"], result["documents"]), key=lambda pair: pair[0])
        return " ".join(text for _id, text in ordered)

    def retrieve(self, records: list[SimulationRecord], where: dict | None = None, fetch_narratives: bool = True) -> RetrievalOutcome:
        """`where`: a ChromaDB metadata filter, e.g. {"equipment_zone": "reactor"}.
        Multi-key filters must use Chroma's explicit $and syntax, e.g.
        {"$and": [{"equipment_zone": "reactor"}, {"risk_level": "high"}]}."""
        conf_cfg = self.config["confidence"]
        rerank_top_n = self.config["reranker"]["top_n"]
        n = len(records)

        if n < FAST_WINDOW_SIZE:
            return RetrievalOutcome(phase=RetrievalPhase.NO_RETRIEVAL, is_novel_condition=False, confidence=ConfidenceLevel.NONE, matches=[])

        pair = window_pair_at(records, end_index=n - 1)
        fast_text = window_to_text(pair.fast_records, "fast")
        fast_fused = self._hybrid(self.collections["fast_windows"], self._fast_bm25, fast_text, where)
        fast_reranked = self.reranker.rerank(fast_text, fast_fused, top_n=rerank_top_n)

        if not pair.has_slow_window:
            matches = [
                _match_from_fused(result, fast_sim=result.dense_similarity, slow_sim=None, combined=result.dense_similarity or 0.0)
                for result, _rerank_score in fast_reranked
            ]
            matches.sort(key=lambda m: m.combined_similarity, reverse=True)
            best = matches[0].combined_similarity if matches else -1.0
            is_novel = best < conf_cfg["novel_condition_threshold"]
            confidence = ConfidenceLevel.NOVEL if is_novel else ConfidenceLevel(conf_cfg["fast_only_confidence_cap"])
            outcome_phase = RetrievalPhase.FAST_ONLY
        else:
            slow_text = window_to_text(pair.slow_records, "slow")
            slow_fused = self._hybrid(self.collections["slow_windows"], self._slow_bm25, slow_text, where)
            slow_reranked = self.reranker.rerank(slow_text, slow_fused, top_n=rerank_top_n)

            fast_by_id = {r.chunk_id: r for r, _s in fast_reranked}
            slow_by_id = {r.chunk_id: r for r, _s in slow_reranked}
            common_ids = set(fast_by_id) & set(slow_by_id)

            matches = []
            for chunk_id in common_ids:
                fast_result = fast_by_id[chunk_id]
                slow_result = slow_by_id[chunk_id]
                fast_sim = fast_result.dense_similarity or 0.0
                slow_sim = slow_result.dense_similarity or 0.0
                # "Both parts line up well" (§7.4) -> bind on the weaker of
                # the two, not their average, so one strong + one weak match
                # doesn't get reported as an overall strong match.
                combined = min(fast_sim, slow_sim)
                matches.append(_match_from_fused(fast_result, fast_sim, slow_sim, combined))
            matches.sort(key=lambda m: m.combined_similarity, reverse=True)

            best = matches[0].combined_similarity if matches else -1.0
            is_novel = best < conf_cfg["novel_condition_threshold"]
            if is_novel:
                confidence = ConfidenceLevel.NOVEL
            elif best >= conf_cfg["high_confidence_threshold"]:
                confidence = ConfidenceLevel.HIGH
            else:
                confidence = ConfidenceLevel.MODERATE
            outcome_phase = RetrievalPhase.FAST_AND_SLOW

        if fetch_narratives:
            for match in matches:
                match.narrative_text = self._narrative_text(match.incident_id, match.stage)

        return RetrievalOutcome(phase=outcome_phase, is_novel_condition=is_novel, confidence=confidence, matches=matches)
