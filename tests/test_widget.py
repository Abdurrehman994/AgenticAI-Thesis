"""The widget's JavaScript checks (widget/core.js) must give the same answers as the Python ones."""
import json
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest

from agent.duplicates import find_duplicates, find_existing
from agent.offline import DatasetTenant
from agent.readiness import check, summary
from agent.snapshot import Snapshot
from scripts.serve_widget import decision_record, offline_payload

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "widget" / "core.js"
NODE = shutil.which("node")

RUNNER = """
const core = require(process.argv[1]);
let input = '';
process.stdin.on('data', d => input += d).on('end', () => {
  const {snapshot, root, pending, query} = JSON.parse(input);
  const report = core.readiness(snapshot, root, pending);
  process.stdout.write(JSON.stringify({
    summary: core.summary(report),
    issues: report.issues,
    bom: report.bom,
    duplicates: core.findDuplicates(snapshot),
    existing: core.findExisting(snapshot, '', query, ''),
  }));
});
"""


def snapshot_of(dataset: dict) -> Snapshot:
    tenant = DatasetTenant(dataset)
    return Snapshot(tenant, tenant.iter_search("*"))


def run_core(snapshot: Snapshot, root: str, pending: list[dict], query: str) -> dict:
    data = {
        "snapshot": {"items": snapshot.items, "children": {i: snapshot.children(i) for i in snapshot.items}},
        "root": root, "pending": pending, "query": query,
    }
    out = subprocess.run([NODE, "-e", RUNNER, str(CORE)], input=json.dumps(data), capture_output=True, text=True,
                         check=True, encoding="utf-8")
    return json.loads(out.stdout)


def same_candidates(js: list[dict], py: list) -> None:
    assert [(c["title"], c["other_title"]) for c in js] == [(c.title, c.other_title) for c in py]
    assert [c["reasons"] for c in js] == [c.reasons for c in py]
    assert all(abs(a["score"] - b.score) < 1e-3 for a, b in zip(js, py))


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("name, root, query", [
    ("dataset.json", "ID-API_ASM_CONVEYOR_LINE", "Hex nut M8, zinc plated"),
    ("dataset_cad.json", "ID-SWC-OrbitalSprinkler", "base gasket"),
])
def test_core_js_matches_python(name, root, query):
    dataset = json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))
    snapshot = snapshot_of(dataset)
    pending = [{"item_id": root, "title": "x", "field": "description", "proposal_id": "abc12345", "value": "v"}]
    js = run_core(snapshot, root, pending, query)

    report = check(snapshot, root, pending=pending)
    assert js["summary"] == summary(report)
    assert js["issues"] == [asdict(i) for i in report.issues]
    assert js["bom"] == [asdict(line) for line in report.bom]
    same_candidates(js["duplicates"], find_duplicates(snapshot))
    same_candidates(js["existing"], find_existing(snapshot, "", query))


def test_offline_payload_marks_proposed_descriptions(dataset):
    payload = offline_payload(dataset)
    by_title = {item["title"]: item for item in payload["items"].values()}
    proposals = {(p["title"], p["field"]): p for p in payload["pending"]}

    assert ("API_NUT_M6_ISO4032", "description") in proposals
    nut = proposals[("API_NUT_M6_ISO4032", "description")]
    assert by_title["API_NUT_M6_ISO4032"]["description"] == f"[PROPOSED] {nut['value']}" and nut["written_to_plm"]
    assert all(not p["written_to_plm"] for p in payload["pending"] if p["field"] == "partNumber")
    assert payload["children"]["ID-API_ASM_GUARD"]


def test_decision_must_match_a_pending_proposal():
    pending = [{"proposal_id": "abc12345", "value": "Guard assembly"}]
    assert decision_record({"proposal_id": "abc12345", "event": "approved", "final_value": "Safety guard"}, pending) == {
        "event": "approved", "proposal_id": "abc12345", "final_value": "Safety guard", "edited": True, "via": "widget"}
    assert decision_record({"proposal_id": "abc12345", "event": "rejected"}, pending) == {
        "event": "rejected", "proposal_id": "abc12345", "via": "widget"}
    for bad in ({"proposal_id": "nope", "event": "approved"}, {"proposal_id": "abc12345", "event": "deleted"},
                {"proposal_id": "abc12345", "event": "approved", "final_value": ""}):
        with pytest.raises(ValueError):
            decision_record(bad, pending)
