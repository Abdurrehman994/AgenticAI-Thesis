"""Phase 4: score the agent's proposals against the ground truth in data/dataset.json.

    python scripts/evaluate.py                                              # latest runs/run-*.json + review log
    python scripts/evaluate.py --run runs/run-20260915-114411.json --out runs/eval.json

Only gaps the dataset left blank on purpose are scored; other gaps (e.g. API_TEST_001) are listed as having
no ground truth. Proposals in the review log are included even when a later run no longer lists their gap,
because run_agent.py skips gaps that are already awaiting review.
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.writeback import DEFAULT_LOG, ProposalLog  # noqa: E402

DATASET = ROOT / "data" / "dataset.json"
RUNS = ROOT / "runs"
# A description sharing at least half its words with the truth (Jaccard) is "close": "Locking lever" vs
# "Locking lever head". Part numbers are identifiers, so for them close means correct.
CLOSE_OVERLAP = 0.5
CONFIDENCE_BANDS = (("confidence >= 0.7", 0.7, 1.01), ("confidence 0.5-0.7", 0.5, 0.7), ("confidence < 0.5", 0.0, 0.5))


def normalize(text: str) -> str:
    """Ignore case, punctuation and spacing: 'Guard hinge, aluminium' == 'guard hinge aluminium'."""
    return " ".join(re.sub(r"[^\w]+", " ", text.lower()).split())


def score(value: str, truth: str, field: str = "description") -> dict:
    words, true_words = set(normalize(value).split()), set(normalize(truth).split())
    union = words | true_words
    overlap = round(len(words & true_words) / len(union), 2) if union else 1.0
    normalized = normalize(value) == normalize(truth)
    return {
        "exact": value == truth,
        "normalized": normalized,
        "close": normalized or (field == "description" and overlap >= CLOSE_OVERLAP),
        "overlap": overlap,
    }


def ground_truth(dataset: dict) -> dict[tuple[str, str], str]:
    return {(e["title"], field): e[field] for e in dataset["items"] for field in e.get("blank", [])}


def collect(run: dict, logged: dict[str, dict], truth: dict) -> list[dict]:
    """One row per gap: its proposal (from the run, else from the log), review status and score."""
    rows = {}
    for result in run["results"]:
        gap = result["gap"]
        rows[(gap["title"], gap["field"])] = {"title": gap["title"], "field": gap["field"], "proposal": result["proposal"]}
    for p in logged.values():
        row = rows.setdefault((p["title"], p["field"]), {"title": p["title"], "field": p["field"], "proposal": None})
        row["proposal"] = row["proposal"] or {k: p[k] for k in ("value", "confidence", "method", "evidence")}
        row["review"] = p["status"]
        row["final_value"] = p.get("final_value")
    for key, row in rows.items():
        row.setdefault("review", None)
        row["truth"] = truth.get(key)
        if row["proposal"] and row["truth"] is not None:
            row.update(score(row["proposal"]["value"], row["truth"], row["field"]))
    return sorted(rows.values(), key=lambda r: (r["title"], r["field"]))


def stats(rows: list[dict]) -> dict:
    n = len(rows)
    return {
        "proposals": n,
        "exact": sum(r["exact"] for r in rows),
        "normalized": sum(r["normalized"] for r in rows),
        "close": sum(r["close"] for r in rows),
        "mean_overlap": round(sum(r["overlap"] for r in rows) / n, 2) if n else None,
        "mean_confidence": round(sum(r["proposal"]["confidence"] for r in rows) / n, 2) if n else None,
    }


def summarize(rows: list[dict], truth: dict) -> dict:
    graded = [r for r in rows if r["truth"] is not None]
    proposed = [r for r in graded if r["proposal"]]
    found = {(r["title"], r["field"]) for r in rows}
    methods = sorted({r["proposal"]["method"] for r in proposed})
    return {
        "dataset_blanks": len(truth),
        "gaps_found": len(graded),
        "missed_blanks": sorted(f"{title} {field}" for title, field in truth if (title, field) not in found),
        "gaps_without_ground_truth": [f"{r['title']} {r['field']}" for r in rows if r["truth"] is None],
        "overall": stats(proposed),
        "by_method": {m: stats([r for r in proposed if r["proposal"]["method"] == m]) for m in methods},
        "by_confidence": {
            name: stats([r for r in proposed if low <= r["proposal"]["confidence"] < high])
            for name, low, high in CONFIDENCE_BANDS
        },
        "review": dict(Counter(r["review"] or "not written" for r in proposed)),
        "approved_correct": sum(
            1 for r in proposed if r["review"] == "approved" and normalize(r["final_value"] or "") == normalize(r["truth"])
        ),
        "rejected_but_correct": sum(1 for r in proposed if r["review"] == "rejected" and r["normalized"]),
    }


def pct(part: int, whole: int) -> str:
    return f"{part}/{whole} ({part / whole:.0%})" if whole else "0/0"


def print_report(run_path: Path, rows: list[dict], s: dict) -> None:
    o = s["overall"]
    print(f"# Evaluation of {run_path.name}\n")
    missed = f"; missed: {', '.join(s['missed_blanks'])}" if s["missed_blanks"] else ""
    print(f"- Gap detection: {pct(s['gaps_found'], s['dataset_blanks'])} dataset blanks found{missed}")
    if s["gaps_without_ground_truth"]:
        print(f"- Not scored (no ground truth): {', '.join(s['gaps_without_ground_truth'])}")
    print(f"- Coverage: {pct(o['proposals'], s['gaps_found'])} gaps have a proposal")
    print(
        f"- Correct: {pct(o['normalized'], o['proposals'])} ignoring case/punctuation, {pct(o['exact'], o['proposals'])} exact, "
        f"{pct(o['close'], o['proposals'])} close (description word overlap >= {CLOSE_OVERLAP})"
    )
    review = ", ".join(f"{name} {count}" for name, count in sorted(s["review"].items()))
    print(f"- Review: {review}; approved and correct {s['approved_correct']}; rejected but correct {s['rejected_but_correct']}")

    print("\n| group | proposals | exact | normalized | close | mean word overlap | mean confidence |")
    print("|---|---|---|---|---|---|---|")
    for name, st in [("all", o), *s["by_method"].items(), *s["by_confidence"].items()]:
        if st["proposals"]:
            print(
                f"| {name} | {st['proposals']} | {st['exact']} | {st['normalized']} | {st['close']} "
                f"| {st['mean_overlap']} | {st['mean_confidence']} |"
            )

    print("\n| item | field | proposal | ground truth | confidence | method | match | review |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        if r["truth"] is None:
            continue
        p = r["proposal"]
        if p is None:
            print(f"| {r['title']} | {r['field']} | - | {r['truth']} | - | - | - | - |")
            continue
        match = "exact" if r["exact"] else "normalized" if r["normalized"] else f"{'close, ' if r['close'] else ''}overlap {r['overlap']}"
        print(f"| {r['title']} | {r['field']} | {p['value']} | {r['truth']} | {p['confidence']} | {p['method']} | {match} | {r['review'] or '-'} |")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", type=Path, help="run file to score (default: the latest runs/run-*.json)")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--dataset", type=Path, help="ground truth (default: the run's dataset, else data/dataset.json)")
    parser.add_argument("--out", type=Path, help="also save the summary and rows as JSON")
    args = parser.parse_args()

    run_path = args.run or max(RUNS.glob("run-*.json"), default=None)
    if run_path is None:
        raise SystemExit("No runs/run-*.json yet: run scripts/run_agent.py first")
    run = json.loads(run_path.read_text(encoding="utf-8"))
    dataset = args.dataset or (ROOT / run["dataset"] if run.get("dataset") else DATASET)
    truth = ground_truth(json.loads(dataset.read_text(encoding="utf-8")))
    # Offline runs never write to the tenant, so the review log says nothing about them
    logged = ProposalLog(args.log).proposals() if not run.get("dataset") else {}
    rows = collect(run, logged, truth)
    summary = summarize(rows, truth)
    print_report(run_path, rows, summary)

    if args.out:
        report = {"run": run_path.name, "summary": summary, "rows": rows}
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nSaved {args.out}")


if __name__ == "__main__":
    main()
