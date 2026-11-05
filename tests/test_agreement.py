from scripts.agreement import gap_decisions


def run(*answers):
    """A run file with one result per (title, value, confidence); value None = no proposal."""
    return {"results": [{"gap": {"title": t, "field": "description"},
                         "proposal": None if v is None else {"value": v, "confidence": c}} for t, v, c in answers]}


TRUTH = {("A", "description"): "Hex nut M6", ("B", "description"): "Flat washer M8"}


def test_majority_answer_with_agreement_and_basis():
    runs = [run(("A", "Hex nut M6", 0.8), ("B", "Washer", 0.3)),
            run(("A", "hex nut, M6", 0.7), ("B", "Flat washer M8", 0.7)),
            run(("A", "Hex nut M6", 0.8), ("B", None, 0))]
    graded, decisions = gap_decisions(runs, TRUTH)
    a, b = decisions
    assert graded == 2
    # A: all three runs agree once case and punctuation are ignored
    assert (a["agreement"], a["distinct"], a["correct"]) == (1.0, 1, True)
    assert abs(a["basis"] - (0.8 + 0.7 + 0.8) / 3) < 1e-9 and abs(a["combined"] - a["basis"]) < 1e-9
    # B: two different answers and one run without a proposal; the tie goes to the more confident answer
    assert (b["value"], b["agreement"], b["distinct"], b["correct"]) == ("Flat washer M8", 1 / 3, 2, True)
    assert abs(b["combined"] - 0.7 / 3) < 1e-9


def test_gap_nobody_answered_is_graded_but_not_decided():
    runs = [run(("A", None, 0)), run(("A", None, 0)), run(("A", None, 0))]
    graded, decisions = gap_decisions(runs, TRUTH)
    assert graded == 1 and decisions == []


def test_close_option_grades_the_majority_answer_leniently():
    runs = [run(("B", "Flat washer M8 zinc", 0.7))] * 3
    assert gap_decisions(runs, TRUTH)[1][0]["correct"] is False
    assert gap_decisions(runs, TRUTH, close=True)[1][0]["correct"] is True
