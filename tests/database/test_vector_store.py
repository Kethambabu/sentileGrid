from backend.database.vector_store import COLLECTION_NAMES, add_chunks, get_client, get_or_create_collections, query, reset_collections


def test_get_or_create_collections_creates_all_three(tmp_path):
    client = get_client(persist_directory=tmp_path / "chroma")
    collections = get_or_create_collections(client)
    assert set(collections.keys()) == set(COLLECTION_NAMES)


def test_add_and_query_round_trip(tmp_path):
    client = get_client(persist_directory=tmp_path / "chroma")
    collections = get_or_create_collections(client)

    add_chunks(
        collections["documents"],
        ids=["a", "b"],
        embeddings=[[1.0, 0.0], [0.0, 1.0]],
        documents=["reactor pressure rising", "unrelated text"],
        metadatas=[{"source_type": "sop"}, {"source_type": "msds"}],
    )
    assert collections["documents"].count() == 2

    result = query(collections["documents"], embedding=[0.9, 0.1], n_results=1)
    assert result["ids"][0][0] == "a"


def test_reset_collections_clears_existing_data(tmp_path):
    client = get_client(persist_directory=tmp_path / "chroma")
    collections = get_or_create_collections(client)
    add_chunks(collections["documents"], ["x"], [[1.0, 0.0]], ["text"], [{"source_type": "sop"}])
    assert collections["documents"].count() == 1

    reset = reset_collections(client)
    assert reset["documents"].count() == 0


def test_query_with_metadata_filter(tmp_path):
    client = get_client(persist_directory=tmp_path / "chroma")
    collections = get_or_create_collections(client)
    add_chunks(
        collections["fast_windows"],
        ids=["w1", "w2"],
        embeddings=[[1.0, 0.0], [1.0, 0.0]],
        documents=["window A", "window B"],
        metadatas=[{"equipment_zone": "reactor"}, {"equipment_zone": "separator"}],
    )
    result = query(collections["fast_windows"], embedding=[1.0, 0.0], n_results=5, where={"equipment_zone": "reactor"})
    assert result["ids"][0] == ["w1"]
