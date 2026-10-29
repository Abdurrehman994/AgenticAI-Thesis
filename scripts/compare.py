"""Phase 4: compare suggesters (rules, LLMs) over several runs, scored against each run's dataset.

    python scripts/compare.py runs/run-a.json runs/run-b.json ...
    python scripts/compare.py --since 20261023 --out runs/compare.json   # every run file from that day on
    python scripts/compare.py --since 20261029 --by-field               # one row per field (description, ...)

Only the run files are scored, not the review log: these are dry runs of what each suggester would propose.
Runs with the same suggester and dataset are repeats; the table shows their mean and range. Only the fields a
run checked (run_agent.py --fields) are graded, so adding material does not change older runs' numbers.

- coverage: graded gaps with a proposal
- accuracy: correct proposals (ignoring case and punctuation) over graded gaps; precision: over proposals
- close: like accuracy, but a description sharing at least half its words with the truth also counts
  (evaluate.CLOSE_OVERLAP); Brier and "written (correct)" use the strict match
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

from scripts.evaluate import RUNS, run_fields, run_group, run_truth, score  # noqa: E402

METRICS = ("graded", "coverage", "accuracy", "close", "precision", "written", "written_correct", "brier", "seconds", "tokens")


def graded_results(results: list[dict], truth: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """The results with ground truth, those of them with a proposal, and each proposal's score."""
    graded = [r for r in results if (r["gap"]["title"], r["gap"]["field"]) in truth]
    proposed = [r for r in graded if r["proposal"]]
    scores = [score(r["proposal"]["value"], truth[(r["gap"]["title"], r["gap"]["field"])], r["gap"]["field"]) for r in proposed]
    return graded, proposed, scores


def score_run(run: dict, truth: dict[tuple[str, str], str], min_confidence: float = 0.5, field: str | None = None) -> dict:
    """Scores over the graded gaps, or only those of one field. Time and tokens are per gap of that selection."""
    selected = [r for r in run["results"] if field is None or r["gap"]["field"] == field]
    graded, proposed, scores = graded_results(selected, truth)
    correct = [r for r, s in zip(proposed, scores) if s["normalized"]]
    close = [r for r, s in zip(proposed, scores) if s["close"]]
    written = [r for r in proposed if r["proposal"]["confidence"] >= min_confidence]
    brier = [(r["proposal"]["confidence"] - (r in correct)) ** 2 for r in proposed]
    tokens = [
        (r["llm"].get("prompt_tokens") or 0) + (r["llm"].get("completion_tokens") or 0)
        for r in selected if r.get("llm")
    ]
    return {
        "graded": len(graded),
        "coverage": len(proposed) / len(graded) if graded else None,
        "accuracy": len(correct) / len(graded) if graded else None,
        "close": len(close) / len(graded) if graded else None,
        "precision": len(correct) / len(proposed) if proposed else None,
        "written": len(written),
        "written_correct": sum(r in correct for r in written),
        "brier": sum(brier) / len(brier) if brier else None,
        "seconds": sum(r.get("elapsed_s", 0) for r in selected) / len(selected) if selected else None,
        "tokens": sum(tokens) / len(tokens) if tokens else None,
        "errors": sum(1 for r in selected if (r.get("llm") or {}).get("error")),
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
    parser.add_argument(
        "--include-live", action="store_true",
        help="also score runs on the real tenant: their blanks depend on what was approved there, not on a dataset",
    )
    parser.add_argument("--by-field", action="store_true", help="one row per field instead of one per suggester and dataset")
    args = parser.parse_args()

    runs = load_runs(args.runs, args.since)
    live = [path.name for path, run in runs if not run.get("dataset")]
    if live and not args.include_live:
        runs = [(path, run) for path, run in runs if run.get("dataset")]
        print(f"Skipped {len(live)} run(s) on the live tenant (--include-live to score them): {', '.join(live)}\n")
    if not runs:
        raise SystemExit("No run files: pass paths or --since")

    datasets, groups, per_run = {}, defaultdict(list), []
    for path, run in runs:
        truth = run_truth(run, datasets)
        label, name = run_group(run)
        for field in run_fields(run) if args.by_field else [None]:
            s = score_run(run, truth, args.min_confidence, field)
            key = (label, name, field) if args.by_field else (label, name)
            groups[key].append(s)
            per_run.append({"run": path.name, "suggester": label, "dataset": name, **({"field": field} if field else {}), **s})

    table = {" | ".join(key): aggregate(scores) for key, scores in sorted(groups.items())}
    field_header = " field |" if args.by_field else ""
    print(f"| suggester | dataset |{field_header} runs | graded gaps | coverage | accuracy | close | precision | written (correct) | Brier | s/gap | tokens/gap | errors |")
    print("|---|---|" + ("---|" if args.by_field else "") + "---|---|---|---|---|---|---|---|---|---|---|")
    for name, a in table.items():
        written = f"{fmt(a['written'], 'int')} ({fmt(a['written_correct'], 'int')})"
        print(
            f"| {name} | {a['runs']} | {fmt(a['graded'], 'int')} | {fmt(a['coverage'], 'pct')} "
            f"| {fmt(a['accuracy'], 'pct')} | {fmt(a['close'], 'pct')} | {fmt(a['precision'], 'pct')} | {written} | {fmt(a['brier'], 'num')} "
            f"| {fmt(a['seconds'], 'num')} | {fmt(a['tokens'], 'int')} | {a['errors']} |"
        )

    if args.out:
        args.out.write_text(json.dumps({"table": table, "runs": per_run}, indent=2), encoding="utf-8")
        print(f"\nSaved {args.out}")


if __name__ == "__main__":
    main()
