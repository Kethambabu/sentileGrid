"""End-to-end Phase 2 verification: seed a temp vector store from the real
knowledge base content and confirm it's queryable and produces sensible
matches — this is the "verify realistic output" check for Phase 2.
"""

from backend.database.vector_store import get_client, get_or_create_collections, query
from backend.rag.embedder import Embedder
from backend.rag.seed_knowledge_base import seed


def test_seed_populates_all_three_collections(tmp_path):
    counts = seed(reset=True, persist_directory=tmp_path / "chroma")

    assert counts["documents"] > 0  # SOPs + MSDS + incident narratives
    assert counts["fast_windows"] == 15  # 5 incidents x 3 stages
    # 14, not 15: compressor_feed_pressure_loss's early_warning stage is at
    # record_index=10 (<20), so it has no slow window yet — expected per
    # CLAUDE.md §7.4, not every stage has one.
    assert counts["slow_windows"] == 14


def test_seeded_documents_are_semantically_queryable(tmp_path):
    seed(reset=True, persist_directory=tmp_path / "chroma")
    client = get_client(persist_directory=tmp_path / "chroma")
    collections = get_or_create_collections(client)
    embedder = Embedder()

    query_vector = embedder.embed_one("reactor cooling water valve behaving erratically")
    result = query(collections["documents"], embedding=query_vector, n_results=3)

    assert len(result["ids"][0]) == 3
    matched_sources = [m["source_name"] for m in result["metadatas"][0]]
    assert any("cw_valve_stiction" in s or "cooling_water" in s for s in matched_sources)


def test_seeded_fast_windows_distinguish_incident_types(tmp_path):
    seed(reset=True, persist_directory=tmp_path / "chroma")
    client = get_client(persist_directory=tmp_path / "chroma")
    collections = get_or_create_collections(client)

    result = collections["fast_windows"].get(where={"scenario_type": "feed_supply_loss"})
    assert len(result["ids"]) == 3  # 3 stages of the a_feed_loss incident
    assert all(m["scenario_type"] == "feed_supply_loss" for m in result["metadatas"])
