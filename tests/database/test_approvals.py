import pytest

from backend.database.approvals import ApprovalNotFoundError, ApprovalService, ApprovalStatus
from backend.database.audit import AuditWriteQueue, verify_chain


@pytest.fixture()
def service(tmp_path):
    queue = AuditWriteQueue(db_path=tmp_path / "audit.sqlite3")
    svc = ApprovalService(audit_queue=queue, db_path=tmp_path / "approvals.sqlite3")
    yield svc
    queue.stop()


def test_new_approval_defaults_to_pending(service):
    record = service.create_pending(run_id="run-1", recommendation_summary="reduce reactor feed rate")
    assert record.status == ApprovalStatus.PENDING
    assert record.operator_id is None


def test_decide_requires_operator_id(service):
    record = service.create_pending(run_id="run-1", recommendation_summary="x")
    service.mark_evidence_viewed(record.approval_id)
    with pytest.raises(ValueError):
        service.decide(record.approval_id, ApprovalStatus.APPROVED, operator_id="")


def test_decide_rejects_pending_as_a_decision(service):
    record = service.create_pending(run_id="run-1", recommendation_summary="x")
    service.mark_evidence_viewed(record.approval_id)
    with pytest.raises(ValueError):
        service.decide(record.approval_id, ApprovalStatus.PENDING, operator_id="op-1")


def test_decide_requires_evidence_viewed_first(service):
    """CLAUDE.md §14 alert-fatigue fix: no reflexive-click approvals."""
    record = service.create_pending(run_id="run-1", recommendation_summary="x")
    with pytest.raises(ValueError):
        service.decide(record.approval_id, ApprovalStatus.APPROVED, operator_id="op-1")


def test_decide_succeeds_after_viewing_evidence(service):
    record = service.create_pending(run_id="run-1", recommendation_summary="x")
    service.mark_evidence_viewed(record.approval_id)
    decided = service.decide(record.approval_id, ApprovalStatus.APPROVED, operator_id="op-1")
    assert decided.status == ApprovalStatus.APPROVED
    assert decided.operator_id == "op-1"
    assert decided.decided_at is not None


def test_decision_is_written_to_audit_log_with_operator_id(service, tmp_path):
    record = service.create_pending(run_id="run-1", recommendation_summary="x")
    service.mark_evidence_viewed(record.approval_id)
    service.decide(record.approval_id, ApprovalStatus.REJECTED, operator_id="op-99")
    service.audit_queue.stop()

    result = verify_chain(tmp_path / "audit.sqlite3")
    assert result.ok is True
    assert result.rows_checked == 1


def test_resolve_or_pending_returns_pending_for_unknown_approval(service):
    """CLAUDE.md §9: approval disconnect -> default to pending, never approved."""
    assert service.resolve_or_pending("does-not-exist") == ApprovalStatus.PENDING


def test_resolve_or_pending_returns_pending_on_lookup_failure(service, monkeypatch):
    record = service.create_pending(run_id="run-1", recommendation_summary="x")

    def broken_connect():
        raise ConnectionError("simulated dropped database connection")

    monkeypatch.setattr(service, "_connect", broken_connect)
    assert service.resolve_or_pending(record.approval_id) == ApprovalStatus.PENDING


def test_resolve_or_pending_reflects_real_status_when_healthy(service):
    record = service.create_pending(run_id="run-1", recommendation_summary="x")
    service.mark_evidence_viewed(record.approval_id)
    service.decide(record.approval_id, ApprovalStatus.APPROVED, operator_id="op-1")
    assert service.resolve_or_pending(record.approval_id) == ApprovalStatus.APPROVED


def test_get_unknown_approval_raises(service):
    with pytest.raises(ApprovalNotFoundError):
        service.get("nope")


def test_approval_survives_simulated_process_restart(tmp_path):
    """Phase 6's actual point: a pending approval must survive the API
    process restarting, not just a fresh service instance in the same
    process — this is what makes 'disconnect -> pending' a real guarantee
    rather than one that happens to hold only because there was nothing to
    disconnect from (CLAUDE.md §9)."""
    db_path = tmp_path / "approvals.sqlite3"
    queue1 = AuditWriteQueue(db_path=tmp_path / "audit.sqlite3")
    service1 = ApprovalService(audit_queue=queue1, db_path=db_path)
    record = service1.create_pending(run_id="run-1", recommendation_summary="reduce feed rate")
    service1.mark_evidence_viewed(record.approval_id)
    queue1.stop()

    # Simulate a fresh process: new AuditWriteQueue, new ApprovalService,
    # same on-disk db_path.
    queue2 = AuditWriteQueue(db_path=tmp_path / "audit.sqlite3")
    service2 = ApprovalService(audit_queue=queue2, db_path=db_path)
    restored = service2.get(record.approval_id)
    assert restored.status == ApprovalStatus.PENDING
    assert restored.viewed_evidence is True

    decided = service2.decide(record.approval_id, ApprovalStatus.APPROVED, operator_id="op-1")
    assert decided.status == ApprovalStatus.APPROVED
    queue2.stop()
