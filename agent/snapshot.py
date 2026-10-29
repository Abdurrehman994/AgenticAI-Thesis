"""Read-only view of one collab space: items from search, BOM links and where-used fetched on demand."""
from collections.abc import Iterable

from plm_client import Engineering


def part_number(item: dict) -> str:
    return (item.get("dseng:EnterpriseReference") or {}).get("partNumber") or ""


def field_value(item: dict, field: str) -> str:
    # Search responses omit empty attributes, so a missing key and "" both mean empty. "material" is only
    # set by the offline tenant: in PLM it is a relationship, not an attribute
    return part_number(item) if field == "partNumber" else item.get(field) or ""


def collab_items(eng: Engineering, search: str = "*", collabspace: str | None = None) -> list[dict]:
    """Search results, limited to one collab space if given (search spans every space the user can see)."""
    return [i for i in eng.iter_search(search) if not collabspace or i.get("collabspace") == collabspace]


class Snapshot:
    def __init__(self, eng: Engineering, items: Iterable[dict]):
        self.eng = eng
        self.items = {item["id"]: item for item in sorted(items, key=lambda i: i.get("title", ""))}
        self._children: dict[str, list[str]] = {}
        self._parents: dict[str, list[str]] = {}

    @classmethod
    def load(cls, eng: Engineering, search: str = "*", collabspace: str | None = None) -> "Snapshot":
        return cls(eng, collab_items(eng, search, collabspace))

    def item(self, item_id: str) -> dict:
        """Items outside the collab space (e.g. a child from a library) are fetched once."""
        if item_id not in self.items:
            self.items[item_id] = self.eng.get_item(item_id)
        return self.items[item_id]

    def children(self, item_id: str) -> list[str]:
        """Child item ids in BOM order, each listed once."""
        if item_id not in self._children:
            ids = [inst["referencedObject"]["identifier"] for inst in self.eng.iter_instances(item_id)]
            self._children[item_id] = list(dict.fromkeys(ids))
        return self._children[item_id]

    def parents(self, item_id: str) -> list[str]:
        if item_id not in self._parents:
            self._parents[item_id] = self.eng.get_parents(item_id)
        return self._parents[item_id]
