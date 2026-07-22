import sqlite3

import pytest

from backend.database.audit import AuditEntryInput, AuditWriteQueue, GENESIS_HASH, verify_chain


@pytest.fixture()
def audit_queue(tmp_path):
    q = AuditWriteQueue(db_path=tmp_path / "audit.sqlite3")
    yield q
    q.stop()


def test_first_row_chains_from_genesis(audit_queue):
    row = audit_queue.submit(AuditEntryInput(event_type="risk_assessment", agent_name="compound_risk_agent", payload={"risk_score": 42}))
    assert row.prev_hash == GENESIS_HASH
    assert row.row_hash != GENESIS_HASH


def test_rows_chain_sequentially(audit_queue):
    row1 = audit_queue.submit(AuditEntryInput(event_type="risk_assessment", payload={"a": 1}))
    row2 = audit_queue.submit(AuditEntryInput(event_type="risk_assessment", payload={"a": 2}))
    assert row2.prev_hash == row1.row_hash


def test_human_decision_requires_operator_id(audit_queue):
    with pytest.raises(ValueError):
        audit_queue.submit(AuditEntryInput(event_type="human_decision", payload={"status": "approved"}))


def test_human_decision_with_operator_id_succeeds(audit_queue):
    row = audit_queue.submit(AuditEntryInput(event_type="human_decision", operator_id="operator-42", payload={"status": "approved"}))
    assert row.operator_id == "operator-42"


def test_verify_chain_passes_on_untampered_log(audit_queue, tmp_path):
    for i in range(5):
        audit_queue.submit(AuditEntryInput(event_type="risk_assessment", payload={"i": i}))
    audit_queue.stop()

    result = verify_chain(tmp_path / "audit.sqlite3")
    assert result.ok is True
    assert result.rows_checked == 5


def test_verify_chain_detects_altered_payload(audit_queue, tmp_path):
    for i in range(3):
        audit_queue.submit(AuditEntryInput(event_type="risk_assessment", payload={"i": i}))
    audit_queue.stop()

    db_path = tmp_path / "audit.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE audit_log SET payload = ? WHERE id = 2", ('{"i": 999}',))
    conn.commit()
    conn.close()

    result = verify_chain(db_path)
    assert result.ok is False
    assert result.first_broken_id == 2
    assert "row_hash" in result.reason


def test_verify_chain_detects_deleted_row(audit_queue, tmp_path):
    for i in range(3):
        audit_queue.submit(AuditEntryInput(event_type="risk_assessment", payload={"i": i}))
    audit_queue.stop()

    db_path = tmp_path / "audit.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM audit_log WHERE id = 2")
    conn.commit()
    conn.close()

    result = verify_chain(db_path)
    assert result.ok is False  # row 3's prev_hash no longer matches row 1's row_hash


def test_verify_chain_on_empty_log(tmp_path):
    q = AuditWriteQueue(db_path=tmp_path / "empty.sqlite3")
    q.submit(AuditEntryInput(event_type="risk_assessment", payload={}))  # ensure schema exists
    q.stop()
    conn = sqlite3.connect(tmp_path / "empty.sqlite3")
    conn.execute("DELETE FROM audit_log")
    conn.commit()
    conn.close()

    result = verify_chain(tmp_path / "empty.sqlite3")
    assert result.ok is True
    assert result.rows_checked == 0
