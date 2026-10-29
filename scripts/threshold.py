"""Phase 4: which confidence threshold to write at, chosen from data instead of fixed at 0.5.

    python scripts/threshold.py --since 20261023                         # curve per suggester and dataset
    python scripts/threshold.py --since 20261023 --select dataset.json   # choose there, test on the other datasets

For every threshold, proposals at or above it would be written to PLM (run_agent.py --apply --min-confidence).
The curve shows, per run (mean over repeats), how many would be written, how many of those are wrong and what
share of the graded gaps they fill correctly. The chosen threshold is the lowest one with no wrong write in any
run: the most coverage that would not have put a wrong value in front of a reviewer.

With --select the threshold is chosen per suggester on one dataset only and then applied unchanged to the others,
so the held-out result does not depend on tuning on the held-out data.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.compare import graded_results, load_runs  # noqa: E402
from scripts.evaluate import run_group, run_truth  # noqa: E402


def graded_proposals(run: dict, truth: dict) -> tuple[int, list[tuple[float, bool]]]:
    """Number of graded gaps, and (confidence, correct) for each graded proposal."""
    graded, proposed, scores = graded_results(run["results"], truth)
    return len(graded), [(r["proposal"]["confidence"], s["normalized"]) for r, s in zip(proposed, scores)]


def curve(runs: list[tuple[int, list[tuple[float, bool]]]]) -> list[dict]:
    """One row per candidate threshold (every confidence seen, plus 'write nothing'), averaged over the runs."""
    thresholds = sorted({c for _, pairs in runs for c, _ in pairs} | {1.01})
    rows = []
    for t in thresholds:
        written = [[ok for c, ok in pairs if c >= t] for _, pairs in runs]
        rows.append({
            "threshold": t,
            "written": sum(len(w) for w in written) / len(runs),
            "wrong": sum(w.count(False) for w in written) / len(runs),
            "max_wrong": max(w.count(False) for w in written),
            "correct_coverage": sum(w.count(True) / graded for (graded, _), w in zip(runs, written) if graded) / len(runs),
        })
    return rows


def choose(rows: list[dict]) -> dict:
    """The lowest threshold at which no run writes a wrong value."""
    return next(r for r in rows if r["max_wrong"] == 0)


def at(rows: list[dict], threshold: float) -> dict:
    """The curve row a threshold chosen elsewhere falls on: proposals at or above it are written."""
    return next((r for r in rows if r["threshold"] >= threshold), rows[-1])


def show(t: float) -> str:
    return "none" if t > 1 else f"{t:.2f}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="*", type=Path)
    parser.add_argument("--since", help="include runs/run-*.json from this timestamp on, e.g. 20261023")
    parser.add_argument("--select", help="dataset file name to choose the threshold on, e.g. dataset.json")
    parser.add_argument("--out", type=Path, help="also save the curves as JSON")
    args = parser.parse_args()

    runs = [(p, r) for p, r in load_runs(args.runs, args.since) if r.get("dataset")]  # offline runs only
    if not runs:
        raise SystemExit("No offline run files: pass paths or --since")

    datasets, groups = {}, defaultdict(list)
    for _, run in runs:
        groups[run_group(run)].append(graded_proposals(run, run_truth(run, datasets)))
    curves = {key: curve(group) for key, group in sorted(groups.items())}

    print("| suggester | dataset | runs | threshold (no wrong write) | written | correct coverage | at 0.5: written (wrong) |")
    print("|---|---|---|---|---|---|---|")
    for (label, name), rows in curves.items():
        best, default = choose(rows), at(rows, 0.5)
        print(
            f"| {label} | {name} | {len(groups[(label, name)])} | {show(best['threshold'])} | {best['written']:.1f} "
            f"| {best['correct_coverage']:.0%} | {default['written']:.1f} ({default['wrong']:.1f}) |"
        )

    if args.select:
        print(f"\nThreshold chosen on {args.select}, applied unchanged to the other datasets:\n")
        print("| suggester | chosen on | threshold | tested on | written | wrong | correct coverage |")
        print("|---|---|---|---|---|---|---|")
        for (label, name), rows in curves.items():
            if name != args.select:
                continue
            chosen = choose(rows)["threshold"]
            for (other_label, other), other_rows in curves.items():
                if other_label == label and other != name:
                    r = at(other_rows, chosen)
                    print(
                        f"| {label} | {name} | {show(chosen)} | {other} | {r['written']:.1f} | {r['wrong']:.1f} "
                        f"| {r['correct_coverage']:.0%} |"
                    )

    if args.out:
        report = {f"{label} | {name}": rows for (label, name), rows in curves.items()}
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nSaved {args.out}")


if __name__ == "__main__":
    main()
