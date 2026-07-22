from backend.rag.embedder import Embedder


def test_embed_returns_normalized_vectors_of_expected_dimension():
    embedder = Embedder()
    vectors = embedder.embed(["reactor pressure trending upward", "cooling water valve sticking"])
    assert len(vectors) == 2
    assert len(vectors[0]) == 384  # bge-small-en-v1.5 dimensionality
    norm = sum(v * v for v in vectors[0]) ** 0.5
    assert abs(norm - 1.0) < 1e-3  # normalize_embeddings=True


def test_embed_empty_list_returns_empty():
    embedder = Embedder()
    assert embedder.embed([]) == []


def test_embed_one():
    embedder = Embedder()
    vector = embedder.embed_one("reactor temperature stable")
    assert len(vector) == 384


def test_similar_texts_are_closer_than_dissimilar_ones():
    embedder = Embedder()
    a, b, c = embedder.embed(
        [
            "reactor pressure and temperature rising together",
            "reactor pressure and temperature climbing steadily",
            "unrelated administrative memo about parking passes",
        ]
    )

    def cosine(x, y):
        return sum(xi * yi for xi, yi in zip(x, y))  # vectors are normalized

    assert cosine(a, b) > cosine(a, c)
