from __future__ import annotations

import sys
import time
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from components.api_client import APIClient, APIError  # noqa: E402

st.set_page_config(page_title="SentinelGrid — Overview", page_icon="🛡️", layout="wide")
st.title("Overview")

client = APIClient(st.session_state.get("base_url", "http://127.0.0.1:8000"))

st.subheader("Start a scenario")
try:
    scenarios = client.list_scenarios()
except APIError as exc:
    st.error(f"Could not load scenarios: {exc}")
    scenarios = []

if scenarios:
    names = [s["name"] for s in scenarios]
    selected = st.selectbox("Scenario", names, format_func=lambda n: n)
    description = next(s["description"] for s in scenarios if s["name"] == selected)
    st.caption(description)

    col1, col2, col3 = st.columns(3)
    duration_hours = col1.number_input("Duration override (hours, 0 = scenario default)", min_value=0.0, value=0.0, step=0.5)
    tick_seconds = col2.number_input("Tick seconds (replay pace)", min_value=0.01, value=0.2, step=0.05)
    assessment_interval = col3.number_input("Assess every N records", min_value=1, value=5, step=1)

    if st.button("Start run", type="primary"):
        try:
            run_id = client.start_run(
                selected, duration_hours=duration_hours or None, tick_seconds=tick_seconds,
                assessment_interval_records=int(assessment_interval),
            )
            st.session_state.run_id = run_id
            st.success(f"Started run {run_id}")
        except APIError as exc:
            st.error(f"Failed to start run: {exc}")

st.divider()
st.subheader("Current run")

run_id = st.session_state.get("run_id")
if not run_id:
    st.info("No run started yet — pick a scenario above.")
else:
    st.text(f"run_id: {run_id}")
    auto_refresh = st.checkbox("Auto-refresh (every 2s)", value=True)

    try:
        run = client.get_run(run_id)
    except APIError as exc:
        st.error(f"Failed to fetch run: {exc}")
        run = None

    if run:
        status_color = {"starting": "🟡", "running": "🟢", "completed": "🔵", "error": "🔴"}.get(run["status"], "⚪")
        st.metric("Status", f"{status_color} {run['status']}")

        col1, col2, col3 = st.columns(3)
        col1.metric("Records revealed", f"{run['revealed_count']} / {run['total_records']}")
        col2.metric("Assessments run", run["assessment_count"])

        try:
            llm = client.llm_status()
            tier_label = llm["active_tier"] or "none yet"
            col3.metric("Active LLM tier", tier_label)
        except APIError:
            col3.metric("Active LLM tier", "unknown")

        if run.get("diverged"):
            st.warning(f"Simulation diverged / tripped: {run.get('diverged_reason')}")
        if run.get("error"):
            st.error(f"Run error: {run['error']}")

        latest = run.get("latest_assessment")
        if latest:
            risk = latest["risk_assessment"]
            st.subheader("Latest risk assessment")
            score = risk["risk_score"]
            if score is None:
                st.warning("🟡 NOVEL CONDITION — no risk score forced; see reasoning below.")
            else:
                level = "🔴 HIGH" if score >= 80 else ("🟠 MODERATE" if score >= 50 else "🟢 LOW")
                st.metric("Risk score", f"{score:.1f}", help=level)
            st.write(f"**Confidence:** {risk['confidence']}  |  **LLM tier:** {risk['llm_tier_used']}")
            st.write(f"**Contributing factors:** {', '.join(risk['contributing_factors']) or 'none'}")
            st.write(f"**Recommended action:** {risk['recommended_action']}")

            explanation = latest.get("explanation")
            if explanation:
                st.subheader("Explanation")
                st.write(explanation["narrative"])

            emergency = latest.get("emergency_recommendation")
            if emergency and emergency["triggered"]:
                st.error(f"🚨 Emergency Agent escalated — approval_id `{emergency['approval_id']}` is pending on the Approvals page.")
        else:
            st.info("No assessment yet — waiting for enough records (needs at least 5).")

    if auto_refresh and run and run["status"] not in ("completed", "error"):
        time.sleep(2)
        st.rerun()
