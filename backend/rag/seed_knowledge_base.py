"""Phase 2 orchestration: load SOPs/MSDS/incidents, chunk, embed, and write
to the vector store. Run directly:

    python -m backend.rag.seed_knowledge_base
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..database.vector_store import DEFAULT_CHROMA_DIR, add_chunks, get_client, get_or_create_collections, reset_collections
from .chunker import build_incident_chunks, chunk_raw_document
from .embedder import Embedder
from .loaders.document_loader import load_documents_from_dir
from .loaders.incident_loader import load_incidents_from_dir
from .loaders.simulation_run_loader import SIMULATION_RUNS_DIR, load_simulation_records

REPO_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = REPO_ROOT / "backend" / "knowledge"
SOPS_DIR = KNOWLEDGE_DIR / "sops"
MSDS_DIR = KNOWLEDGE_DIR / "msds"
INCIDENTS_DIR = KNOWLEDGE_DIR / "incidents"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def seed(reset: bool = True, persist_directory: Path = DEFAULT_CHROMA_DIR) -> dict[str, int]:
    embedder = Embedder()
    client = get_client(persist_directory=persist_directory)
    collections = reset_collections(client) if reset else get_or_create_collections(client)

    doc_ids: list[str] = []
    doc_texts: list[str] = []
    doc_metas: list[dict] = []

    for doc in load_documents_from_dir(SOPS_DIR):
        for chunk in chunk_raw_document(doc, source_type="sop", metadata={"source_name": doc.source_name}):
            doc_ids.append(chunk.chunk_id)
            doc_texts.append(chunk.text)
            doc_metas.append({"source_type": chunk.source_type, "source_name": chunk.source_name, **chunk.metadata})
    logger.info("Loaded %d SOP chunks", len(doc_ids))

    msds_start = len(doc_ids)
    for doc in load_documents_from_dir(MSDS_DIR):
        for chunk in chunk_raw_document(doc, source_type="msds", metadata={"source_name": doc.source_name}):
            doc_ids.append(chunk.chunk_id)
            doc_texts.append(chunk.text)
            doc_metas.append({"source_type": chunk.source_type, "source_name": chunk.source_name, **chunk.metadata})
    logger.info("Loaded %d MSDS chunks", len(doc_ids) - msds_start)

    fast_ids, fast_texts, fast_metas = [], [], []
    slow_ids, slow_texts, slow_metas = [], [], []

    incident_narrative_count = 0
    incidents = load_incidents_from_dir(INCIDENTS_DIR)
    for incident in incidents:
        run_path = SIMULATION_RUNS_DIR / incident.source_simulation_run
        if not run_path.exists():
            raise FileNotFoundError(
                f"Incident '{incident.incident_id}' references simulation run {run_path}, "
                "which doesn't exist — run backend/simulation/run_simulation.py for its scenario first."
            )
        records = load_simulation_records(run_path)
        narrative_chunks, window_chunks = build_incident_chunks(incident, records)

        for chunk in narrative_chunks:
            doc_ids.append(chunk.chunk_id)
            doc_texts.append(chunk.text)
            doc_metas.append({"source_type": chunk.source_type, "source_name": chunk.source_name, **chunk.metadata})
            incident_narrative_count += 1

        for wchunk in window_chunks:
            target_ids, target_texts, target_metas = (fast_ids, fast_texts, fast_metas) if wchunk.window_kind == "fast" else (slow_ids, slow_texts, slow_metas)
            target_ids.append(wchunk.chunk_id)
            target_texts.append(wchunk.text)
            target_metas.append(wchunk.metadata)

    logger.info(
        "Loaded %d incidents -> %d narrative chunks, %d fast windows, %d slow windows",
        len(incidents), incident_narrative_count, len(fast_ids), len(slow_ids),
    )

    logger.info("Embedding %d document chunks...", len(doc_texts))
    doc_embeddings = embedder.embed(doc_texts)
    add_chunks(collections["documents"], doc_ids, doc_embeddings, doc_texts, doc_metas)

    logger.info("Embedding %d fast-window chunks...", len(fast_texts))
    fast_embeddings = embedder.embed(fast_texts)
    add_chunks(collections["fast_windows"], fast_ids, fast_embeddings, fast_texts, fast_metas)

    logger.info("Embedding %d slow-window chunks...", len(slow_texts))
    slow_embeddings = embedder.embed(slow_texts)
    add_chunks(collections["slow_windows"], slow_ids, slow_embeddings, slow_texts, slow_metas)

    counts = {
        "documents": collections["documents"].count(),
        "fast_windows": collections["fast_windows"].count(),
        "slow_windows": collections["slow_windows"].count(),
    }
    logger.info("Seeding complete: %s", counts)
    return counts


if __name__ == "__main__":
    seed()
