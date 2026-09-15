"""Phase 3 agent run: find gaps in a collab space, suggest values, write them back for review.

    python scripts/run_agent.py                          # dry run: prints gaps and proposals, writes nothing
    python scripts/run_agent.py --apply                  # writes [PROPOSED] descriptions, logs every proposal
    python scripts/run_agent.py --apply --min-confidence 0

Every run saves runs/run-<timestamp>.json with all gaps, including those with no proposal.
Review written proposals with scripts/review.py.
"""
import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.gaps import find_gaps  # noqa: E402
from agent.snapshot import Snapshot  # noqa: E402
from agent.suggest import RuleBasedSuggester  # noqa: E402
from agent.writeback import ProposalLog, write_proposal  # noqa: E402
from plm_client import Engineering, PLMError, PLMSession, Settings  # noqa: E402

RUNS = ROOT / "runs"


def run(
    eng: Engineering,
    *,
    collabspace: str,
    search: str = "*",
    apply: bool = False,
    min_confidence: float = 0.5,
    log: ProposalLog | None = None,
) -> list[dict]:
    log = log or ProposalLog()
    suggester = RuleBasedSuggester()
    snapshot = Snapshot.load(eng, search, collabspace)
    pending = {(p["item_id"], p["field"]) for p in log.pending()}
    gaps = find_gaps(snapshot.items.values(), pending)
    print(f"{len(snapshot.items)} items in {collabspace}: {len(gaps)} gaps, {len(pending)} already awaiting review\n")

    results = []
    for gap in gaps:
        proposal = suggester.suggest(gap, snapshot)
        result = {"gap": asdict(gap), "proposal": asdict(proposal) if proposal else None, "proposal_id": None}
        results.append(result)
        if proposal is None:
            print(f"  {gap.title:<28} {gap.field:<12} no evidence")
            continue
        print(f"  {gap.title:<28} {gap.field:<12} {proposal.value!r:<42} {proposal.confidence:.1f}  {proposal.method}")
        for line in proposal.evidence:
            print(f"      - {line}")
        if not apply or proposal.confidence < min_confidence:
            continue
        try:
            record = write_proposal(eng, proposal, snapshot.items[gap.item_id], suggester=suggester.name)
        except PLMError as exc:
            print(f"      ! not written: {exc}")
            continue
        log.append(record)
        result["proposal_id"] = record["proposal_id"]
        print(f"      -> proposal {record['proposal_id']}" + ("" if record["written_to_plm"] else " (logged, written on approval)"))

    proposed = sum(1 for r in results if r["proposal"])
    written = sum(1 for r in results if r["proposal_id"])
    print(f"\n{proposed} of {len(gaps)} gaps have a proposal.", end=" ")
    if apply:
        print(f"{written} at confidence >= {min_confidence} logged to {log.path}.")
    else:
        print("Dry run: nothing written. Re-run with --apply.")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--collabspace", default="API_development")
    parser.add_argument("--search", default="*")
    parser.add_argument("--apply", action="store_true", help="write proposals to PLM and the proposal log")
    parser.add_argument("--min-confidence", type=float, default=0.5, help="only write proposals at or above this")
    args = parser.parse_args()

    eng = Engineering(PLMSession(Settings.from_env()))
    results = run(eng, collabspace=args.collabspace, search=args.search, apply=args.apply, min_confidence=args.min_confidence)

    RUNS.mkdir(exist_ok=True)
    out = RUNS / f"run-{datetime.now():%Y%m%d-%H%M%S}.json"
    summary = {
        "collabspace": args.collabspace,
        "suggester": RuleBasedSuggester.name,
        "applied": args.apply,
        "min_confidence": args.min_confidence,
        "results": results,
    }
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
