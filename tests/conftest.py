import copy
import json
from pathlib import Path

import pytest

from plm_client import PLMError

DATASET = Path(__file__).resolve().parents[1] / "data" / "dataset.json"


class FakeEngineering:
    """In-memory tenant built from data/dataset.json with the blanks applied.

    Implements the Engineering methods the agent uses, including the cestamp check on PATCH.
    Item ids are "ID-<title>".
    """

    def __init__(self, dataset: dict):
        self.items: dict[str, dict] = {}
        self.bom: dict[str, list[str]] = {}
        self.patches: list[tuple[str, dict]] = []
        for entry in dataset["items"]:
            item_id = f"ID-{entry['title']}"
            blank = set(entry.get("blank", []))
            item = {"id": item_id, "title": entry["title"], "collabspace": dataset["collabspace"], "cestamp": "c0"}
            if "description" not in blank:
                item["description"] = entry["description"]
            if "partNumber" not in blank:
                item["dseng:EnterpriseReference"] = {"partNumber": entry["partNumber"]}
            self.items[item_id] = item
            self.bom[item_id] = [f"ID-{child}" for child in entry.get("children", [])]

    def iter_search(self, search, **kwargs):
        return [copy.deepcopy(item) for item in self.items.values()]

    def get_item(self, item_id, **kwargs):
        if item_id not in self.items:
            raise PLMError(404, f"Engineering Item {item_id} not found")
        return copy.deepcopy(self.items[item_id])

    def patch_item(self, item_id, attributes, *, cestamp=None, **kwargs):
        item = self.items[item_id]
        if cestamp is not None and cestamp != item["cestamp"]:
            raise PLMError(400, "cestamp is outdated")
        for key, value in attributes.items():
            if isinstance(value, dict):
                item.setdefault(key, {}).update(value)
            elif value == "":
                item.pop(key, None)  # like search responses, empty attributes are left out
            else:
                item[key] = value
        item["cestamp"] = f"c{int(item['cestamp'][1:]) + 1}"
        self.patches.append((item_id, attributes))
        return copy.deepcopy(item)

    def iter_instances(self, item_id, **kwargs):
        return [{"referencedObject": {"identifier": child}} for child in self.bom.get(item_id, [])]

    def get_parents(self, item_id):
        return [parent for parent, children in self.bom.items() if item_id in children]


@pytest.fixture
def dataset() -> dict:
    return json.loads(DATASET.read_text(encoding="utf-8"))


@pytest.fixture
def tenant(dataset) -> FakeEngineering:
    return FakeEngineering(dataset)
