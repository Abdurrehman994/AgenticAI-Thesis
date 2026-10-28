"""Review proposals in 3DEXPERIENCE: one route per batch, one Approve task per proposal.

The reviewer approves or rejects each task in the platform's own task inbox; a comment starting with
"value:" approves with an edited value. sync() turns finished tasks into the same approve / reject calls
as scripts/review.py, so the conflict check (field changed in PLM since the proposal) still applies.
"""
from datetime import datetime

from .writeback import PROPOSED_PREFIX

EDIT_PREFIX = "value:"
FIELD_NAMES = {"description": "description", "partNumber": "part number"}


def task_title(record: dict) -> str:
    """Starts with the proposal id, which is how sync() finds the task again."""
    return f"{record['proposal_id']} {record['title']} {FIELD_NAMES.get(record['field'], record['field'])}"


def task_instructions(record: dict) -> str:
    current = (
        f"It is shown in PLM as '{PROPOSED_PREFIX} {record['value']}'."
        if record["written_to_plm"] else "It is not in PLM yet: approving writes it."
    )
    evidence = "; ".join(record.get("evidence") or []) or "none given"
    return (
        f"The AI agent proposes {FIELD_NAMES.get(record['field'], record['field'])} '{record['value']}' "
        f"for {record['title']} (confidence {record['confidence']:.1f}, {record['method']}). {current} "
        f"Evidence: {evidence}. Approve to accept, reject to restore the previous value. "
        f"To accept a different value, approve with the comment '{EDIT_PREFIX} <new value>'."
    )


def build_route(records: list[dict], reviewer: str, *, now: datetime | None = None, attach_items: bool = True) -> dict:
    """requestBodies/routes payload. Same-order tasks run in parallel; a rejection does not stop the others."""
    now = now or datetime.now()
    route = {
        "title": f"AI proposals review {now:%Y-%m-%d %H:%M}",
        "description": f"{len(records)} values proposed by the PLM enrichment agent, one task per proposal.",
        "routeBasePurpose": "Approval",
        "AutoStopOnRejection": "Deferred",
        "routeCompletionAction": "Notify Route Owner",
        "tasks": [
            {
                "title": task_title(r),
                "instructions": task_instructions(r),
                "taskAction": "Approve",
                "taskOrder": "1",
                "parallelNodeProcessionRule": "All",
                "taskAssigneeUsername": reviewer,
            }
            for r in records
        ],
    }
    if attach_items:
        route["contentIds"] = "|".join(dict.fromkeys(r["item_id"] for r in records))
    return route


def decision(task: dict) -> tuple[str | None, str | None]:
    """("approve", edited value or None), ("reject", None) or (None, None) while the task is open."""
    status = (task.get("approvalStatus") or "").strip().lower()
    if status.startswith("approve"):
        comment = (task.get("comments") or "").strip()
        edited = comment[len(EDIT_PREFIX):].strip() if comment.lower().startswith(EDIT_PREFIX) else None
        return "approve", edited or None
    if status.startswith("reject"):
        return "reject", None
    return None, None


def decisions(route: dict, records: list[dict]) -> list[tuple[dict, str | None, str | None]]:
    """For each routed proposal: (record, action, edited value). A proposal whose task is missing stays open."""
    tasks = route.get("tasks") or []
    out = []
    for record in records:
        task = next((t for t in tasks if (t.get("title") or "").startswith(record["proposal_id"])), None)
        out.append((record, *decision(task)) if task else (record, None, None))
    return out
