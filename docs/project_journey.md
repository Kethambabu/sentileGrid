# SentinelGrid — Complete Project Reference & Development Journey

This document covers the project end-to-end: what it is, how every piece works,
every model/agent involved, and — separately — the full story of what was
found wrong during review, how each issue was fixed, and what's still open.
Everything here reflects the actual code and real, live-verified test results
as of this writing, not aspirational design.

---

## Part 1 — What SentinelGrid Is

**Core thesis:** danger in a chemical plant often lives in the *relationship
and trend* between multiple sensor readings over time, not in any single
reading crossing a threshold. A simple alarm ("if temp > 90°C") misses this.
SentinelGrid detects compound risk by reasoning over live sensor data,
historical incidents, and safety procedures using retrieval-augmented
reasoning, and it never takes plant-changing action itself — every
recommendation stops at a human approval gate.

Built for InnovaHack Chapter 1, Team Fantastic Four, Generative AI domain.

### Hard constraints the whole design serves
- Zero paid resources, runs on an 8GB RAM laptop, everything local except the
  two LLM calls (which use free-tier hosted APIs with no offline fallback).
- Human-in-the-loop is structural, not a convention: no code path can ever
  execute a plant action. Everything terminates at "recommend + await
  approval."
- Every risk assessment, recommendation, and human decision is written to an
  append-only, hash-chained audit table — this is load-bearing for the
  project's safety claim, not decoration.

---

## Part 2 — Architecture

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
backend/database (SQLite transactional + DuckDB analytics + ChromaDB vectors)
    ↓
