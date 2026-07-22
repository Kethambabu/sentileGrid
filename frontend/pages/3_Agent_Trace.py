from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from components.api_client import APIClient, APIError  # noqa: E402

st.set_page_config(page_title="SentinelGrid — Agent Trace", page_icon="🛡️", layout="wide")
st.title("Agent Trace")

client = APIClient(st.session_state.get("base_url", "http://127.0.0.1:8000"))
run_id = st.session_state.get("run_id")

if not run_id:
    st.info("No run selected — start one on the Overview page first.")
    st.stop()

st.text(f"run_id: {run_id}")

st.subheader("Audit chain integrity")
try:
    verification = client.audit_verify()
    if verification["ok"]:
        st.success(f"✅ Hash chain verified — {verification['rows_checked']} rows, untampered.")
    else:
        st.error(f"❌ Audit chain broken at row {verification['first_broken_id']}: {verification['reason']}")
except APIError as exc:
    st.warning(f"Could not verify audit chain: {exc}")

st.divider()

try:
    assessments = client.get_assessments(run_id)
except APIError as exc:
    st.error(f"Failed to fetch assessments: {exc}")
    st.stop()

if not assessments:
    st.info("No assessments yet — need at least 5 revealed records.")
    st.stop()

for i, entry in enumerate(reversed(assessments)):
    idx = len(assessments) - i
    with st.expander(f"Assessment #{idx} — t={entry['t_hours']:.2f}h — record #{entry['record_index']}", expanded=(i == 0)):
        st.write(f"**Retrieval phase:** {entry['retrieval_phase']}  |  **Confidence:** {entry['retrieval_confidence']}  |  **Novel condition:** {entry['is_novel_condition']}")

        risk = entry["risk_assessment"]
        st.markdown("### 1. Compound-Risk Agent")
        st.write(f"Risk score: **{risk['risk_score'] if risk['risk_score'] is not None else 'N/A (novel condition)'}**  (tier: {risk['llm_tier_used']})")
        st.write(f"Contributing factors: {', '.join(risk['contributing_factors']) or 'none'}")
        st.write(f"Recommended action: {risk['recommended_action']}")
        st.write(f"Reasoning: {risk['reasoning']}")
        if risk["cited_chunk_ids"]:
            st.caption(f"Cited: {', '.join(risk['cited_chunk_ids'])}")

        compliance = entry["compliance_result"]
        st.markdown("### 2. Compliance Agent")
        st.write(f"{'✅ Approved' if compliance['approved'] else '❌ Not approved'}  (tier: {compliance['llm_tier_used']})")
        st.write(compliance["notes"])
        if compliance["cited_sop_chunk_ids"]:
            st.caption(f"Cited SOP: {', '.join(compliance['cited_sop_chunk_ids'])}")

        explanation = entry["explanation"]
        st.markdown("### 3. Explanation Agent")
        st.write(explanation["narrative"])

        emergency = entry["emergency_recommendation"]
        st.markdown("### 4. Emergency Agent")
        if emergency["triggered"]:
            st.error(f"Escalated — approval_id `{emergency['approval_id']}` (see Approvals page)")
            for item in emergency["recommended_interventions"]:
                st.write(f"- {item}")
        else:
            st.write("Not triggered (risk below threshold or novel condition).")
