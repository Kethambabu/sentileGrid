"""Append-only, hash-chained audit log (CLAUDE.md §8/§12): every risk
assessment, recommendation, and human decision gets written here — this is
load-bearing for the project's core safety claim, not a feature to skip
under time pressure.

SQLite in WAL mode, all writes funneled through a single background writer
thread (CLAUDE.md §8: "funnel all writes through a single async queue/
worker — don't let multiple agents write directly and concurrently"). This
project's agent/orchestrator code is synchronous, so "single queue/worker"
is implemented as one dedicated writer thread draining a queue.Queue, giving
callers a simple blocking submit() rather than requiring the whole codebase
adopt asyncio for this one concern.

Each row's hash covers its own content AND the previous row's hash, forming
a tamper-evident chain — verify_chain() walks the table and recomputes every
hash to detect any row that was altered or deleted after the fact.
"""

from __future__ import annotations

import hashlib
import json
import queue
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "sentinelgrid.sqlite3"

GENESIS_HASH = "0" * 64


class AuditEntryInput(BaseModel):
    event_type: str  # "risk_assessment" | "compliance_check" | "explanation" | "emergency_recommendation" | "human_decision" | "llm_call"
    agent_name: str | None = None
    run_id: str | None = None
    operator_id: str | None = None  # required for event_type == "human_decision" (CLAUDE.md §14)
    payload: dict


class AuditRow(BaseModel):
    id: int
    timestamp: str
    event_type: str
    agent_name: str | None
    run_id: str | None
    operator_id: str | None
    payload: dict
    prev_hash: str
    row_hash: str


def _canonical_payload(entry: AuditEntryInput, timestamp: str, prev_hash: str) -> str:
    return json.dumps(
        {
            "timestamp": timestamp,
            "event_type": entry.event_type,
            "agent_name": entry.agent_name,
            "run_id": entry.run_id,
            "operator_id": entry.operator_id,
            "payload": entry.payload,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
    )


def _compute_row_hash(entry: AuditEntryInput, timestamp: str, prev_hash: str) -> str:
    return hashlib.sha256(_canonical_payload(entry, timestamp, prev_hash).encode("utf-8")).hexdigest()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            agent_name TEXT,
            run_id TEXT,
            operator_id TEXT,
            payload TEXT NOT NULL,
            prev_hash TEXT NOT NULL,
            row_hash TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _write_entry(conn: sqlite3.Connection, entry: AuditEntryInput) -> AuditRow:
    if entry.event_type == "human_decision" and not entry.operator_id:
        raise ValueError("human_decision audit entries must include operator_id (CLAUDE.md §14)")

    cur = conn.execute("SELECT row_hash FROM audit_log ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    prev_hash = row[0] if row else GENESIS_HASH

    timestamp = datetime.now(timezone.utc).isoformat()
    row_hash = _compute_row_hash(entry, timestamp, prev_hash)
    payload_json = json.dumps(entry.payload, sort_keys=True)

    cur = conn.execute(
        "INSERT INTO audit_log (timestamp, event_type, agent_name, run_id, operator_id, payload, prev_hash, row_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (timestamp, entry.event_type, entry.agent_name, entry.run_id, entry.operator_id, payload_json, prev_hash, row_hash),
    )
    conn.commit()
    return AuditRow(
        id=cur.lastrowid, timestamp=timestamp, event_type=entry.event_type, agent_name=entry.agent_name,
        run_id=entry.run_id, operator_id=entry.operator_id, payload=entry.payload, prev_hash=prev_hash, row_hash=row_hash,
    )


@dataclass
class VerificationResult:
    ok: bool
    rows_checked: int
    first_broken_id: int | None = None
    reason: str | None = None


def verify_chain(db_path: Path = DEFAULT_DB_PATH) -> VerificationResult:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT id, timestamp, event_type, agent_name, run_id, operator_id, payload, prev_hash, row_hash "
            "FROM audit_log ORDER BY id ASC"
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    expected_prev = GENESIS_HASH
    for row in rows:
        row_id, timestamp, event_type, agent_name, run_id, operator_id, payload_json, prev_hash, row_hash = row
        if prev_hash != expected_prev:
            return VerificationResult(ok=False, rows_checked=row_id, first_broken_id=row_id, reason="prev_hash does not match preceding row's row_hash")
        entry = AuditEntryInput(event_type=event_type, agent_name=agent_name, run_id=run_id, operator_id=operator_id, payload=json.loads(payload_json))
        recomputed = _compute_row_hash(entry, timestamp, prev_hash)
        if recomputed != row_hash:
            return VerificationResult(ok=False, rows_checked=row_id, first_broken_id=row_id, reason="row_hash does not match recomputed hash — row content was altered")
        expected_prev = row_hash

    return VerificationResult(ok=True, rows_checked=len(rows))


class AuditWriteQueue:
    """The single writer thread all audit writes funnel through."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        _ensure_schema(conn)
        while True:
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                if self._stop_event.is_set():
                    break
                continue
            entry, result_event, result_holder = item
            try:
                result_holder["row"] = _write_entry(conn, entry)
            except Exception as exc:  # noqa: BLE001
                result_holder["error"] = exc
            finally:
                result_event.set()
                self._queue.task_done()
        conn.close()

    def submit(self, entry: AuditEntryInput, timeout: float = 5.0) -> AuditRow:
        result_event = threading.Event()
        result_holder: dict = {}
        self._queue.put((entry, result_event, result_holder))
        if not result_event.wait(timeout=timeout):
            raise TimeoutError(f"Audit write for event_type={entry.event_type!r} timed out after {timeout}s")
        if "error" in result_holder:
            raise result_holder["error"]
        return result_holder["row"]

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        self._thread.join(timeout=timeout)


_default_queue: AuditWriteQueue | None = None


def get_default_audit_queue() -> AuditWriteQueue:
    global _default_queue
    if _default_queue is None:
        _default_queue = AuditWriteQueue()
    return _default_queue
