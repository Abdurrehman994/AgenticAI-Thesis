"""Phase 3 agent run: find gaps in a collab space, suggest values, write them back for review.

    python scripts/run_agent.py                          # dry run: prints gaps and proposals, writes nothing
    python scripts/run_agent.py --apply                  # writes [PROPOSED] descriptions, logs every proposal
    python scripts/run_agent.py --apply --min-confidence 0
    python scripts/run_agent.py --suggester llm          # LLM from LLM_* in .env instead of the rules
    python scripts/run_agent.py --suggester agent        # the same LLM, gathering its own evidence with tools
    python scripts/run_agent.py --only API_ASM_GUARD --fields description --apply   # one item, one field

Phase 4 runs use --dataset: the agent works on an in-memory tenant built from the dataset file, so every run
starts from the same blanks and nothing touches the real tenant. LLM answers vary, so repeat them:

    python scripts/run_agent.py --dataset data/dataset_cad.json --suggester llm --repeat 3
    python scripts/run_agent.py --dataset data/dataset.json --suggester llm --confidence evidence
    python scripts/run_agent.py --dataset data/dataset_cad.json --fields material   # offline only: 403 in PLM

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

from agent.gaps import ALL_FIELDS, FIELDS, MATERIAL, find_gaps  # noqa: E402
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
    fields: tuple[str, ...] = FIELDS,
    only: set[str] | None = None,
    snapshot: Snapshot | None = None,
) -> list[dict]:
    """snapshot: an already loaded collab space (watch_agent.py), so it is not searched twice."""
    log = log or ProposalLog()
    suggester = suggester or RuleBasedSuggester()
    snapshot = snapshot or Snapshot.load(eng, search, collabspace)
    pending = {(p["item_id"], p["field"]) for p in log.pending()}
    gaps = find_gaps(snapshot.items.values(), pending, fields)
    if only is not None:  # titles or item ids; the whole collab space is still loaded, so the evidence is the same
        missing = only - {key for item in snapshot.items.values() for key in (item.get("title"), item["id"])}
        if missing:
            print(f"Not found in {collabspace}: {', '.join(sorted(missing))}")
        gaps = [gap for gap in gaps if gap.title in only or gap.item_id in only]
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


def save_run(results: list[dict], *, collabspace: str, suggester: Suggester, dataset: str | None,
             fields: tuple[str, ...], applied: bool, min_confidence: float, **extra) -> Path:
    """runs/run-<timestamp>.json: every gap of the run, the Phase 4 input."""
    RUNS.mkdir(exist_ok=True)
    out = RUNS / f"run-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
    summary = {
        "collabspace": collabspace,
        "suggester": suggester.name,
        "label": getattr(suggester, "method", suggester.name),
        "dataset": dataset,
        "fields": list(fields),
        "applied": applied,
        "min_confidence": min_confidence,
        **extra,
        "results": results,
    }
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


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


def make_suggester(name: str, model: str | None, confidence: str = "self") -> Suggester:
    if name == "rules":
        return RuleBasedSuggester()
    from agent.llm import LLMSettings, LLMSuggester

    if name == "agent":  # the same LLM, gathering its own evidence with tools
        from agent.agentic import AgenticSuggester

        return AgenticSuggester(LLMSettings.from_env(model), confidence=confidence)
    return LLMSuggester(LLMSettings.from_env(model), confidence=confidence)


SUGGESTERS = ("rules", "llm", "agent")


def parse_fields(parser: argparse.ArgumentParser, text: str) -> tuple[str, ...]:
    """--fields "description,material" -> ("description", "material"), or a usage error."""
    fields = tuple(dict.fromkeys(f.strip() for f in text.split(",") if f.strip()))
    if not fields or set(fields) - set(ALL_FIELDS):
        parser.error(f"--fields takes {', '.join(ALL_FIELDS)}")
    return fields


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--collabspace", default="API_development")
    parser.add_argument("--search", default="*")
    parser.add_argument("--apply", action="store_true", help="write proposals to PLM and the proposal log")
    parser.add_argument("--min-confidence", type=float, default=0.5, help="only write proposals at or above this")
    parser.add_argument("--suggester", choices=SUGGESTERS, default="rules")
    parser.add_argument("--model", help="model id for --suggester llm (default: LLM_MODEL in .env)")
    parser.add_argument(
        "--confidence", choices=("self", "evidence"), default="self",
        help="--suggester llm: the model's own confidence, or one mapped from the evidence it names",
    )
    parser.add_argument("--dataset", type=Path, help="run offline on an in-memory tenant built from this dataset")
    parser.add_argument("--repeat", type=int, default=1, help="number of runs, each saved separately (dry runs only)")
    parser.add_argument(
        "--fields", default=",".join(FIELDS),
        help=f"comma-separated fields to check, from {', '.join(ALL_FIELDS)} (material needs --dataset)",
    )
    parser.add_argument("--only", nargs="+", metavar="TITLE", help="only propose for these item titles")
    args = parser.parse_args()
    fields = parse_fields(parser, args.fields)
    if MATERIAL in fields and not args.dataset:
        parser.error("material is a dsspec:Material relationship the current roles cannot read (403): use --dataset")
    if args.dataset and args.apply:
        parser.error("--apply writes to the real tenant and cannot be combined with --dataset")
    if args.repeat > 1 and args.apply:
        parser.error("--repeat is for dry runs: a second --apply run skips the gaps the first one proposed")

    suggester = make_suggester(args.suggester, args.model, args.confidence)
    if args.dataset:
        from agent.offline import DatasetTenant

        dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
        eng, collabspace = DatasetTenant(dataset), dataset["collabspace"]
        log = ProposalLog(Path("unused"))  # no pending proposals in a fresh in-memory tenant
    else:
        eng, collabspace, log = Engineering(PLMSession(Settings.from_env())), args.collabspace, None

    for repeat in range(1, args.repeat + 1):
        if args.repeat > 1:
            print(f"\n=== run {repeat} of {args.repeat} ===")
        results = run(
            eng, collabspace=collabspace, search=args.search, apply=args.apply,
            min_confidence=args.min_confidence, log=log, suggester=suggester, fields=fields,
            only=set(args.only) if args.only else None,
        )
        out = save_run(
            results, collabspace=collabspace, suggester=suggester, fields=fields, applied=args.apply,
            dataset=args.dataset.resolve().relative_to(ROOT).as_posix() if args.dataset else None,
            min_confidence=args.min_confidence,
        )
        print(f"Saved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
