"""Human-in-the-loop approval state (CLAUDE.md §2/§9/§14). This is the
backend model the Emergency Agent's "recommend + await approval" contract
terminates at — no code path here or anywhere else may cause the system to
execute a plant action.

Phase 6 ("make the human-approval loop fully real"): persisted to SQLite
(WAL mode) rather than an in-memory dict, so a pending approval survives an
API process restart — a dropped server is exactly the kind of "disconnect"
CLAUDE.md §9 says must resolve to PENDING, and an in-memory store made that
true only by accident (nothing to disconnect FROM). The public contract is
unchanged from the Phase 4 in-memory version, so agents/API routes/tests
didn't need to change.

Two non-negotiable rules, both explicitly required to be tested
(CLAUDE.md §9):
  1. A dropped/failed lookup must resolve to PENDING, never APPROVED —
     see resolve_or_pending().
  2. An approval can't be decided until its evidence has been marked
     viewed — see decide()'s viewed_evidence check (the alert-fatigue fix:
     no reflexive-click approvals).
Every decision is written to the audit log with a specific operator_id,
never a bare approved/rejected flag (CLAUDE.md §14).
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel

from .audit import AuditEntryInput, AuditWriteQueue, get_default_audit_queue

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_APPROVALS_DB_PATH = REPO_ROOT / "data" / "approvals.sqlite3"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalRecord(BaseModel):
    approval_id: str
    run_id: str
    recommendation_summary: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    operator_id: str | None = None
    decided_at: str | None = None
    viewed_evidence: bool = False


class ApprovalNotFoundError(KeyError):
    pass


def _row_to_record(row: tuple) -> ApprovalRecord:
    approval_id, run_id, recommendation_summary, status, operator_id, decided_at, viewed_evidence = row
    return ApprovalRecord(
        approval_id=approval_id, run_id=run_id, recommendation_summary=recommendation_summary,
        status=ApprovalStatus(status), operator_id=operator_id, decided_at=decided_at, viewed_evidence=bool(viewed_evidence),
    )


class ApprovalService:
    def __init__(self, audit_queue: AuditWriteQueue | None = None, db_path: Path = DEFAULT_APPROVALS_DB_PATH) -> None:
        self.audit_queue = audit_queue or get_default_audit_queue()
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS approvals (
                        approval_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        recommendation_summary TEXT NOT NULL,
                        status TEXT NOT NULL,
                        operator_id TEXT,
                        decided_at TEXT,
                        viewed_evidence INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def create_pending(self, run_id: str, recommendation_summary: str) -> ApprovalRecord:
        record = ApprovalRecord(approval_id=str(uuid.uuid4()), run_id=run_id, recommendation_summary=recommendation_summary)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO approvals (approval_id, run_id, recommendation_summary, status, operator_id, decided_at, viewed_evidence) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (record.approval_id, record.run_id, record.recommendation_summary, record.status.value, None, None, 0),
                )
                conn.commit()
            finally:
                conn.close()
        return record

    def mark_evidence_viewed(self, approval_id: str) -> ApprovalRecord:
        with self._lock:
            conn = self._connect()
            try:
                record = self._fetch(conn, approval_id)
                conn.execute("UPDATE approvals SET viewed_evidence = 1 WHERE approval_id = ?", (approval_id,))
                conn.commit()
            finally:
                conn.close()
        record.viewed_evidence = True
        return record

    def decide(self, approval_id: str, status: ApprovalStatus, operator_id: str) -> ApprovalRecord:
        if status == ApprovalStatus.PENDING:
            raise ValueError("decide() cannot be called with PENDING — that's the default state, not a decision")
        if not operator_id:
            raise ValueError("operator_id is required for any approval decision (CLAUDE.md §14)")

        with self._lock:
            conn = self._connect()
            try:
                record = self._fetch(conn, approval_id)
                if not record.viewed_evidence:
                    raise ValueError(
                        "cannot decide on an approval whose evidence/explanation panel has not been viewed "
                        "(CLAUDE.md §14 alert-fatigue fix — no reflexive-click approvals)"
                    )
                decided_at = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "UPDATE approvals SET status = ?, operator_id = ?, decided_at = ? WHERE approval_id = ?",
                    (status.value, operator_id, decided_at, approval_id),
                )
                conn.commit()
            finally:
                conn.close()

        record.status = status
        record.operator_id = operator_id
        record.decided_at = decided_at
        self.audit_queue.submit(
            AuditEntryInput(
                event_type="human_decision",
                run_id=record.run_id,
                operator_id=operator_id,
                payload={"approval_id": approval_id, "status": status.value, "recommendation_summary": record.recommendation_summary},
            )
        )
        return record

    def get(self, approval_id: str) -> ApprovalRecord:
        with self._lock:
            conn = self._connect()
            try:
                return self._fetch(conn, approval_id)
            finally:
                conn.close()

    def resolve_or_pending(self, approval_id: str) -> ApprovalStatus:
        """CLAUDE.md §9: 'Approval disconnect → default to pending, never
        approved.' Any failure resolving the record — not found, a lookup
        error, a dropped connection to the database — must resolve to
        PENDING here, not raise and not silently report APPROVED."""
        try:
            return self.get(approval_id).status
        except Exception:  # noqa: BLE001 — deliberately catches everything; see docstring
            return ApprovalStatus.PENDING

    def _fetch(self, conn: sqlite3.Connection, approval_id: str) -> ApprovalRecord:
        row = conn.execute(
            "SELECT approval_id, run_id, recommendation_summary, status, operator_id, decided_at, viewed_evidence "
            "FROM approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
        if row is None:
            raise ApprovalNotFoundError(approval_id)
        return _row_to_record(row)
