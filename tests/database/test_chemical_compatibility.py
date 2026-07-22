import pytest

from backend.database.chemical_compatibility import DEFAULT_CSV_PATH, get_connection, lookup_compatibility


@pytest.fixture(scope="module")
def con():
    connection = get_connection()
    yield connection
    connection.close()


def test_csv_seed_exists():
    assert DEFAULT_CSV_PATH.exists()


def test_lookup_known_pair(con):
    result = lookup_compatibility(con, "A", "D")
    assert result is not None
    assert result["compatible"] is True


def test_lookup_is_order_independent(con):
    forward = lookup_compatibility(con, "A", "D")
    backward = lookup_compatibility(con, "D", "A")
    assert forward["hazard_note"] == backward["hazard_note"]


def test_lookup_flagged_incompatible_pair(con):
    result = lookup_compatibility(con, "D", "E")
    assert result is not None
    assert result["compatible"] is False
    assert "CAUTION" in result["hazard_note"]


def test_lookup_unknown_pair_returns_none(con):
    assert lookup_compatibility(con, "A", "Z") is None
    assert lookup_compatibility(con, "X", "Y") is None
