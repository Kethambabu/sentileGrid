# SentinelGrid — Demo Runbook

CLAUDE.md §14's Demo-Specific Risk table calls for two things: a rehearsed live demo, and a pre-recorded backup clip in case venue wifi drops both LLM tiers at once. This document is the script for both — walk through it once live to rehearse, then screen-record yourself walking through it a second time to produce the actual backup clip. Test on the real venue wifi beforehand if at all possible.

## Before the room

1. Confirm `.env` has valid `GEMINI_API_KEY` and `GROQ_API_KEY` (Section 5a) — check the "Active LLM tier" indicator shows a real tier once the first assessment runs, not "unknown."
2. Start the backend: `uvicorn backend.api.main:app --reload`
3. Start the dashboard: `streamlit run frontend/app.py`
4. Open the Streamlit URL. Confirm the top banner reads "Connected to backend API" — if it doesn't, the backend isn't reachable and nothing else will work.
5. Have this runbook and CLAUDE.md open in a second window for reference if a judge asks a question you want to answer precisely.

## Lead scenario: `reactor_a_feed_loss`

Most narratively polished of the five — a clean escalation with a clear "the valve told you 2.5 hours before the pressure did" story. Use this unless a judge specifically asks to see something else.

1. **Overview page.** Select `reactor_a_feed_loss` from the scenario dropdown. Leave duration/tick/assessment-interval at defaults. Click **Start run**.
2. **Narrate while it runs:** "This is replaying a 6-hour simulation compressed into real time. Every 5 records, the agent pipeline — Sensor, Trend, Retrieval, Compound-Risk, Compliance, Explanation — reassesses the current state." Point at the **Active LLM tier** metric: "This shows which of our two free-tier LLM providers actually served the last call — Gemini primary, Groq fallback, with no silent hang if both are down."
3. **Watch the risk score climb.** Early assessments should read LOW with a novel-condition or low-confidence flag (not enough window yet — Section 7.5's fast-only cap). By mid-run it should read MODERATE, climbing to HIGH near the end.
4. **When risk score reads HIGH and an Emergency Agent escalation fires:** point out the red banner ("Emergency Agent escalated — approval_id ... pending"). This is the human-in-the-loop moment: "No code path in this system executes a plant action. It stops here and waits for a human."
5. **Switch to the Approvals page.** Show the pending approval card. Try clicking Approve immediately — it's disabled. Expand "View evidence / explanation," read a line of the narrative aloud, click "Mark evidence as viewed" — now Approve/Reject light up. This is the alert-fatigue fix (Section 14): reflexive clicks are structurally impossible.
6. **Enter an operator ID, click Approve.** Point out the decision now shows "Decided by \<operator_id\> at \<timestamp\>" — accountability is per-decision, not a bare flag.
7. **Switch to Agent Trace.** Show the citation-tagged explanation — which claim is backed by which retrieved chunk — and the hash-chain verification status for the audit log.
8. **Switch to Timeline.** Show the reactor pressure/temperature trend against the risk score overlay — this is the visual version of the compound-risk thesis: no single reading crosses a hard threshold, but the trend does.

## If a judge asks for a different scenario

Reserve `separator_cooling_duty_loss` as the second scenario to show — it has the most visually distinct signature (a pulsing, intermittent pattern rather than a monotonic climb), which makes for a good "not just severity variants of one fault" answer if asked how the fault library varies. `compressor_feed_pressure_loss` is the third-in-reserve, notable for showing a case where the reactor-side readings stay deceptively normal while compressor-side readings show real stress — the clearest illustration of "danger in the relationship between readings, not any one reading."

## Prepared answers

**"Is this real incident data?"** TEP physics are real and published (Downs & Vogel, 1993). The incident/near-miss library is synthetically generated and self-labeled on top of that real simulator — not real plant records. The Vizag (LG Polymers) incident is real-world motivation for why this matters, not a data source. See README.md and CLAUDE.md §14 for the same answer in writing.

**"What happens if both LLM providers are down?"** Start a run on the `baseline` scenario (or just point at the Active LLM tier indicator) and explain: the system shows an explicit "reasoning service unavailable" state rather than hanging or silently retrying forever — this is a tested requirement (Section 5's LLM router), not an assumption.

**"How do you know your retrieval actually generalizes, not just memorizes?"** Point to `backend/evaluation/README.md` — held-out scenario runs, never used to seed the knowledge base, split by run ID per Section 9.3. Be ready to also volunteer the known limitation documented there (novelty-detection false-positive rate) rather than waiting to be asked — it's better disclosed than discovered.

**"Why only 20 fault types?"** TEP is a 1993 published benchmark with 20 defined disturbance types; that's a stated scope limit of the physics layer, not the full extent of what the compound-risk labeling layer above it can eventually cover. Section 14 states this explicitly rather than implying broader coverage than tested.

## After the room

Stop both servers (`Ctrl+C` in each terminal). Don't leave them running unattended.
