"""Phase 4, wider evaluation: score a suggester on several random blank patterns of the CAD data, not just one.

    python scripts/sweep.py                                   # rules, seeds 2026-2035, all fields
    python scripts/sweep.py --seeds 20 --blank-fraction 0.5
    python scripts/sweep.py --suggester llm --seeds 3 --out runs/sweep-llm.json   # Lehmus AI: university network

data/dataset_cad.json is one draw (seed 2026) of which values are blanked, so its scores depend on that draw.
Here every seed blanks a different share of the same CAD values (cad_to_dataset.convert, in memory), the agent
runs offline on each, and the table shows the mean and range per field. Nothing is written to the tenant.
"""
import argparse
import contextlib
import io
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.gaps import ALL_FIELDS  # noqa: E402
from agent.offline import DatasetTenant  # noqa: E402
from agent.writeback import ProposalLog  # noqa: E402
from scripts.cad_to_dataset import DATA, convert  # noqa: E402
from scripts.compare import aggregate, fmt, score_run  # noqa: E402
from scripts.evaluate import ground_truth  # noqa: E402
from scripts.run_agent import SUGGESTERS, make_suggester, parse_fields, run  # noqa: E402


def sweep(extract: dict, suggester, *, seeds: list[int], blank_fraction: float, fields: tuple[str, ...],
          min_confidence: float = 0.5) -> dict[str, list[dict]]:
    """field -> one score per seed (scripts/compare.py metrics)."""
    scores = defaultdict(list)
    for seed in seeds:
        dataset = convert(extract, blank_fraction=blank_fraction, seed=seed, collabspace="CAD")
        with contextlib.redirect_stdout(io.StringIO()):  # run() prints every gap
            results = run(DatasetTenant(dataset), collabspace="CAD", log=ProposalLog(Path("unused")),
                          suggester=suggester, fields=fields)
        truth = ground_truth(dataset, list(fields))
        for field in fields:
            scores[field].append({"seed": seed, **score_run({"results": results}, truth, min_confidence, field)})
    return scores


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--extract", type=Path, default=DATA / "cad_extract.json")
    parser.add_argument("--seeds", type=int, default=10, help="number of blank patterns, seeds from --first-seed on")
    parser.add_argument("--first-seed", type=int, default=2026, help="2026 is the pattern in data/dataset_cad.json")
    parser.add_argument("--blank-fraction", type=float, default=0.3)
    parser.add_argument("--fields", default=",".join(ALL_FIELDS))
    parser.add_argument("--suggester", choices=SUGGESTERS, default="rules")
    parser.add_argument("--model")
    parser.add_argument("--confidence", choices=("self", "evidence"), default="self")
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--out", type=Path, help="also save the per-seed scores and the table as JSON")
    args = parser.parse_args()
    fields = parse_fields(parser, args.fields)

    extract = json.loads(args.extract.read_text(encoding="utf-8"))
    suggester = make_suggester(args.suggester, args.model, args.confidence)
    seeds = list(range(args.first_seed, args.first_seed + args.seeds))
    scores = sweep(extract, suggester, seeds=seeds, blank_fraction=args.blank_fraction, fields=fields,
                   min_confidence=args.min_confidence)

    label = getattr(suggester, "method", suggester.name)
    print(f"{label}: {len(seeds)} blank patterns (seeds {seeds[0]}-{seeds[-1]}), blank fraction {args.blank_fraction}\n")
    print("| field | graded gaps | coverage | accuracy | close | precision | written (correct) | Brier |")
    print("|---|---|---|---|---|---|---|---|")
    table = {field: aggregate(field_scores) for field, field_scores in scores.items()}
    for field, a in table.items():
        written = f"{fmt(a['written'], 'int')} ({fmt(a['written_correct'], 'int')})"
        print(
            f"| {field} | {fmt(a['graded'], 'int')} | {fmt(a['coverage'], 'pct')} | {fmt(a['accuracy'], 'pct')} "
            f"| {fmt(a['close'], 'pct')} | {fmt(a['precision'], 'pct')} | {written} | {fmt(a['brier'], 'num')} |"
        )

    if args.out:
        report = {"suggester": label, "seeds": seeds, "blank_fraction": args.blank_fraction, "table": table, "runs": scores}
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nSaved {args.out}")


if __name__ == "__main__":
    main()
