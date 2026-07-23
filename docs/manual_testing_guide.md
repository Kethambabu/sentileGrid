# Manual Testing Guide — Swagger UI (`/docs`)

This guide walks through testing the SentinelGrid backend by hand using FastAPI's
auto-generated Swagger UI, no code required. Every step below was verified against
a real, live run of this exact server before being written down — including the
real response bodies you should expect to see.

## Setup

1. Make sure `.env` at the repo root has valid `HF_API_TOKEN` and `GROQ_API_KEY`
   values (see `.env.example` for the variable names — get real values from
   https://huggingface.co/settings/tokens and https://console.groq.com/keys).
2. Start the backend:
   ```bash
   uvicorn backend.api.main:app --reload
   ```
3. Open **http://localhost:8000/docs** in your browser.

You'll see 5 route groups: `scenarios`, `runs`, `approvals`, `audit`, `llm`.

---

## Part 1 — Happy path: run a scenario to a real emergency approval

### Step 1.1 — List scenarios

Expand **GET /scenarios** → **Try it out** → **Execute** (no parameters needed).

You should get a `200` with a JSON array of 6 scenarios. Note the exact `name`
field of each — you'll use one as a literal string in the next step. For this
walkthrough we'll use `reactor_a_feed_loss` (a 6-hour run, one of the faster
scenarios to reach a real emergency escalation).

### Step 1.2 — Start a run

Expand **POST /runs** → **Try it out**. Replace the example request body with:

```json
{
  "scenario_name": "reactor_a_feed_loss",
  "tick_seconds": 0.05,
  "assessment_interval_records": 20
}
```

- `tick_seconds` controls how fast simulated records are "revealed" — 0.05 makes
  this finish in seconds instead of the ~24s the default (0.2) would take for
  this scenario's 120 records.
