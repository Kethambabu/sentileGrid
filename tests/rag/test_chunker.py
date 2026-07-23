import json

from backend.rag.chunker import build_incident_chunks, chunk_static_text, compute_feature_vector, window_to_text
from backend.rag.loaders.incident_loader import load_incidents_from_dir
from backend.rag.loaders.simulation_run_loader import SIMULATION_RUNS_DIR, load_simulation_records
from backend.rag.seed_knowledge_base import INCIDENTS_DIR
from backend.rag.windowing import window_pair_at


def test_chunk_static_text_splits_long_text_with_overlap():
    text = " ".join(f"word{i}" for i in range(700))
    chunks = chunk_static_text(text, source_type="sop", source_name="doc", chunk_size_words=300, overlap_words=50)
    assert len(chunks) >= 2
    assert all(len(c.text.split()) <= 300 for c in chunks)
    # consecutive chunks overlap
    first_words = chunks[0].text.split()
    second_words = chunks[1].text.split()
    assert first_words[-10:] == second_words[: len(first_words[-10:])] or set(first_words[-50:]) & set(second_words[:50])


def test_chunk_static_text_short_text_single_chunk():
    chunks = chunk_static_text("short text here", source_type="msds", source_name="doc")
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "doc::part0"


def test_chunk_static_text_empty_returns_no_chunks():
    assert chunk_static_text("", source_type="sop", source_name="doc") == []


def test_window_to_text_reports_trend_for_summarized_fields():
    for incident in load_incidents_from_dir(INCIDENTS_DIR):
        records = load_simulation_records(SIMULATION_RUNS_DIR / incident.source_simulation_run)
        stage = incident.stages[-1]
        pair = window_pair_at(records, stage.record_index)
        text = window_to_text(pair.fast_records, "fast")
        assert "reactor_pressure_kpa" in text
        assert "->" in text
        return
    raise AssertionError("no incidents found to test against")


def test_build_incident_chunks_produces_narrative_and_window_chunks():
    # Picked explicitly, not incidents[0]: incident loading is alphabetically
    # sorted, and compressor_feed_pressure_loss (which now sorts first) has
    # an early_warning stage at record_index=10 (<20), so it deliberately
    # has no slow window for that stage — not what this test is checking.
    incidents = load_incidents_from_dir(INCIDENTS_DIR)
    incident = next(i for i in incidents if i.incident_id == "reactor_a_feed_loss")
    records = load_simulation_records(SIMULATION_RUNS_DIR / incident.source_simulation_run)
    doc_chunks, window_chunks = build_incident_chunks(incident, records)

    assert len(doc_chunks) >= len(incident.stages)
    fast_chunks = [w for w in window_chunks if w.window_kind == "fast"]
    slow_chunks = [w for w in window_chunks if w.window_kind == "slow"]
    assert len(fast_chunks) == len(incident.stages)  # every stage has enough records for a fast window
    for chunk in doc_chunks:
        assert chunk.metadata["incident_id"] == incident.incident_id
        assert chunk.metadata["risk_level"] in ("low", "moderate", "high")
    # reactor_a_feed_loss's stage record_indices (20, 60, 117) are all >= 20 → slow window exists for every stage
    assert len(slow_chunks) == len(incident.stages)


def test_build_incident_chunks_attaches_feature_vector_to_window_metadata():
    """retriever.py's numeric feature-similarity channel (the fix for
    retrieval.yaml's documented text-embedding cosine-similarity gap) reads
    this metadata key at retrieval time — confirm it's actually populated."""
    incidents = load_incidents_from_dir(INCIDENTS_DIR)
    incident = next(i for i in incidents if i.incident_id == "reactor_a_feed_loss")
    records = load_simulation_records(SIMULATION_RUNS_DIR / incident.source_simulation_run)
    _doc_chunks, window_chunks = build_incident_chunks(incident, records)

    for chunk in window_chunks:
        assert "feature_vector_json" in chunk.metadata
        vector = json.loads(chunk.metadata["feature_vector_json"])
        assert isinstance(vector, list)
        assert len(vector) > 0
        assert all(isinstance(v, (int, float)) for v in vector)


def test_compute_feature_vector_empty_records_returns_zero_vector():
    vector = compute_feature_vector([])
    assert all(v == 0.0 for v in vector)


def test_compute_feature_vector_near_zero_for_baseline_matching_window():
    """A window whose last record sits at the known baseline operating
    point should produce a near-zero deviation vector — the reference case
    a genuinely novel/baseline live window's numeric similarity check
    depends on."""
    for incident in load_incidents_from_dir(INCIDENTS_DIR):
        records = load_simulation_records(SIMULATION_RUNS_DIR / incident.source_simulation_run)
        pre_fault_records = [r for r in records if r.t_hours < incident.stages[0].t_hours]
        if len(pre_fault_records) < 5:
            continue
        vector = compute_feature_vector(pre_fault_records[:5])
        # Pre-fault (near-baseline) deviations should be small relative to
        # a genuinely faulted window's — not asserting an exact bound since
        # normal process noise is real, just that it's a modest vector.
        assert all(abs(v) < 20 for v in vector)
        return
    raise AssertionError("no incident had enough pre-fault records to test against")


def test_compute_feature_vector_large_for_clearly_deviated_window():
    """A window from deep into an incident's critical stage should produce
    a numerically larger deviation vector than one from its own pre-fault
    baseline — this is the discriminative signal retriever.py relies on."""
    incident = next(i for i in load_incidents_from_dir(INCIDENTS_DIR) if i.incident_id == "reactor_a_feed_loss")
    records = load_simulation_records(SIMULATION_RUNS_DIR / incident.source_simulation_run)
    critical_stage = next(s for s in incident.stages if s.stage == "critical")

    pre_fault_vector = compute_feature_vector(records[:5])
    critical_pair = window_pair_at(records, critical_stage.record_index)
    critical_vector = compute_feature_vector(critical_pair.fast_records)

    pre_fault_magnitude = sum(v * v for v in pre_fault_vector) ** 0.5
    critical_magnitude = sum(v * v for v in critical_vector) ** 0.5
    assert critical_magnitude > pre_fault_magnitude
