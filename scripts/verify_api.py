"""Standalone backend API verification script.

Exercises the FastAPI REST + WebSocket surface end to end against a
RunManager built from ScriptedLLMProvider (see tests/fakes.py) — no real
Hugging Face/Groq calls are made, no frontend is started, no real
GEMINI_API_KEY/GROQ_API_KEY is needed. Reuses the exact dependency-override
pattern already proven in tests/api/test_api.py; this script exists to give
a human-readable PASS/FAIL line per check rather than a pytest report.

Run: python scripts/verify_api.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.api.main import app  # noqa: E402
from backend.api.run_manager import RunManager  # noqa: E402
from backend.api.state import get_run_manager  # noqa: E402
from backend.database.approvals import ApprovalService  # noqa: E402
from backend.database.audit import AuditWriteQueue  # noqa: E402
from backend.database.vector_store import get_client  # noqa: E402
from backend.rag.retriever import LiveRetriever  # noqa: E402
from backend.rag.seed_knowledge_base import seed  # noqa: E402
from backend.utils.llm_router import LLMRouter, LLMTier  # noqa: E402
from tests.fakes import ScriptedLLMProvider  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"
EMERGENCY_RISK_THRESHOLD = 80.0  # backend/agents/emergency_agent.py::DEFAULT_RISK_THRESHOLD

results: list[tuple[str, str, str]] = []  # (check_name, status, detail)


def check(name: str, condition: bool, detail: str = "") -> None:
    status = PASS if condition else FAIL
    results.append((name, status, detail))
    line = f"[{status}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)


def build_run_manager(tmp_path: Path, risk_score: float) -> tuple[RunManager, Path]:
    persist_dir = tmp_path / "chroma"
    seed(reset=True, persist_directory=persist_dir)
    client = get_client(persist_directory=persist_dir)

    audit_db_path = tmp_path / "audit.sqlite3"
    audit_queue = AuditWriteQueue(db_path=audit_db_path)
    approval_service = ApprovalService(audit_queue=audit_queue, db_path=tmp_path / "approvals.sqlite3")

    rules = [
        (
            '"risk_score"',
            json.dumps(
                {
                    "risk_score": risk_score,
                    "contributing_factors": ["test factor"],
                    "recommended_action": "Increase reactor cooling water flow",
                    "cited_chunk_ids": [],
                    "reasoning": "test reasoning",
                }
            ),
        ),
        (
            '"approved"',
            json.dumps(
                {"approved": True, "cited_sop_chunk_ids": ["reactor_high_pressure_response::part0"], "notes": "ok"}
            ),
        ),
        (
            '"recommended_interventions"',
            json.dumps({"recommended_interventions": ["Reduce reactor feed rate"], "reasoning": "test"}),
        ),
    ]
    fake_provider = ScriptedLLMProvider(LLMTier.GEMINI, rules, default_content="Plain narrative explanation for the operator.")
    llm_router = LLMRouter(
        gemini_provider=fake_provider,
        groq_provider=fake_provider,
        config={
            "gemini": {"model": "m", "timeout_seconds": 5},
            "groq": {"model": "m", "timeout_seconds": 5},
            "cache": {"ttl_seconds": 0},
            "defaults": {"max_tokens": 500, "temperature": 0.1},
        },
    )

    manager = RunManager(
        audit_queue=audit_queue, approval_service=approval_service, llm_router=llm_router, retriever=LiveRetriever(client=client)
    )
    return manager, audit_db_path


def wait_for(client: TestClient, run_id: str, predicate, timeout_s: float = 90.0) -> dict:
    deadline = time.monotonic() + timeout_s
    data: dict = {}
    while time.monotonic() < deadline:
        data = client.get(f"/runs/{run_id}").json()
        if predicate(data):
            return data
        time.sleep(0.1)
    raise TimeoutError(f"run {run_id} did not satisfy predicate in time: {data}")


def main() -> int:
    print("=" * 78)
    print("SentinelGrid backend API verification — fake LLM provider, no real HF/Groq, no frontend")
    print("=" * 78)

    tmp_path = Path(tempfile.mkdtemp(prefix="sentinelgrid_api_verify_"))
    # risk_score=95.0 is deliberately >= EMERGENCY_RISK_THRESHOLD (80.0) so every
    # run in this script triggers an escalation, exercising the approvals flow.
    manager, audit_db_path = build_run_manager(tmp_path, risk_score=95.0)
    app.dependency_overrides[get_run_manager] = lambda: manager
    client = TestClient(app)

    run_id: str | None = None
    approval_id: str | None = None

    try:
        # ---------------------------------------------------------------
        # Baseline routes
        # ---------------------------------------------------------------
        resp = client.get("/health")
        check(
            "GET /health -> 200 {status: ok}",
            resp.status_code == 200 and resp.json() == {"status": "ok"},
            f"got {resp.status_code} {resp.text}",
        )

        resp = client.get("/scenarios")
        scenario_names = {s["name"] for s in resp.json()} if resp.status_code == 200 else set()
        check(
            "GET /scenarios -> 200, includes 'baseline'",
            resp.status_code == 200 and "baseline" in scenario_names,
            f"got {resp.status_code}, names={scenario_names}",
        )

        # ---------------------------------------------------------------
        # POST /runs
        # ---------------------------------------------------------------
        resp = client.post(
            "/runs", json={"scenario_name": "baseline", "duration_hours": 0.3, "tick_seconds": 0.01, "assessment_interval_records": 5}
        )
        check(
            "POST /runs valid scenario -> 200 + run_id",
            resp.status_code == 200 and "run_id" in resp.json(),
            f"got {resp.status_code} {resp.text}",
        )
        run_id = resp.json().get("run_id") if resp.status_code == 200 else None

        resp = client.post("/runs", json={"scenario_name": "does_not_exist_scenario"})
        check("POST /runs unknown scenario -> 404", resp.status_code == 404, f"got {resp.status_code} {resp.text}")

        resp = client.post("/runs", json={"scenario_name": "baseline", "tick_seconds": -1})
        check("POST /runs invalid tick_seconds (<=0) -> 422", resp.status_code == 422, f"got {resp.status_code} {resp.text}")

        resp = client.post("/runs", json={})
        check("POST /runs missing scenario_name -> 422", resp.status_code == 422, f"got {resp.status_code} {resp.text}")

        # ---------------------------------------------------------------
        # GET /runs/{run_id}, /assessments, /readings — unknown run_id
        # ---------------------------------------------------------------
        resp = client.get("/runs/does-not-exist")
        check("GET /runs/{unknown} -> 404", resp.status_code == 404, f"got {resp.status_code} {resp.text}")

        resp = client.get("/runs/does-not-exist/assessments")
        check("GET /runs/{unknown}/assessments -> 404", resp.status_code == 404, f"got {resp.status_code} {resp.text}")

        resp = client.get("/runs/does-not-exist/readings")
        check("GET /runs/{unknown}/readings -> 404", resp.status_code == 404, f"got {resp.status_code} {resp.text}")

        # ---------------------------------------------------------------
        # Poll the valid run until it completes or an approval appears
        # ---------------------------------------------------------------
        if run_id:
            try:
                data = wait_for(
                    client,
                    run_id,
                    lambda d: d["status"] in ("completed", "error")
                    or ((d.get("latest_assessment") or {}).get("emergency_recommendation") or {}).get("approval_id"),
                )
                check("GET /runs/{id} polling reaches completion or escalation", True, f"status={data.get('status')}")
                latest = data.get("latest_assessment") or {}
                approval_id = (latest.get("emergency_recommendation") or {}).get("approval_id")
                check(
                    f"Run escalates (risk_score=95.0 >= {EMERGENCY_RISK_THRESHOLD} threshold)",
                    approval_id is not None,
                    f"approval_id={approval_id}",
                )
            except TimeoutError as exc:
                check("GET /runs/{id} polling reaches completion or escalation", False, str(exc))
        else:
            check("GET /runs/{id} polling reaches completion or escalation", False, "no run_id from POST /runs")

        # ---------------------------------------------------------------
        # GET /runs/{id}/assessments, /readings — on the real run
        # ---------------------------------------------------------------
        if run_id:
            resp = client.get(f"/runs/{run_id}/assessments")
            body = resp.json() if resp.status_code == 200 else None
            check(
                "GET /runs/{id}/assessments -> 200, non-empty list",
                resp.status_code == 200 and isinstance(body, list) and len(body) >= 1,
                f"got {resp.status_code}, len={len(body) if isinstance(body, list) else 'n/a'}",
            )

            resp = client.get(f"/runs/{run_id}/readings")
            body = resp.json() if resp.status_code == 200 else None
            check(
                "GET /runs/{id}/readings -> 200, non-empty list",
                resp.status_code == 200 and isinstance(body, list) and len(body) > 0,
                f"got {resp.status_code}, len={len(body) if isinstance(body, list) else 'n/a'}",
            )

        # ---------------------------------------------------------------
        # Approvals flow
        # ---------------------------------------------------------------
        if approval_id:
            resp = client.get(f"/approvals/{approval_id}")
            check(
                "GET /approvals/{id} -> 200, status=pending",
                resp.status_code == 200 and resp.json().get("status") == "pending",
                f"got {resp.status_code} {resp.text}",
            )

            resp = client.get("/approvals/does-not-exist")
            check("GET /approvals/{unknown} -> 404", resp.status_code == 404, f"got {resp.status_code} {resp.text}")

            resp = client.post(f"/approvals/{approval_id}/decide", json={"operator_id": "verify-op", "status": "approved"})
            check(
                "POST /approvals/{id}/decide before viewed_evidence -> 400",
                resp.status_code == 400,
                f"got {resp.status_code} {resp.text}",
            )

            resp = client.post(f"/approvals/{approval_id}/decide", json={"operator_id": "", "status": "approved"})
            check(
                "POST /approvals/{id}/decide empty operator_id -> 422",
                resp.status_code == 422,
                f"got {resp.status_code} {resp.text}",
            )

            resp = client.post(f"/approvals/{approval_id}/decide", json={"status": "approved"})
            check(
                "POST /approvals/{id}/decide missing operator_id -> 422",
                resp.status_code == 422,
                f"got {resp.status_code} {resp.text}",
            )

            resp = client.post(f"/approvals/{approval_id}/decide", json={"operator_id": "verify-op", "status": "banana"})
            check(
                "POST /approvals/{id}/decide invalid status value -> 400",
                resp.status_code == 400,
                f"got {resp.status_code} {resp.text}",
            )

            resp = client.post(f"/approvals/{approval_id}/view")
            check(
                "POST /approvals/{id}/view -> 200, viewed_evidence=true",
                resp.status_code == 200 and resp.json().get("viewed_evidence") is True,
                f"got {resp.status_code} {resp.text}",
            )

            resp = client.post("/approvals/does-not-exist/view")
            check("POST /approvals/{unknown}/view -> 404", resp.status_code == 404, f"got {resp.status_code} {resp.text}")

            resp = client.post(f"/approvals/{approval_id}/decide", json={"operator_id": "verify-op", "status": "approved"})
            decided_ok = (
                resp.status_code == 200
                and resp.json().get("status") == "approved"
                and resp.json().get("operator_id") == "verify-op"
            )
            check(
                "POST /approvals/{id}/decide valid + viewed -> 200, approved, correct operator_id",
                decided_ok,
                f"got {resp.status_code} {resp.text}",
            )
        else:
            for name in [
                "GET /approvals/{id} -> 200, status=pending",
                "GET /approvals/{unknown} -> 404",
                "POST /approvals/{id}/decide before viewed_evidence -> 400",
                "POST /approvals/{id}/decide empty operator_id -> 422",
                "POST /approvals/{id}/decide missing operator_id -> 422",
                "POST /approvals/{id}/decide invalid status value -> 400",
                "POST /approvals/{id}/view -> 200, viewed_evidence=true",
                "POST /approvals/{unknown}/view -> 404",
                "POST /approvals/{id}/decide valid + viewed -> 200, approved, correct operator_id",
            ]:
                check(name, False, "SKIPPED — no approval_id (escalation did not occur)")

        # ---------------------------------------------------------------
        # Audit
        # ---------------------------------------------------------------
        resp = client.get("/audit/verify")
        audit_body = resp.json() if resp.status_code == 200 else {}
        check(
            "GET /audit/verify -> 200, ok=true, rows_checked>0",
            resp.status_code == 200 and audit_body.get("ok") is True and audit_body.get("rows_checked", 0) > 0,
            f"got {resp.status_code} {audit_body}",
        )

        if approval_id:
            conn = sqlite3.connect(audit_db_path)
            try:
                human_decision_rows = conn.execute(
                    "SELECT event_type, run_id, operator_id, payload FROM audit_log WHERE event_type = 'human_decision'"
                ).fetchall()
                run_row_count = conn.execute("SELECT COUNT(*) FROM audit_log WHERE run_id = ?", (run_id,)).fetchone()[0]
            finally:
                conn.close()

            matching = [
                r for r in human_decision_rows if r[2] == "verify-op" and json.loads(r[3]).get("approval_id") == approval_id
            ]
            check(
                "audit_log has a human_decision row with the correct operator_id",
                len(matching) == 1,
                f"found {len(matching)} matching of {len(human_decision_rows)} human_decision rows total",
            )
            check("audit_log has entries for this run_id", run_row_count > 0, f"count={run_row_count}")

        # ---------------------------------------------------------------
        # LLM status
        # ---------------------------------------------------------------
        resp = client.get("/llm/status")
        llm_body = resp.json() if resp.status_code == 200 else {}
        llm_shape_ok = resp.status_code == 200 and "active_tier" in llm_body and "available" in llm_body
        check("GET /llm/status -> 200, correct shape", llm_shape_ok, f"got {resp.status_code} {llm_body}")
        if llm_shape_ok:
            check(
                "GET /llm/status reports the fake tier (gemini)",
                llm_body.get("active_tier") == "gemini",
                f"active_tier={llm_body.get('active_tier')}",
            )

        # ---------------------------------------------------------------
        # WebSocket
        # ---------------------------------------------------------------
        try:
            with client.websocket_connect("/runs/ws/does-not-exist") as ws:
                msg = ws.receive_json()
            check("WS /runs/ws/{unknown} -> {type: error}", msg.get("type") == "error", f"got {msg}")
        except Exception as exc:  # noqa: BLE001 — report any connection-level failure as a finding, not a crash
            check("WS /runs/ws/{unknown} -> {type: error}", False, f"exception: {exc!r}")

        resp = client.post(
            "/runs", json={"scenario_name": "baseline", "duration_hours": 0.3, "tick_seconds": 0.01, "assessment_interval_records": 5}
        )
        ws_run_id = resp.json().get("run_id") if resp.status_code == 200 else None
        if ws_run_id:
            try:
                messages = []
                with client.websocket_connect(f"/runs/ws/{ws_run_id}") as ws:
                    while True:
                        msg = ws.receive_json()
                        messages.append(msg)
                        if msg.get("status") in ("completed", "error"):
                            break
                got_update = any(m.get("type") == "update" for m in messages)
                reached_terminal = messages[-1].get("status") in ("completed", "error") if messages else False
                check(
                    "WS /runs/ws/{id} streams update messages and reaches completion",
                    got_update and reached_terminal,
                    f"{len(messages)} messages received, last status={messages[-1].get('status') if messages else None}",
                )
            except Exception as exc:  # noqa: BLE001
                check("WS /runs/ws/{id} streams update messages and reaches completion", False, f"exception: {exc!r}")
        else:
            check(
                "WS /runs/ws/{id} streams update messages and reaches completion",
                False,
                "SKIPPED — could not start a second run for the WS check",
            )

    finally:
        app.dependency_overrides.clear()
        manager.audit_queue.stop()

    print("=" * 78)
    total = len(results)
    passed = sum(1 for _, status, _ in results if status == PASS)
    failed = total - passed
    print(f"SUMMARY: {passed}/{total} PASSED, {failed} FAILED")
    if failed:
        print("\nFailed checks:")
        for name, status, detail in results:
            if status == FAIL:
                print(f"  - {name}: {detail}")
    print("=" * 78)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