- `assessment_interval_records: 20` means the full LLM-backed agent pipeline
  (Sensor→Trend→Retrieval→Compound-Risk→Compliance→Explanation→Emergency) only
  runs every 20th record instead of every 5th (the default) — this matters
  because each assessment makes 3–4 **real** calls to Hugging Face/Groq, and
  fewer assessments means faster + cheaper testing. Omit both fields (or use
  the schema's defaults) if you want the full-fidelity default cadence instead.

Click **Execute**. Expect `200` with:
```json
{"run_id": "<some-uuid>"}
```
**Copy this `run_id`** — you'll paste it into every `{run_id}` field below.

### Step 1.3 — Poll run status

Expand **GET /runs/{run_id}** → **Try it out** → paste your `run_id` → **Execute**.
Re-run this every few seconds (there's no auto-refresh in Swagger UI — just
click **Execute** again).

- While running: `"status": "starting"` then `"status": "running"`.
- When done: `"status": "completed"`, `"total_records": 120`,
  `"revealed_count": 120`.

The response also includes `"latest_assessment"` — this is where you'll see the
real risk assessment. **Note:** the *first* assessment or two (early in the run,
soon after the fault starts) will often come back with
`"confidence": "novel"` / `"risk_score": null` even though the LLM is working
fine (`reasoning_unavailable: false`) — this is the retrieval layer correctly
(if a bit eagerly) declining to guess before the window has escalated enough
to confidently match a known incident. It's a known, documented limitation
(see `backend/evaluation/README.md`'s novelty-detection section), not a bug.
Keep polling — by the final assessment near the end of the run, the fault
should have escalated enough to match. In a verified live run against
`reactor_a_feed_loss`, the final assessment looked like this (abbreviated):

```json
{
  "risk_assessment": {
    "risk_score": 85.0,
    "is_novel_condition": false,
    "confidence": "high",
    "recommended_action": "initiate controlled reactor feed-rate reduction and/or prepare for a controlled shutdown sequence",
    "llm_tier_used": "groq",
    "reasoning_unavailable": false
  },
  "compliance_result": { "approved": true, "llm_tier_used": "groq" },
  "explanation": { "narrative": "...", "llm_tier_used": "groq" },
  "emergency_recommendation": {
    "triggered": true,
    "recommended_interventions": ["controlled reactor feed-rate reduction", "controlled shutdown sequence"],
    "approval_id": "<some-uuid>",
    "llm_tier_used": "groq"
  },
  "errors": []
}
```

Note `llm_tier_used: "groq"` throughout — this is the real fallback tier active
right now; yours may say `"huggingface"` instead depending on quota/availability
at the time you run this. **Copy the `approval_id`** from
`emergency_recommendation.approval_id` — you need it for Part 2. (If
`"triggered": false` and `approval_id` is `null`, risk never crossed the
emergency threshold in your run — try again, or use a longer/slower-escalating
scenario like `reactor_kinetics_drift`.)

### Step 1.4 — Check other run endpoints (optional)

- **GET /runs/{run_id}/assessments** — full list of every assessment cycle, not
  just the latest one.
- **GET /runs/{run_id}/readings** — the revealed sensor-reading summaries per
  record (pressure, temperature, level, etc.).

---

## Part 2 — The approval flow (view-gate → decide)

### Step 2.1 — Fetch the approval, confirm it's pending

Expand **GET /approvals/{approval_id}** → **Try it out** → paste the
`approval_id` from Step 1.3 → **Execute**.

Expect `200`:
```json
{
  "approval_id": "...",
  "run_id": "...",
  "recommendation_summary": "controlled reactor feed-rate reduction; controlled shutdown sequence",
  "status": "pending",
  "operator_id": null,
  "decided_at": null,
  "viewed_evidence": false
}
```

### Step 2.2 — Try to decide WITHOUT viewing evidence first (expect 400)

Expand **POST /approvals/{approval_id}/decide** → **Try it out** → paste the
`approval_id` → request body:
```json
{
  "operator_id": "test_operator_1",
  "status": "approved"
}
```
Click **Execute**.

**Expect `400`**, not success — this is the alert-fatigue safeguard (CLAUDE.md
§14) working as designed. Verified real response body:
```json
{
  "detail": "cannot decide on an approval whose evidence/explanation panel has not been viewed (CLAUDE.md §14 alert-fatigue fix — no reflexive-click approvals)"
}
```

### Step 2.3 — Mark evidence viewed

Expand **POST /approvals/{approval_id}/view** → **Try it out** → paste the
`approval_id` (no request body needed) → **Execute**.

Expect `200` with `"viewed_evidence": true` now in the response, `"status"`
still `"pending"`.

### Step 2.4 — Decide again (now expect success)

Repeat Step 2.2's request (same `approval_id`, same body) — **Execute** again.

**Expect `200`** this time:
```json
{
  "approval_id": "...",
  "run_id": "...",
  "status": "approved",
  "operator_id": "test_operator_1",
  "decided_at": "2026-07-23T05:19:11.153913+00:00",
  "viewed_evidence": true
}
```

Try `"status": "rejected"` on a different approval if you want to see that path
too — same view-gate applies.

---

## Part 3 — Cross-cutting checks

### Step 3.1 — Active LLM tier indicator

Expand **GET /llm/status** → **Try it out** → **Execute** (no parameters).

After the run above, expect:
```json
{"active_tier": "groq", "available": true}
```
Before any run has happened since server start, `active_tier` is `null` and
`available` is `false`.

**Quirk worth knowing:** `available` really means *"has the router attempted
at least one call"*, not *"is the LLM currently usable."* If both tiers are
down (see Part 4), you'll see `"active_tier": "unavailable", "available": true`
— `true` because a call was attempted, even though it failed. Don't read
`available: true` as "LLM is working."

### Step 3.2 — Audit hash-chain verification

Expand **GET /audit/verify** → **Try it out** → **Execute**.

Expect `200`:
```json
{"ok": true, "rows_checked": 45, "first_broken_id": null, "reason": null}
```
`rows_checked` will grow as you run more scenarios/decisions — every risk
assessment, compliance check, explanation, emergency recommendation, and human
decision writes a hash-chained row.

---

## Part 4 — Testing the reasoning-service-down path

This is the one thing the automated test suite can't fully substitute for —
seeing the real behavior when both LLM tiers are actually unreachable.

1. **Stop the server** (Ctrl+C in its terminal).
2. Open `.env` and **blank both values** (keep the variable names, empty the
   values):
   ```
   HF_API_TOKEN=
   GROQ_API_KEY=
   ```
3. **Restart** the server: `uvicorn backend.api.main:app --reload`
4. Repeat Part 1 (start a run, e.g. `reactor_a_feed_loss` again, same body as
   Step 1.2) and poll it to completion via **GET /runs/{run_id}**.

**Confirmed real behavior with both keys blanked** (verified live, not
assumed):

- **(i) The run does not crash.** It completes normally with
  `"status": "completed"`.
- **(ii) `GET /llm/status` reports the down state**: `{"active_tier": "unavailable", "available": true}` (see the quirk note in Step 3.1 — `available: true` here just means a call was attempted).
- **(iii) Important — a pending approval does *not* appear, and this is
  correct, expected behavior, not a bug.** The real verified response looks
  like this:
  ```json
  {
    "risk_assessment": {
      "risk_score": null,
      "contributing_factors": ["Reasoning service unavailable — both LLM tiers failed"],
      "llm_tier_used": "unavailable",
      "reasoning_unavailable": true
    },
    "compliance_result": { "approved": false, "reasoning_unavailable": true },
    "explanation": { "narrative": "Reasoning service is currently unavailable — both LLM tiers failed. Manual review required.", "reasoning_unavailable": true },
    "emergency_recommendation": {
      "triggered": false,
      "approval_id": null,
      "reasoning_unavailable": false
    },
    "errors": [
      "compound_risk_agent: reasoning service unavailable (both LLM tiers failed)",
      "compliance_agent: reasoning service unavailable (both LLM tiers failed)",
      "explanation_agent: reasoning service unavailable (both LLM tiers failed)"
    ]
  }
  ```
  **Why no approval appears:** `EmergencyAgent` only ever escalates when it's
  handed a real `risk_score` above the threshold. If the Compound-Risk Agent's
  own LLM call fails (which it will, immediately, if both tiers are down from
  the start of the run), `risk_score` stays `null` — there's nothing to
  threshold-check, so `EmergencyAgent` correctly reports `triggered: false`
  without ever calling an LLM itself. This is the safe, intended behavior: the
  system never manufactures a fake emergency just because it can't reason —
  per CLAUDE.md §9.2, no forced/guessed score, ever.
  The "approval still gets created despite the LLM being down" behavior *does*
  exist in the code, but it protects a narrower, later failure window: if risk
  was *already* determined to be high (Compound-Risk succeeded) and only the
  *Emergency* agent's own subsequent call fails, a pending approval is still
  created with a manual-review placeholder message. Blanking both keys for the
  *entire* run doesn't exercise that narrower path — it exercises the earlier,
  simpler "never even determined a risk score" path instead, which is what the
  `errors` array above is showing you.
- Every one of the 3 LLM-calling agents in this cycle (`compound_risk_agent`,
  `compliance_agent`, `explanation_agent`) reports its own failure in the
  `errors` array — this is real, not a placeholder; it comes from
  `SentinelGridState.errors` populated by the orchestrator graph.

5. **Restore your real keys** in `.env` and restart the server again before
   going back to Part 1–3.

---

## Part 5 — WebSocket streaming (can't be tested from Swagger UI)

Swagger UI doesn't support WebSocket endpoints, so `GET /runs/ws/{run_id}` won't
show up as something you can "Try it out" on. To see the live push behavior,
use a short standalone script instead — save this as `ws_test.py` and run it
with the same `run_id` from a fresh **POST /runs** call:

```python
import asyncio
import websockets

async def main():
    run_id = "PASTE_A_RUN_ID_HERE"
    async with websockets.connect(f"ws://localhost:8000/runs/ws/{run_id}") as ws:
        async for message in ws:
            print(message)

asyncio.run(main())
```

Run it right after starting a new run via **POST /runs** — you'll see a stream
of `{"type": "update", ...}` JSON messages as records are revealed and
assessments complete, ending when the run reaches `"status": "completed"` (or
`"error"`), at which point the server closes the connection. If you request a
`run_id` that doesn't exist, you'll get one `{"type": "error", "message": "No run with id ..."}` message before the connection closes.
