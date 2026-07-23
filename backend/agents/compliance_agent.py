"""Compliance Agent (CLAUDE.md §6): checks the Compound-Risk Agent's
recommended first-line action against retrieved SOP evidence, tagging it
approved/flagged with cited procedure. Queries the RAG "documents"
collection directly (filtered to source_type=sop), not the incident-window
LiveRetriever — a proposed action needs procedural precedent, not a
sensor-window match.
"""

from __future__ import annotations

import json

from ..database.vector_store import get_client, get_or_create_collections
from ..rag.bm25_index import BM25Index
from ..rag.embedder import Embedder
from ..rag.hybrid_retrieval import hybrid_query
from ..rag.prompt_builder import REFERENCE_DATA_PREAMBLE, build_reference_data_block_from_chunks, sanitize
from ..utils.llm_router import LLMMessage, LLMRequest, LLMRouter, ReasoningServiceUnavailableError
from .models import ComplianceResult

TASK_INSTRUCTION = """You are the Compliance Agent for SentinelGrid, an industrial safety monitoring system. You are given a proposed first-line action and relevant SOP excerpts (in the reference_data block). Determine whether the action is consistent with documented procedure.

Respond with ONLY a JSON object, no other text, matching exactly this schema:
{
  "approved": <true or false>,
  "cited_sop_chunk_ids": [<string chunk_id from reference_data that supports your decision>, ...],
  "notes": <string: 1-3 sentences citing the specific SOP guidance>
}

If no relevant SOP was retrieved (the reference_data block is empty or says so), set approved to false and explain in notes that this action lacks documented procedural support — do not approve an action you have no cited basis for."""


class ComplianceAgent:
    def __init__(self, router: LLMRouter | None = None, client=None, embedder: Embedder | None = None) -> None:
        self.router = router or LLMRouter()
        self.client = client or get_client()
        self.collections = get_or_create_collections(self.client)
        self.embedder = embedder or Embedder()
        self._documents_bm25 = BM25Index.from_collection(self.collections["documents"])

    def refresh_bm25_index(self) -> None:
        self._documents_bm25 = BM25Index.from_collection(self.collections["documents"])

    def review(self, recommended_action: str) -> ComplianceResult:
        embedding = self.embedder.embed_one(recommended_action)
        fused = hybrid_query(
            self.collections["documents"], self._documents_bm25, recommended_action, embedding,
            where={"source_type": "sop"}, fused_top_k=3,
        )
        chunks = [(r.chunk_id, r.text) for r in fused]
        block = build_reference_data_block_from_chunks(chunks, empty_note="(No relevant SOP found for this action.)")

        prompt = "\n".join(
            [TASK_INSTRUCTION, "", f"Proposed action: {sanitize(recommended_action)}", "", REFERENCE_DATA_PREAMBLE, block]
        )
        try:
            response = self.router.complete(
                LLMRequest(messages=[LLMMessage(role="user", content=prompt)], temperature=0.1, max_tokens=400, json_mode=True)
            )
        except ReasoningServiceUnavailableError:
            return ComplianceResult(
                action_reviewed=recommended_action,
                approved=False,
                cited_sop_chunk_ids=[],
                notes="Reasoning service unavailable — both LLM tiers failed; action not approved pending manual review.",
                llm_tier_used="unavailable",
                latency_ms=0.0,
                reasoning_unavailable=True,
            )

        parse_error = False
        try:
            parsed = json.loads(response.content)
            approved = bool(parsed.get("approved", False))
            cited = list(parsed.get("cited_sop_chunk_ids", []))
            notes = str(parsed.get("notes", ""))
        except (json.JSONDecodeError, AttributeError, TypeError):
            parse_error = True
            approved = False
            cited = []
            notes = "LLM output could not be parsed as JSON; action not approved pending manual review."

        if not chunks:
            approved = False  # code-level enforcement: never approve with zero cited SOP evidence

        return ComplianceResult(
            action_reviewed=recommended_action, approved=approved, cited_sop_chunk_ids=cited, notes=notes,
            llm_tier_used=response.tier_used.value, latency_ms=response.latency_ms, parse_error=parse_error,
        )
