# CLAUDE.md — SentinelGrid Project Guide

This file gives Claude Code the context it needs to work on this repo correctly, without re-explaining the project every session. Read this before making changes.

---

## 1. Project Summary

**SentinelGrid** is an AI-powered industrial safety intelligence platform for chemical plants. Instead of simple threshold alarms ("if temp > 90°C, alert"), it detects **compound risk** — situations where multiple sensor readings are individually normal but their _combination and trend_ signal danger — by reasoning over live sensor data, historical incidents, and safety procedures using retrieval-augmented reasoning.

Built for: InnovaHack Chapter 1 (Elite Forums), Team Fantastic Four, Generative AI domain.

**Core thesis to protect in every implementation decision:** danger lives in relationships between readings across time, not in any single reading. Every feature should serve proving this, not dilute it.

---

## 2. Hard Constraints — Never Violate These

- **Zero paid resources.** No paid API tiers, no Azure, no AWS, no Pinecone paid plans, no GPU dependency of any kind.
- **Must run on an 8GB RAM laptop.** Before adding any dependency or model, check its RAM footprint. If in doubt, ask before installing.
- **Everything runs locally except LLM calls**, which use free-tier hosted APIs with a local offline fallback (see Section 5).
- **Python backend.** Don't introduce other backend languages.
- **Human-in-the-loop is non-negotiable.** No code path may ever cause the system to execute a plant action (adjust equipment, force a state change) without an explicit human approval step. If you're implementing the Emergency Agent or any action-taking code, it must terminate at "recommend + await approval," never further. Flag this loudly if you're ever unsure whether a change respects this.
- **No shortcuts on the audit log.** Every risk assessment, recommendation, and human decision must be written to the append-only, hash-chained audit table (Section 8). Don't skip this "to save time" during a feature build — it's load-bearing for the project's core safety claim.

---

## 3. Architecture (Layers, Top to Bottom)

```
frontend (Streamlit)
    ↓ HTTP/WebSocket only — never direct DB access
backend/api (FastAPI)
    ↓
backend/orchestrator (LangGraph state graph)
    ↓
backend/agents (Sensor → Trend → Retrieval → Compound-Risk → Compliance → Explanation → Emergency)
    ↓
backend/rag (retrieval pipeline, consumed by agents, never bypassed)
    ↓
backend/database (SQLite transactional + DuckDB analytics + Chroma/LanceDB vectors)
    ↓
backend/simulation (TEP-based data source)
```

Rule: a layer only talks to the layer directly below it. If you find yourself wiring the frontend straight to the database, or an agent straight to the simulation layer, stop — that breaks the separation this architecture depends on.

---

## 4. Folder Structure

```
sentinelgrid/
├── frontend/                  # Streamlit dashboard
│   ├── pages/                  # overview, timeline, agent trace views
│   └── components/             # reusable widgets
├── backend/
│   ├── api/                    # FastAPI routers — runs, scenarios, approvals, audit, llm_status
│   ├── orchestrator/           # LangGraph graph + typed state schema
│   ├── agents/                 # one file per agent, single responsibility each
│   ├── rag/                    # loaders, chunker, embedder, hybrid retrieval, reranker, numeric similarity
│   ├── knowledge/               # static docs: SOPs, MSDS, chemical_compatibility.csv, incident YAML
│   ├── simulation/              # TEP integration (tep/ process model + controller + faults), scenario_definitions/
│   ├── database/                 # audit.py, approvals.py, vector_store.py, chemical_compatibility.py (DuckDB, exact-match only — see note below)
│   ├── utils/                     # config_loader, llm_router, monitoring
│   ├── evaluation/                 # groundedness/precision/latency/judge scripts — see backend/evaluation/README.md for latest measured numbers
│   └── config/                      # YAML — model names, thresholds, file paths
├── docs/                        # demo_runbook.md, manual_testing_guide.md, project_journey.md
├── logs/                        # audit.log (hash-chained, append-only), monitoring.log
├── tests/                       # pytest, mirrors backend/ structure 1:1 (except tests/fakes.py — see §16)
├── data/                        # generated simulation output, seed knowledge base, evaluation reports
├── requirements.txt
└── README.md
```

When creating a new module, put it in the folder matching its layer above — don't create ad hoc top-level files.

