"""In-memory tenant built from a dataset file, for tests and offline evaluation runs.

Implements the Engineering methods the agent uses, including the cestamp check on PATCH. Item ids are
"ID-<title>". Every evaluation run starts from the same blanks, whatever was approved in the real tenant.
"""
import copy

from plm_client import PLMError

from .gaps import MATERIAL


class DatasetTenant:
    def __init__(self, dataset: dict):
        self.items: dict[str, dict] = {}
        self.bom: dict[str, list[str]] = {}
        self.patches: list[tuple[str, dict]] = []
        for entry in dataset["items"]:
            item_id = f"ID-{entry['title']}"
            blank = set(entry.get("blank", []))
            item = {"id": item_id, "title": entry["title"], "collabspace": dataset["collabspace"], "cestamp": "c0"}
            # A field missing from the entry has no known value: it is a gap with no ground truth
            if entry.get("description") and "description" not in blank:
                item["description"] = entry["description"]
            if entry.get("partNumber") and "partNumber" not in blank:
                item["dseng:EnterpriseReference"] = {"partNumber": entry["partNumber"]}
            if entry.get(MATERIAL) and MATERIAL not in blank:
                item[MATERIAL] = entry[MATERIAL]  # stands in for the dsspec:Material relationship
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
