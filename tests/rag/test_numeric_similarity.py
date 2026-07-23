import pytest

from backend.rag.numeric_similarity import vector_similarity


def test_identical_vectors_score_one():
    assert vector_similarity([1.0, -2.0, 3.5], [1.0, -2.0, 3.5]) == 1.0


def test_zero_vectors_score_one():
    assert vector_similarity([0.0, 0.0], [0.0, 0.0]) == 1.0


def test_similarity_decreases_as_distance_grows():
    close = vector_similarity([1.0, 1.0], [1.1, 0.9])
    far = vector_similarity([1.0, 1.0], [10.0, 10.0])
    assert close > far
    assert 0.0 < far < close <= 1.0


def test_empty_vectors_score_one():
    assert vector_similarity([], []) == 1.0


def test_mismatched_length_raises():
    with pytest.raises(ValueError):
        vector_similarity([1.0, 2.0], [1.0])
