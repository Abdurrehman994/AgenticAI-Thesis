import json
from pathlib import Path

from agent.gaps import find_gaps
from agent.offline import DatasetTenant
from agent.snapshot import Snapshot
from agent.suggest import RuleBasedSuggester
from scripts.cad_to_dataset import convert, true_values
from scripts.compare import aggregate, score_run
from scripts.evaluate import ground_truth, run_fields
from scripts.sweep import sweep

EXTRACT = {
    "Kit/Box.SLDASM": {"kind": "assembly", "properties": {}, "configurations": {"Default": {"Description": "Box assembly"}},
                       "children": {"lid.sldprt": 1, "screw.sldprt": 4, "toolbox-part.sldprt": 2}},
    "Kit/Lid.SLDPRT": {"kind": "part", "properties": {"Partnumber": "100-01", "Description": "Lid"},
                       "configurations": {"Default": {"Description": "Lid, old"}}},
    "Kit/Screw.SLDPRT": {"kind": "part", "properties": {"Part No": "100-02"}, "configurations": {}},
    "Kit/Broken.SLDPRT": {"error": "could not open"},
}


def test_true_values_prefer_custom_tab_then_configuration():
    assert true_values(EXTRACT["Kit/Lid.SLDPRT"]) == {"description": "Lid", "partNumber": "100-01"}
    assert true_values(EXTRACT["Kit/Box.SLDASM"]) == {"description": "Box assembly"}
    assert true_values(EXTRACT["Kit/Screw.SLDPRT"]) == {"partNumber": "100-02"}


def test_convert_resolves_children_and_blanks_reproducibly():
    dataset = convert(EXTRACT, blank_fraction=0.5, seed=1, collabspace="CS")
    items = {i["title"]: i for i in dataset["items"]}

    assert set(items) == {"Box", "Lid", "Screw"}
    assert items["Box"]["children"] == ["Lid", "Screw"]
    assert dataset["_unresolved_children"] == ["toolbox-part.sldprt"]
    blanks = [(t, f) for t, i in items.items() for f in i.get("blank", [])]
    assert len(blanks) == 2  # half of the 4 known values
    assert all(f in items[t] for t, f in blanks)  # only known values are blanked
    assert convert(EXTRACT, blank_fraction=0.5, seed=1, collabspace="CS") == dataset


def test_unknown_fields_are_gaps_without_ground_truth():
    dataset = convert(EXTRACT, blank_fraction=0.5, seed=1, collabspace="CS")
    tenant = DatasetTenant(dataset)
    gaps = {(g.title, g.field) for g in find_gaps(Snapshot(tenant, tenant.iter_search("*")).items.values())}
    truth = ground_truth(dataset)

    assert set(truth) <= gaps
    assert ("Box", "partNumber") in gaps - set(truth)  # no CAD value


def test_heldout_dataset_file_is_consistent():
    path = Path(__file__).resolve().parents[1] / "data" / "dataset_cad.json"
    dataset = json.loads(path.read_text(encoding="utf-8"))
    titles = [i["title"] for i in dataset["items"]]
    assert len(titles) == len(set(titles))
    assert all(child in titles for i in dataset["items"] for child in i.get("children", []))
    assert all(field in i for i in dataset["items"] for field in i.get("blank", []))


def result(title, field, value=None, confidence=0.0):
    proposal = {"value": value, "confidence": confidence} if value else None
    return {"gap": {"title": title, "field": field}, "proposal": proposal, "elapsed_s": 0.5}


