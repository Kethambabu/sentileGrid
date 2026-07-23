"""API-level verification: exercises the FastAPI surface with a RunManager
built from a scripted fake LLM provider (see tests/fakes.py), so these tests
never make a live Hugging Face/Groq call.
"""

import json
import time

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api.run_manager import RunManager
from backend.api.state import get_run_manager
from backend.database.approvals import ApprovalService, ApprovalStatus
from backend.database.audit import AuditWriteQueue
from backend.database.vector_store import get_client
from backend.rag.retriever import LiveRetriever
from backend.rag.seed_knowledge_base import seed
from backend.utils.llm_router import LLMRouter, LLMTier
from tests.fakes import ScriptedLLMProvider


def _build_test_run_manager(tmp_path, risk_score: float) -> RunManager:
    persist_dir = tmp_path / "chroma"
    seed(reset=True, persist_directory=persist_dir)
    client = get_client(persist_directory=persist_dir)

    audit_queue = AuditWriteQueue(db_path=tmp_path / "audit.sqlite3")
    approval_service = ApprovalService(audit_queue=audit_queue, db_path=tmp_path / "approvals.sqlite3")

    rules = [
        ('"risk_score"', json.dumps({
            "risk_score": risk_score, "contributing_factors": ["test factor"],
            "recommended_action": "Increase reactor cooling water flow", "cited_chunk_ids": [], "reasoning": "test reasoning",
        })),
        ('"approved"', json.dumps({"approved": True, "cited_sop_chunk_ids": ["reactor_high_pressure_response::part0"], "notes": "ok"})),
        ('"recommended_interventions"', json.dumps({"recommended_interventions": ["Reduce reactor feed rate"], "reasoning": "test"})),
    ]
    fake_provider = ScriptedLLMProvider(LLMTier.GEMINI, rules, default_content="Plain narrative explanation for the operator.")
    llm_router = LLMRouter(gemini_provider=fake_provider, groq_provider=fake_provider, config={
        "gemini": {"model": "m", "timeout_seconds": 5}, "groq": {"model": "m", "timeout_seconds": 5},
        "cache": {"ttl_seconds": 0}, "defaults": {"max_tokens": 500, "temperature": 0.1},
    })

    return RunManager(audit_queue=audit_queue, approval_service=approval_service, llm_router=llm_router, retriever=LiveRetriever(client=client))


@pytest.fixture()
def api_client(tmp_path):
    manager = _build_test_run_manager(tmp_path, risk_score=40.0)
    app.dependency_overrides[get_run_manager] = lambda: manager
    client = TestClient(app)
    yield client, manager
    app.dependency_overrides.clear()
    manager.audit_queue.stop()


def _wait_for_completion(client: TestClient, run_id: str, timeout_s: float = 90.0) -> dict:
    deadline = time.monotonic() + timeout_s
    data = {}
    while time.monotonic() < deadline:
        data = client.get(f"/runs/{run_id}").json()
        if data["status"] in ("completed", "error"):
            return data
        time.sleep(0.1)
    raise TimeoutError(f"run {run_id} did not complete in time: {data}")


def test_health():
    resp = TestClient(app).get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_list_scenarios():
    resp = TestClient(app).get("/scenarios")
    assert resp.status_code == 200
    names = {s["name"] for s in resp.json()}
    assert "baseline" in names
    assert "reactor_a_feed_loss" in names


def test_start_unknown_scenario_returns_404(api_client):
    client, _ = api_client
    resp = client.post("/runs", json={"scenario_name": "does_not_exist"})
    assert resp.status_code == 404


def test_get_unknown_run_returns_404(api_client):
    client, _ = api_client
    resp = client.get("/runs/does-not-exist")
    assert resp.status_code == 404


def test_full_run_completes_and_produces_an_assessment(api_client):
    client, _ = api_client
    resp = client.post("/runs", json={"scenario_name": "baseline", "duration_hours": 0.3, "tick_seconds": 0.01, "assessment_interval_records": 5})
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    data = _wait_for_completion(client, run_id)
    assert data["status"] == "completed"
    assert data["assessment_count"] >= 1
    assert data["latest_assessment"]["risk_assessment"]["risk_score"] == 40.0
    assert data["latest_assessment"]["compliance_result"]["approved"] is True


