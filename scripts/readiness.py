"""Release-readiness check of one assembly: is its whole BOM complete, or what blocks the release?

    python scripts/readiness.py API_ASM_CONVEYOR_LINE                  # live tenant, read-only
    python scripts/readiness.py API_ASM_GUARD --out runs/readiness.json
    python scripts/readiness.py "Hand Truck" --dataset data/dataset_cad.json --fields description,partNumber,material
    python scripts/readiness.py API_ASM_GUARD --route                  # dry run: prints the route task
    python scripts/readiness.py API_ASM_GUARD --route --yes            # creates it in the reviewer's task inbox

Exit code 0 when the structure is ready and 1 when it is not, so other scripts can use it as a gate.
Pending proposals come from runs/proposals.jsonl (live tenant only). See agent/readiness.py for the checks.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.gaps import MATERIAL  # noqa: E402
from agent.readiness import build_route, check, render  # noqa: E402
from agent.snapshot import Snapshot  # noqa: E402
from agent.writeback import ProposalLog  # noqa: E402
from plm_client import Engineering, PLMSession, Settings  # noqa: E402
from scripts.run_agent import parse_fields  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("item", help="title or id of the assembly (or part) to check")
    parser.add_argument("--collabspace", help="default: PLM_COLLABSPACE, else the space in PLM_SECURITY_CONTEXT")
    parser.add_argument("--search", default="*")
    parser.add_argument("--fields", default="description,partNumber", help="fields that must be filled")
    parser.add_argument("--dataset", type=Path, help="check an in-memory tenant built from this dataset instead")
    parser.add_argument("--out", type=Path, help="also save the report as JSON")
    parser.add_argument("--route", action="store_true", help="send the result as a route task to the reviewer")
    parser.add_argument("--reviewer", help="platform user name for --route (default: you)")
    parser.add_argument("--yes", action="store_true", help="with --route: create the route (default: dry run)")
    args = parser.parse_args()
    fields = parse_fields(parser, args.fields)
    if MATERIAL in fields and not args.dataset:
        parser.error("material is a dsspec:Material relationship the current roles cannot read (403): use --dataset")
    if args.route and args.dataset:
        parser.error("--route needs the real tenant")

    if args.dataset:
        from agent.offline import DatasetTenant

        dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
        eng, collabspace, pending = DatasetTenant(dataset), dataset["collabspace"], []
    else:
        settings = Settings.from_env()
        eng, collabspace, pending = Engineering(PLMSession(settings)), args.collabspace or settings.collabspace, ProposalLog().pending()

    snapshot = Snapshot.load(eng, args.search, collabspace)
    root_id = snapshot.find(args.item)
    if root_id is None:
        parser.error(f"no item {args.item!r} in {collabspace} (search lags a few minutes behind new items)")
    report = check(snapshot, root_id, fields=fields, pending=pending)
    print(render(report))

    if args.out:
        args.out.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nSaved {args.out}")

    if args.route:
        from plm_client import Routes

        routes = Routes(eng.session)
        route = build_route(report, args.reviewer or routes.current_username())
        print("\n" + json.dumps(route, indent=2, ensure_ascii=False))
        if not args.yes:
            print("\nDry run: no route created. Re-run with --yes.")
        else:
            created = routes.create(route)
            if not created.get("id"):
                raise SystemExit(f"Route not created, response: {created}")
            routes.start(created["id"])
            print(f"\nCreated and started route {created.get('name', '')} ({created['id']}).")

    return 0 if report.ready else 1


if __name__ == "__main__":
    sys.exit(main())
