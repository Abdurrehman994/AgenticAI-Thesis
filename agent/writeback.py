"""Reviewable write-back and the append-only proposal log.

Descriptions go into PLM as "[PROPOSED] value", so reviewers see them in the 3DEXPERIENCE app.
Part numbers are identifiers that a prefix would corrupt: they are only logged, and written to
PLM when a reviewer approves them.
"""
import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from plm_client import Engineering

from .gaps import PROPOSED_PREFIX
from .snapshot import field_value
from .suggest import Proposal

DEFAULT_LOG = Path(__file__).resolve().parents[1] / "runs" / "proposals.jsonl"


class Conflict(RuntimeError):
    pass


def proposed_text(value: str) -> str:
    return f"{PROPOSED_PREFIX} {value}"


class ProposalLog:
    """One JSON object per line. Review decisions are appended as new lines, never edited in place."""

    def __init__(self, path: Path = DEFAULT_LOG):
        self.path = path

    def append(self, record: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **record}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def proposals(self) -> dict[str, dict]:
        """proposal_id -> proposal with its current status: pending, approved or rejected."""
        state = {}
        for record in self.records():
            if record["event"] == "proposed":
                state[record["proposal_id"]] = {**record, "status": "pending"}
            elif record["proposal_id"] in state:
                state[record["proposal_id"]]["status"] = record["event"]
        return state

    def pending(self) -> list[dict]:
        return [p for p in self.proposals().values() if p["status"] == "pending"]


def write_proposal(eng: Engineering, proposal: Proposal, item: dict, *, suggester: str) -> dict:
    """Write one proposal to PLM (descriptions only) and return its log record."""
    record = {
        "event": "proposed",
        "proposal_id": uuid.uuid4().hex[:8],
        "suggester": suggester,
        **asdict(proposal),
        "old_value": field_value(item, proposal.field),
        "written_to_plm": proposal.field == "description",
    }
    if record["written_to_plm"]:
        updated = eng.patch_item(item["id"], {"description": proposed_text(proposal.value)}, cestamp=item.get("cestamp"))
        item["cestamp"] = updated.get("cestamp", item.get("cestamp"))
    record["cestamp"] = item.get("cestamp")
    return record


def _attributes(field: str, value: str) -> dict:
    return {"dseng:EnterpriseReference": {"partNumber": value}} if field == "partNumber" else {field: value}


def _unchanged_item(eng: Engineering, record: dict) -> dict:
    """The current item, or Conflict if the field was edited in PLM after the proposal was made.

    Compares the field's content rather than cestamp: a second proposal on the same item also
    changes cestamp, and that must not block reviewing the first one.
    """
    item = eng.get_item(record["item_id"])
    expected = proposed_text(record["value"]) if record["written_to_plm"] else record["old_value"]
    current = field_value(item, record["field"])
    if current != expected:
        raise Conflict(
            f"{record['title']} {record['field']} is now {current!r}, expected {expected!r}: "
            "it was changed in PLM, review it there"
        )
    return item


def approve(eng: Engineering, record: dict, *, value: str | None = None) -> dict:
    """Write the proposed value (or the reviewer's edited value) as the real field value."""
    item = _unchanged_item(eng, record)
    final = record["value"] if value is None else value
    eng.patch_item(item["id"], _attributes(record["field"], final), cestamp=item.get("cestamp"))
    return {"event": "approved", "proposal_id": record["proposal_id"], "final_value": final, "edited": final != record["value"]}


def reject(eng: Engineering, record: dict) -> dict:
    """Restore the value from before the proposal. Part number proposals never reached PLM."""
    if record["written_to_plm"]:
        item = _unchanged_item(eng, record)
        eng.patch_item(item["id"], _attributes(record["field"], record["old_value"]), cestamp=item.get("cestamp"))
    return {"event": "rejected", "proposal_id": record["proposal_id"]}
