from backend.utils.monitoring import log_event, read_events


def test_log_event_appends_json_line(tmp_path):
    path = tmp_path / "monitoring.log"
    event = log_event("run_started", path=path, run_id="run-1", scenario_name="baseline")
    assert event["event_type"] == "run_started"
    assert "timestamp" in event

    events = read_events(path)
    assert len(events) == 1
    assert events[0]["run_id"] == "run-1"


def test_multiple_events_append_in_order(tmp_path):
    path = tmp_path / "monitoring.log"
    log_event("run_started", path=path, run_id="run-1")
    log_event("assessment_completed", path=path, run_id="run-1", risk_score=42.0)
    log_event("run_completed", path=path, run_id="run-1")

    events = read_events(path)
    assert [e["event_type"] for e in events] == ["run_started", "assessment_completed", "run_completed"]


def test_read_events_on_missing_file_returns_empty_list(tmp_path):
    assert read_events(tmp_path / "does_not_exist.log") == []


def test_event_fields_survive_non_trivial_types(tmp_path):
    path = tmp_path / "monitoring.log"
    log_event("assessment_completed", path=path, risk_score=None, is_novel_condition=True, latencies={"a": 1.5})
    events = read_events(path)
    assert events[0]["risk_score"] is None
    assert events[0]["is_novel_condition"] is True
    assert events[0]["latencies"] == {"a": 1.5}
