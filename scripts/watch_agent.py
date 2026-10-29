"""Run the agent continuously: poll the collab space and handle only items that are new or changed.

    python scripts/watch_agent.py                        # dry run, polls every 5 minutes until Ctrl+C
    python scripts/watch_agent.py --interval 60 --apply  # writes [PROPOSED] values for changed items
    python scripts/watch_agent.py --baseline             # remember the current state, handle only later changes
    python scripts/watch_agent.py --once                 # one poll, e.g. from a scheduled task

This is the polling stand-in for platform events (agent/watch.py). Each poll that finds gaps saves a run file
like run_agent.py. The first poll sees every item as new, so it equals a full run unless --baseline is given.
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.gaps import FIELDS  # noqa: E402
from agent.snapshot import Snapshot, collab_items  # noqa: E402
from agent.watch import DEFAULT_STATE, ChangeTracker  # noqa: E402
from agent.writeback import ProposalLog  # noqa: E402
from plm_client import Engineering, PLMError, PLMSession, Settings  # noqa: E402
from scripts.run_agent import SUGGESTERS, make_suggester, run, save_run  # noqa: E402


def poll(eng, tracker: ChangeTracker, *, collabspace: str, search: str = "*", handle: bool = True,
         **run_options) -> tuple[set[str], list[dict]]:
    """One search: the changed item ids, and the agent's results for them (none if nothing changed or not handle)."""
    items = collab_items(eng, search, collabspace)
    changed = tracker.changed(items)
    results = []
    if changed and handle:  # the agent works on the same search result the changes were detected in
        results = run(eng, collabspace=collabspace, only=changed, snapshot=Snapshot(eng, items), **run_options)
    tracker.save()
    return changed, results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--collabspace", default="API_development")
    parser.add_argument("--search", default="*")
    parser.add_argument("--interval", type=float, default=300, help="seconds between polls")
    parser.add_argument("--once", action="store_true", help="poll once and exit")
    parser.add_argument("--baseline", action="store_true", help="record the current state first, without handling it")
    parser.add_argument("--apply", action="store_true", help="write proposals to PLM and the proposal log")
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--suggester", choices=SUGGESTERS, default="rules")
    parser.add_argument("--model")
    parser.add_argument("--confidence", choices=("self", "evidence"), default="self")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE, help="where the last seen cestamps are kept")
    args = parser.parse_args()

    eng = Engineering(PLMSession(Settings.from_env()))
    suggester = make_suggester(args.suggester, args.model, args.confidence)
    tracker, log = ChangeTracker(args.state), ProposalLog()
    if args.baseline:
        changed, _ = poll(eng, tracker, collabspace=args.collabspace, search=args.search, handle=False)
        print(f"Baseline: {len(tracker.seen)} items recorded in {args.state} ({len(changed)} new or changed)")

    while True:
        try:
            changed, results = poll(
                eng, tracker, collabspace=args.collabspace, search=args.search, apply=args.apply,
                min_confidence=args.min_confidence, log=log, suggester=suggester,
            )
        except PLMError as exc:  # a failed poll is retried at the next interval
            print(f"{datetime.now():%H:%M:%S} poll failed: {exc}")
            changed, results = set(), []
        if not changed:
            print(f"{datetime.now():%H:%M:%S} no changes")
        if results:
            out = save_run(
                results, collabspace=args.collabspace, suggester=suggester, dataset=None, fields=FIELDS,
                applied=args.apply, min_confidence=args.min_confidence, trigger="watch",
            )
            print(f"Saved {out.relative_to(ROOT)}")
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