def test_readings_endpoint_returns_full_history(api_client):
    client, _ = api_client
    run_id = client.post("/runs", json={"scenario_name": "baseline", "duration_hours": 0.3, "tick_seconds": 0.01, "assessment_interval_records": 5}).json()["run_id"]
    data = _wait_for_completion(client, run_id)

    readings = client.get(f"/runs/{run_id}/readings").json()
    assert len(readings) == data["total_records"]
    assert readings[0]["record_index"] == 0
    assert "reactor_pressure_kpa" in readings[0]


def test_assessments_endpoint_returns_full_history(api_client):
    client, _ = api_client
    run_id = client.post("/runs", json={"scenario_name": "baseline", "duration_hours": 0.3, "tick_seconds": 0.01, "assessment_interval_records": 5}).json()["run_id"]
    _wait_for_completion(client, run_id)

    assessments = client.get(f"/runs/{run_id}/assessments").json()
    assert len(assessments) >= 1
    assert "risk_assessment" in assessments[0]


def test_emergency_escalation_creates_pending_approval_via_api(tmp_path):
    manager = _build_test_run_manager(tmp_path, risk_score=95.0)
    app.dependency_overrides[get_run_manager] = lambda: manager
    client = TestClient(app)
    try:
        run_id = client.post("/runs", json={"scenario_name": "baseline", "duration_hours": 0.3, "tick_seconds": 0.01, "assessment_interval_records": 5}).json()["run_id"]
        data = _wait_for_completion(client, run_id)

        approval_id = data["latest_assessment"]["emergency_recommendation"]["approval_id"]
        assert approval_id is not None

        approval = client.get(f"/approvals/{approval_id}").json()
        assert approval["status"] == "pending"

        # decide before viewing evidence -> rejected by the API
        decide_resp = client.post(f"/approvals/{approval_id}/decide", json={"operator_id": "op-1", "status": "approved"})
        assert decide_resp.status_code == 400

        view_resp = client.post(f"/approvals/{approval_id}/view")
        assert view_resp.status_code == 200

        decide_resp = client.post(f"/approvals/{approval_id}/decide", json={"operator_id": "op-1", "status": "approved"})
        assert decide_resp.status_code == 200
        assert decide_resp.json()["status"] == "approved"
        assert decide_resp.json()["operator_id"] == "op-1"
    finally:
        app.dependency_overrides.clear()
        manager.audit_queue.stop()


def test_decide_without_operator_id_is_rejected(api_client):
    client, manager = api_client
    record = manager.approval_service.create_pending(run_id="run-x", recommendation_summary="test")
    manager.approval_service.mark_evidence_viewed(record.approval_id)

    resp = client.post(f"/approvals/{record.approval_id}/decide", json={"operator_id": "", "status": "approved"})
    assert resp.status_code == 422  # min_length=1 on operator_id, rejected by request validation


def test_llm_status_endpoint(api_client):
    client, _ = api_client
    resp = client.get("/llm/status")
    assert resp.status_code == 200
    assert "active_tier" in resp.json()


def test_audit_verify_endpoint_returns_expected_shape():
    resp = TestClient(app).get("/audit/verify")
    assert resp.status_code == 200
    body = resp.json()
    assert "ok" in body and "rows_checked" in body


def test_websocket_streams_updates_until_completion(api_client):
    client, _ = api_client
    run_id = client.post("/runs", json={"scenario_name": "baseline", "duration_hours": 0.3, "tick_seconds": 0.01, "assessment_interval_records": 5}).json()["run_id"]

    messages = []
    with client.websocket_connect(f"/runs/ws/{run_id}") as ws:
        while True:
            msg = ws.receive_json()
            messages.append(msg)
            if msg.get("status") in ("completed", "error"):
                break

    assert messages[-1]["status"] == "completed"
    assert any(m.get("assessment_count", 0) >= 1 for m in messages)


def test_websocket_reports_error_for_unknown_run():
    client = TestClient(app)
    with client.websocket_connect("/runs/ws/does-not-exist") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "error"
