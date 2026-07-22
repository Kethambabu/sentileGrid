"""SentinelGrid dashboard entrypoint. CLAUDE.md §5: Streamlit, talking to
backend/api only (see components/api_client.py) — never a direct database
connection from this layer.

Run: streamlit run frontend/app.py
(with `uvicorn backend.api.main:app` already running separately)
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from components.api_client import APIClient, DEFAULT_BASE_URL  # noqa: E402

st.set_page_config(page_title="SentinelGrid", page_icon="🛡️", layout="wide")

if "base_url" not in st.session_state:
    st.session_state.base_url = DEFAULT_BASE_URL
if "run_id" not in st.session_state:
    st.session_state.run_id = None
if "operator_id" not in st.session_state:
    st.session_state.operator_id = ""

st.title("🛡️ SentinelGrid")
st.caption("AI-powered compound-risk monitoring for a chemical plant — see CLAUDE.md for the full architecture.")

client = APIClient(st.session_state.base_url)
if client.health():
    st.success(f"Connected to backend API at {st.session_state.base_url}")
else:
    st.error(
        f"Cannot reach the backend API at {st.session_state.base_url}. "
        "Start it with: uvicorn backend.api.main:app --reload"
    )

st.markdown(
    """
Use the sidebar to navigate:

- **Overview** — pick a scenario, start a run, see the current risk assessment and active LLM tier.
- **Timeline** — reactor readings and risk score over the course of a run.
- **Agent Trace** — what each agent produced at every assessment, with citations and audit-chain verification.
- **Approvals** — pending Emergency Agent recommendations awaiting human approval.

Danger, in this system's own words, lives in the *relationship between readings across time* — not in any single reading.
"""
)
