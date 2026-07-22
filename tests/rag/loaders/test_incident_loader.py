from backend.rag.loaders.incident_loader import load_incidents_from_dir
from backend.rag.seed_knowledge_base import INCIDENTS_DIR


def test_load_incidents_from_dir():
    incidents = load_incidents_from_dir(INCIDENTS_DIR)
    assert len(incidents) == 5
    ids = {i.incident_id for i in incidents}
    assert ids == {
        "reactor_kinetics_drift", "reactor_cw_valve_stiction", "reactor_a_feed_loss",
        "compressor_feed_pressure_loss", "separator_cooling_duty_loss",
    }


def test_incidents_have_three_stages_varying_in_cause():
    incidents = load_incidents_from_dir(INCIDENTS_DIR)
    cause_categories = set()
    for incident in incidents:
        assert len(incident.stages) == 3
        stage_names = [s.stage for s in incident.stages]
        assert stage_names == ["early_warning", "mid_escalation", "critical"]
        cause_categories.add(incident.cause_category)
    assert len(cause_categories) == 5  # varying in cause, not just severity (CLAUDE.md §14)


def test_incident_stage_record_indices_are_monotonic():
    for incident in load_incidents_from_dir(INCIDENTS_DIR):
        indices = [s.record_index for s in incident.stages]
        assert indices == sorted(indices)
