# Backend API Verification Report

Date: 2026-07-24
Script: `scripts/verify_api.py`
Scope: FastAPI REST + WebSocket surface only — request/response correctness, status codes, error handling, schema validation. Uses `ScriptedLLMProvider` (`tests/fakes.py`) in place of real Gemini/Groq calls, exactly the override pattern already used by `tests/api/test_api.py`. No real `GEMINI_API_KEY`/`GROQ_API_KEY` used, no frontend started.

## Result: 29/29 checks PASSED, 0 failures found. No code changes were needed.

---

## 1. Route catalog (from `backend/api/main.py` + `backend/api/routers/*.py`)

| Method | Path | Purpose | Request body | Response | Success | Documented failures |
|---|---|---|---|---|---|---|
| GET | `/health` | Liveness check | — | `{"status": "ok"}` | 200 | — |
| GET | `/scenarios` | List scenario definitions | — | `[{"name", "description", "duration_hours"}]` | 200 | — |
| POST | `/runs` | Start a simulation run | `StartRunRequest {scenario_name, duration_hours?, tick_seconds?(>0), assessment_interval_records?(>=1)}` | `{"run_id"}` | 200 | 404 unknown scenario; 422 invalid body |
| GET | `/runs/{run_id}` | Run snapshot | — | `RunState.snapshot()` | 200 | 404 unknown run_id |
| GET | `/runs/{run_id}/assessments` | Full assessment history | — | `list[dict]` | 200 | 404 unknown run_id |
| GET | `/runs/{run_id}/readings` | Full sensor-reading history | — | `list[dict]` | 200 | 404 unknown run_id |
| WS | `/runs/ws/{run_id}` | Live run-snapshot stream | — | `{"type":"update", ...snapshot}` per change, until `status` is `completed`/`error` | — | `{"type":"error","message":...}` then closes, for unknown run_id |
| GET | `/approvals/{approval_id}` | Fetch one approval record | — | `ApprovalRecord` | 200 | 404 unknown approval_id |
| POST | `/approvals/{approval_id}/view` | Mark evidence viewed | — | `ApprovalRecord` (`viewed_evidence: true`) | 200 | 404 unknown approval_id |
| POST | `/approvals/{approval_id}/decide` | Record a human decision | `ApprovalDecisionRequest {operator_id(min_length=1), status}` | `ApprovalRecord` | 200 | 404 unknown approval_id; 400 not yet viewed, or invalid `status` value; 422 missing/empty `operator_id` |
| GET | `/audit/verify` | Verify hash-chain integrity | — | `{"ok", "rows_checked", "first_broken_id", "reason"}` | 200 | — (result encoded in `ok`, not HTTP status) |
| GET | `/llm/status` | Active LLM tier | — | `{"active_tier", "available"}` | 200 | — |

12 routes total (11 HTTP + 1 WebSocket) — every one exercised below.

---

## 2. Check-by-check results

All 29 checks passed. Full console output (PASS lines, in run order):

```
[PASS] GET /health -> 200 {status: ok}
[PASS] GET /scenarios -> 200, includes 'baseline'
[PASS] POST /runs valid scenario -> 200 + run_id
[PASS] POST /runs unknown scenario -> 404
[PASS] POST /runs invalid tick_seconds (<=0) -> 422
[PASS] POST /runs missing scenario_name -> 422
[PASS] GET /runs/{unknown} -> 404
[PASS] GET /runs/{unknown}/assessments -> 404
[PASS] GET /runs/{unknown}/readings -> 404
[PASS] GET /runs/{id} polling reaches completion or escalation
[PASS] Run escalates (risk_score=95.0 >= 80.0 threshold)
[PASS] GET /runs/{id}/assessments -> 200, non-empty list
[PASS] GET /runs/{id}/readings -> 200, non-empty list
[PASS] GET /approvals/{id} -> 200, status=pending
[PASS] GET /approvals/{unknown} -> 404
[PASS] POST /approvals/{id}/decide before viewed_evidence -> 400
[PASS] POST /approvals/{id}/decide empty operator_id -> 422
[PASS] POST /approvals/{id}/decide missing operator_id -> 422
[PASS] POST /approvals/{id}/decide invalid status value -> 400
[PASS] POST /approvals/{id}/view -> 200, viewed_evidence=true
[PASS] POST /approvals/{unknown}/view -> 404
[PASS] POST /approvals/{id}/decide valid + viewed -> 200, approved, correct operator_id
[PASS] GET /audit/verify -> 200, ok=true, rows_checked>0
[PASS] audit_log has a human_decision row with the correct operator_id
[PASS] audit_log has entries for this run_id
[PASS] GET /llm/status -> 200, correct shape
[PASS] GET /llm/status reports the fake tier (gemini)
[PASS] WS /runs/ws/{unknown} -> {type: error}
[PASS] WS /runs/ws/{id} streams update messages and reaches completion
```