**Note on DuckDB's actual scope:** despite §3/§8 describing DuckDB as also handling trend/analytics queries, the only DuckDB usage in the codebase today is `backend/database/chemical_compatibility.py`'s exact-match lookup (§7.8). No trend/analytics DuckDB layer over the SQLite data has been built yet — don't assume one exists when working in that area.

---

## 5. Tech Stack (What to Use, and What Not to Substitute)

| Purpose               | Use this                                                                                                                                     | Do not substitute with                                                                                                                                                                                                                                                                                                                                                  |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Backend API           | FastAPI                                                                                                                                      | Flask, Django (breaks async assumptions elsewhere)                                                                                                                                                                                                                                                                                                                      |
| Dashboard             | Streamlit                                                                                                                                    | A hand-rolled React app, unless explicitly requested                                                                                                                                                                                                                                                                                                                    |
| Orchestration         | LangGraph                                                                                                                                    | Manual if/else chains — LangGraph's explicit state graph is part of the pitch                                                                                                                                                                                                                                                                                           |
| Vector store          | ChromaDB (LanceDB acceptable if corpus size demands it)                                                                                      | Any paid vector DB (Pinecone paid tier, Weaviate Cloud, etc.)                                                                                                                                                                                                                                                                                                           |
| Relational storage    | SQLite (WAL mode enabled)                                                                                                                    | PostgreSQL/MySQL — adds a server process we don't need                                                                                                                                                                                                                                                                                                                  |
| Analytics/aggregation | DuckDB                                                                                                                                       | Raw pandas loops for windowed aggregation — DuckDB is meaningfully faster and simpler here                                                                                                                                                                                                                                                                              |
| Embeddings            | Sentence-Transformers (bge-small/base)                                                                                                       | OpenAI/paid embedding APIs                                                                                                                                                                                                                                                                                                                                              |
| Simulation            | pyTEP (Tennessee Eastman Process)                                                                                                            | Hand-derived custom ODEs — TEP is the credibility anchor, don't quietly drop it for something "easier"                                                                                                                                                                                                                                                                  |
| LLM reasoning         | Two-tier fallback chain, in order: Google Gemini API (free tier, `gemini-flash-latest`) → Groq (free tier, `llama-3.3-70b-versatile`) | Any single-provider dependency, no local/offline model tier — build the fallback logic as a shared utility (`utils/llm_router.py`) used by every agent, don't hardcode one provider per agent |

**LLM router requirements:** implement retry-with-fallback (timeout or rate-limit on Gemini → try Groq), log which tier actually served each request to the audit trail, and expose the currently-active tier to the frontend for the "active tier" dashboard indicator. If both tiers fail (e.g. no internet), the system must show a clear "reasoning service unavailable" state rather than hanging or silently retrying forever — fail visibly, not silently.

**Provider history (2026-07-23):** the original primary tier was Hugging Face's free Serverless Inference API — since retired entirely (DNS-dead). Its replacement ("Inference Providers") is metered pay-as-you-go with only $0.10/month free credit, exhausted almost immediately at real volume — a genuine external change to this section's zero-paid-resources constraint, not fixable in code. Cerebras was evaluated and rejected next: despite claims of a card-free tier, a real account confirmed a payment method is required before any API access works at all. Gemini was verified live (real success, no billing setup) as the replacement primary tier. See `backend/utils/llm_router.py`'s module docstring for the full account.

**Model name (updated 2026-07-24):** pinned Gemini version names are account/project-dependent — `gemini-2.5-flash` 404'd as "no longer available to new users" on a second real account, and `gemini-2.0-flash`/`-lite` 429'd on the same account. The `-latest` alias (currently `gemini-flash-latest`) is what's configured, since it worked live on both accounts. Re-verify with a live call before assuming any specific pinned version name works.

**Gemini quota is tight — plan test/demo runs around it.** Verified live via a real 429 response body (not vendor docs, which claimed a 20–500/day range): the free tier caps at **20 requests/day, per project+model**. At ~3–4 Gemini calls per assessment cycle, that's roughly **5 full assessments before Gemini falls through to Groq for the rest of the day**. This is expected two-tier behavior, not a bug — but don't burn the quota running repeated manual/eval passes against Gemini specifically without accounting for it; see `backend/config/llm.yaml`'s header comment for the full account.

