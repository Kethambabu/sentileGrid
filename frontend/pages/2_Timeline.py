from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from components.api_client import APIClient, APIError  # noqa: E402

st.set_page_config(page_title="SentinelGrid — Timeline", page_icon="🛡️", layout="wide")
st.title("Timeline")

client = APIClient(st.session_state.get("base_url", "http://127.0.0.1:8000"))
run_id = st.session_state.get("run_id")

if not run_id:
    st.info("No run selected — start one on the Overview page first.")
    st.stop()

st.text(f"run_id: {run_id}")

try:
    readings = client.get_readings(run_id)
    assessments = client.get_assessments(run_id)
except APIError as exc:
    st.error(f"Failed to fetch data: {exc}")
    st.stop()

if not readings:
    st.info("No readings yet.")
    st.stop()

readings_df = pd.DataFrame(readings).set_index("t_hours")

st.subheader("Reactor readings")
st.line_chart(readings_df[["reactor_pressure_kpa", "separator_pressure_kpa"]])
st.line_chart(readings_df[["reactor_temperature_c"]])
st.line_chart(readings_df[["reactor_level_pct", "stripper_level_pct"]])

st.subheader("Risk score over time")
if assessments:
    risk_rows = [
        {"t_hours": a["t_hours"], "risk_score": a["risk_assessment"]["risk_score"], "is_novel_condition": a["is_novel_condition"]}
        for a in assessments
    ]
    risk_df = pd.DataFrame(risk_rows).set_index("t_hours")
    st.line_chart(risk_df[["risk_score"]])

    novel_count = sum(1 for r in risk_rows if r["is_novel_condition"])
    if novel_count:
        st.caption(f"{novel_count} of {len(risk_rows)} assessments were flagged NOVEL CONDITION (no risk score forced).")
else:
    st.info("No assessments yet — need at least 5 revealed records.")
