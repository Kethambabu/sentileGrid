"""CLAUDE.md §9/§14: the approve button must not become clickable until the
operator has viewed the explanation/evidence panel (alert-fatigue fix), and
every decision requires a specific operator ID, never a bare flag.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from components.api_client import APIClient, APIError  # noqa: E402

st.set_page_config(page_title="SentinelGrid — Approvals", page_icon="🛡️", layout="wide")
st.title("Approvals")

client = APIClient(st.session_state.get("base_url", "http://127.0.0.1:8000"))
run_id = st.session_state.get("run_id")

st.session_state.operator_id = st.text_input("Operator ID (required to approve or reject)", value=st.session_state.get("operator_id", ""))

if not run_id:
    st.info("No run selected — start one on the Overview page first.")
    st.stop()

try:
    assessments = client.get_assessments(run_id)
except APIError as exc:
    st.error(f"Failed to fetch assessments: {exc}")
    st.stop()

pending_approval_ids = [
    a["emergency_recommendation"]["approval_id"]
    for a in assessments
    if a["emergency_recommendation"]["triggered"] and a["emergency_recommendation"]["approval_id"]
]

if not pending_approval_ids:
    st.info("No Emergency Agent escalations for this run yet.")
    st.stop()

for approval_id in dict.fromkeys(pending_approval_ids):  # de-dup, preserve order
    try:
        approval = client.get_approval(approval_id)
    except APIError as exc:
        st.warning(f"Could not load approval {approval_id}: {exc}")
        continue

    matching = next(
        (a for a in assessments if a["emergency_recommendation"]["approval_id"] == approval_id), None
    )

    with st.container(border=True):
        st.subheader(f"Approval `{approval_id[:8]}`")
        status = approval["status"]
        st.write(f"**Status:** {'🟡 PENDING' if status == 'pending' else ('🟢 APPROVED' if status == 'approved' else '🔴 REJECTED')}")
        st.write(f"**Recommendation:** {approval['recommendation_summary']}")
        if approval.get("operator_id"):
            st.caption(f"Decided by {approval['operator_id']} at {approval['decided_at']}")

        if matching:
            with st.expander("View evidence / explanation (required before deciding)"):
                st.write(matching["explanation"]["narrative"])
                st.write(f"Risk score: {matching['risk_assessment']['risk_score']}")
                st.write(f"Compliance: {'approved' if matching['compliance_result']['approved'] else 'not approved'} — {matching['compliance_result']['notes']}")
                if st.button("Mark evidence as viewed", key=f"view-{approval_id}"):
                    client.mark_viewed(approval_id)
                    st.rerun()

        viewed = approval.get("viewed_evidence", False)
        if status == "pending":
            if not viewed:
                st.warning("Evidence must be viewed (above) before this can be decided — reflexive-click approvals are disabled by design.")
            operator_id = st.session_state.operator_id
            col1, col2 = st.columns(2)
            approve_disabled = not viewed or not operator_id
            reject_disabled = not viewed or not operator_id
            if col1.button("✅ Approve", key=f"approve-{approval_id}", disabled=approve_disabled):
                try:
                    client.decide(approval_id, operator_id, "approved")
                    st.rerun()
                except APIError as exc:
                    st.error(str(exc))
            if col2.button("❌ Reject", key=f"reject-{approval_id}", disabled=reject_disabled):
                try:
                    client.decide(approval_id, operator_id, "rejected")
                    st.rerun()
                except APIError as exc:
                    st.error(str(exc))
            if not operator_id:
                st.caption("Enter an operator ID above to enable the decision buttons.")
