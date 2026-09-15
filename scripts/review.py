"""Review proposals written by run_agent.py.

    python scripts/review.py                                   # list pending proposals
    python scripts/review.py --approve 1a2b3c4d 5e6f7a8b       # accept as proposed
    python scripts/review.py --approve 1a2b3c4d --value "Idler roller, 50 mm"   # accept with an edit
    python scripts/review.py --reject 1a2b3c4d                 # restore the value from before the proposal

Refuses to touch a field that was changed in PLM after the proposal was written.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.writeback import DEFAULT_LOG, Conflict, ProposalLog, approve, reject  # noqa: E402
from plm_client import Engineering, PLMError, PLMSession, Settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--approve", nargs="+", default=[], metavar="ID")
    parser.add_argument("--reject", nargs="+", default=[], metavar="ID")
    parser.add_argument("--value", help="approve with this value instead of the proposed one (one --approve ID only)")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    args = parser.parse_args()
    if args.value is not None and len(args.approve) != 1:
        parser.error("--value needs exactly one --approve ID")

    log = ProposalLog(args.log)
    pending = {p["proposal_id"]: p for p in log.pending()}
    if not args.approve and not args.reject:
        print(f"{len(pending)} pending proposals:")
        for p in pending.values():
            where = "" if p["written_to_plm"] else "  (not in PLM until approved)"
            print(f"  {p['proposal_id']}  {p['title']:<28} {p['field']:<12} {p['value']!r:<42} {p['confidence']:.1f}  {p['method']}{where}")
        return

    eng = Engineering(PLMSession(Settings.from_env()))
    for action, ids in (("approve", args.approve), ("reject", args.reject)):
        for proposal_id in ids:
            record = pending.get(proposal_id)
            if record is None:
                print(f"  {proposal_id}: not a pending proposal")
                continue
            try:
                event = approve(eng, record, value=args.value) if action == "approve" else reject(eng, record)
            except (Conflict, PLMError) as exc:
                print(f"  {proposal_id}: {exc}")
                continue
            log.append(event)
            print(f"  {proposal_id}: {event['event']} {record['title']} {record['field']}")


if __name__ == "__main__":
    main()
