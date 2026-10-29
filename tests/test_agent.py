import pytest

from agent.gaps import Gap, find_gaps
from agent.snapshot import Snapshot
from agent.suggest import RuleBasedSuggester, match_case
from agent.writeback import Conflict, ProposalLog, approve, reject, write_proposal
from scripts.run_agent import run


def propose_all(tenant):
    snapshot = Snapshot(tenant, tenant.iter_search("*"))
    suggester = RuleBasedSuggester()
    gaps = find_gaps(snapshot.items.values())
    return snapshot, {(g.title, g.field): suggester.suggest(g, snapshot) for g in gaps}


def test_gaps_are_exactly_the_dataset_blanks(tenant, dataset):
    snapshot = Snapshot(tenant, tenant.iter_search("*"))
    found = {(g.title, g.field) for g in find_gaps(snapshot.items.values())}
    assert found == {(e["title"], field) for e in dataset["items"] for field in e.get("blank", [])}


def test_proposed_values_and_pending_proposals_are_not_gaps():
    items = [{"id": "A", "title": "A", "description": "[PROPOSED] x"}, {"id": "B", "title": "B"}]
    assert find_gaps(items, pending={("B", "description")}) == [Gap("A", "A", "partNumber"), Gap("B", "B", "partNumber")]


@pytest.mark.parametrize(
    ("title", "field", "value", "method"),
    [
        ("API_ROLLER_IDLER_D50", "description", "Idler roller, D50 mm", "description-analogy"),
        ("API_BOLT_M6X16_ISO4017", "description", "Hex bolt M6x16 ISO 4017, zinc plated", "description-analogy"),
        ("API_NUT_M6_ISO4032", "description", "Hex nut M6 ISO 4032, zinc plated", "description-analogy"),
        # MESH->AL is not a dimension change, so the guard panel is not used as an analogy
        ("API_GUARD_HINGE_AL", "description", "Guard hinge aluminium", "title-expansion"),
        ("API_GUARD_HINGE_AL", "partNumber", "GRD-3002", "sibling-numbers"),
        # the shared bolt (CNV-1005) in the motor bracket BOM is ignored
        ("API_WASHER_M8_ISO7089", "partNumber", "MTR-2003", "sibling-numbers"),
    ],
)
def test_rules_on_dataset(tenant, title, field, value, method):
    _, proposals = propose_all(tenant)
    assert (proposals[(title, field)].value, proposals[(title, field)].method) == (value, method)


def test_no_part_number_when_several_siblings_are_unnumbered(tenant):
    # Idler and belt share a parent: CNV-1003 and CNV-1006 are free, but not which goes where
    _, proposals = propose_all(tenant)
    assert proposals[("API_ROLLER_IDLER_D50", "partNumber")] is None
    assert proposals[("API_BELT_PVC_600", "partNumber")] is None


def test_part_numbers_do_not_depend_on_bom_order(tenant):
    tenant.bom = {parent: list(reversed(children)) for parent, children in tenant.bom.items()}
    _, proposals = propose_all(tenant)
    assert proposals[("API_GUARD_HINGE_AL", "partNumber")].value == "GRD-3002"
    assert proposals[("API_WASHER_M8_ISO7089", "partNumber")].value == "MTR-2003"


def test_match_case():
    assert match_case("Drive", "IDLER") == "Idler"
    assert match_case("M8x25", "M6X16") == "M6x16"
    assert match_case("m8", "M6") == "m6"


def test_description_proposed_then_approved(tenant, tmp_path):
    snapshot, proposals = propose_all(tenant)
    proposal = proposals[("API_NUT_M6_ISO4032", "description")]
    log = ProposalLog(tmp_path / "proposals.jsonl")

    log.append(write_proposal(tenant, proposal, snapshot.items[proposal.item_id], suggester="rules"))
    assert tenant.items[proposal.item_id]["description"] == "[PROPOSED] Hex nut M6 ISO 4032, zinc plated"

    (pending,) = log.pending()
    log.append(approve(tenant, pending))
    assert tenant.items[proposal.item_id]["description"] == "Hex nut M6 ISO 4032, zinc plated"
    assert log.pending() == []
    assert log.proposals()[pending["proposal_id"]]["status"] == "approved"


def test_reject_restores_old_value(tenant):
    snapshot, proposals = propose_all(tenant)
    proposal = proposals[("API_BOLT_M6X16_ISO4017", "description")]
    record = write_proposal(tenant, proposal, snapshot.items[proposal.item_id], suggester="rules")
    reject(tenant, record)
    assert "description" not in tenant.items[proposal.item_id]


def test_part_number_written_only_on_approval(tenant):
    snapshot, proposals = propose_all(tenant)
    proposal = proposals[("API_GUARD_HINGE_AL", "partNumber")]
    record = write_proposal(tenant, proposal, snapshot.items[proposal.item_id], suggester="rules")
    assert tenant.patches == [] and not record["written_to_plm"]

    approve(tenant, record, value="GRD-3002-A")
    assert tenant.items[proposal.item_id]["dseng:EnterpriseReference"] == {"partNumber": "GRD-3002-A"}


def test_approve_refuses_field_edited_in_plm(tenant):
    snapshot, proposals = propose_all(tenant)
    proposal = proposals[("API_ROLLER_IDLER_D50", "description")]
    record = write_proposal(tenant, proposal, snapshot.items[proposal.item_id], suggester="rules")
    tenant.patch_item(proposal.item_id, {"description": "Changed by an engineer"})
    with pytest.raises(Conflict):
        approve(tenant, record)


def test_run_writes_confident_proposals_once(tenant, tmp_path):
    log = ProposalLog(tmp_path / "proposals.jsonl")
    first = run(tenant, collabspace="API_development", apply=True, min_confidence=0.5, log=log)
    assert len(first) == 12
    written = [r for r in first if r["proposal_id"]]
    assert len(written) == len(log.pending()) == 5
    assert all(r["proposal"]["confidence"] >= 0.5 for r in written)

    second = run(tenant, collabspace="API_development", apply=True, min_confidence=0.5, log=log)
    assert len(second) == 7 and not any(r["proposal_id"] for r in second)


def test_run_only_proposes_for_the_given_titles(tenant, tmp_path):
    results = run(tenant, collabspace=tenant.items["ID-API_ASM_GUARD"]["collabspace"], log=ProposalLog(tmp_path / "log.jsonl"),
                  fields=("description",), only={"API_ASM_GUARD"})
    assert [(r["gap"]["title"], r["gap"]["field"]) for r in results] == [("API_ASM_GUARD", "description")]
