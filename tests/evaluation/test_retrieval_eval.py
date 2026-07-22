from backend.evaluation.retrieval_eval import RetrievalEvalSample, summarize


def _sample(scenario_name, expected, correct_top1, expected_in_topk, is_novel=False):
    return RetrievalEvalSample(
        scenario_name=scenario_name, seed=1, record_index=10, t_hours=0.5, expected_incident_id=expected,
        phase="fast_and_slow", is_novel_condition=is_novel, top_match_incident_id=expected if correct_top1 else "other",
        top_match_similarity=0.9, correct_top1=correct_top1, expected_in_topk=expected_in_topk,
    )


def test_summarize_empty_returns_zero_samples():
    assert summarize([]) == {"n_samples": 0}


def test_summarize_computes_precision_and_recall_for_fault_runs():
    samples = [
        _sample("a", "a", correct_top1=True, expected_in_topk=True),
        _sample("a", "a", correct_top1=False, expected_in_topk=True),
        _sample("b", "b", correct_top1=True, expected_in_topk=True),
    ]
    summary = summarize(samples)
    assert summary["n_samples"] == 3
    assert summary["precision_at_1_fault_runs"] == 2 / 3
    assert summary["recall_at_topk_fault_runs"] == 1.0


def test_summarize_negative_control_false_positive_rate():
    samples = [
        _sample("baseline", None, correct_top1=True, expected_in_topk=True, is_novel=True),
        _sample("baseline", None, correct_top1=False, expected_in_topk=False, is_novel=False),
    ]
    summary = summarize(samples)
    assert summary["false_positive_rate_negative_control"] == 0.5


def test_summarize_by_scenario_breakdown():
    samples = [
        _sample("a", "a", correct_top1=True, expected_in_topk=True),
        _sample("b", "b", correct_top1=False, expected_in_topk=False),
    ]
    summary = summarize(samples)
    assert summary["by_scenario"]["a"]["precision_at_1"] == 1.0
    assert summary["by_scenario"]["b"]["precision_at_1"] == 0.0
