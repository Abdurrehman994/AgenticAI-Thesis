"""Engineering Item calls, built against docs/openapi/dseng-1.4.1.json."""
from collections.abc import Iterator

from .session import MODELER_PATH, PLMError, PLMSession

ITEM = "/dseng/dseng:EngItem"

MASK_DEFAULT = "dskern:Mask.Default"
MASK_COMMON = "dsmveng:EngItemMask.Common"
MASK_DETAILS = "dsmveng:EngItemMask.Details"  # adds partNumber, enterprise attributes, isManufacturable
INSTANCE_MASK_DETAILS = "dsmveng:EngInstanceMask.Details"  # adds referencedObject (child) and findNumber

CREATE_BATCH_LIMIT = 50  # POST /dseng:EngItem accepts at most 50 items per call
SEARCH_TOP_LIMIT = 1000


class Engineering:
    def __init__(self, session: PLMSession):
        self.session = session

    def search_items(self, search_str: str, *, mask: str = MASK_DETAILS, top: int = 50, skip: int = 0) -> list[dict]:
        """Indexed search. Empty attributes are omitted from the response, not returned as ""."""
        data = self.session.request(
            "GET",
            f"{ITEM}/search",
            params={"$searchStr": search_str, "$mask": mask, "$top": min(top, SEARCH_TOP_LIMIT), "$skip": skip},
        )
        return data.get("member", [])

    def iter_search(self, search_str: str, *, mask: str = MASK_DETAILS, page_size: int = 100) -> Iterator[dict]:
        skip = 0
        while True:
            page = self.search_items(search_str, mask=mask, top=page_size, skip=skip)
            yield from page
            if len(page) < page_size:
                return
            skip += page_size

    def get_item(self, item_id: str, *, mask: str = MASK_DETAILS) -> dict:
        members = self.session.request("GET", f"{ITEM}/{item_id}", params={"$mask": mask}).get("member", [])
        if not members:
            raise PLMError(404, f"Engineering Item {item_id} not found")
        return members[0]

    def patch_item(self, item_id: str, attributes: dict, *, cestamp: str | None = None, mask: str = MASK_DETAILS) -> dict:
        """Modify attributes. cestamp is required by the schema; fetched if not given.

        Writable per dseng_EngItem_PATCH: title, description, versionComment, isManufacturable,
        dseng:EnterpriseReference, dseno:EnterpriseAttributes, customerAttributes.
        """
        if cestamp is None:
            cestamp = self.get_item(item_id, mask=MASK_DEFAULT)["cestamp"]
        data = self.session.request(
            "PATCH", f"{ITEM}/{item_id}", params={"$mask": mask}, json={**attributes, "cestamp": cestamp}
        )
        return data.get("member", [{}])[0]

    def create_items(self, attributes: list[dict], *, item_type: str = "VPMReference", mask: str = MASK_DETAILS) -> list[dict]:
        created = []
        for start in range(0, len(attributes), CREATE_BATCH_LIMIT):
            batch = attributes[start : start + CREATE_BATCH_LIMIT]
            data = self.session.request(
                "POST",
                ITEM,
                params={"$mask": mask},
                json={"items": [{"type": item_type, "attributes": a} for a in batch]},
            )
            created.extend(data.get("member", []))
        return created

    def get_instances(self, item_id: str, *, mask: str = INSTANCE_MASK_DETAILS, top: int = 50, skip: int = 0) -> list[dict]:
        """Child instances (BOM lines) of an item; referencedObject points at the child item."""
        data = self.session.request(
            "GET", f"{ITEM}/{item_id}/dseng:EngInstance", params={"$mask": mask, "$top": top, "$skip": skip}
        )
        return data.get("member", [])

    def iter_instances(self, item_id: str, *, mask: str = INSTANCE_MASK_DETAILS, page_size: int = 100) -> Iterator[dict]:
        skip = 0
        while True:
            page = self.get_instances(item_id, mask=mask, top=page_size, skip=skip)
            yield from page
            if len(page) < page_size:
                return
            skip += page_size

    def add_instance(self, parent_id: str, child_id: str, *, name: str) -> dict:
        """Add child_id to parent_id's BOM."""
        body = {"instances": [{"referencedObject": self._reference(child_id), "attributes": {"name": name}}]}
        data = self.session.request(
            "POST", f"{ITEM}/{parent_id}/dseng:EngInstance", params={"$mask": INSTANCE_MASK_DETAILS}, json=body
        )
        return data.get("member", [{}])[0]

    def get_parents(self, item_id: str) -> list[str]:
        """Where-used: ids of items whose BOM contains item_id. Index based, so new links appear with a delay."""
        data = self.session.request(
            "POST",
            f"{ITEM}/locate",
            json={"referencedObjects": [self._reference(item_id)], "navigateTo": ["dseng:EngItem"]},
        )
        parents = []
        for member in data.get("member", []):
            for instance in (member.get("dseng:EngInstance") or {}).get("member", []):
                parent_id = (instance.get("parentObject") or {}).get("identifier")
                if parent_id and parent_id not in parents:
                    parents.append(parent_id)
        return parents

    def get_material(self, item_id: str) -> dict:
        """Material is a dsspec:Material relationship, not an item attribute."""
        return self.session.request("GET", f"{ITEM}/{item_id}/dsspec:Material")

    def _reference(self, item_id: str) -> dict:
        # The tenant rejects the spec's "$3DSpace" and "/dseng:EngItem/{id}" examples: it wants its
        # own 3DSpace URL as source and the full modeler path
        return {
            "source": self.session.cfg.space_url,
            "type": "dseng:EngItem",
            "identifier": item_id,
            "relativePath": f"{MODELER_PATH}{ITEM}/{item_id}",
        }
