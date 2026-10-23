"""Phase 3 agent run: find gaps in a collab space, suggest values, write them back for review.

    python scripts/run_agent.py                          # dry run: prints gaps and proposals, writes nothing
    python scripts/run_agent.py --apply                  # writes [PROPOSED] descriptions, logs every proposal
    python scripts/run_agent.py --apply --min-confidence 0
    python scripts/run_agent.py --suggester llm          # LLM from LLM_* in .env instead of the rules

Phase 4 runs use --dataset: the agent works on an in-memory tenant built from the dataset file, so every run
starts from the same blanks and nothing touches the real tenant. LLM answers vary, so repeat them:

    python scripts/run_agent.py --dataset data/dataset_cad.json --suggester llm --repeat 3

Every run saves runs/run-<timestamp>.json with all gaps, including those with no proposal.
Review written proposals with scripts/review.py; compare runs with scripts/compare.py.
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.gaps import find_gaps  # noqa: E402
from agent.snapshot import Snapshot  # noqa: E402
from agent.suggest import RuleBasedSuggester, Suggester  # noqa: E402
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
    suggester: Suggester | None = None,
) -> list[dict]:
    log = log or ProposalLog()
    suggester = suggester or RuleBasedSuggester()
    snapshot = Snapshot.load(eng, search, collabspace)
    pending = {(p["item_id"], p["field"]) for p in log.pending()}
    gaps = find_gaps(snapshot.items.values(), pending)
    print(f"{len(snapshot.items)} items in {collabspace}: {len(gaps)} gaps, {len(pending)} already awaiting review\n")

    results, proposals = [], []
    for gap in gaps:
        started = time.monotonic()
        proposal = suggester.suggest(gap, snapshot)
        result = {
            "gap": asdict(gap),
            "proposal": asdict(proposal) if proposal else None,
            "proposal_id": None,
            "elapsed_s": round(time.monotonic() - started, 3),
        }
        if getattr(suggester, "last_call", None):
            result["llm"] = suggester.last_call
        results.append(result)
        proposals.append(proposal)
    drop_duplicate_part_numbers(results, proposals)

    for gap, result, proposal in zip(gaps, results, proposals):
        if proposal is None:
            error = (result.get("llm") or {}).get("error")
            reason = f"! {error}" if error else f"ambiguous: {result['ambiguous']}" if "ambiguous" in result else "no evidence"
            print(f"  {gap.title:<28} {gap.field:<12} {reason}")
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


def drop_duplicate_part_numbers(results: list[dict], proposals: list) -> None:
    """Two items cannot get the same part number, and nothing tells which of them it belongs to: drop all.

    Order independent on purpose: keeping the first claim would let a wrong early answer block the right one.
    The dropped value stays in the run file under "ambiguous".
    """
    claims = defaultdict(list)
    for i, proposal in enumerate(proposals):
        if proposal and proposal.field == "partNumber":
            claims[proposal.value].append(i)
    for value, indexes in claims.items():
        for i in indexes if len(indexes) > 1 else []:
            others = [results[j]["gap"]["title"] for j in indexes if j != i]
            results[i]["ambiguous"] = f"{value} also proposed for {', '.join(others)}"
            results[i]["proposal"], proposals[i] = None, None


def make_suggester(name: str, model: str | None) -> Suggester:
    if name == "rules":
        return RuleBasedSuggester()
    from agent.llm import LLMSettings, LLMSuggester

    return LLMSuggester(LLMSettings.from_env(model))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--collabspace", default="API_development")
    parser.add_argument("--search", default="*")
    parser.add_argument("--apply", action="store_true", help="write proposals to PLM and the proposal log")
    parser.add_argument("--min-confidence", type=float, default=0.5, help="only write proposals at or above this")
    parser.add_argument("--suggester", choices=("rules", "llm"), default="rules")
    parser.add_argument("--model", help="model id for --suggester llm (default: LLM_MODEL in .env)")
    parser.add_argument("--dataset", type=Path, help="run offline on an in-memory tenant built from this dataset")
    parser.add_argument("--repeat", type=int, default=1, help="number of runs, each saved separately (dry runs only)")
    args = parser.parse_args()
    if args.dataset and args.apply:
        parser.error("--apply writes to the real tenant and cannot be combined with --dataset")
    if args.repeat > 1 and args.apply:
        parser.error("--repeat is for dry runs: a second --apply run skips the gaps the first one proposed")

    suggester = make_suggester(args.suggester, args.model)
    if args.dataset:
        from agent.offline import DatasetTenant

        dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
        eng, collabspace = DatasetTenant(dataset), dataset["collabspace"]
        log = ProposalLog(Path("unused"))  # no pending proposals in a fresh in-memory tenant
    else:
        eng, collabspace, log = Engineering(PLMSession(Settings.from_env())), args.collabspace, None

    RUNS.mkdir(exist_ok=True)
    for repeat in range(1, args.repeat + 1):
        if args.repeat > 1:
            print(f"\n=== run {repeat} of {args.repeat} ===")
        results = run(
            eng, collabspace=collabspace, search=args.search, apply=args.apply,
            min_confidence=args.min_confidence, log=log, suggester=suggester,
        )
        out = RUNS / f"run-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
        summary = {
            "collabspace": collabspace,
            "suggester": suggester.name,
            "label": getattr(suggester, "method", suggester.name),
            "dataset": args.dataset.resolve().relative_to(ROOT).as_posix() if args.dataset else None,
            "applied": args.apply,
            "min_confidence": args.min_confidence,
            "results": results,
        }
        out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Saved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
