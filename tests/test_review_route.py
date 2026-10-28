from datetime import datetime

from agent.review_route import build_route, decision, decisions, task_title
from agent.snapshot import Snapshot
from agent.gaps import find_gaps
from agent.suggest import RuleBasedSuggester
from agent.writeback import ProposalLog, approve, write_proposal


def pending_records(tenant, tmp_path):
    """The rules' confident proposals on the dataset, written and logged as run_agent.py --apply does."""
    snapshot = Snapshot(tenant, tenant.iter_search("*"))
    log = ProposalLog(tmp_path / "proposals.jsonl")
    suggester = RuleBasedSuggester()
    for gap in find_gaps(snapshot.items.values()):
        proposal = suggester.suggest(gap, snapshot)
        if proposal and proposal.confidence >= 0.5:
            log.append(write_proposal(tenant, proposal, snapshot.items[gap.item_id], suggester="rules"))
    return log


def test_route_has_one_approve_task_per_proposal(tenant, tmp_path):
    records = pending_records(tenant, tmp_path).pending()
    route = build_route(records, "reviewer1", now=datetime(2026, 10, 29, 9, 30))

    assert route["title"] == "AI proposals review 2026-10-29 09:30"
    assert len(route["tasks"]) == len(records) == 5
    task = route["tasks"][0]
    assert task["title"].startswith(records[0]["proposal_id"])
    assert (task["taskAction"], task["taskOrder"], task["taskAssigneeUsername"]) == ("Approve", "1", "reviewer1")
    assert records[0]["value"] in task["instructions"]
    assert route["contentIds"].split("|") == list(dict.fromkeys(r["item_id"] for r in records))
    assert "contentIds" not in build_route(records, "reviewer1", attach_items=False)


def test_decision_from_task():
    assert decision({"approvalStatus": "Approved", "comments": "looks right"}) == ("approve", None)
    assert decision({"approvalStatus": "Approved", "comments": "value: Idler roller, 50 mm"}) == ("approve", "Idler roller, 50 mm")
    assert decision({"approvalStatus": "Rejected", "comments": "wrong part"}) == ("reject", None)
    assert decision({"approvalStatus": "None"}) == (None, None)
    assert decision({}) == (None, None)


def test_routed_proposal_stays_pending_and_sync_applies_decision(tenant, tmp_path):
    log = pending_records(tenant, tmp_path)
    nut = next(p for p in log.pending() if p["title"] == "API_NUT_M6_ISO4032")
    log.append({"event": "routed", "proposal_id": nut["proposal_id"], "route_id": "R1", "task_title": task_title(nut)})

    routed = log.proposals()[nut["proposal_id"]]
    assert (routed["status"], routed["route_id"]) == ("pending", "R1")

    route = {"tasks": [{"title": task_title(nut), "approvalStatus": "Approved", "comments": "value: Hex nut M6, zinc"}]}
    ((record, action, edited),) = decisions(route, [routed])
    assert (action, edited) == ("approve", "Hex nut M6, zinc")
    log.append(approve(tenant, record, value=edited))
    assert tenant.items[nut["item_id"]]["description"] == "Hex nut M6, zinc"
    assert log.proposals()[nut["proposal_id"]]["status"] == "approved"


def test_task_missing_from_route_stays_open(tenant, tmp_path):
    record = pending_records(tenant, tmp_path).pending()[0]
    assert decisions({"tasks": []}, [record]) == [(record, None, None)]
