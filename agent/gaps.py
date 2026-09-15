"""Gap detection: plain rules, no AI, so the thesis can separate "what is missing" from "what to fill in"."""
from collections.abc import Iterable
from dataclasses import dataclass

from .snapshot import field_value

FIELDS = ("description", "partNumber")
PROPOSED_PREFIX = "[PROPOSED]"


@dataclass(frozen=True)
class Gap:
    item_id: str
    title: str
    field: str


def find_gaps(items: Iterable[dict], pending: set[tuple[str, str]] = frozenset()) -> list[Gap]:
    """Empty fields, skipping (item_id, field) pairs that already have a proposal awaiting review.

    A description holding a [PROPOSED] value is not empty, so it is never reported twice.
    """
    return [
        Gap(item["id"], item.get("title", ""), field)
        for item in items
        for field in FIELDS
        if (item["id"], field) not in pending and not field_value(item, field).strip()
    ]
