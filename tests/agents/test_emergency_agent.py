import json

from backend.agents.emergency_agent import EmergencyAgent
from backend.agents.models import RiskAssessment
from backend.database.approvals import ApprovalService, ApprovalStatus
from backend.database.audit import AuditWriteQueue
from backend.rag.retriever import ConfidenceLevel, RetrievalOutcome, RetrievalPhase
from backend.utils.llm_router import LLMRouter, LLMTier
from tests.fakes import FakeLLMProvider


def _router(content: str) -> LLMRouter:
    hf = FakeLLMProvider(LLMTier.HUGGING_FACE, content=content)
    groq = FakeLLMProvider(LLMTier.GROQ, content=content)
    return LLMRouter(hf_provider=hf, groq_provider=groq, config={
        "huggingface": {"model": "m", "timeout_seconds": 5}, "groq": {"model": "m", "timeout_seconds": 5},
        "cache": {"ttl_seconds": 0}, "defaults": {"max_tokens": 500, "temperature": 0.3},
    })


def _failing_router() -> LLMRouter:
    hf = FakeLLMProvider(LLMTier.HUGGING_FACE, should_fail=True)
    groq = FakeLLMProvider(LLMTier.GROQ, should_fail=True)
    return LLMRouter(hf_provider=hf, groq_provider=groq, config={
        "huggingface": {"model": "m", "timeout_seconds": 5}, "groq": {"model": "m", "timeout_seconds": 5},
        "cache": {"ttl_seconds": 0}, "defaults": {"max_tokens": 500, "temperature": 0.3},
    })


def _outcome():
    return RetrievalOutcome(phase=RetrievalPhase.FAST_AND_SLOW, is_novel_condition=False, confidence=ConfidenceLevel.HIGH, matches=[])


def _risk(score):
    return RiskAssessment(
        risk_score=score, is_novel_condition=score is None, confidence="high", contributing_factors=[],
        recommended_action="x", cited_chunk_ids=[], reasoning="y", llm_tier_used="huggingface", latency_ms=1.0,
    )


def test_no_escalation_below_threshold(tmp_path):
    queue = AuditWriteQueue(db_path=tmp_path / "audit.sqlite3")
    agent = EmergencyAgent(router=_router("{}"), approval_service=ApprovalService(audit_queue=queue, db_path=tmp_path / "approvals.sqlite3"), risk_threshold=80.0)
    result = agent.maybe_escalate(_risk(50.0), _outcome(), run_id="run-1")
    assert result.triggered is False
    assert result.approval_id is None
    queue.stop()


def test_no_escalation_when_risk_score_is_none(tmp_path):
    queue = AuditWriteQueue(db_path=tmp_path / "audit.sqlite3")
    agent = EmergencyAgent(router=_router("{}"), approval_service=ApprovalService(audit_queue=queue, db_path=tmp_path / "approvals.sqlite3"), risk_threshold=80.0)
    result = agent.maybe_escalate(_risk(None), _outcome(), run_id="run-1")
    assert result.triggered is False
    queue.stop()


def test_escalation_above_threshold_creates_pending_approval(tmp_path):
    queue = AuditWriteQueue(db_path=tmp_path / "audit.sqlite3")
    content = json.dumps({"recommended_interventions": ["Reduce reactor feed rate", "Notify shift supervisor"], "reasoning": "pressure near trip"})
    approval_service = ApprovalService(audit_queue=queue, db_path=tmp_path / "approvals.sqlite3")
    agent = EmergencyAgent(router=_router(content), approval_service=approval_service, risk_threshold=80.0)

    result = agent.maybe_escalate(_risk(92.0), _outcome(), run_id="run-1")

    assert result.triggered is True
    assert result.requires_approval is True
    assert result.approval_id is not None
    assert len(result.recommended_interventions) == 2

    record = approval_service.get(result.approval_id)
    assert record.status == ApprovalStatus.PENDING  # never auto-approved
    queue.stop()


def test_unparseable_response_still_creates_pending_approval_not_a_crash(tmp_path):
    queue = AuditWriteQueue(db_path=tmp_path / "audit.sqlite3")
    approval_service = ApprovalService(audit_queue=queue, db_path=tmp_path / "approvals.sqlite3")
    agent = EmergencyAgent(router=_router("not json"), approval_service=approval_service, risk_threshold=80.0)

    result = agent.maybe_escalate(_risk(95.0), _outcome(), run_id="run-1")
    assert result.triggered is True
    assert result.approval_id is not None
    assert approval_service.get(result.approval_id).status == ApprovalStatus.PENDING
    queue.stop()


def test_reasoning_unavailable_above_threshold_still_creates_pending_approval(tmp_path):
    """The single most consequential case in the whole safety layer: if risk
    already crossed the emergency threshold and THEN both LLM tiers fail,
    a pending approval record must still exist — CLAUDE.md §14's "both free
    tiers fail" case must never mean "no record of a detected emergency"."""
    queue = AuditWriteQueue(db_path=tmp_path / "audit.sqlite3")
    approval_service = ApprovalService(audit_queue=queue, db_path=tmp_path / "approvals.sqlite3")
    agent = EmergencyAgent(router=_failing_router(), approval_service=approval_service, risk_threshold=80.0)

    result = agent.maybe_escalate(_risk(92.0), _outcome(), run_id="run-1")

    assert result.triggered is True
    assert result.reasoning_unavailable is True
    assert result.llm_tier_used == "unavailable"
    assert result.approval_id is not None
    assert approval_service.get(result.approval_id).status == ApprovalStatus.PENDING
    queue.stop()


def test_emergency_agent_has_no_execution_method():
    """Guard-rail test: this agent must never gain a way to act on its own
    recommendations — CLAUDE.md §2's non-negotiable human-in-the-loop rule."""
    forbidden_names = {"execute", "apply", "run_action", "act", "perform", "trigger_action"}
    agent_methods = {name for name in dir(EmergencyAgent) if not name.startswith("_")}
    assert agent_methods.isdisjoint(forbidden_names)
