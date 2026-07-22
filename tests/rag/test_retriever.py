"""Core Phase 3 verification: the live retrieval sequence (CLAUDE.md §7.4)
against the real seeded Phase 2 knowledge base, including a self-consistency
check (an incident's own source records should retrieve that same incident).
"""

import pytest

from backend.rag.loaders.incident_loader import load_incidents_from_dir
from backend.rag.loaders.simulation_run_loader import SIMULATION_RUNS_DIR, load_simulation_records
from backend.rag.retriever import ConfidenceLevel, LiveRetriever, RetrievalPhase, load_retrieval_config
from backend.rag.seed_knowledge_base import INCIDENTS_DIR, seed
from backend.rag.windowing import FAST_WINDOW_SIZE, SLOW_WINDOW_SIZE


@pytest.fixture(scope="module")
def seeded_retriever(tmp_path_factory):
    persist_dir = tmp_path_factory.mktemp("chroma")
    seed(reset=True, persist_directory=persist_dir)
    from backend.database.vector_store import get_client

    return LiveRetriever(client=get_client(persist_directory=persist_dir))


def test_no_retrieval_below_fast_window_size(seeded_retriever):
    incident = load_incidents_from_dir(INCIDENTS_DIR)[0]
    records = load_simulation_records(SIMULATION_RUNS_DIR / incident.source_simulation_run)
    outcome = seeded_retriever.retrieve(records[: FAST_WINDOW_SIZE - 1])
    assert outcome.phase == RetrievalPhase.NO_RETRIEVAL
    assert outcome.confidence == ConfidenceLevel.NONE
    assert outcome.matches == []


def test_fast_only_phase_caps_confidence_at_moderate(seeded_retriever):
    incident = load_incidents_from_dir(INCIDENTS_DIR)[0]
    records = load_simulation_records(SIMULATION_RUNS_DIR / incident.source_simulation_run)
    outcome = seeded_retriever.retrieve(records[:FAST_WINDOW_SIZE])
    assert outcome.phase == RetrievalPhase.FAST_ONLY
    # capped even if raw similarity happens to be very strong
    assert outcome.confidence in (ConfidenceLevel.NOVEL, ConfidenceLevel.MODERATE)
    assert outcome.confidence != ConfidenceLevel.HIGH


def test_fast_and_slow_phase_at_slow_window_size(seeded_retriever):
    incident = load_incidents_from_dir(INCIDENTS_DIR)[0]
    records = load_simulation_records(SIMULATION_RUNS_DIR / incident.source_simulation_run)
    outcome = seeded_retriever.retrieve(records[:SLOW_WINDOW_SIZE])
    assert outcome.phase == RetrievalPhase.FAST_AND_SLOW
    for match in outcome.matches:
        assert match.fast_similarity is not None
        assert match.slow_similarity is not None


def test_retrieves_own_incident_as_top_match_at_critical_stage(seeded_retriever):
    """Self-consistency check: feeding an incident's own source records back
    as a 'live' stream, up through its critical-stage record, should
    retrieve that same incident as the top (or a top) match."""
    incident = next(i for i in load_incidents_from_dir(INCIDENTS_DIR) if i.incident_id == "reactor_a_feed_loss")
    records = load_simulation_records(SIMULATION_RUNS_DIR / incident.source_simulation_run)
    critical_stage = next(s for s in incident.stages if s.stage == "critical")

    outcome = seeded_retriever.retrieve(records[: critical_stage.record_index + 1])
    assert outcome.phase == RetrievalPhase.FAST_AND_SLOW
    assert not outcome.is_novel_condition
    matched_incident_ids = {m.incident_id for m in outcome.matches}
    assert "reactor_a_feed_loss" in matched_incident_ids


def test_strict_novelty_threshold_forces_novel_condition(seeded_retriever):
    """Mechanism test, independent of embedding-similarity fuzziness: an
    impossibly strict threshold must force novel_condition=True even for an
    incident's own (otherwise strongly-matching) records."""
    incident = load_incidents_from_dir(INCIDENTS_DIR)[0]
    records = load_simulation_records(SIMULATION_RUNS_DIR / incident.source_simulation_run)
    strict_config = load_retrieval_config()
    strict_config["confidence"]["novel_condition_threshold"] = 0.999

    retriever = LiveRetriever(client=seeded_retriever.client, config=strict_config)
    outcome = retriever.retrieve(records[:SLOW_WINDOW_SIZE])
    assert outcome.is_novel_condition is True
    assert outcome.confidence == ConfidenceLevel.NOVEL


def test_lenient_novelty_threshold_never_flags_novel(seeded_retriever):
    incident = load_incidents_from_dir(INCIDENTS_DIR)[0]
    records = load_simulation_records(SIMULATION_RUNS_DIR / incident.source_simulation_run)
    lenient_config = load_retrieval_config()
    lenient_config["confidence"]["novel_condition_threshold"] = -1.0

    retriever = LiveRetriever(client=seeded_retriever.client, config=lenient_config)
    outcome = retriever.retrieve(records[:SLOW_WINDOW_SIZE])
    assert outcome.is_novel_condition is False


def test_metadata_filter_restricts_matches(seeded_retriever):
    incident = load_incidents_from_dir(INCIDENTS_DIR)[0]
    records = load_simulation_records(SIMULATION_RUNS_DIR / incident.source_simulation_run)
    lenient_config = load_retrieval_config()
    lenient_config["confidence"]["novel_condition_threshold"] = -1.0
    retriever = LiveRetriever(client=seeded_retriever.client, config=lenient_config)

    # "stripper" and "condenser" remain genuinely unused zones even after the
    # Phase 7 library expansion (reactor/compressor/separator are all used
    # now) — see test_metadata_filter_matches_separator_zone below for the
    # positive case this negative case is paired with.
    outcome = retriever.retrieve(records[:SLOW_WINDOW_SIZE], where={"equipment_zone": "stripper"})
    assert outcome.matches == []  # no seed incident is tagged equipment_zone=stripper


def test_metadata_filter_matches_separator_zone(seeded_retriever):
    """Phase 7 added separator_cooling_duty_loss (equipment_zone=separator) —
    confirms the metadata filter actually restricts TO a zone, not just away
    from one (test_metadata_filter_restricts_matches above)."""
    incident = next(i for i in load_incidents_from_dir(INCIDENTS_DIR) if i.incident_id == "separator_cooling_duty_loss")
    records = load_simulation_records(SIMULATION_RUNS_DIR / incident.source_simulation_run)
    lenient_config = load_retrieval_config()
    lenient_config["confidence"]["novel_condition_threshold"] = -1.0
    retriever = LiveRetriever(client=seeded_retriever.client, config=lenient_config)

    outcome = retriever.retrieve(records[:SLOW_WINDOW_SIZE], where={"equipment_zone": "separator"})
    assert outcome.matches != []
    assert all(m.equipment_zone == "separator" for m in outcome.matches)
