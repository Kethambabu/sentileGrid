import json

from backend.agents.compliance_agent import ComplianceAgent
from backend.rag.seed_knowledge_base import seed
from backend.utils.llm_router import LLMRouter, LLMTier
from tests.fakes import FakeLLMProvider


def _router(content: str) -> LLMRouter:
    gemini = FakeLLMProvider(LLMTier.GEMINI, content=content)
    groq = FakeLLMProvider(LLMTier.GROQ, content=content)
    return LLMRouter(gemini_provider=gemini, groq_provider=groq, config={
        "gemini": {"model": "m", "timeout_seconds": 5}, "groq": {"model": "m", "timeout_seconds": 5},
        "cache": {"ttl_seconds": 0}, "defaults": {"max_tokens": 500, "temperature": 0.1},
    })


def _failing_router() -> LLMRouter:
    gemini = FakeLLMProvider(LLMTier.GEMINI, should_fail=True)
    groq = FakeLLMProvider(LLMTier.GROQ, should_fail=True)
    return LLMRouter(gemini_provider=gemini, groq_provider=groq, config={
        "gemini": {"model": "m", "timeout_seconds": 5}, "groq": {"model": "m", "timeout_seconds": 5},
        "cache": {"ttl_seconds": 0}, "defaults": {"max_tokens": 500, "temperature": 0.1},
    })


def _seeded_agent(tmp_path, content):
    persist_dir = tmp_path / "chroma"
    seed(reset=True, persist_directory=persist_dir)
    from backend.database.vector_store import get_client

    return ComplianceAgent(router=_router(content), client=get_client(persist_directory=persist_dir))


def _seeded_agent_with_router(tmp_path, router: LLMRouter):
    persist_dir = tmp_path / "chroma"
    seed(reset=True, persist_directory=persist_dir)
    from backend.database.vector_store import get_client

    return ComplianceAgent(router=router, client=get_client(persist_directory=persist_dir))


def test_action_with_sop_support_can_be_approved(tmp_path):
    content = json.dumps({"approved": True, "cited_sop_chunk_ids": ["reactor_high_pressure_response::part0"], "notes": "Matches SOP-REACT-001."})
    agent = _seeded_agent(tmp_path, content)

    result = agent.review("Increase reactor cooling water flow toward its upper operating range")
    assert result.approved is True
    assert result.cited_sop_chunk_ids


def test_llm_approval_is_overridden_when_no_sop_evidence_found(tmp_path, monkeypatch):
    """Code-level guarantee: never approve with zero cited evidence, even if the LLM says approved."""
    content = json.dumps({"approved": True, "cited_sop_chunk_ids": ["fabricated"], "notes": "looks fine"})
    agent = _seeded_agent(tmp_path, content)

    from backend.rag import hybrid_retrieval
    monkeypatch.setattr(hybrid_retrieval, "hybrid_query", lambda *a, **k: [])
    # ComplianceAgent imported hybrid_query directly into its module namespace
    import backend.agents.compliance_agent as compliance_module
    monkeypatch.setattr(compliance_module, "hybrid_query", lambda *a, **k: [])

    result = agent.review("Do something with no SOP precedent whatsoever")
    assert result.approved is False


def test_unparseable_response_defaults_to_not_approved(tmp_path):
    agent = _seeded_agent(tmp_path, "not json")
    result = agent.review("Increase reactor cooling water flow")
    assert result.approved is False
    assert result.parse_error is True


def test_reasoning_unavailable_defaults_to_not_approved(tmp_path):
    """CLAUDE.md §14: both LLM tiers down must never be treated as approval."""
    agent = _seeded_agent_with_router(tmp_path, _failing_router())
    result = agent.review("Increase reactor cooling water flow")
    assert result.approved is False
    assert result.reasoning_unavailable is True
    assert result.llm_tier_used == "unavailable"
