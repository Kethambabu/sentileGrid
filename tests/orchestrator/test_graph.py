"""First end-to-end assessment (CLAUDE.md §11 Phase 4 deliverable): the full
Sensor -> Trend -> Retrieval -> Compound-Risk -> Compliance -> Explanation
-> Emergency graph, against the real seeded Phase 2/3 knowledge base, with
fake LLM providers standing in for the three LLM-calling agents so this
test is deterministic and network-free.
"""

import json

from backend.agents.compliance_agent import ComplianceAgent
from backend.agents.compound_risk_agent import CompoundRiskAgent
from backend.agents.emergency_agent import EmergencyAgent
from backend.agents.explanation_agent import ExplanationAgent
from backend.agents.retrieval_agent import RetrievalAgent
from backend.agents.sensor_agent import SensorAgent
from backend.agents.trend_agent import TrendAgent
from backend.database.approvals import ApprovalService, ApprovalStatus
from backend.database.audit import AuditWriteQueue, verify_chain
from backend.database.vector_store import get_client
from backend.orchestrator.graph import build_graph
from backend.orchestrator.state import SentinelGridState
from backend.rag.loaders.incident_loader import load_incidents_from_dir
from backend.rag.loaders.simulation_run_loader import SIMULATION_RUNS_DIR, load_simulation_records
from backend.rag.retriever import LiveRetriever
from backend.rag.seed_knowledge_base import INCIDENTS_DIR, seed
from backend.utils.llm_router import LLMRouter, LLMTier
from tests.fakes import FakeLLMProvider


def _fake_router(content: str) -> LLMRouter:
    hf = FakeLLMProvider(LLMTier.HUGGING_FACE, content=content)
    groq = FakeLLMProvider(LLMTier.GROQ, content=content)
    return LLMRouter(hf_provider=hf, groq_provider=groq, config={
        "huggingface": {"model": "m", "timeout_seconds": 5}, "groq": {"model": "m", "timeout_seconds": 5},
        "cache": {"ttl_seconds": 0}, "defaults": {"max_tokens": 500, "temperature": 0.1},
    })


def _build_test_graph(tmp_path, risk_score: float):
    persist_dir = tmp_path / "chroma"
    seed(reset=True, persist_directory=persist_dir)
    client = get_client(persist_directory=persist_dir)

    audit_queue = AuditWriteQueue(db_path=tmp_path / "audit.sqlite3")
    approval_service = ApprovalService(audit_queue=audit_queue, db_path=tmp_path / "approvals.sqlite3")

    risk_content = json.dumps({
        "risk_score": risk_score, "contributing_factors": ["reactor pressure trending toward trip threshold"],
        "recommended_action": "Increase reactor cooling water flow toward its upper operating range",
        "cited_chunk_ids": ["reactor_a_feed_loss::critical"], "reasoning": "matches feed-loss precedent",
    })
    compliance_content = json.dumps({"approved": True, "cited_sop_chunk_ids": ["reactor_high_pressure_response::part0"], "notes": "Matches SOP-REACT-001."})
    emergency_content = json.dumps({"recommended_interventions": ["Reduce reactor feed rate", "Notify shift supervisor"], "reasoning": "near trip"})

    graph = build_graph(
        sensor_agent=SensorAgent(),
        trend_agent=TrendAgent(),
        retrieval_agent=RetrievalAgent(retriever=LiveRetriever(client=client)),
        compound_risk_agent=CompoundRiskAgent(router=_fake_router(risk_content)),
        compliance_agent=ComplianceAgent(router=_fake_router(compliance_content), client=client),
        explanation_agent=ExplanationAgent(router=_fake_router("Reactor pressure is climbing toward its trip threshold, matching the feed-loss precedent [chunk_id=\"reactor_a_feed_loss::critical\"].")),
        emergency_agent=EmergencyAgent(router=_fake_router(emergency_content), approval_service=approval_service, risk_threshold=80.0),
        audit_queue=audit_queue,
    )
    return graph, audit_queue, approval_service


def _live_records():
    incident = next(i for i in load_incidents_from_dir(INCIDENTS_DIR) if i.incident_id == "reactor_a_feed_loss")
    records = load_simulation_records(SIMULATION_RUNS_DIR / incident.source_simulation_run)
    critical_stage = next(s for s in incident.stages if s.stage == "critical")
    return records[: critical_stage.record_index + 1]


def test_full_pipeline_below_emergency_threshold(tmp_path):
    graph, audit_queue, approval_service = _build_test_graph(tmp_path, risk_score=55.0)
    initial_state = SentinelGridState(run_id="run-below", records=_live_records())

    final_state = graph.invoke(initial_state)

    assert final_state["sensor_output"] is not None
    assert final_state["trend_output"] is not None
    assert final_state["retrieval_outcome"] is not None
    assert final_state["risk_assessment"].risk_score == 55.0
    assert final_state["compliance_result"].approved is True
    assert final_state["explanation"].narrative
    assert final_state["emergency_recommendation"].triggered is False

    audit_queue.stop()
    result = verify_chain(tmp_path / "audit.sqlite3")
    assert result.ok is True
    assert result.rows_checked == 3  # risk_assessment, compliance_check, explanation (no emergency row)


def test_full_pipeline_above_emergency_threshold_creates_pending_approval(tmp_path):
    graph, audit_queue, approval_service = _build_test_graph(tmp_path, risk_score=92.0)
    initial_state = SentinelGridState(run_id="run-above", records=_live_records())

    final_state = graph.invoke(initial_state)

    emergency = final_state["emergency_recommendation"]
    assert emergency.triggered is True
    assert emergency.approval_id is not None

    record = approval_service.get(emergency.approval_id)
    assert record.status == ApprovalStatus.PENDING  # human-in-the-loop: never auto-approved

    audit_queue.stop()
    result = verify_chain(tmp_path / "audit.sqlite3")
    assert result.ok is True
    assert result.rows_checked == 4  # + emergency_recommendation row


def test_sensor_agent_output_flows_through_to_retrieval(tmp_path):
    """Sensor-cleaned records (not the raw input) are what Trend/Retrieval
    actually reason over — this is CLAUDE.md §14's sensor-fault-isolation
    requirement, verified at the orchestration level, not just per-agent."""
    graph, audit_queue, _ = _build_test_graph(tmp_path, risk_score=40.0)
    records = _live_records()
    initial_state = SentinelGridState(run_id="run-sensor-flow", records=records)

    final_state = graph.invoke(initial_state)
    assert len(final_state["sensor_output"].records) == len(records)
    audit_queue.stop()
