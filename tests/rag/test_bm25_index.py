from backend.rag.bm25_index import BM25Index, tokenize


def test_tokenize_lowercases_and_strips_punctuation():
    assert tokenize("Reactor Pressure: 2705 kPa!") == ["reactor", "pressure", "2705", "kpa"]


def test_query_ranks_matching_document_first():
    index = BM25Index(
        ids=["a", "b", "c"],
        texts=[
            "reactor cooling water valve sticking erratically",
            "unrelated administrative memo about parking passes",
            "stripper level control loop tuning notes",
        ],
    )
    results = index.query("cooling water valve sticking", top_k=3)
    assert results[0][0] == "a"


def test_query_excludes_zero_score_documents():
    # BM25's IDF term is ~0 (or negative) for a word appearing in half of a
    # 2-document corpus — a real property of the algorithm, not specific to
    # this wrapper — so this needs a large-enough corpus for "reactor
    # pressure" to be a meaningfully rare term.
    texts = ["reactor pressure rising"] + [f"unrelated document number {i} about office logistics" for i in range(10)]
    index = BM25Index(ids=[f"doc{i}" for i in range(len(texts))], texts=texts)
    results = index.query("reactor pressure", top_k=10)
    ids = [r[0] for r in results]
    assert "doc0" in ids
    assert "doc1" not in ids


def test_empty_index_returns_empty_results():
    index = BM25Index(ids=[], texts=[])
    assert index.query("anything") == []


def test_mismatched_lengths_raises():
    import pytest

    with pytest.raises(ValueError):
        BM25Index(ids=["a"], texts=["one", "two"])