---

## 5a. Required API Keys

Exactly two keys are needed — everything else in the stack is local/free with no account required.

| Key                       | Where to get it                                                                                               | Env var        | Used by                                                                                    |
| ------------------------- | ------------------------------------------------------------------------------------------------------------- | -------------- | ------------------------------------------------------------------------------------------ |
| Google AI Studio API key  | https://aistudio.google.com/apikey (free, no card)                                                             | `GEMINI_API_KEY` | Primary LLM tier (gemini-2.5-flash): Compound-Risk, Compliance, Explanation agents       |
| Groq API key              | Groq Console — https://console.groq.com/keys (free tier, no card)                                             | `GROQ_API_KEY` | Secondary/fallback LLM tier                                                                |

No key needed for: Sentence-Transformers (downloads weights locally from Hugging Face), ChromaDB/LanceDB, SQLite, DuckDB, or pyTEP.

**Setup rule:** both keys live in a `.env` file at the repo root, read via environment variables in `utils/llm_router.py` — never hardcoded in code. `.env` must be added to `.gitignore` immediately on repo init; it should never be committed.

---

## 6. Agent Contracts

Each agent is a single-responsibility function/class with a typed input and output (Pydantic models), wired together via the LangGraph state object — not free-form message passing.

| Agent               | Input                                     | Output                                                                                                  | Uses LLM?                                             |
| ------------------- | ----------------------------------------- | ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| Sensor Agent        | Raw simulator stream                      | Cleaned window + `sensor_fault` flag if applicable                                                      | No                                                    |
| Trend Agent         | Window sequence                           | Rate-of-change / directional features                                                                   | No                                                    |
| Retrieval Agent     | Window + trend features                   | Ranked evidence chunks (hybrid + reranked)                                                              | No (uses embeddings + reranker model, not a chat LLM) |
| Compound-Risk Agent | Window + trend + evidence                 | Risk score, contributing factors, or "novel condition, low confidence" if similarity is below threshold | Yes                                                   |
| Compliance Agent    | Recommended action + SOP evidence         | Approved/flagged action with cited regulation                                                           | Yes                                                   |
| Explanation Agent   | Risk score + evidence + compliance result | Plain-language narrative                                                                                | Yes                                                   |
| Emergency Agent     | Risk score above threshold                | Recommended interventions — never executes                                                              | Yes                                                   |

Keep LLM calls to exactly these three agents (Compound-Risk, Compliance, Explanation/Emergency can share a call if needed) to stay within free-tier rate limits during a live demo — don't add LLM calls to Sensor/Trend/Retrieval "for consistency."

---

## 6a. What a Single Record Contains

A "record" (the unit that fast/slow windows stack 5 or 20 of) is a full feature-vector snapshot at one timestep — not a single value. It maps onto TEP's standard tag set (XMEAS/XMV), grouped by equipment:

| Equipment                  | Readings in one record                                                     |
| -------------------------- | -------------------------------------------------------------------------- |
| Reactor                    | temperature, pressure, level, feed flow rates (A/B/C/D/E), agitator speed  |
| Compressor                 | recycle valve position, work/power draw, discharge pressure                |
| Pumps                      | flow rate, discharge pressure                                              |
| Heat exchanger / condenser | cooling water inlet/outlet temp, cooling water flow rate, exit stream temp |
| Separator                  | temperature, pressure, liquid level                                        |
| Stripper / tanks / boilers | level, temperature, pressure, steam flow (boiler)                          |

Each record also carries, layered on top of the raw readings:

- `sensor_fault` flag per reading (Sensor Agent output — NaN/flatline/out-of-range, tagged before anything else touches it)
- Worker-presence flag (custom compound-risk layer — is a person near this equipment right now)
- Rate-of-change / trend features (Trend Agent output — deltas derived across the window, not raw)

Don't reduce a record to "one sensor value" anywhere in the pipeline — the fast/slow windows in Section 7 stack full snapshots like this, not scalars.

---

## 6b. Synthetic Sensors Not Native to TEP

`methane_ppm`, `vibration_mm_s`, and `valve_health_pct` do not exist in pyTEP's output — they are a synthetic layer built on top of it, and must be calculated from real TEP variables + scenario config, not random noise:

