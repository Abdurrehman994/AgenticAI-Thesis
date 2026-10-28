"""Review proposals through a 3DEXPERIENCE route (approval workflow) instead of review.py.

    python scripts/review_route.py create                 # dry run: prints the route it would create
    python scripts/review_route.py create --yes           # creates and starts it; tasks reach the reviewer's inbox
    python scripts/review_route.py sync                   # dry run: shows the decisions made in the platform
    python scripts/review_route.py sync --yes             # applies them (approve / reject, as review.py does)
    python scripts/review_route.py delete ROUTE_ID --yes  # remove a test route

create takes the pending proposals that are not in a route yet (run_agent.py --apply makes them). The
reviewer defaults to the logged-in user (--reviewer to assign someone else). One Approve task per proposal;
approving with the comment "value: <new value>" accepts an edited value.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.review_route import build_route, decisions, task_title  # noqa: E402
from agent.writeback import DEFAULT_LOG, Conflict, ProposalLog, approve, reject  # noqa: E402
from plm_client import Engineering, PLMError, PLMSession, Routes, Settings  # noqa: E402


def create(routes: Routes, log: ProposalLog, args) -> None:
    records = [p for p in log.pending() if not p.get("route_id")]
    if not records:
        print("No pending proposals outside a route. Run scripts/run_agent.py --apply first.")
        return
    reviewer = args.reviewer or routes.current_username()
    route = build_route(records, reviewer, attach_items=not args.no_items)
    print(f"Route for {len(records)} proposals, reviewer {reviewer}:\n")
    print(json.dumps(route, indent=2, ensure_ascii=False))
    if not args.yes:
        print("\nDry run: nothing created. Re-run with --yes.")
        return

    created = routes.create(route)
    route_id = created.get("id")
    if not route_id:
        raise SystemExit(f"Route not created, response: {created}")
    routes.start(route_id)
    for record in records:
        log.append({"event": "routed", "proposal_id": record["proposal_id"], "route_id": route_id, "task_title": task_title(record)})
    print(f"\nCreated and started route {created.get('name', '')} ({route_id}). Run 'sync' after the reviewer has decided.")


def sync(routes: Routes, log: ProposalLog, args) -> None:
    by_route = defaultdict(list)
    for record in log.pending():
        if record.get("route_id"):
            by_route[record["route_id"]].append(record)
    if not by_route:
        print("No pending proposals in a route.")
        return

    eng = Engineering(routes.session)
    for route_id, records in by_route.items():
        route = routes.get(route_id)
        print(f"Route {route.get('name', route_id)}: {route.get('state', '?')}, {route.get('routeStatus', '?')}")
        for record, action, edited in decisions(route, records):
            label = f"  {record['proposal_id']}  {record['title']:<28} {record['field']:<12}"
            if action is None:
                print(f"{label} open")
                continue
            shown = f"{action} {edited!r}" if edited else action
            if not args.yes:
                print(f"{label} {shown} (dry run)")
                continue
            try:
                event = approve(eng, record, value=edited) if action == "approve" else reject(eng, record)
            except (Conflict, PLMError) as exc:
                print(f"{label} ! {exc}")
                continue
            log.append({**event, "via": f"route {route_id}"})
            print(f"{label} {shown}")
    if not args.yes:
        print("\nDry run: nothing applied. Re-run with --yes.")


def delete(routes: Routes, log: ProposalLog, args) -> None:
    if not args.yes:
        print(f"Would delete route(s) {', '.join(args.route_ids)}. Re-run with --yes.")
        return
    print(routes.delete(args.route_ids))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "sync", "delete"):
        sub = commands.add_parser(name)
        sub.add_argument("--yes", action="store_true", help="write to the tenant (default: dry run)")
        if name == "create":
            sub.add_argument("--reviewer", help="platform user name of the reviewer (default: you)")
            sub.add_argument("--no-items", action="store_true", help="do not attach the items as route content")
        if name == "delete":
            sub.add_argument("route_ids", nargs="+")
    args = parser.parse_args()

    routes = Routes(PLMSession(Settings.from_env()))
    {"create": create, "sync": sync, "delete": delete}[args.command](routes, ProposalLog(args.log), args)


if __name__ == "__main__":
    main()
