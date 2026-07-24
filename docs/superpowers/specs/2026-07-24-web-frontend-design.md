# SentinelGrid Web Frontend — Design Spec

Date: 2026-07-24
Status: Approved (brainstorming phase) — implementation plan not yet written

## Context

The current frontend is 4 plain Streamlit pages (`frontend/app.py`, `frontend/pages/1_Overview.py`, `2_Timeline.py`, `3_Agent_Trace.py`, `4_Approvals.py`) with no custom theming, talking to the FastAPI backend via `frontend/components/api_client.py`. CLAUDE.md §5 pins the dashboard stack to Streamlit "unless explicitly requested" otherwise — this is that explicit request. The backend is complete and unchanged by this work; CORS is already open (`allow_origins=["*"]` in `backend/api/main.py`), so no backend changes are required for a separately-hosted frontend to call it.

Goal: an enterprise-grade web UI replacing Streamlit, built as a new, separate app. The existing `frontend/` Streamlit app is left in place and untouched, not deleted, so it keeps working as a fallback until the new app is trusted.

## Decisions Made During Brainstorming

- **Replace Streamlit** with a real web app rather than restyling Streamlit (Streamlit's rerun-per-interaction model caps how far "enterprise" polish can go).
- **Stack:** Next.js 14 (App Router) + TypeScript + Tailwind + shadcn/ui.
- **Charting:** recharts (via shadcn's chart components).
- **Live updates:** use the existing, currently-unused WebSocket endpoint (`/runs/ws/{run_id}`) instead of polling.
- **Information architecture:** redesigned around one persistent app shell (sidebar nav + operator identity), not a 1:1 restyle of the 4 old pages.
- **Operator identity:** lightweight sign-in at app load (operator ID only, no password — the backend has no auth concept beyond the ID string), persisted in the shell and reused automatically for approval decisions.
- **Visual direction:** "Dark Control Room" — reuses the palette and voice already established in the SentinelGrid pitch/landing page artifact (blue-charcoal grounds, cyan structural accent `#3fb8c9`, green/amber/red used only as real semantic risk states, condensed technical display type + monospace for data).
- **Live Monitor page layout:** stacked (KPI row → chart → latest-assessment panel), not split-panel or feed-style.
- **List pattern (Agent Trace & Approvals):** master-detail (scannable list left, full detail right), not accordion.
- **Location in repo:** new top-level `web/` directory. Not nested in `frontend/` (different toolchain — Node/TypeScript vs the rest of the repo's Python) and not replacing `frontend/`.
- **Testing:** included — Vitest + React Testing Library for components, Playwright for smoke e2e flows.
- **No deployment/build pipeline requested** — this is a local dev-server app, same operating model as the current Streamlit one.

## Architecture

```
web/
├── app/                      # Next.js App Router
│   ├── layout.tsx            # shell: sidebar nav, header (connection + LLM tier), sign-in gate
│   ├── monitor/page.tsx      # Live Monitor (merges old Overview + Timeline)
│   ├── trace/page.tsx        # Agent Trace (master-detail)
│   └── approvals/page.tsx    # Approvals (master-detail)
├── components/
│   ├── shell/                # Sidebar, header, sign-in prompt
│   ├── monitor/              # KPI row, scenario picker/run-start form, timeline chart, assessment panel
│   ├── trace/                # Assessment list, agent-stage detail blocks
│   ├── approvals/            # Approval list, evidence panel, decide buttons
│   └── ui/                   # shadcn primitives
├── lib/
│   ├── api-client.ts         # mirrors frontend/components/api_client.py 1:1
│   ├── use-run-socket.ts     # WebSocket hook: subscribes to /runs/ws/{run_id}, falls back to polling
│   └── operator-context.tsx  # operator ID state + localStorage persistence
├── tests/                    # Vitest component tests
└── e2e/                      # Playwright smoke tests
```

The frontend talks only to the existing FastAPI backend (CLAUDE.md §3: HTTP/WebSocket only, never direct DB access) — this rule is inherited, not re-derived, since it applies to any frontend regardless of framework.

### Data flow for a live run

1. POST `/runs` → get `run_id`.
2. Open `wss://…/runs/ws/{run_id}`.
3. Each `{"type": "update", ...snapshot}` message writes directly into the React Query cache (`queryClient.setQueryData`) rather than triggering a refetch, so KPI row / chart / assessment panel all re-render from one consistent snapshot per message.
4. If the socket drops: fall back to 2s polling of `GET /runs/{run_id}` automatically, show a "reconnecting…" indicator, keep retrying the socket in the background.
5. Non-run-scoped data (scenario list, `/audit/verify`, `/llm/status`) uses plain React Query polling — no WS needed there.

### Backend contract reference (verified against current code, not assumed)

- `GET /runs/{run_id}` / WS `update` payload = `RunState.snapshot()`: `run_id, scenario_name, status (starting|running|completed|error), total_records, revealed_count, diverged, diverged_reason, error, latest_record_summary, latest_assessment, assessment_count`.
- `latest_record_summary` / each item in `GET /runs/{run_id}/readings`: `record_index, t_hours, reactor_pressure_kpa, reactor_temperature_c, reactor_level_pct, separator_pressure_kpa, stripper_level_pct`.
- `latest_assessment` / each item in `GET /runs/{run_id}/assessments`: `retrieval_phase, retrieval_confidence, is_novel_condition, risk_assessment, compliance_result, explanation, emergency_recommendation, record_index, t_hours`.
- `risk_assessment` (`RiskAssessment`): `risk_score` (float 0–100 **or null — null exactly when `is_novel_condition` is true, never a forced guess**), `is_novel_condition, confidence, contributing_factors[], recommended_action, cited_chunk_ids[], reasoning, llm_tier_used, latency_ms, parse_error, reasoning_unavailable`.
- `compliance_result` (`ComplianceResult`): `action_reviewed, approved, cited_sop_chunk_ids[], notes, llm_tier_used, latency_ms, parse_error, reasoning_unavailable`.
- `explanation` (`ExplanationResult`): `narrative, cited_chunk_ids[], llm_tier_used, latency_ms, reasoning_unavailable`.
- `emergency_recommendation` (`EmergencyRecommendation`): `triggered, recommended_interventions[], requires_approval, approval_id, llm_tier_used, latency_ms, reasoning_unavailable`.
- `GET /approvals/{id}` / `POST /approvals/{id}/view` / `POST /approvals/{id}/decide` (`ApprovalRecord`): `approval_id, run_id, recommendation_summary, status (pending|approved|rejected), operator_id, decided_at, viewed_evidence`.
- `GET /llm/status`: `{ active_tier, available }`.
- `GET /audit/verify`: `{ ok, rows_checked, first_broken_id, reason }`.
- `GET /scenarios`: list of `{ name, description, ... }`.

Any field not listed here should be read from the live backend response at implementation time, not guessed.

## Pages

### App shell

- Persistent sidebar: Live Monitor / Agent Trace / Approvals (badge = pending-approval count).
- Header: backend connection status (health check, same message text as the current Streamlit app on failure), WS connection indicator, active LLM tier (`/llm/status`).
- Sign-in gate on first load: operator ID only, stored in `operator-context` + `localStorage`, shown as "Signed in as {id}" persistently, threaded automatically into `/approvals/{id}/decide`.

### Live Monitor (`/monitor`) — merges old Overview + Timeline

- No active run: scenario picker (from `/scenarios`) + run-start form (duration override, tick seconds, assessment interval — same fields as today).
- Active run, stacked top to bottom:
  1. KPI row: status, records revealed/total, active risk score (or "novel"), active LLM tier — `tabular-nums`.
  2. Sensor timeline chart (recharts line chart) from `/runs/{id}/readings`: reactor temp/pressure/level: lines highlighted when the corresponding field appears in the latest assessment's `contributing_factors`.
  3. Latest-assessment panel: risk score or explicit "novel condition — low confidence" state (never blank, never a fabricated number), confidence, contributing factors, recommended action, explanation narrative.
- `diverged` / `error` states surfaced as banners, same as current Streamlit warnings.

### Agent Trace (`/trace`) — master-detail

- Audit-chain verification strip at the top (`/audit/verify`), always visible, not tucked in a tab — this is a core safety claim (CLAUDE.md §8).
- Left: list of assessments (index, `t_hours`, risk score or "novel", color-coded), newest first.
- Right: four labeled agent-stage blocks for the selected assessment (Compound-Risk → Compliance → Explanation → Emergency), each showing its cited chunk/SOP IDs and `llm_tier_used`.

### Approvals (`/approvals`) — master-detail

- Left: pending + decided items for the current run (`approval_id`, recommendation summary, status).
- Right: evidence panel (explanation narrative, risk score, compliance notes) + Approve/Reject buttons.
- Approve/Reject stay disabled with a "view evidence first" notice until `viewed_evidence` is true (CLAUDE.md §9/§14 alert-fatigue gate) — identical rule to today, just relocated into the detail pane.
- Decision always requires the signed-in operator ID (auto-filled from shell context).

## Error Handling

| Condition | Behavior |
|---|---|
| Backend unreachable | Shell-level banner ("Cannot reach the backend API…"), rest of UI stays visible but inert — matches current Streamlit message. |
| `reasoning_unavailable: true` on any agent result | Rendered as an explicit "reasoning service unavailable" state on that assessment — never hidden, never silently retried client-side (CLAUDE.md §5/§14 fail-visibly contract). |
| WebSocket drops mid-run | Auto-falls back to 2s polling of `GET /runs/{run_id}`; "reconnecting…" indicator in header; socket retried in background. |
| Approval decision in flight during a drop | Never optimistically applied — row only updates once the server actually responds; a dropped connection cannot show a false "approved" (CLAUDE.md §9.1/§14, same guarantee the backend already provides, preserved client-side). |
| `risk_score: null` (`is_novel_condition: true`) | Rendered as "novel condition, low confidence" — never blank, never a fabricated score. |

## Testing

- **Vitest + React Testing Library:** approval-gate logic (button disabled until `viewed_evidence`), risk-score rendering (`null` → novel-condition state), WebSocket-drop → polling fallback behavior.
- **Playwright, 2 smoke flows against a real running backend:** (1) start a run and see the first assessment arrive; (2) approve a pending recommendation end-to-end with an operator ID.
- Matches this project's existing "test everything safety-relevant" convention (CLAUDE.md §12) rather than skipping it for the new stack.

## Rollout

- Entirely inside `web/` — `backend/` and `frontend/` are untouched.
- Dev workflow: `uvicorn backend.api.main:app --reload` in one terminal, `npm run dev` (inside `web/`) in another.
- `NEXT_PUBLIC_API_BASE_URL` env var, defaulting to `http://127.0.0.1:8000` (same default as the current `DEFAULT_BASE_URL`).
- No deployment/build pipeline requested — out of scope. Local dev-server app, same operating model as the Streamlit app it replaces.

## Out of Scope

- Deployment/hosting/build pipeline.
- Backend changes (none required — CORS already open, all needed endpoints already exist).
- Removing or retiring `frontend/` (left in place as-is).
- Authentication beyond the existing operator-ID-as-string model (no passwords/sessions — matches backend's existing concept of identity).