- **methane_ppm** — baseline value, increased a bit when pressure rises more than normal (a leak often follows pressure buildup). Which fault scenarios trigger this and by how much is set per scenario in `backend/simulation/scenario_definitions`, not hardcoded.
- **vibration_mm_s** — baseline value, increased when a motor/valve is moving faster or more erratically than its normal speed.
- **valve_health_pct** — starts at 100 and only ever decreases over time (never bounces back up), wearing down faster when that valve is under heavier stress.

State this distinction explicitly in any judge-facing material: native TEP variables (temperature, pressure, flow) are real physics; these three are documented synthetic proxies for failure modes TEP doesn't simulate, calculated with a stated method — not fabricated data dressed up as real.

**Record scoping:** each part of the plant only reports on its own equipment, not everything — a record only contains the fields relevant to its own zone (e.g. a Reactor Bay record carries reactor fields + methane/vibration/valve-health if applicable; a Heat Exchanger record carries its own cooling-water fields instead, not the reactor's fields). Section 6a's table is the full universe of possible fields across all zones, not a requirement that every record contain every field.

---

## 7. RAG Pipeline Requirements

1. Separate loaders per source type (PDF SOPs vs. plain-text incidents vs. structured simulation windows) — don't force one generic loader.
2. Static docs: ~300-token overlapping chunks.
3. **Simulation windows use a dual-window chunking scheme, not a single window:**
   - Each knowledge-base chunk stores **two windows together**: a **fast window** (5 records — short-term/recent pattern) and a **slow window** (20 records — long-term/overall pattern), plus its label (scenario type, risk level, etc.).
   - **Each historical incident must be authored as multiple chunks along its own progression** (e.g. early-warning, mid-escalation, critical stages), each with its own fast+slow window pair at that point in the incident — not one chunk representing only the incident's final state. Otherwise an early-stage live window has nothing fair to match against, since it would only ever be compared to a chunk representing the incident's escalated end-state.
4. **Live retrieval sequence:**
   - Records 1–4 arriving: not enough for a fast window yet — no retrieval runs.
   - Record 5 arrives: first fast window exists (records 1–5). Retrieval compares this fast window against **every chunk's fast window** only (no slow window exists yet on the live side).
   - Records 6–19: fast window slides forward by one record each time (2–6, 3–7, ... 15–19); same fast-window-only comparison repeats against the full KB each time.
   - Record 20 arrives: slow window now exists too (records 1–20), alongside the fast window (16–20). From here on, retrieval compares **both parts at once** — fast-vs-fast and slow-vs-slow — against every chunk. A chunk counts as a strong match only when both parts line up well.
   - Record 21 onward: both windows keep sliding together (fast: 17–21, slow: 2–21); the full two-part comparison against the whole KB repeats every new record, indefinitely.
   - This "compare against every chunk" step is performed via the vector index's approximate-nearest-neighbor search (ChromaDB/LanceDB), not a literal brute-force Python loop — describe it that way in any judge-facing material.
5. **Confidence must differ by phase:** a strong match found during the fast-window-only phase (minutes 5–19) is less trustworthy than a strong match found once fast+slow are combined (minute 20+), since less context is available. Cap the Compound-Risk Agent's reported confidence at "moderate" during the fast-only phase even if the raw similarity score is high — don't let it report full confidence on half the evidence.
6. Hybrid retrieval: dense (embeddings) + BM25 keyword, merged.
7. Re-rank top candidates with a small cross-encoder before handing to the LLM.
8. **Chemical compatibility data does not go through RAG** — it's an exact-match lookup, load it into DuckDB/SQLite directly. Don't embed it just for consistency.
9. Prompt template must explicitly label retrieved content as **reference data, not instructions** — this is a security requirement (see Section 9), not a style preference.
10. Output must tag which claim is supported by which retrieved chunk (grounded output) — this is required for the evaluation harness in Section 10, don't treat it as optional polish.
11. Note the startup gap: no retrieval-based signal exists for the first 4 live records (Trend Agent's plain-math signal still runs). This is an accepted trade-off for a compressed-time demo — state it explicitly if asked, don't leave it as a silent gap.

---

## 8. Database & Audit Requirements

- SQLite: enable WAL mode. Funnel all writes through a single async queue/worker — don't let multiple agents write directly and concurrently.
- Audit table: append-only at the application layer, **and** hash-chained (each row stores a hash of the previous row + its own content). Implement and test the hash-chain verifier as part of Phase 6 — it's a testable requirement, not a nice-to-have.
- DuckDB: used for trend/analytics queries over the SQLite data — query directly, no separate ETL step needed.

---

## 9. Security / Robustness Requirements (Non-Negotiable)

These came out of an explicit adversarial review of the architecture — implement them alongside the features they affect, not as a final pass:

1. **Approval disconnect → default to "pending," never "approved."** Test this explicitly.
2. **Low-retrieval-confidence → explicit "novel condition" output**, never a forced/guessed risk score.
3. **Train/test split by scenario run ID**, not by window, when building the evaluation set — seeding the knowledge base and evaluating retrieval precision from the same runs is invalid and must not happen.
4. **Retrieved text is never executed as instructions.** If you're prompting an LLM with retrieved chunks, the prompt template must clearly delimit them as data.
5. **Evaluation judge model must differ from the model that produced the original answer** being judged — no self-grading.
6. **Sensor faults (flatline, NaN, out-of-physical-range) get tagged separately from process anomalies** by the Sensor Agent, before reaching Trend/Retrieval/Risk agents.

---

## 10. Evaluation Harness Requirements

Build `backend/evaluation/` in parallel with the agents it evaluates, not after. Required metrics: retrieval precision/recall (held-out runs only, see Section 9.3), groundedness, hallucination rate, risk accuracy, latency per agent call, explainability score (citation completeness). Every number in any report must come from an actual script run in this folder — no placeholder numbers.

---

## 11. Development Phases (Build in This Order)

1. Simulation core (pyTEP integration, verify realistic output) — no other module depends on being built first.
2. Windowing + labeling + knowledge base seeding (SOPs/MSDS/incidents into vector store).
3. RAG pipeline (retriever + reranker + prompt builder), test against Phase 2 data.
4. Agent layer + LangGraph orchestration, first end-to-end assessment.
5. API + dashboard.
6. Audit/monitoring + evaluation harness, make human-approval loop fully real.
7. Scenario library + polish + demo rehearsal.

When asked to implement something, check which phase it belongs to and flag if a prerequisite from an earlier phase isn't done yet, rather than building out of order.

---

## 12. Coding Conventions

- Type-hint everything; use Pydantic models for all agent inputs/outputs and API request/response schemas.
- One responsibility per agent file — if an agent file is doing two things, split it.
- Config (model names, thresholds, file paths) goes in `backend/config/`, never hardcoded inline.
- Tests live in `tests/`, mirroring `backend/` — write a test alongside any new agent or pipeline stage, especially for the Section 9 requirements, since those are exactly the kind of thing that silently regresses if untested.
- Prefer explicit, readable code over clever one-liners — this codebase needs to be explainable to judges in a 5-minute walkthrough.

---

## 13. When Claude Code Should Ask Before Proceeding

- Before adding any new dependency — check RAM/CPU footprint against the 8GB constraint first.
- Before touching anything in the human-approval or audit-logging path — these are the project's core safety claims, not routine code.
- Before changing the LLM fallback order or removing the remaining fallback tier.
- Before switching TEP for a custom/simplified simulator "for speed" — this is a deliberate credibility decision, don't quietly reverse it.

---

## 14. Known Edge Cases and How We Solve Them

This section is the accumulated result of an adversarial review of the architecture. Treat every row as a real requirement to implement, not a hypothetical — each one was found by asking "where does this break," and each fix should land in code alongside the feature it protects, not as a final pre-demo pass.

### Simulation / Data Layer

| Edge case                                                                          | Fix                                                                                                                                                                                           |
| ---------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Sensor looks broken vs. process actually failing (flatline, NaN, impossible value) | Sensor Agent validates range/continuity _before_ anything else touches the reading; tags it `sensor_fault` and routes it separately so it's never reasoned over as a real anomaly             |
| TEP's ~20 defined fault types don't cover every real-world scenario                | Be explicit in docs/pitch about this scope limit rather than implying broader coverage than tested; the compound-risk labeling layer on top of TEP is where coverage is deliberately extended |
| Fast-forwarded simulation time misaligns window boundaries                         | Use slightly overlapping windows (not strictly non-overlapping) so a transition near an edge is still captured cleanly in at least one window                                                 |

### Retrieval / Memory (RAG)

| Edge case                                                              | Fix                                                                                                                                               |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| No similar past incident exists for the current window                 | Below a similarity threshold, output "novel condition, low confidence" instead of a forced risk score — never let the LLM guess with no grounding |
| Retrieval returns a superficially similar but causally wrong precedent | Filter by metadata (zone, equipment type, scenario category) before vector search, not just raw numeric similarity                                |
| Knowledge base is too small/repetitive, inflating precision metrics    | Author scenarios varying in cause, not just severity; track distinct scenario types represented, not just window count                            |
| Evaluation data leakage (seed and eval scenarios overlap)              | Split by scenario run ID, never by window — seed from one set of runs, evaluate only on held-out runs never ingested                              |
| **Known open gap:** §9.2's "novel condition, low confidence" trigger essentially never fires — measured 100% false-positive rate on negative-control (no-fault) windows | Root-caused to embedding-similarity compression (`bge-small-en-v1.5` cosine scores compress into a ~1%-wide band near 1.0 regardless of match correctness — statistically indistinguishable). A supplementary numeric feature-vector similarity channel was built and gives real wrong-vs-correct discrimination, but does NOT close the gap (baseline windows still score as similar as genuine matches, for a different structural reason — near-zero deviation vectors always look close to each other). A relative/comparative novelty signal was also tried and discarded as a genuine negative result. Full measured numbers, root causes, and the next concrete unimplemented fix (gate on live window's own deviation magnitude before comparing to the KB at all): `backend/evaluation/README.md`. Don't re-attempt a plain threshold tweak on either similarity channel without reading that writeup first — it documents which approaches were already tried and why they failed. |

### LLM Reasoning Layer

| Edge case                                                               | Fix                                                                                                                                                                                                                                             |
| ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Both free tiers (Gemini + Groq) fail or rate-limit simultaneously | Show a clear "reasoning service unavailable" state, never a silent hang or infinite retry. There is no third/offline tier (Ollama was explicitly removed) — keep a short pre-recorded demo clip as day-of insurance against this exact scenario |
| Free-tier rate limits hit during a demo burst of repeated queries       | Cache identical/near-identical window queries for a few seconds to avoid multiplying real API calls                                                                                                                                             |
| Inconsistent risk scores on repeated calls to the same input            | Set low temperature and constrained/structured JSON output for the Compound-Risk Agent specifically; reserve higher creativity for the Explanation Agent only                                                                                   |
| Prompt injection via text embedded in a retrieved document              | Wrap all retrieved chunks in a clearly delimited block (e.g. `<reference_data>...</reference_data>`) with an explicit instruction to treat it as data to analyze, never as instructions to follow                                               |
| Self-grading evaluation (same model answers and judges)                 | Use a different model/tier to judge groundedness than the one that produced the original answer being judged                                                                                                                                    |

### Human-in-the-Loop / Safety Layer

| Edge case                                          | Fix                                                                                                                                  |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Approval-screen disconnects mid-assessment         | Default state is always "pending" — a dropped connection must never resolve to "approved"                                            |
| Alert fatigue leading to reflexive approval clicks | Require the human to have viewed the explanation/evidence panel (track a "viewed" state) before the approve button becomes clickable |
| Ambiguous accountability for who approved what     | Every audit entry logs a specific operator ID with the decision, not just a bare approved/rejected flag                              |

### Storage / Infrastructure

| Edge case                                                            | Fix                                                                                                                                                       |
| -------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SQLite write contention under concurrent agent writes                | WAL mode enabled, all writes funneled through a single async queue/worker                                                                                 |
| Audit log could be edited without detection                          | Hash-chain every entry (hash of previous entry + own content); implement and test the verifier                                                            |
| Non-persistent disk on free cloud hosting (e.g. Hugging Face Spaces) | Pre-build and commit the vector index and seed database into the repo so a restart reloads from disk instead of re-ingesting live                         |
| Cold start / first-run delay on a new machine                        | Provide a one-command setup script that pre-downloads embedding models and pre-loads the vector index ahead of demo day; document expected first-run time |

### Demo-Specific Risk

| Edge case                                                  | Fix                                                                                                                                                                                                                                          |
| ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Venue wifi drops (kills both LLM tiers at once)            | Pre-recorded backup demo clip; test actual venue wifi beforehand if possible                                                                                                                                                                 |
| Judge asks to see a scenario outside the pre-built library | Build at least 4–5 scenarios spanning genuinely different fault types, not just severity variations of one                                                                                                                                   |
| "Is this real incident data?" question from a judge        | Have the honest answer ready: TEP physics are real and published; the incident/near-miss library is synthetically generated and self-labeled on top of that real simulator; the Vizag incident is real-world motivation, not the data source |

**Priority if time is short:** implement the evaluation-leakage fix and verify it in code (not just described), and have the pre-recorded demo backup ready — these two are the highest-consequence items on this list.

---

## 15. Useful Commands

All verified against the real repo as of Phase 7. On Windows/PowerShell, activate with `.venv\Scripts\Activate.ps1` instead of `source .venv/bin/activate`; the rest are identical cross-platform (`python -m ...` module invocations).

```bash
# Setup
python -m venv .venv && source .venv/bin/activate      # or .venv\Scripts\Activate.ps1 on Windows
pip install -r requirements.txt

# Run backend (from repo root; needs GEMINI_API_KEY / GROQ_API_KEY in .env for Phase 4+ agent calls)
uvicorn backend.api.main:app --reload

# Run dashboard (in a second terminal, with the backend already running)
streamlit run frontend/app.py

# Run a single simulation scenario (writes data/simulation_runs/<scenario>_<run_id>.csv)
python -m backend.simulation.run_simulation --scenario baseline
python -m backend.simulation.run_simulation --scenario reactor_a_feed_loss

# Re-seed the RAG knowledge base (SOPs/MSDS/incidents -> ChromaDB) after
# editing anything in backend/knowledge/ or adding a new scenario+incident
python -m backend.rag.seed_knowledge_base

# Generate held-out evaluation runs (CLAUDE.md §9.3 — never used to seed the KB)
python -m backend.evaluation.generate_holdout_runs

# Run the full evaluation harness (retrieval, groundedness, hallucination,
# risk accuracy, latency — real LLM calls, writes data/evaluation/reports/)
python -m backend.evaluation.run_eval

# Run tests
pytest tests/

# Run tests for one layer only (mirrors backend/ 1:1)
pytest tests/rag/
pytest tests/agents/
```

**Scenario library** (`backend/simulation/scenario_definitions/*.yaml`, 5 fault scenarios + baseline): `reactor_a_feed_loss`, `reactor_cw_valve_stiction`, `reactor_kinetics_drift`, `compressor_feed_pressure_loss`, `separator_cooling_duty_loss`. Adding a new one: write the scenario YAML, run it, rename the output to `data/simulation_runs/<name>_seed.csv`, author `backend/knowledge/incidents/<name>.yaml` against the real values in that CSV, then re-seed. See `backend/evaluation/README.md` for current measured retrieval/groundedness/risk-accuracy numbers and known limitations.

---

## 16. Implementation Notes Not Covered Above

- **`utils/llm_router.py` deliberately does not import `backend.database`.** It sits below the agent/orchestrator layer (Section 3) and must not depend upward on it. Callers that want a response written to the audit trail pass an `on_response` callback into `LLMRouter`; the router itself has no opinion on whether or how that happens. Keep this direction if you touch the router — audit-logging belongs in the agent/orchestrator node, not inside `llm_router.py`.
- **Shared LLM test doubles live in `tests/fakes.py`**, not mirrored under any single `backend/` subpackage — the one deliberate exception to the "tests/ mirrors backend/ 1:1" rule (Section 12), because `FakeLLMProvider` and `ScriptedLLMProvider` are reused across `tests/agents/`, `tests/orchestrator/`, and `tests/utils/`. Use `ScriptedLLMProvider` (keyword-routed canned responses) when a single fake provider needs to stand in for multiple LLM-calling agents at once, e.g. testing the full graph in `tests/orchestrator/test_graph.py`.
- **No linter/formatter is configured** (no ruff/flake8/black/pyproject.toml in the repo). Don't assume one or invent a lint command — `pytest tests/` is the only verification command that currently exists alongside manual review.
