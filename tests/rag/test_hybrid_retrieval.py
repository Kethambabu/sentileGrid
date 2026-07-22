from backend.database.vector_store import add_chunks, get_client, get_or_create_collections
from backend.rag.bm25_index import BM25Index
from backend.rag.hybrid_retrieval import hybrid_query


def _seed_synthetic_collection(tmp_path):
    client = get_client(persist_directory=tmp_path / "chroma")
    collections = get_or_create_collections(client)
    add_chunks(
        collections["documents"],
        ids=["reactor_hit", "unrelated_a", "unrelated_b"],
        embeddings=[[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]],
        documents=[
            "reactor cooling water valve sticking erratically",
            "unrelated text about parking passes",
            "another unrelated document about weather",
        ],
        metadatas=[
            {"equipment_zone": "reactor", "source_type": "incident_narrative"},
            {"equipment_zone": "admin", "source_type": "sop"},
            {"equipment_zone": "admin", "source_type": "sop"},
        ],
    )
    return collections["documents"]


def test_hybrid_query_ranks_dense_and_bm25_agreement_first(tmp_path):
    collection = _seed_synthetic_collection(tmp_path)
    bm25 = BM25Index.from_collection(collection)

    results = hybrid_query(
        collection, bm25, query_text="reactor cooling water valve sticking",
        query_embedding=[1.0, 0.0], dense_top_k=3, bm25_top_k=3, rrf_k=60, fused_top_k=3,
    )
    assert results[0].chunk_id == "reactor_hit"
    assert results[0].dense_similarity is not None
    assert results[0].bm25_score is not None


def test_hybrid_query_respects_metadata_filter(tmp_path):
    collection = _seed_synthetic_collection(tmp_path)
    bm25 = BM25Index.from_collection(collection)

    results = hybrid_query(
        collection, bm25, query_text="reactor cooling water valve sticking",
        query_embedding=[1.0, 0.0], where={"equipment_zone": "admin"},
    )
    assert all(r.metadata["equipment_zone"] == "admin" for r in results)
    assert "reactor_hit" not in [r.chunk_id for r in results]


def test_hybrid_query_dense_only_match_still_returned(tmp_path):
    """A chunk that matches densely but shares no keywords with the query
    should still surface via the dense half of the fusion."""
    collection = _seed_synthetic_collection(tmp_path)
    bm25 = BM25Index.from_collection(collection)

    results = hybrid_query(
        collection, bm25, query_text="xyzzy plugh zzyzx", query_embedding=[1.0, 0.0],
    )
    ids = [r.chunk_id for r in results]
    assert "reactor_hit" in ids