backend/simulation (Tennessee Eastman Process simulator)
```

A layer only ever talks to the layer directly below it. The frontend never
touches the database or orchestrator directly; agents never call the
simulator directly.

### Folder structure
```
backend/
├── api/            FastAPI routers — runs, approvals, audit, llm, scenarios
├── orchestrator/    LangGraph graph + typed state schema
├── agents/          one file per agent, single responsibility each
├── rag/             loader, chunker, embedder, retriever, reranker
├── knowledge/       static docs: SOPs, MSDS, incidents (near-miss library)
├── simulation/       TEP integration, synthetic sensors, scenario definitions
├── database/         SQLite models, DuckDB views, ChromaDB vector store client
├── utils/             config loader, LLM router, monitoring
├── evaluation/          groundedness/precision/latency scripts, judge harness
└── config/               YAML — model names, thresholds, file paths
```

---

## Part 3 — The Models and Services Actually In Use

| Purpose | Technology | Notes |
| --- | --- | --- |
| Simulation | **pyTEP** (Tennessee Eastman Process) | Real published chemical-process physics (Downs & Vogel, 1993), not a simplified stand-in — a line-by-line port of the reference Fortran model. |
| Reasoning LLM (primary) | **Google Gemini** (`gemini-flash-latest`, currently resolving to `gemini-3.6-flash`) | Free, card-free, verified live. See Part 6 for the full story of how this was chosen. |
| Reasoning LLM (fallback) | **Groq** (`llama-3.3-70b-versatile`) | Free tier, independent company/infrastructure from Gemini — genuine redundancy. |
| Embeddings | **Sentence-Transformers** (`BAAI/bge-small-en-v1.5`) | Local, no API key needed. |
| Reranking | **Cross-encoder** (`cross-encoder/ms-marco-MiniLM-L-6-v2`) | Local, small model. |
| Vector store | **ChromaDB** (persistent, on-disk) | `chromadb==0.5.23` specifically — see Part 5's environment section for why. |
| Relational storage | **SQLite** (WAL mode) | Audit log + approvals, funneled through a single async write queue. |
| Analytics | **DuckDB** | Trend/analytics queries directly over SQLite data. |
| Orchestration | **LangGraph** | Explicit typed state graph, not manual if/else chains. |
| API | **FastAPI** | |
| Dashboard | **Streamlit** | |

### API keys needed
Two, both free/card-free: `GEMINI_API_KEY` (https://aistudio.google.com/apikey)
and `GROQ_API_KEY` (https://console.groq.com/keys). Both live in a
git-ignored `.env` file at the repo root — never committed, never hardcoded.

---

## Part 4 — The Agent Pipeline (all 7 agents)

Each agent is single-responsibility, typed Pydantic input/output, wired
through a LangGraph state object (`SentinelGridState`) — never free-form
message passing. They run in this fixed order every assessment cycle:

| # | Agent | Input | Output | Uses LLM? |
| - | --- | --- | --- | --- |
| 1 | **Sensor Agent** | Raw simulator stream | Cleaned window + `sensor_fault` flag per reading (NaN/flatline/out-of-range) | No |
| 2 | **Trend Agent** | Cleaned window | Rate-of-change / directional features per channel | No |
| 3 | **Retrieval Agent** | Window + trend features | Ranked evidence chunks (hybrid dense+BM25 search + cross-encoder rerank) | No — embeddings + reranker, not a chat LLM |
| 4 | **Compound-Risk Agent** | Window + trend + evidence | Risk score (0-100) or `None` if "novel condition", contributing factors, recommended action | **Yes** (temp 0.1, JSON mode) |
| 5 | **Compliance Agent** | Recommended action + SOP evidence | Approved/flagged action with cited regulation | **Yes** (temp 0.1, JSON mode) |
| 6 | **Explanation Agent** | Risk score + evidence + compliance result | Plain-language narrative with inline chunk citations | **Yes** (temp 0.7, plain text — the one agent allowed creativity) |
| 7 | **Emergency Agent** | Risk score above threshold (80.0) | Recommended interventions — **never executes anything** | **Yes** (temp 0.3, JSON mode) |

### Why this order, and what's structurally guaranteed
- **Sensor faults never reach the reasoning agents as real anomalies.** The
  Sensor Agent tags NaN/flatline/out-of-range readings *before* Trend or
  Retrieval ever see them.
- **A "novel condition" (no real precedent found) forces `risk_score = None`
  at the code level**, regardless of what the LLM returns — this is enforced
  in `compound_risk_agent.py` after JSON parsing, not a prompt-level request
  the model could ignore.
- **The Emergency Agent has no execute/apply/act method anywhere in the file
  — on purpose.** There's a dedicated test
  (`test_emergency_agent_has_no_execution_method`) that asserts a blocklist
  of method names is disjoint from the class's public methods, specifically
  so this can never silently regress.
- **Every emergency recommendation becomes a `PENDING` approval**, never
  anything else. A human must explicitly view the evidence panel
  (`viewed_evidence` flag) before the decide endpoint will even accept a
  decision — this is enforced server-side, tested, and was re-verified live
  through the actual API (see Part 8).

---

## Part 5 — The RAG Pipeline

### Dual-window chunking (the core retrieval design)
Every knowledge-base chunk stores **two windows together**: a **fast window**
(5 records — short-term pattern) and a **slow window** (20 records —
long-term pattern), plus a label. Each historical incident is authored as
*multiple* chunks along its own progression (early-warning → mid-escalation →
critical), each with its own fast+slow pair at that point in the incident —
otherwise an early-stage live window has nothing fair to match against.

### Live retrieval sequence
- Records 1–4: not enough for a fast window — no retrieval runs yet.
- Record 5 onward (until 20): fast-window-only comparison against every
  chunk's fast window.
- Record 20 onward: fast+slow combined — a chunk only counts as a strong
  match if **both** windows line up well (the combined score is
  `min(fast_similarity, slow_similarity)`, not an average, so one strong +
  one weak match doesn't read as an overall strong match).
- Confidence is capped at "moderate" during the fast-only phase, even on a
  high raw similarity score, since less context is available.

### Hybrid retrieval + reranking
Dense (embedding) search and BM25 keyword search are merged via reciprocal
rank fusion, then the top candidates are re-ranked by a small cross-encoder
before being handed to the LLM. Chemical compatibility data deliberately
**does not** go through this pipeline — it's an exact-match DuckDB/SQLite
lookup, since embedding it would add noise for no benefit.

### The novelty-detection problem (see Part 7 Fix 2 for the full story)
The system is supposed to output "novel condition, low confidence" instead
of a forced risk score whenever retrieval doesn't genuinely support one. This
was found broken (text-embedding similarity doesn't discriminate at all —
every window looks ~99.6% similar to everything, correct or not) and a fix
was attempted (a numeric feature-vector channel computed directly from
sensor deviations). **The fix is real but partial** — see Part 7 for the
measured numbers and the honest verdict.

---

## Part 6 — The Database & Audit Layer

- SQLite with WAL mode enabled; all writes funneled through a single async
  queue/worker, not concurrent direct writes.
- The audit table is append-only at the application layer **and**
  hash-chained: each row stores a hash of the previous row's hash plus its
  own content. A dedicated verifier (`verify_chain()`, exposed at
  `GET /audit/verify`) walks the whole table and detects both content
  tampering and row deletion. This was live-verified through the real API
  multiple times during testing (351 rows checked, clean, in the final
  session).
- Approval records: `PENDING` is always the default and the only way in;
  a decision requires both `viewed_evidence=True` and a non-empty
  `operator_id`; a dropped connection or any lookup failure resolves to
  `PENDING`, never `APPROVED`. All of this was re-verified live, not just in
  unit tests (see Part 8).

---

## Part 7 — The Full Story: Audit Findings, Fixes, and What Happened

This section is the actual chronological account of the work done on this
codebase in this session — an initial deep audit, three critical fixes
chosen from that audit, and then a long, honest debugging saga getting the
LLM provider layer to genuinely work.

### 7.1 — The initial audit

Three parallel deep-read reviews covered every layer: agents/orchestrator,
RAG/database, and API/simulation/utils/evaluation. Overall verdict: **well
above hackathon-grade** — real TEP physics, structurally-enforced (not just
conventional) safety guarantees, genuine adversarial tests, honest
self-documentation of known gaps. Three critical findings were chosen to fix:

1. **No agent or orchestrator node caught `ReasoningServiceUnavailableError`**
   (both LLM tiers down) — it crashed the whole assessment run instead of
   degrading visibly, and the Emergency Agent could skip creating an approval
   record for an already-detected emergency if the LLM failed at exactly that
   step.
2. **The novelty-detection safety gate was non-functional** — cosine
   similarity on templated text compresses into a ~1%-wide band regardless of
   match correctness, so "novel condition, never force a score" almost never
   fired.
3. **`synthetic_sensors.py` was a Phase-1 stub** — `methane_ppm`,
   `vibration_mm_s`, `valve_health_pct` always returned a fixed baseline,
   silently consumed downstream (chunker embeddings, sensor-fault validation)
   as if real.

### 7.2 — Fix 1: reasoning-service-unavailable handling

**What was wrong:** if both LLM tiers failed mid-assessment, the exception
propagated uncaught through the whole LangGraph run, crashing it. Worse,
if risk had already been determined to be high and *only* the Emergency
Agent's own call failed, no approval record was created for a real,
detected emergency.

**What was implemented:**
- Every one of the four LLM-calling agents (`compound_risk_agent.py`,
  `compliance_agent.py`, `explanation_agent.py`, `emergency_agent.py`) now
  catches `ReasoningServiceUnavailableError` and returns a safe, explicitly
  flagged result (`reasoning_unavailable: bool` added to every result model)
  instead of raising.
- **Critically, `EmergencyAgent` still creates a pending approval record
  even if its own LLM call fails**, with a generic "escalate to on-call
  operator for manual review" message — the approval record is decoupled
  from whether the LLM successfully generated recommendation text.
- `SentinelGridState.errors` (a field that existed in the schema but was
  never written to or read anywhere — confirmed dead code by a full-repo
  grep) is now populated by each orchestrator node and surfaced through the
  API's per-assessment response.

**Verification:** unit tests added for all four agents plus two new
orchestrator integration tests (novel-condition end-to-end, both-tiers-down
end-to-end). Later, live-tested for real by blanking both API keys, starting
a real run, and confirming: no crash, `errors` array correctly populated,
`emergency_recommendation.triggered: false` (correctly — you can't declare
an emergency when you never determined a real risk score).

### 7.3 — Fix 3: synthetic sensor layer implementation

**What was wrong:** `methane_ppm`/`vibration_mm_s`/`valve_health_pct` always
returned the same fixed baseline values regardless of actual plant state,
despite CLAUDE.md §6b requiring them to be calculated from real TEP variables
+ scenario config. Downstream code (the RAG chunker, the sensor-fault
validator) consumed this stub output as if it were real.

**What was implemented:**
- `SyntheticSensorLayer` made stateful (tracking previous pressure, previous
  valve positions, a rolling erraticness window, cumulative valve wear).
- `methane_ppm` now tracks the *rate* of reactor pressure rise (a leak often
  follows pressure buildup).
- `vibration_mm_s` now tracks valve-position erraticness (standard deviation
  of recent position deltas on scenario-designated "watched" valves).
- `valve_health_pct` only ever decreases, wearing faster under higher stress
  — enforced by construction (always subtracting a non-negative amount).
- A new typed `SyntheticSensorRules` schema replaced the previously-unused
  `synthetic_sensor_rules: dict` field on `ScenarioConfig`, threaded through
  `SimulationRunConfig` into the simulator.
- All 6 seed simulation runs (baseline + 5 fault scenarios) regenerated with
  real dynamic synthetic-sensor values instead of flat stub data.

**Verification:** full test suite for the new formulas (pressure-rise →
methane increase, valve erraticness → vibration increase, monotonic
non-increasing valve health across randomized sequences), plus an
end-to-end simulator test confirming rules flow through from a
`ScenarioConfig` to real varying output.

### 7.4 — Fix 2: numeric feature-vector similarity channel (honest partial fix)

**What was wrong:** measured directly — `bge-small-en-v1.5` cosine
similarity on templated window-description text is statistically
indistinguishable between correct matches (mean 0.9969), wrong matches
(0.9963), and true negatives (0.9960). No threshold, however tuned, can
separate these. Result: **100% false-positive rate** on the negative
control in the original evaluation.

**What was implemented:** a supplementary similarity channel computed
directly on the raw numeric window vectors (deviation-from-baseline across
16 summary channels, normalized by per-channel-group thresholds), rather
than on embedded text — attacking the actual root cause (boilerplate text
dominance) instead of working around it. New module
`backend/rag/numeric_similarity.py`; `chunker.py` gained
`compute_feature_vector()`; `retriever.py`'s novelty decision now uses this
channel instead of raw cosine similarity.

**What was measured (3 independent real passes against held-out data):**

| group | pass 1 | pass 2 | pass 3 |
| --- | --- | --- | --- |
| fault run, correct top-1 match | 0.227 | 0.262 | 0.193 |
| fault run, wrong top-1 match | 0.174 | 0.156 | 0.206 |
| baseline (should be "novel") | 0.313 | 0.266 | 0.333 |

**Honest verdict:** this is a **real, partial improvement** — "wrong" vs
"correct" match discrimination is now genuine signal that didn't exist
before. But in **all three** independent passes, the baseline group's mean
similarity *exceeds* the fault-correct group's mean — the opposite of what
novelty detection needs. Root cause: a flat/no-fault window's deviation
vector is near-zero across all channels, and near-zero vectors are always
numerically close to *any other* near-zero vector (including an incident's
own early, pre-escalation stage), regardless of whether they represent the
same real precedent. **This means no single global threshold on this metric
can correctly separate "no fault" from "genuine fault, correctly matched."**
Three thresholds were tested live: 0.5 (universal caution — 100% of both
fault and negative samples flagged novel, zero usable risk scores ever),
0.20 (100% false-positive rate *and* 58.6% of real faults suppressed — worse
on both axes), and the current 0.25 (a documented best-effort compromise,
explicitly not claimed as validated). The flagged, unimplemented next step:
gate on the *live window's own* deviation magnitude as a first-pass filter,
independent of best-match similarity to any KB chunk.

### 7.5 — Environment repair (a full day of its own)

Before any of the above could even be tested, the development machine
itself had a cascade of native-dependency problems:

1. **Torch/chromadb/onnxruntime all crashed with DLL initialization
   errors.** Root cause: the system's `msvcp140.dll` (VS2019-era) was too
   old for modern compiled builds of these libraries. Fixed by pinning
   older, compatible versions in a fresh `.venv`:
   `torch==2.1.2+cpu`, `numpy<2`, `transformers==4.41.2`,
   `chromadb==0.5.23` (pre-Rust-backend), `onnxruntime==1.17.3`.
2. Full test suite re-verified clean after the pin: 183 passed, 0 failed.

### 7.6 — The LLM provider saga

This is the longest thread of the whole session and worth documenting in
full, since every step was verified against a real account/key, not
assumed from documentation:

1. **Hugging Face's free Serverless Inference API is gone.**
   `api-inference.huggingface.co` no longer resolves at all (confirmed via
   DNS lookup and a live call). Its replacement (`router.huggingface.co`,
   "Inference Providers") is a metered, pay-as-you-go service — free
   accounts get **$0.10/month** credit, exhausted almost immediately at real
   usage. A provider (`featherless-ai`) was found and wired up as a stopgap,
   with the token-permission requirement ("Make calls to Inference
   Providers," not on by default) discovered and worked around.
2. **Cerebras was evaluated as a replacement and rejected.** Despite
   third-party blog claims of a card-free ongoing free tier ("1M
   tokens/day"), a real account hit a real `402 Payment Required` — Cerebras
   currently requires a verified payment method before *any* API access
   works, even to unlock the $5/30-day trial credit.
3. **Google Gemini was adopted as the new primary tier.** Verified live
   (real `200 OK`, real content, no billing setup at all) — genuinely free
   and card-free. `LLMTier.HUGGING_FACE`/`HuggingFaceProvider` renamed to
   `GEMINI`/`GeminiProvider` throughout the codebase (14 files).
4. **Two real bugs found during live re-verification** (not caught by unit
   tests, since those use fakes, not real API calls):
   - `GeminiProvider` crashed with a raw `KeyError` when Gemini's internal
     "thinking" process consumed the entire token budget, leaving no visible
     output (`finishReason: MAX_TOKENS`, empty `content`). Fixed to raise a
     clear, diagnostic `RuntimeError` instead.
   - A stale `"Both Hugging Face and Groq..."` string survived the rename in
     `compound_risk_agent.py`'s fallback message.
5. **Gemini's real free quota, verified via an actual `429` error body (not
   secondary sources): 20 requests/day**, project+model scoped. This
   exhausts after roughly 5 real assessment cycles — accepted as a known
   constraint rather than reordering the tiers, since Groq's quota
   comfortably covers the rest.
6. **The exact pinned model name turned out to be account-dependent.** A
   second, newer Google account got a real `404` ("no longer available to
   new users") on the exact same `gemini-2.5-flash` name that worked on the
   first account. The `-latest` alias (`gemini-flash-latest`) was found to
   work live on both accounts and is now what's configured, specifically
   *because* it's more robust to this kind of per-account model
   availability difference than a pinned dated version.
7. **A truncated/malformed-JSON issue was found in production-sized real
   calls** — the same "thinking" mechanism, at `compliance_agent`'s actual
   `max_tokens=400`, produced JSON missing its own leading `{`. A
   `thinkingConfig: {"thinkingLevel": "low"}` addition was implemented per
   Gemini's official docs as the fix. Verification was blocked for a full
   day by quota exhaustion on every available key, but was **confirmed
   working the next day**: a real production-sized call (`emergency_agent`'s
   actual `max_tokens=500`, `json_mode=True`, through the full running API,
   not a synthetic script) returned clean, correctly-parsed JSON with two
   coherent interventions — not the "unparseable response" fallback text
   that would appear if truncation were still happening. (This edge case
   was already safely contained by the existing malformed-JSON fallback
   logic regardless while unverified — it defaults to "not approved /
   manual review," never a crash or false positive — but it's now confirmed
   fixed, not just safely contained.)

### 7.7 — A security issue found and fixed along the way

`.env.example` — which should contain placeholder values — was discovered
to contain **real, working HF/Groq credentials**, already committed to git
history. The user rotated both keys at their respective consoles;
`.env.example` was fixed to contain obviously-fake placeholders. (Separately,
several fresh real keys were pasted directly into the chat during later
debugging — each was written straight to the git-ignored `.env` file, never
to a tracked file, and the user was reminded to rotate those too once done.)

### 7.8 — Manual testing guide, written and live-verified twice

`docs/manual_testing_guide.md` was written for someone testing the backend
by hand via Swagger UI (`/docs`), with every endpoint, request body, and
expected response verified against a real running server — not guessed.
It covers the happy path (start a run → real risk escalation → real
emergency approval → the full view-gate/decide flow), the reasoning-down
path (what actually happens when both keys are blanked — narrower than a
naive reading of the spec would suggest, since `EmergencyAgent` only
escalates when handed a *real* risk score), and a note on testing WebSocket
streaming (not supported by Swagger UI itself). This guide was
**independently re-verified twice**: once by Claude during the Gemini
migration, and once by the user working through it live end-to-end,
catching and confirming the real `400`→`200` approval sequence, the active
LLM tier indicator, and a clean audit-chain verification (351 rows, no
breaks) along the way.

---

## Part 8 — Current State (as of the last commit)

**Committed, in order:**
1. `dc210c0` — Initial commit: Phases 1-7 complete.
2. `3f13cbf` — Reasoning-service-unavailable handling (Fix 1).
3. `1d8592e` — Synthetic sensor layer (Fix 3).
4. `010f591` — Numeric feature-vector similarity channel (Fix 2).
5. `8e722cf` — Hugging Face → featherless-ai routing (superseded by #8).
6. `8c3e9fc` — `.env.example` credential fix.
7. `8603cd6` — `llm_router` documentation + manual testing guide.
8. `3987558` — Full switch to Gemini as primary tier, plus bugs found/fixed
   during live re-verification.

**Verified working, live, end-to-end:** the full pipeline from starting a
scenario run through a real risk escalation, a real emergency approval, the
complete human-in-the-loop decision flow (including the alert-fatigue
view-gate reproducibly blocking premature decisions), the active-tier
indicator, and the audit hash-chain integrity.

**Known, honestly-documented open items:**
- The novelty-detection gate (Fix 2) is a real but partial improvement, not
  a closed gap — see Part 7.4's measured numbers.
- Gemini's real daily quota (20 requests/day) means it will typically only
  serve the first few real assessments of any given day before the system
  correctly falls back to Groq for the rest — confirmed to reset daily,
  just tight enough that testing alone exhausts it quickly.

**Since resolved:** the `thinkingConfig` fix for Gemini's JSON-truncation
issue (Part 7.6, item 7) was confirmed working the day after it was
implemented — a real production-sized call through the running API returned
clean, correctly-parsed JSON, not the earlier truncated/malformed output.
