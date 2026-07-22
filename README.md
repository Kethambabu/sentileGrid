# SentinelGrid

AI-powered industrial safety intelligence for chemical plants. Instead of simple threshold alarms ("if temp > 90°C, alert"), SentinelGrid detects **compound risk** — situations where multiple sensor readings are individually normal but their *combination and trend* signal danger — by reasoning over live sensor data, historical incidents, and safety procedures using retrieval-augmented reasoning.

Danger lives in relationships between readings across time, not in any single reading. Every part of this system exists to serve that thesis.

Built for InnovaHack Chapter 1 (Elite Forums), Team Fantastic Four, Generative AI domain. Full architecture, constraints, and rationale for every design decision live in [CLAUDE.md](CLAUDE.md) — this README is the quickstart; that file is the spec.

## Architecture

```
frontend (Streamlit)
    |  HTTP/WebSocket only -- never direct DB access
backend/api (FastAPI)
    |
backend/orchestrator (LangGraph state graph)
    |
backend/agents (Sensor -> Trend -> Retrieval -> Compound-Risk -> Compliance -> Explanation -> Emergency)
    |
backend/rag (retrieval pipeline: dual fast/slow-window hybrid search + cross-encoder rerank)
    |
backend/database (SQLite transactional + DuckDB analytics + ChromaDB vectors)
    |
backend/simulation (Tennessee Eastman Process simulator)
```

Every risk assessment, recommendation, and human approval/rejection decision is written to an append-only, hash-chained audit log. No code path executes a plant action — the system recommends and waits for an explicit human approval; this is enforced structurally, not by convention.

## Setup

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows PowerShell; `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in two free-tier keys (no card required):

| Key | Get it at | Used for |
| --- | --- | --- |
| `HF_API_TOKEN` | https://huggingface.co/settings/tokens | Primary LLM tier (Hugging Face Serverless Inference) |
| `GROQ_API_KEY` | https://console.groq.com/keys | Fallback LLM tier |

Everything else (embeddings, ChromaDB, SQLite, DuckDB, the simulator) runs fully local with no account. See CLAUDE.md §5a for details, and §5 for why the fallback chain is structured the way it is (no single-provider dependency, no silent hang if both tiers fail).

## Running it

```bash
# Terminal 1 — backend
uvicorn backend.api.main:app --reload

# Terminal 2 — dashboard (backend must already be running)
streamlit run frontend/app.py
```

Open the Streamlit URL, pick a scenario in **Overview**, start a run, and watch **Timeline** / **Agent Trace** / **Approvals** update as the agent pipeline processes it. See `docs/demo_runbook.md` for a scripted walkthrough.

Full command reference — running a single simulation scenario, re-seeding the knowledge base, generating held-out evaluation runs, running tests — is in [CLAUDE.md §15](CLAUDE.md#15-useful-commands).

## Scenario library

Six scenarios ship seeded: a no-fault `baseline` plus five fault incidents, each a genuinely different failure mechanism and equipment zone (not severity variants of the same fault):

| Incident | Zone | Fault mechanism |
| --- | --- | --- |
| `reactor_a_feed_loss` | reactor | Total feed-stream loss (step) |
| `reactor_cw_valve_stiction` | reactor | Cooling water valve actuator sticking |
| `reactor_kinetics_drift` | reactor | Slow reaction-kinetics drift |
| `compressor_feed_pressure_loss` | compressor | Partial feed-header pressure loss |
| `separator_cooling_duty_loss` | separator | Intermittent pulse-shaped cooling-duty loss |

Each is authored as multiple stages (early warning / mid escalation / critical) with narrative text citing real numbers read from an actual simulation run — never invented.

## "Is this real incident data?"

The honest answer, ready for exactly this question: **TEP physics are real and published** (Downs & Vogel, 1993 — the same benchmark used across decades of process-control research). The **incident/near-miss library is synthetically generated and self-labeled** on top of that real simulator, not sourced from real plant records. The **Vizag (LG Polymers) incident is real-world motivation** for why compound-risk detection matters — it is not the source of any data in this system. TEP's 20 defined fault types are also a stated scope limit, not implied full coverage of real-world failure modes; see CLAUDE.md §14.

## Known limitations

Retrieval novelty detection (flagging "no real match found" instead of forcing a guess) currently has a documented false-positive gap, root-caused to embedding-similarity compression on templated text rather than a wording or calibration problem — including a negative result from a relative-threshold fix that was tried, tested against real held-out data, and discarded because it didn't work. Full writeup, with real measured numbers: [backend/evaluation/README.md](backend/evaluation/README.md).

## Tests

```bash
pytest tests/
```

`tests/` mirrors `backend/` 1:1. Every agent, pipeline stage, and Section 9 security/robustness requirement (approval-disconnect defaults to pending, novel-condition detection, train/test split by scenario run ID, prompt-injection delimiting, cross-tier judging, sensor-fault tagging) has a dedicated test.
