"""Change detection for the polling agent: which items are new or changed since the last poll.

Without the Enterprise Integration Architect role there are no platform events, so the agent polls search and
compares each item's cestamp with the one it saw last time. A changed cestamp means the item was modified (also
by the agent's own write-back; its gaps are then pending and skipped). When events become available, the event
handler calls the same entry point with the item id from the event: run_agent.run(..., only={item_id}).

Search is index based, so a change shows up a few minutes after it was made.
"""
import json
from pathlib import Path

DEFAULT_STATE = Path(__file__).resolve().parents[1] / "runs" / "watch-state.json"


class ChangeTracker:
    """item id -> last seen cestamp, kept in a JSON file so a restarted watcher does not redo everything."""

    def __init__(self, path: Path | None = DEFAULT_STATE):
        self.path = path
        self.seen: dict[str, str] = {}
        if path and path.exists():
            self.seen = json.loads(path.read_text(encoding="utf-8"))

    def changed(self, items: list[dict]) -> set[str]:
        """Ids of items that are new or whose cestamp differs, and remember the current cestamps."""
        changed = {i["id"] for i in items if self.seen.get(i["id"]) != i.get("cestamp")}
        self.seen.update({i["id"]: i.get("cestamp", "") for i in items})
        return changed

    def save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.seen, indent=1), encoding="utf-8")
