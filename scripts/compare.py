"""Phase 4: compare suggesters (rules, LLMs) over several runs, scored against each run's dataset.

    python scripts/compare.py runs/run-a.json runs/run-b.json ...
    python scripts/compare.py --since 20261023 --out runs/compare.json   # every run file from that day on

Only the run files are scored, not the review log: these are dry runs of what each suggester would propose.
Runs with the same suggester and dataset are repeats; the table shows their mean and range.

- coverage: graded gaps with a proposal
- accuracy: correct proposals (ignoring case and punctuation) over graded gaps; precision: over proposals
- written: proposals at confidence >= --min-confidence (what --apply would put in PLM) and how many are correct
- Brier: mean (confidence - correct)^2 over proposals; 0 is perfect, always answering 0.5 gives 0.25
"""
import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluate import DATASET, RUNS, ground_truth, normalize  # noqa: E402

METRICS = ("graded", "coverage", "accuracy", "precision", "written", "written_correct", "brier", "seconds", "tokens")


def score_run(run: dict, truth: dict[tuple[str, str], str], min_confidence: float = 0.5) -> dict:
    graded = [r for r in run["results"] if (r["gap"]["title"], r["gap"]["field"]) in truth]
    proposed = [r for r in graded if r["proposal"]]
    correct = [
        r for r in proposed
        if normalize(r["proposal"]["value"]) == normalize(truth[(r["gap"]["title"], r["gap"]["field"])])
    ]
    written = [r for r in proposed if r["proposal"]["confidence"] >= min_confidence]
    brier = [(r["proposal"]["confidence"] - (r in correct)) ** 2 for r in proposed]
    tokens = [
        (r["llm"].get("prompt_tokens") or 0) + (r["llm"].get("completion_tokens") or 0)
        for r in run["results"] if r.get("llm")
    ]
    return {
        "graded": len(graded),
        "coverage": len(proposed) / len(graded) if graded else None,
        "accuracy": len(correct) / len(graded) if graded else None,
        "precision": len(correct) / len(proposed) if proposed else None,
        "written": len(written),
        "written_correct": sum(r in correct for r in written),
        "brier": sum(brier) / len(brier) if brier else None,
        "seconds": sum(r.get("elapsed_s", 0) for r in run["results"]) / len(run["results"]) if run["results"] else None,
        "tokens": sum(tokens) / len(tokens) if tokens else None,
        "errors": sum(1 for r in run["results"] if (r.get("llm") or {}).get("error")),
    }


def aggregate(scores: list[dict]) -> dict:
    """Mean and range of each metric over repeated runs."""
    out = {"runs": len(scores), "errors": sum(s["errors"] for s in scores)}
    for name in METRICS:
        values = [s[name] for s in scores if s[name] is not None]
        out[name] = {"mean": statistics.mean(values), "min": min(values), "max": max(values)} if values else None
    return out


def fmt(stat: dict | None, kind: str) -> str:
    if stat is None:
        return "-"
    show = {"pct": lambda v: f"{v:.0%}", "num": lambda v: f"{v:.3g}", "int": lambda v: f"{v:.1f}".removesuffix(".0")}[kind]
    if stat["min"] == stat["max"]:
        return show(stat["mean"])
    return f"{show(stat['mean'])} ({show(stat['min'])}-{show(stat['max'])})"


def load_runs(paths: list[Path], since: str | None) -> list[tuple[Path, dict]]:
    if since:
        paths = paths + sorted(p for p in RUNS.glob("run-*.json") if p.stem.removeprefix("run-") >= since)
    return [(p, json.loads(p.read_text(encoding="utf-8"))) for p in dict.fromkeys(paths)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="*", type=Path)
    parser.add_argument("--since", help="also include runs/run-*.json from this timestamp on, e.g. 20261023")
    parser.add_argument("--min-confidence", type=float, default=0.5)
    parser.add_argument("--out", type=Path, help="also save per-run scores and the table as JSON")
    args = parser.parse_args()

    runs = load_runs(args.runs, args.since)
    if not runs:
        raise SystemExit("No run files: pass paths or --since")

    truths, groups, per_run = {}, defaultdict(list), []
    for path, run in runs:
        dataset = ROOT / run["dataset"] if run.get("dataset") else DATASET  # live runs use the Phase 3 dataset
        if dataset not in truths:
            truths[dataset] = ground_truth(json.loads(dataset.read_text(encoding="utf-8")))
        s = score_run(run, truths[dataset], args.min_confidence)
        key = (run.get("label") or run.get("suggester", "rules"), dataset.name)
        groups[key].append(s)
        per_run.append({"run": path.name, "suggester": key[0], "dataset": key[1], **s})

    table = {f"{label} | {dataset}": aggregate(scores) for (label, dataset), scores in sorted(groups.items())}
    print("| suggester | dataset | runs | graded gaps | coverage | accuracy | precision | written (correct) | Brier | s/gap | tokens/gap | errors |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for name, a in table.items():
        label, dataset = name.split(" | ")
        written = f"{fmt(a['written'], 'int')} ({fmt(a['written_correct'], 'int')})"
        print(
            f"| {label} | {dataset} | {a['runs']} | {fmt(a['graded'], 'int')} | {fmt(a['coverage'], 'pct')} "
            f"| {fmt(a['accuracy'], 'pct')} | {fmt(a['precision'], 'pct')} | {written} | {fmt(a['brier'], 'num')} "
            f"| {fmt(a['seconds'], 'num')} | {fmt(a['tokens'], 'int')} | {a['errors']} |"
        )

    if args.out:
        args.out.write_text(json.dumps({"table": table, "runs": per_run}, indent=2), encoding="utf-8")
        print(f"\nSaved {args.out}")


if __name__ == "__main__":
    main()
