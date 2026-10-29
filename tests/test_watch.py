from agent.watch import ChangeTracker
from agent.writeback import ProposalLog
from scripts.threshold import at, choose, curve
from scripts.watch_agent import poll


def test_tracker_reports_new_and_changed_items_and_survives_a_restart(tmp_path):
    state = tmp_path / "state.json"
    tracker = ChangeTracker(state)
    assert tracker.changed([{"id": "A", "cestamp": "1"}, {"id": "B", "cestamp": "1"}]) == {"A", "B"}
    tracker.save()

    restarted = ChangeTracker(state)
    assert restarted.changed([{"id": "A", "cestamp": "1"}, {"id": "B", "cestamp": "2"}, {"id": "C", "cestamp": "1"}]) == {"B", "C"}


def test_poll_handles_only_changed_items(tenant, tmp_path):
    tracker, log = ChangeTracker(None), ProposalLog(tmp_path / "log.jsonl")
    collabspace = tenant.items["ID-API_ASM_GUARD"]["collabspace"]

    changed, results = poll(tenant, tracker, collabspace=collabspace, log=log)
    assert changed == set(tenant.items) and results  # first poll: everything is new
    assert poll(tenant, tracker, collabspace=collabspace, log=log) == (set(), [])

    tenant.patch_item("ID-API_ASM_GUARD", {"title": "API_ASM_GUARD"})  # any change bumps the cestamp
    changed, results = poll(tenant, tracker, collabspace=collabspace, log=log)
    assert changed == {"ID-API_ASM_GUARD"}
    assert {r["gap"]["title"] for r in results} == {"API_ASM_GUARD"}


def test_threshold_is_the_lowest_with_no_wrong_write():
    runs = [
        (4, [(0.8, True), (0.6, True), (0.4, False), (0.3, True)]),
        (4, [(0.8, True), (0.6, False), (0.3, False)]),
    ]
    rows = curve(runs)
    best = choose(rows)
    assert best["threshold"] == 0.8  # at 0.6 the second run writes a wrong value
    assert best["written"] == 1 and best["correct_coverage"] == 0.25
    assert at(rows, 0.5)["threshold"] == 0.6 and at(rows, 0.5)["wrong"] == 0.5
    assert choose(curve([(2, [(0.9, False)])]))["threshold"] > 1  # nothing is safe: write nothing
