"""Duplicate detection: parts that may already exist in PLM under another title or part number. Read-only.

    python scripts/duplicates.py                                        # live tenant: every candidate pair
    python scripts/duplicates.py --dataset data/dataset_cad.json        # offline
    python scripts/duplicates.py --new "Hex nut M8, zinc plated"        # before creating a part: does it exist?
    python scripts/duplicates.py --new "Flat washer M8" --title WASHER_NEW --material steel
    python scripts/duplicates.py --dataset data/dataset.json --plant 6 --seeds 10   # evaluation, planted copies

Exit code 1 when a candidate is found (with --new: the part may already exist), so other scripts can use it as a
gate; 0 otherwise. With --plant, recall and precision at several thresholds instead (always exit 0).
See agent/duplicates.py for the rules.
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.duplicates import MIN_SCORE, find_duplicates, find_existing, plant, render, score_planted  # noqa: E402
from agent.snapshot import Snapshot  # noqa: E402
from plm_client import Engineering, PLMSession, Settings  # noqa: E402

THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)


def offline_snapshot(dataset: dict) -> Snapshot:
    from agent.offline import DatasetTenant

    tenant = DatasetTenant(dataset)
    return Snapshot(tenant, tenant.iter_search("*"))


def evaluate(dataset: dict, n: int, seeds: int) -> dict:
    """Mean recall and precision over `seeds` random sets of n planted duplicates."""
    per_seed = []
    for seed in range(2026, 2026 + seeds):
        planted, pairs = plant(dataset, n, seed)
        candidates = find_duplicates(offline_snapshot(planted), min_score=min(THRESHOLDS))
        per_seed.append({"seed": seed, "pairs": pairs, "rows": score_planted(candidates, pairs, THRESHOLDS)})
    table = []
    for k, threshold in enumerate(THRESHOLDS):
        rows = [s["rows"][k] for s in per_seed]
        table.append({
            "threshold": threshold,
            **{key: statistics.mean(r[key] for r in rows) for key in ("found", "recall", "precision")},
            "recall_min": min(r["recall"] for r in rows),
            "precision_min": min(r["precision"] for r in rows),
        })
    return {"planted_per_seed": n, "seeds": seeds, "table": table, "per_seed": per_seed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--collabspace", default="API_development")
    parser.add_argument("--search", default="*")
    parser.add_argument("--dataset", type=Path, help="an in-memory tenant built from this dataset instead")
    parser.add_argument("--new", metavar="DESCRIPTION", help="check a part before it is created")
    parser.add_argument("--title", default="", help="with --new: the planned title")
    parser.add_argument("--material", default="", help="with --new: the planned material")
    parser.add_argument("--min-score", type=float, default=MIN_SCORE)
    parser.add_argument("--plant", type=int, metavar="N", help="evaluation: add N known duplicates (needs --dataset)")
    parser.add_argument("--seeds", type=int, default=10, help="with --plant: how many random sets")
    parser.add_argument("--out", type=Path, help="also save the result as JSON")
    args = parser.parse_args()
    if args.plant and not args.dataset:
        parser.error("--plant needs --dataset: the planted copies exist only in the in-memory tenant")
    if (args.title or args.material) and not args.new:
        parser.error("--title and --material describe a new part: use them with --new")

    dataset = json.loads(args.dataset.read_text(encoding="utf-8")) if args.dataset else None

    if args.plant:
        result = evaluate(dataset, args.plant, args.seeds)
        print(f"{args.plant} planted duplicates in {args.dataset}, {args.seeds} seeds (mean; min)\n")
        print("| threshold | pairs found | recall | precision |")
        print("|---|---|---|---|")
        for row in result["table"]:
            print(f"| {row['threshold']:.1f} | {row['found']:.1f} | {row['recall']:.0%} ({row['recall_min']:.0%}) "
                  f"| {row['precision']:.0%} ({row['precision_min']:.0%}) |")
        if args.out:
            args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"\nSaved {args.out}")
        return 0

    if dataset:
        snapshot, collabspace = offline_snapshot(dataset), dataset["collabspace"]
    else:
        collabspace = args.collabspace
        snapshot = Snapshot.load(Engineering(PLMSession(Settings.from_env())), args.search, collabspace)

    if args.new:
        found = find_existing(snapshot, args.title, args.new, args.material, min_score=args.min_score)
        header = (f"{len(found)} existing items in {collabspace} may already be this part (score >= {args.min_score}):"
                  if found else f"No existing item in {collabspace} looks like this part (score >= {args.min_score}).")
    else:
        found = find_duplicates(snapshot, min_score=args.min_score)
        header = f"{len(found)} possible duplicate pairs among {len(snapshot.items)} items in {collabspace} (score >= {args.min_score})"
    print(render(found, header=header))

    if args.out:
        args.out.write_text(json.dumps([c.to_dict() for c in found], indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nSaved {args.out}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
