from backend.rag.loaders.simulation_run_loader import SIMULATION_RUNS_DIR, load_simulation_records
from backend.rag.loaders.incident_loader import load_incidents_from_dir
from backend.rag.seed_knowledge_base import INCIDENTS_DIR


def test_load_simulation_records_round_trips_correctly():
    incident = load_incidents_from_dir(INCIDENTS_DIR)[0]
    records = load_simulation_records(SIMULATION_RUNS_DIR / incident.source_simulation_run)
    assert len(records) > 0
    assert records[0].record_index == 0
    assert [r.record_index for r in records] == list(range(len(records)))
    assert all(isinstance(r.xmeas.reactor_pressure_kpa, float) for r in records)
    assert all(isinstance(r.idv_active.idv_6, bool) for r in records)


def test_all_incident_source_runs_exist_and_load():
    for incident in load_incidents_from_dir(INCIDENTS_DIR):
        records = load_simulation_records(SIMULATION_RUNS_DIR / incident.source_simulation_run)
        max_needed_index = max(s.record_index for s in incident.stages)
        assert len(records) > max_needed_index
