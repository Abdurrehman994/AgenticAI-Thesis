import pytest

from collections import Counter

from scripts.calibration import (ALL, FIXED, accuracy, accuracy_interval, bootstrap, brier, by_gap, choose_tolerant, ece, learn_mapping,
                                 plot, proposal_rows, reliability, remap, selected, split_runs, threshold_transfer)
from scripts.threshold import curve


def test_ece_is_zero_when_confidence_matches_accuracy():
    pairs = [(0.75, True)] * 3 + [(0.75, False)] + [(0.25, True)] + [(0.25, False)] * 3
    assert ece(pairs) == pytest.approx(0.0)
    assert ece([]) is None


def test_ece_measures_over_confidence():
    # Always 0.9 sure, right half the time: off by 0.4 in the only bin
    assert ece([(0.9, True), (0.9, False)]) == pytest.approx(0.4)
    assert brier([(1.0, True), (0.0, False)]) == 0.0


def test_reliability_bins_and_top_bin_includes_one():
    bins = reliability([(1.0, True), (0.85, False), (0.1, False)])
    assert [(b["bin"], b["n"]) for b in bins] == [("0.0-0.2", 1), ("0.8-1.0", 2)]
    assert bins[1]["accuracy"] == 0.5


def test_bootstrap_counts_a_gap_once_however_often_it_was_repeated():
    rows = [{"gap": f"g{i}", "confidence": 0.8, "correct": i % 2 == 0} for i in range(10)]
    repeated = rows * 6  # the same 10 gaps answered in six runs
    assert len(by_gap(repeated)) == 10
    once, six = bootstrap(by_gap(rows), accuracy), bootstrap(by_gap(repeated), accuracy)
    assert once == six  # six repeats add no information: the interval stays as wide
    low, high = once
    assert low < 0.5 < high and high - low > 0.3
    assert bootstrap(by_gap(rows[:4]), accuracy) is None  # too few gaps for an interval


def test_bootstrap_is_reproducible():
    clusters = [[(0.7, True)], [(0.7, False)], [(0.3, False)], [(0.3, True)], [(0.8, True)], [(0.1, False)]]
    assert bootstrap(clusters, ece) == bootstrap(clusters, ece)


def test_split_runs_keeps_graded_gaps_per_field():
    rows = [{"field": "description"}, {"field": "partNumber"}, {"field": "description"}]
    group = [(Counter(description=5, partNumber=3), rows)]
    assert split_runs(group, "partNumber") == [(3, [rows[1]])]
    assert split_runs(group, ALL) == [(8, rows)]


def test_learned_mapping_is_smoothed_accuracy_per_basis():
    rows = [{"basis": "copied", "correct": True}] * 3 + [{"basis": "inferred", "correct": False}] * 2
    mapping = learn_mapping(rows)
    assert mapping["copied"] == pytest.approx(4 / 5) and mapping["inferred"] == pytest.approx(1 / 4)
    assert remap([{"basis": "guess", "correct": False}], mapping) == [(mapping["*"], False)]  # unseen basis


def test_threshold_chosen_on_training_runs_is_applied_to_test_runs():
    train = [(4, [(0.8, True), (0.3, False)])]
    test = [(4, [(0.8, False), (0.8, True), (0.3, False)])]
    t = threshold_transfer(train, test)
    assert t["threshold"] == 0.8 and t["written"] == 2 and t["wrong"] == 1
    assert set(FIXED) == {"copied", "pattern", "inferred", "guess"}


def test_tolerant_threshold_accepts_a_small_share_of_wrong_writes():
    # 0.8 bin: 19 right, 1 wrong (5%); 0.3 bin: all wrong. Strict writes nothing, tolerant (10%) writes the 0.8s
    runs = [(30, [(0.8, True)] * 19 + [(0.8, False)] + [(0.3, False)] * 10)]
    rows = curve(runs)
    assert choose_tolerant(rows, 0.1)["threshold"] == 0.8
    assert choose_tolerant(rows, 0.0)["threshold"] > 1  # nothing qualifies: write nothing
    strict, loose = threshold_transfer(runs, runs), threshold_transfer(runs, runs, 0.1)
    assert strict["written"] == 0 and (loose["written"], loose["wrong"]) == (20, 1)


def test_close_option_counts_near_matches():
    run = {"results": [{"gap": {"title": "A", "field": "description"},
                        "proposal": {"value": "Sprinkler rotation adjuster", "confidence": 0.7, "method": "m"},
                        "llm": {"basis": "pattern"}}]}
    truth = {("A", "description"): "Rotation Adjuster"}
    assert proposal_rows(run, truth)[0]["correct"] is False
    assert proposal_rows(run, truth, close=True)[0] == {"confidence": 0.7, "correct": True, "basis": "pattern",
                                                         "field": "description", "gap": "A|description"}


def test_suggester_filter_matches_label_parts():
    assert selected("agent-v3:gpt-oss-120b+evidence", ["agent-v3"]) and selected("rules", [])
    assert not selected("agent-v2:gpt-oss-120b+evidence", ["agent-v3", "rules"])


def test_plot_writes_a_figure(tmp_path):
    rows = [{"suggester": "rules", "dataset": "dataset.json", "ece": 0.1,
             "reliability": [{"confidence": 0.3, "accuracy": 0.2, "n": 10}, {"confidence": 0.75, "accuracy": 1.0, "n": 6}]}]
    plot(rows, tmp_path / "r.png", close=False)
    assert (tmp_path / "r.png").stat().st_size > 1000


def test_rule_of_three_when_every_gap_has_the_same_outcome():
    all_wrong = [[(0.3, False)] for _ in range(10)]
    assert bootstrap(all_wrong, accuracy) == (0.0, 0.0)  # the bootstrap alone claims certainty
    assert accuracy_interval(all_wrong) == (0.0, 0.3)  # 0 of 10: at most about 30%
    assert accuracy_interval([[(0.8, True)] for _ in range(6)]) == (0.5, 1.0)
