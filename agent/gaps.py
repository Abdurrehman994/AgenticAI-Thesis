"""Gap detection: plain rules, no AI, so the thesis can separate "what is missing" from "what to fill in"."""
from collections.abc import Iterable
from dataclasses import dataclass

from .snapshot import field_value

FIELDS = ("description", "partNumber")
# Material is a dsspec:Material relationship that the current roles cannot read (403), so it is checked only in
# offline runs on a dataset (run_agent.py --dataset --fields ...): the CAD files hold the ground truth.
MATERIAL = "material"
ALL_FIELDS = (*FIELDS, MATERIAL)
PROPOSED_PREFIX = "[PROPOSED]"


@dataclass(frozen=True)
class Gap:
    item_id: str
    title: str
    field: str


def find_gaps(
    items: Iterable[dict], pending: set[tuple[str, str]] = frozenset(), fields: Iterable[str] = FIELDS
) -> list[Gap]:
    """Empty fields, skipping (item_id, field) pairs that already have a proposal awaiting review.

    A description holding a [PROPOSED] value is not empty, so it is never reported twice.
    """
    return [
        Gap(item["id"], item.get("title", ""), field)
        for item in items
        for field in fields
        if (item["id"], field) not in pending and not field_value(item, field).strip()
    ]
