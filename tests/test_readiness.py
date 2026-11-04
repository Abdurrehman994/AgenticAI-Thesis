import json
from pathlib import Path

from agent.offline import DatasetTenant
from agent.readiness import CYCLE, DUPLICATE, MISSING, PENDING, UNAPPROVED, build_route, check, render, summary
from agent.snapshot import Snapshot

ROOT_ID = "ID-API_ASM_CONVEYOR_LINE"


def snapshot_of(tenant) -> Snapshot:
    return Snapshot(tenant, tenant.iter_search("*"))


def test_reports_every_blank_in_the_structure(tenant, dataset):
    report = check(snapshot_of(tenant), ROOT_ID)
    blanks = {(e["title"], f) for e in dataset["items"] for f in e.get("blank", [])}

    assert {(i.title, i.field) for i in report.issues} == blanks
    assert {i.kind for i in report.issues} == {MISSING}
    assert len(report.bom) == len(dataset["items"]) and report.bom[0].depth == 0
    assert not report.ready and summary(report).startswith("NOT READY: 12 issues on 9 of 18 items")


def test_a_sub_assembly_is_checked_on_its_own(tenant):
    report = check(snapshot_of(tenant), "ID-API_ASM_GUARD")
    assert {line.title for line in report.bom} == {
        "API_ASM_GUARD", "API_GUARD_PANEL_MESH", "API_GUARD_HINGE_AL", "API_BOLT_M6X16_ISO4017", "API_NUT_M6_ISO4032"
    }


def test_complete_structure_is_ready(dataset):
    complete = {**dataset, "items": [{k: v for k, v in e.items() if k != "blank"} for e in dataset["items"]]}
    report = check(snapshot_of(DatasetTenant(complete)), ROOT_ID)
    assert report.ready and summary(report) == "READY: 18 items checked"
    assert "READY" in render(report)


def test_unapproved_values_and_pending_proposals_block_release(tenant):
    tenant.items["ID-API_ASM_GUARD"]["description"] = "[PROPOSED] Guard assembly"
    pending = [{"item_id": "ID-API_BELT_PVC_600", "title": "API_BELT_PVC_600", "field": "partNumber",
                "proposal_id": "p1", "value": "CNV-1006"}, {"item_id": "ID-elsewhere", "title": "X", "field": "description",
                                                           "proposal_id": "p2", "value": "x"}]
    report = check(snapshot_of(tenant), ROOT_ID, pending=pending)
    kinds = {(i.title, i.kind) for i in report.issues}

    assert ("API_ASM_GUARD", UNAPPROVED) in kinds and ("API_ASM_GUARD", MISSING) not in kinds
    assert ("API_BELT_PVC_600", PENDING) in kinds and ("X", PENDING) not in kinds  # only proposals in this BOM


def test_duplicate_part_numbers_are_reported_on_both_items(tenant):
    tenant.items["ID-API_NUT_M6_ISO4032"]["dseng:EnterpriseReference"] = {"partNumber": "MTR-2002"}  # the M8 nut's
    duplicates = [i for i in check(snapshot_of(tenant), ROOT_ID).issues if i.kind == DUPLICATE]
    assert {i.title for i in duplicates} == {"API_NUT_M6_ISO4032", "API_NUT_M8_ISO4032"}
    assert "also on API_NUT_M8_ISO4032" in next(i.detail for i in duplicates if i.title == "API_NUT_M6_ISO4032")


def test_cycle_is_reported_and_does_not_loop(tenant):
    tenant.bom["ID-API_GUARD_PANEL_MESH"] = ["ID-API_ASM_GUARD"]
    report = check(snapshot_of(tenant), "ID-API_ASM_GUARD")
    cycle = next(i for i in report.issues if i.kind == CYCLE)
    assert cycle.detail == "API_ASM_GUARD > API_GUARD_PANEL_MESH > API_ASM_GUARD"


def test_material_is_required_on_parts_only():
    dataset = {"collabspace": "CS", "items": [{"title": "Box", "children": ["Lid"]}, {"title": "Lid"}]}
    tenant = DatasetTenant(dataset)
    report = check(snapshot_of(tenant), "ID-Box", fields=("material",))
    assert [(i.title, i.field) for i in report.issues] == [("Lid", "material")]


def test_route_carries_the_verdict_and_the_root_item(tenant):
    report = check(snapshot_of(tenant), "ID-API_ASM_GUARD")
    route = build_route(report, "reviewer")
    task = route["tasks"][0]
    assert route["contentIds"] == "ID-API_ASM_GUARD" and route["description"] == summary(report)
    assert "API_GUARD_HINGE_AL: missing partNumber" in task["instructions"] and task["taskAssigneeUsername"] == "reviewer"
    assert json.loads(json.dumps(report.to_dict()))["ready"] is False


def test_cli_exit_code_is_the_verdict(monkeypatch, tmp_path, capsys):
    from scripts import readiness

    dataset = Path(__file__).resolve().parents[1] / "data" / "dataset.json"
    out = tmp_path / "report.json"
    monkeypatch.setattr("sys.argv", ["readiness.py", "API_ASM_GUARD", "--dataset", str(dataset), "--out", str(out)])
    assert readiness.main() == 1
    assert json.loads(out.read_text(encoding="utf-8"))["root_title"] == "API_ASM_GUARD"
    assert "NOT READY" in capsys.readouterr().out