def test_score_run():
    truth = {("A", "description"): "Hex nut M6", ("B", "partNumber"): "X-2", ("C", "partNumber"): "X-3"}
    truth[("E", "description")] = "Locking lever head"
    run = {"results": [
        result("A", "description", "hex nut, m6", 0.9),  # correct after normalizing
        result("B", "partNumber", "X-9", 0.6),  # wrong
        result("C", "partNumber"),  # no proposal
        result("D", "description", "anything", 0.9),  # no ground truth: not graded
        result("E", "description", "Locking lever", 0.2),  # close, not correct
    ]}
    s = score_run(run, truth)

    assert s["graded"] == 4
    assert (s["coverage"], s["accuracy"], s["close"], s["precision"]) == (3 / 4, 1 / 4, 2 / 4, 1 / 3)
    assert (s["written"], s["written_correct"]) == (2, 1)
    assert round(s["brier"], 3) == round(((0.9 - 1) ** 2 + 0.6**2 + 0.2**2) / 3, 3)
    assert s["tokens"] is None and s["errors"] == 0

    a = aggregate([s, {**s, "accuracy": 3 / 4}])
    assert a["runs"] == 2 and a["accuracy"] == {"mean": 0.5, "min": 1 / 4, "max": 3 / 4}


def test_material_is_read_and_blanked_without_changing_the_other_blanks():
    with_material = {k: dict(v) for k, v in EXTRACT.items()}
    with_material["Kit/Lid.SLDPRT"]["properties"] = {**EXTRACT["Kit/Lid.SLDPRT"]["properties"], "Material": "ABS"}
    with_material["Kit/Screw.SLDPRT"]["properties"] = {**EXTRACT["Kit/Screw.SLDPRT"]["properties"], "Material": "Steel"}
    assert true_values(with_material["Kit/Lid.SLDPRT"])["material"] == "ABS"

    def other_blanks(dataset):
        return [(i["title"], [f for f in i.get("blank", []) if f != "material"]) for i in dataset["items"]]

    before = convert(EXTRACT, blank_fraction=0.5, seed=1, collabspace="CS")
    after = convert(with_material, blank_fraction=0.5, seed=1, collabspace="CS")
    assert other_blanks(after) == other_blanks(before)
    assert sum("material" in i.get("blank", []) for i in after["items"]) == 1  # half of the 2 materials


def test_material_from_siblings():
    dataset = {"collabspace": "CS", "items": [
        {"title": "Box", "children": ["A", "B", "C", "D"]},
        {"title": "A", "material": "ABS"}, {"title": "B", "material": "ABS"}, {"title": "C", "material": "Steel"},
        {"title": "D", "material": "ABS", "blank": ["material"]},
    ]}
    tenant = DatasetTenant(dataset)
    snapshot = Snapshot(tenant, tenant.iter_search("*"))
    gaps = find_gaps(snapshot.items.values(), fields=["material"])
    assert {g.title for g in gaps} == {"Box", "D"}

    proposals = {g.title: RuleBasedSuggester().suggest(g, snapshot) for g in gaps}
    assert proposals["Box"] is None  # assemblies get no material
    assert (proposals["D"].value, proposals["D"].confidence) == ("ABS", 0.4)  # a majority, not unanimous


def test_scores_only_the_fields_a_run_checked():
    dataset = {"items": [{"title": "A", "description": "x", "material": "ABS", "blank": ["description", "material"]}]}
    assert set(ground_truth(dataset)) == {("A", "description"), ("A", "material")}
    assert set(ground_truth(dataset, run_fields({}))) == {("A", "description")}  # runs from before --fields

    truth = ground_truth(dataset)
    run = {"results": [result("A", "description", "y", 0.3), result("A", "material", "abs", 0.6)]}
    assert score_run(run, truth, field="material")["accuracy"] == 1.0
    assert score_run(run, truth, field="description")["accuracy"] == 0.0


def test_sweep_scores_every_seed_and_field():
    extract = {k: dict(v) for k, v in EXTRACT.items()}
    scores = sweep(extract, RuleBasedSuggester(), seeds=[1, 2, 3], blank_fraction=0.5, fields=("description", "partNumber"))
    assert set(scores) == {"description", "partNumber"}
    assert [s["seed"] for s in scores["partNumber"]] == [1, 2, 3]
