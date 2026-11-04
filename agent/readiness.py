"""Release-readiness check: can this assembly be released, or what is still missing in its BOM?

Walks the whole product structure under one item and reports every blocker, plain code and read-only:
- an empty field (description, part number; material only offline, it is a 403 relationship in PLM, and only
  on parts);
- a description still marked [PROPOSED] (an AI value nobody has approved yet);
- a proposal for the item still pending review in the proposal log;
- a part number used by more than one item (in the BOM or anywhere in the collab space);
- a cycle in the structure (an assembly that contains itself).

The agent fills gaps; this check shows whether the result is complete. It only reports and notifies (optionally
with a route task): blocking a maturity change would need the lifecycle API, which is not used yet.
"""
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime

from .gaps import FIELDS, MATERIAL, PROPOSED_PREFIX, find_gaps
from .snapshot import Snapshot, field_value, part_number

MISSING, UNAPPROVED, PENDING, DUPLICATE, CYCLE = "missing", "unapproved AI value", "pending review", "duplicate part number", "cycle"


@dataclass
class Issue:
    item_id: str
    title: str
    kind: str
    field: str = ""
    detail: str = ""


@dataclass
class BomLine:
    item_id: str
    title: str
    depth: int


@dataclass
class Report:
    root_id: str
    root_title: str
    fields: tuple[str, ...]
    bom: list[BomLine] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict:
        return {**asdict(self), "ready": self.ready}


def walk_bom(snapshot: Snapshot, root_id: str) -> tuple[list[BomLine], list[Issue]]:
    """Every item under root_id once (depth first, root at depth 0), and an issue for each cycle found."""
    lines, cycles, done = [], [], set()

    def visit(item_id: str, depth: int, path: tuple[str, ...]) -> None:
        title = snapshot.item(item_id).get("title", item_id)
        if item_id in path:
            cycles.append(Issue(item_id, title, CYCLE, detail=" > ".join(snapshot.item(i).get("title", i) for i in (*path, item_id))))
            return
        if item_id in done:  # a part used in several assemblies is checked once
            return
        done.add(item_id)
        lines.append(BomLine(item_id, title, depth))
        for child in snapshot.children(item_id):
            visit(child, depth + 1, (*path, item_id))

    visit(root_id, 0, ())
    return lines, cycles


def check(snapshot: Snapshot, root_id: str, *, fields: tuple[str, ...] = FIELDS, pending: list[dict] = ()) -> Report:
    """The readiness report for the structure under root_id. `pending`: proposals awaiting review (ProposalLog)."""
    bom, issues = walk_bom(snapshot, root_id)
    items = [snapshot.item(line.item_id) for line in bom]

    for gap in find_gaps(items, fields=fields):
        if gap.field == MATERIAL and snapshot.children(gap.item_id):
            continue  # material belongs to parts, not assemblies (as in the material suggester)
        issues.append(Issue(gap.item_id, gap.title, MISSING, gap.field))
    for item in items:
        if field_value(item, "description").startswith(PROPOSED_PREFIX):
            issues.append(Issue(item["id"], item.get("title", ""), UNAPPROVED, "description", field_value(item, "description")))

    in_bom = {line.item_id for line in bom}
    for record in pending:
        if record["item_id"] in in_bom:
            issues.append(Issue(record["item_id"], record["title"], PENDING, record["field"],
                                f"proposal {record['proposal_id']}: {record['value']!r}"))

    users = defaultdict(list)  # part number -> titles of every item in the collab space and the BOM using it
    for item in {**snapshot.items, **{i["id"]: i for i in items}}.values():
        if part_number(item):
            users[part_number(item)].append(item.get("title", item["id"]))
    for item in items:
        number = part_number(item)
        others = [t for t in users.get(number, []) if t != item.get("title")]
        if number and others:
            issues.append(Issue(item["id"], item.get("title", ""), DUPLICATE, "partNumber", f"{number} also on {', '.join(sorted(others))}"))

    order = {line.item_id: n for n, line in enumerate(bom)}
    issues.sort(key=lambda i: (order.get(i.item_id, len(order)), i.kind, i.field))
    root = snapshot.item(root_id)
    return Report(root_id, root.get("title", root_id), tuple(fields), bom, issues)


def summary(report: Report) -> str:
    """'NOT READY: 7 issues on 5 of 18 items (missing 5, pending review 2)' or 'READY: 18 items checked'."""
    if report.ready:
        return f"READY: {len(report.bom)} items checked"
    kinds = defaultdict(int)
    for issue in report.issues:
        kinds[issue.kind] += 1
    items = len({i.item_id for i in report.issues})
    counts = ", ".join(f"{kind} {n}" for kind, n in sorted(kinds.items()))
    return f"NOT READY: {len(report.issues)} issues on {items} of {len(report.bom)} items ({counts})"


def render(report: Report) -> str:
    """Plain-text report: the BOM as a tree with each item's issues under it."""
    by_item = defaultdict(list)
    for issue in report.issues:
        by_item[issue.item_id].append(issue)
    lines = [f"Release readiness of {report.root_title} (checked: {', '.join(report.fields)})", summary(report), ""]
    for line in report.bom:
        mark = "!" if by_item.get(line.item_id) else " "
        lines.append(f"{mark} {'  ' * line.depth}{line.title}")
        for issue in by_item.get(line.item_id, []):
            text = f"{issue.kind}" + (f" {issue.field}" if issue.field else "") + (f": {issue.detail}" if issue.detail else "")
            lines.append(f"    {'  ' * line.depth}- {text}")
    for issue in report.issues:
        if issue.kind == CYCLE:
            lines.append(f"! cycle: {issue.detail}")
    return "\n".join(lines)


def build_route(report: Report, reviewer: str, *, now: datetime | None = None) -> dict:
    """A route with one task for the reviewer: the verdict and the blockers, with the root item attached.

    Same route shape as the proposal review (agent/review_route.py), which is verified on the tenant.
    """
    now = now or datetime.now()
    blockers = "; ".join(
        f"{i.title}: {i.kind}" + (f" {i.field}" if i.field else "") for i in report.issues[:30]
    ) + (f"; and {len(report.issues) - 30} more" if len(report.issues) > 30 else "")
    return {
        "title": f"Release readiness {report.root_title} {now:%Y-%m-%d %H:%M}",
        "description": summary(report),
        "routeBasePurpose": "Approval",
        "AutoStopOnRejection": "Deferred",
        "routeCompletionAction": "Notify Route Owner",
        "contentIds": report.root_id,
        "tasks": [{
            "title": f"Release readiness: {report.root_title}",
            "instructions": (
                f"{summary(report)}. " + (f"Blockers: {blockers}. " if blockers else "")
                + "Approve when the blockers are resolved or accepted, reject to send the structure back for completion."
            ),
            "taskAction": "Approve",
            "taskOrder": "1",
            "parallelNodeProcessionRule": "All",
            "taskAssigneeUsername": reviewer,
        }],
    }
