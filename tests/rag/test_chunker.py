from backend.rag.chunker import build_incident_chunks, chunk_static_text, window_to_text
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
