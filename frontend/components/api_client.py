"""HTTP client for backend/api. CLAUDE.md §3: the frontend talks to the
backend ONLY through this — never direct database access. (The API also
exposes a WebSocket per run for push-style updates; this dashboard uses
polling over the same REST surface for simplicity within Streamlit's
rerun-per-interaction execution model, which is still HTTP-only, just not
the WS endpoint specifically.)
"""

from __future__ import annotations

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:8000"


class APIError(RuntimeError):
    pass


class APIClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str) -> dict | list:
        resp = requests.get(f"{self.base_url}{path}", timeout=10)
        if not resp.ok:
            raise APIError(resp.json().get("detail", resp.text))
        return resp.json()

    def _post(self, path: str, json: dict | None = None) -> dict:
        resp = requests.post(f"{self.base_url}{path}", json=json or {}, timeout=10)
        if not resp.ok:
            raise APIError(resp.json().get("detail", resp.text))
        return resp.json()

    def health(self) -> bool:
        try:
            return self._get("/health").get("status") == "ok"
        except Exception:
            return False

    def list_scenarios(self) -> list[dict]:
        return self._get("/scenarios")

    def start_run(self, scenario_name: str, duration_hours: float | None = None, tick_seconds: float = 0.2, assessment_interval_records: int = 5) -> str:
        payload = {"scenario_name": scenario_name, "tick_seconds": tick_seconds, "assessment_interval_records": assessment_interval_records}
        if duration_hours is not None:
            payload["duration_hours"] = duration_hours
        return self._post("/runs", json=payload)["run_id"]

    def get_run(self, run_id: str) -> dict:
        return self._get(f"/runs/{run_id}")

    def get_assessments(self, run_id: str) -> list[dict]:
        return self._get(f"/runs/{run_id}/assessments")

    def get_readings(self, run_id: str) -> list[dict]:
        return self._get(f"/runs/{run_id}/readings")

    def get_approval(self, approval_id: str) -> dict:
        return self._get(f"/approvals/{approval_id}")

    def mark_viewed(self, approval_id: str) -> dict:
        return self._post(f"/approvals/{approval_id}/view")

    def decide(self, approval_id: str, operator_id: str, status: str) -> dict:
        return self._post(f"/approvals/{approval_id}/decide", json={"operator_id": operator_id, "status": status})

    def llm_status(self) -> dict:
        return self._get("/llm/status")

    def audit_verify(self) -> dict:
        return self._get("/audit/verify")
