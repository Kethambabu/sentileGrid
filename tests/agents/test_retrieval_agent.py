from backend.agents.retrieval_agent import RetrievalAgent
from backend.rag.loaders.incident_loader import load_incidents_from_dir
from backend.rag.loaders.simulation_run_loader import SIMULATION_RUNS_DIR, load_simulation_records
from backend.rag.retriever import LiveRetriever, RetrievalPhase
from backend.rag.seed_knowledge_base import INCIDENTS_DIR, seed


def test_retrieval_agent_delegates_to_retriever(tmp_path):
    persist_dir = tmp_path / "chroma"
    seed(reset=True, persist_directory=persist_dir)
    from backend.database.vector_store import get_client

    retriever = LiveRetriever(client=get_client(persist_directory=persist_dir))
    agent = RetrievalAgent(retriever=retriever)

    incident = load_incidents_from_dir(INCIDENTS_DIR)[0]
    records = load_simulation_records(SIMULATION_RUNS_DIR / incident.source_simulation_run)

    outcome = agent.retrieve(records[:20])
    assert outcome.phase == RetrievalPhase.FAST_AND_SLOW


def test_retrieval_agent_applies_equipment_zone_filter(tmp_path):
    persist_dir = tmp_path / "chroma"
    seed(reset=True, persist_directory=persist_dir)
    from backend.database.vector_store import get_client

    retriever = LiveRetriever(client=get_client(persist_directory=persist_dir))
    agent = RetrievalAgent(retriever=retriever)

    incident = load_incidents_from_dir(INCIDENTS_DIR)[0]
    records = load_simulation_records(SIMULATION_RUNS_DIR / incident.source_simulation_run)

    # "stripper" remains a genuinely unused zone even after the Phase 7
    # library expansion added a real separator-zone incident (which is why
    # this negative case no longer uses "separator" — that zone now matches).
    outcome = agent.retrieve(records[:20], equipment_zone="stripper")
    assert outcome.matches == []  # no seed incident is tagged equipment_zone=stripper