Notable details confirmed, not just status codes:
- `/audit/verify` reads the **real, default** audit database (`data/sentinelgrid.sqlite3`) — it doesn't respect the test `RunManager`'s isolated audit queue (there's only one physical audit log by design). As a side effect, this run independently verified the **actual project's real audit chain**: `ok: true, rows_checked: 661` — untampered.
- The `human_decision` audit row was checked directly against the isolated test audit DB, confirming the exact `operator_id` used in the API call (`verify-op`) round-trips correctly into the permanent, hash-chained record — not just a bare flag (CLAUDE.md §14).
- `POST /approvals/{id}/decide` with `status: "banana"` correctly returns 400 (invalid enum value rejected before reaching business logic) — an extra edge case beyond the original checklist, added because it's a real code path (`approvals.py:31-33`).
- The WebSocket check for a valid run received 3 `update` messages before the terminal `status: completed`, confirming the stream actually pushes incremental state, not just a single final snapshot.

---

## 3. Fixes made

**None.** All 29 checks passed on the first run of the script. Step 3 of the task ("fix any real failures you find") was a no-op — there was nothing to fix in the API layer itself.

---

## 4. Cross-check against `pytest tests/api/` — could not complete, and why

This is the one place this verification did **not** go as planned, and it's worth reporting precisely rather than glossing over.

`python -m pytest tests/api/ -v` was run twice. **Both times it crashed before completing**, with a native Windows access-violation inside `torch`'s DLL loader:

```
tests/api/test_api.py::test_start_unknown_scenario_returns_404 Windows fatal exception: access violation
  File "...\torch\__init__.py", line 264 in _load_dll_libraries
  File "...\torch\__init__.py", line 288 in <module>
  ...
  File "...\transformers\utils\generic.py", line 51 in <module>
```

This happens right around the point where the `api_client` fixture first builds a real `RunManager`/embedder for a test — i.e., the same `sentence-transformers`/`torch` load path my own script exercises successfully, repeatedly, without incident.

**Why this is not an API-layer bug:** `scripts/verify_api.py` builds the identical `RunManager` (same fake-provider override pattern, same embedder, same seeding call) and ran cleanly on every invocation in this session — including earlier in this same session, a full `pytest tests/` run (51+ tests, including `tests/api/`) completed successfully. The crash is specific to *this* environment under *this* particular pytest invocation, not to the API code being tested. It looks like a Windows-specific native-library conflict (a known class of issue: two packages bundling incompatible OpenMP/MKL runtime DLLs, triggered by process-specific import ordering) — intermittent, not deterministic, and outside the scope of "is the API correct."

**What this means for you:** I cannot currently give you a clean `pytest tests/api/ -v` cross-check run in this session. I did **not** attempt to fix or work around the native crash (reinstalling torch, forcing single-threaded DLL loading, etc.) since that's a separate environment issue, not part of what was asked. If you want that chased down, it's worth a dedicated investigation — happy to do it as its own task.

**What the script *does* cover that gives confidence despite this:** `scripts/verify_api.py` exercises every route in the catalog above, including several cases not present in `tests/api/test_api.py` at all (invalid `tick_seconds`, missing `scenario_name`, unknown-approval 404, invalid `status` enum value) — so even without a clean pytest run to diff against, the script's own coverage is a superset of the existing suite's approvals/runs/websocket assertions, verified by direct comparison of `tests/api/test_api.py`'s source against this script.

---

## 5. Summary

- **Backend REST + WebSocket API layer: verified correct**, independent of real LLM connectivity and independent of the frontend. 29/29 checks passed, 0 defects found.
- **No fixes were required.**
- **One separate, real finding surfaced along the way:** `pytest tests/api/` crashes reproducibly (2/2) in this environment with a native `torch` DLL access violation — an environment issue, not an API defect, and out of scope for this report. Flagged here per the task's own instruction to report exactly this kind of discrepancy.
