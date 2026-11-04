import json
from pathlib import Path

from agent.duplicates import find_duplicates, find_existing, plant, score_planted, specs, words
from agent.offline import DatasetTenant
from agent.snapshot import Snapshot

CAD_DATASET = Path(__file__).resolve().parents[1] / "data" / "dataset_cad.json"


def snapshot_of(dataset: dict) -> Snapshot:
    tenant = DatasetTenant(dataset)
    return Snapshot(tenant, tenant.iter_search("*"))


def with_items(dataset: dict, *entries: dict) -> dict:
    return {**dataset, "items": [*dataset["items"], *entries]}


def test_words_keep_sizes_apart():
    assert words("Hex nut M8 ISO 4032, zinc plated") == {"hex", "nut", "m8", "iso", "4032", "zinc", "plated"}
    assert words('1 1/4" STANDARD WEIGHT PIPE') == {"1+1/4", "standard", "weight", "pipe"}
    assert words("Bearing Upper - 22 mm") == words("bearing upper 22mm")
    assert specs(words('1" pipe')) != specs(words('1 1/4" pipe'))


def test_no_duplicates_in_the_ground_truth(dataset):
    # The M6 and M8 nuts and bolts share every word but the size: variants, not duplicates
    assert find_duplicates(snapshot_of(dataset)) == []


def test_a_part_created_twice_is_found(dataset):
    copy = {"title": "Nut m8 iso4032", "description": "hex nut m8 iso 4032"}
    found = find_duplicates(snapshot_of(with_items(dataset, copy)))
    assert [(c.title, c.other_title) for c in found] == [("API_NUT_M8_ISO4032", "Nut m8 iso4032")]
    assert any("m8" in reason for reason in found[0].reasons)


def test_description_matches_when_the_title_says_nothing(dataset):
    copy = {"title": "prd-00012345", "description": "Hex bolt M8x25 ISO 4017"}
    found = find_duplicates(snapshot_of(with_items(dataset, copy)))
    assert {(c.title, c.other_title) for c in found} == {("API_BOLT_M8X25_ISO4017", "prd-00012345")}


def test_different_material_is_not_a_duplicate(dataset):
    dataset = with_items(
        dataset,
        {"title": "SPACER_A", "description": "Spacer ring 10 mm", "material": "Brass"},
        {"title": "SPACER_B", "description": "Spacer ring 10 mm", "material": "Nylon"},
        {"title": "SPACER_C", "description": "Spacer ring 10 mm", "material": "brass"},
    )
    found = {(c.title, c.other_title) for c in find_duplicates(snapshot_of(dataset))}
    assert found == {("SPACER_A", "SPACER_C")}


def test_assemblies_with_the_same_children_are_duplicates(dataset):
    children = ["API_GUARD_PANEL_MESH", "API_GUARD_HINGE_AL", "API_BOLT_M6X16_ISO4017", "API_NUT_M6_ISO4032"]
    found = find_duplicates(snapshot_of(with_items(dataset, {"title": "COVER_UNIT", "children": children})))
    assert [(c.title, c.other_title) for c in found] == [("API_ASM_GUARD", "COVER_UNIT")]
    assert "same children: 4 of 4" in found[0].reasons


def test_unapproved_ai_description_is_not_evidence(dataset):
    tenant = DatasetTenant(with_items(dataset, {"title": "PLATE_X"}))
    tenant.items["ID-PLATE_X"]["description"] = "[PROPOSED] Side plate, S235 steel, laser cut"
    assert find_duplicates(Snapshot(tenant, tenant.iter_search("*"))) == []


def test_new_part_is_checked_before_creation(dataset):
    found = find_existing(snapshot_of(dataset), "", "Hex nut M8, zinc plated")
    assert [c.other_title for c in found][:1] == ["API_NUT_M8_ISO4032"]
    assert find_existing(snapshot_of(dataset), "", "Hex nut M10, zinc plated") == []  # other size: a new part


def test_planted_duplicates_are_found(dataset):
    planted, pairs = plant(dataset, 6, seed=2026)
    assert len(pairs) == 6 and len(planted["items"]) == len(dataset["items"]) + 6
    assert plant(dataset, 6, seed=2026) == (planted, pairs)  # reproducible
    rows = score_planted(find_duplicates(snapshot_of(planted)), pairs, [0.5])
    assert rows[0]["recall"] == 1.0 and rows[0]["precision"] == 1.0


def test_held_out_cad_data_has_real_near_duplicates():
    found = {frozenset((c.title, c.other_title)) for c in find_duplicates(snapshot_of(json.loads(CAD_DATASET.read_text(encoding="utf-8"))))}
    assert frozenset(("SWC-Gasket sprinkler", "SWC-Gasket-jet sprinkler")) in found
    assert frozenset(("Lower Pipe", "Short.Pipe")) in found
    assert frozenset(("Handle", "Lower Pipe")) not in found  # 1" and 1 1/4" pipe
