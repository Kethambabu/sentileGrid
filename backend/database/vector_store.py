"""ChromaDB client wrapper (CLAUDE.md §5: local, free vector store — never a
paid tier). Three collections, matching the three text streams the RAG
pipeline produces (see rag/chunker.py's docstring for why there are three,
not one): "documents" (SOP/MSDS/incident-narrative text), "fast_windows",
and "slow_windows" (templated descriptions of a window's numeric trend,
keyed by the same chunk_id as their source incident-narrative chunk).

CLAUDE.md §14: the vector index is pre-built and committed (or at least
regenerable via seed_knowledge_base.py) so a restart reloads from disk
instead of re-ingesting live — hence PersistentClient, not an in-memory one.
"""

from __future__ import annotations

from pathlib import Path

import chromadb
from chromadb.api.models.Collection import Collection

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHROMA_DIR = REPO_ROOT / "data" / "chroma_db"

COLLECTION_NAMES = ("documents", "fast_windows", "slow_windows")


def get_client(persist_directory: Path = DEFAULT_CHROMA_DIR) -> chromadb.ClientAPI:
    persist_directory.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(persist_directory))


def get_or_create_collections(client: chromadb.ClientAPI) -> dict[str, Collection]:
    return {name: client.get_or_create_collection(name) for name in COLLECTION_NAMES}


def reset_collections(client: chromadb.ClientAPI) -> dict[str, Collection]:
    existing = {c.name for c in client.list_collections()}
    for name in COLLECTION_NAMES:
        if name in existing:
            client.delete_collection(name)
    return get_or_create_collections(client)


def add_chunks(
    collection: Collection, ids: list[str], embeddings: list[list[float]], documents: list[str], metadatas: list[dict]
) -> None:
    if not ids:
        return
    collection.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)


def query(collection: Collection, embedding: list[float], n_results: int = 5, where: dict | None = None):
    return collection.query(query_embeddings=[embedding], n_results=n_results, where=where)
