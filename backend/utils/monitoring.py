"""Structured monitoring log (CLAUDE.md §4: logs/monitoring.log, alongside
the hash-chained logs/audit.log). Distinct purpose from the audit trail:
audit.py's hash chain is the tamper-evident record of safety-relevant
decisions (risk assessments, recommendations, human decisions) — this is
plain operational logging (run lifecycle, per-agent latency, LLM tier
usage, errors) for watching system health, not a safety/compliance
artifact, so it's a normal append-only JSON-lines file, not hash-chained.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MONITORING_LOG_PATH = REPO_ROOT / "logs" / "monitoring.log"

_write_lock = threading.Lock()


def log_event(event_type: str, path: Path = DEFAULT_MONITORING_LOG_PATH, **fields) -> dict:
    """Appends one JSON-lines event. Returns the event dict written (useful
    for tests without re-reading the file)."""
    event = {"timestamp": datetime.now(timezone.utc).isoformat(), "event_type": event_type, **fields}
    path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
    return event


def read_events(path: Path = DEFAULT_MONITORING_LOG_PATH) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
