"""Phase 4, step 2a: is an answer the agent gives in every repeated run more often right? Offline, from run files.

    python scripts/agreement.py --since 20261023
    python scripts/agreement.py --since 20261023 --suggester agent-v3 --suggester llm: --close --out runs/agreement.json

Repeated runs of the same suggester on the same dataset answer the same gaps. Here each gap becomes one decision,
as it would if the agent were run R times and only then written: the majority answer over the R runs (values
compared ignoring case and punctuation; a tie goes to the higher mean confidence), with
- agreement: the share of the R runs that gave the majority answer (a run with no proposal counts against it);
- basis: the mean confidence the runs gave that answer (the evidence mode's fixed 0.8 / 0.7 / 0.3 / 0.1, or the
  model's own rating);
- combined: basis x agreement.

Three tables:
1. Agreement and correctness: how often the majority answer is right, for unanimous and for split gaps.
2. Calibration of each score over the gap decisions: ECE and Brier, 95% bootstrap interval over gaps.
3. Transfer: for each score, a threshold chosen on one dataset (strict: no wrong write; tolerant: at most
   --max-wrong-rate wrong) and what it writes on the other.

Only suggesters with at least 3 runs per dataset count: the rules give the same answer every time. The price of
the signal is R model calls per gap instead of one.
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.calibration import (MAX_WRONG_RATE, accuracy, accuracy_interval, bootstrap, brier, ece, fmt, interval,  # noqa: E402
                                 rate, selected, threshold_transfer)
from scripts.compare import load_runs  # noqa: E402
from scripts.evaluate import normalize, run_group, run_truth, score  # noqa: E402
from scripts.threshold import show  # noqa: E402

MIN_RUNS = 3
SCORES = ("basis", "agreement", "combined")


def gap_decisions(runs: list[dict], truth: dict[tuple[str, str], str], *, close: bool = False) -> tuple[int, list[dict]]:
    """Graded gaps, and one majority decision per gap that at least one run proposed a value for."""
    answers = defaultdict(list)  # (title, field) -> [(value, confidence)] over the runs
    graded = {k for k in truth if any((r["gap"]["title"], r["gap"]["field"]) == k for run in runs for r in run["results"])}
    for run in runs:
        for r in run["results"]:
            key = (r["gap"]["title"], r["gap"]["field"])
            if key in truth and r["proposal"]:
                answers[key].append((r["proposal"]["value"], r["proposal"]["confidence"]))
    decisions = []
    for key, given in sorted(answers.items()):
        votes = defaultdict(list)
        for value, confidence in given:
            votes[normalize(value)].append((value, confidence))
        # Majority; a tie goes to the answer given with more confidence, then alphabetically (reproducible)
        best = min(votes, key=lambda v: (-len(votes[v]), -sum(c for _, c in votes[v]) / len(votes[v]), v))
        value = votes[best][0][0]
        s = score(value, truth[key], key[1])
        agreement = len(votes[best]) / len(runs)
        basis = sum(c for _, c in votes[best]) / len(votes[best])
        decisions.append({"gap": f"{key[0]}|{key[1]}", "field": key[1], "value": value, "answers": len(given),
                          "distinct": len(votes), "agreement": agreement, "basis": basis, "combined": basis * agreement,
                          "correct": bool(s["close" if close else "normalized"])})
    return len(graded), decisions


def pairs_for(decisions: list[dict], name: str) -> list[tuple[float, bool]]:
    return [(d[name], d["correct"]) for d in decisions]


def clusters(decisions: list[dict], name: str) -> list[list[tuple[float, bool]]]:
    return [[(d[name], d["correct"])] for d in decisions]  # one decision per gap: each gap is its own cluster


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="*", type=Path)
    parser.add_argument("--since", help="include runs/run-*.json from this timestamp on, e.g. 20261023")
    parser.add_argument("--suggester", action="append", default=[], metavar="TEXT",
                        help="only suggesters whose label contains TEXT (repeatable)")
    parser.add_argument("--close", action="store_true", help="a near match (half the words shared) counts as correct")
    parser.add_argument("--max-wrong-rate", type=float, default=MAX_WRONG_RATE)
    parser.add_argument("--out", type=Path, help="also save the decisions and tables as JSON")
    args = parser.parse_args()

    loaded = [r for _, r in load_runs(args.runs, args.since) if r.get("dataset") and selected(run_group(r)[0], args.suggester)]
    by_group = defaultdict(list)
    for run in loaded:
        by_group[run_group(run)].append(run)
    datasets, groups = {}, {}
    for key, runs in sorted(by_group.items()):
        if len(runs) >= MIN_RUNS:
            groups[key] = gap_decisions(runs, run_truth(runs[0], datasets), close=args.close)
    if not groups:
        raise SystemExit(f"No suggester has {MIN_RUNS}+ offline runs on one dataset")

    measure = "close match" if args.close else "exact match (ignoring case and punctuation)"
    out = {"correct": measure, "groups": [], "transfer": []}
    print(f"Correct = {measure}. One decision per gap: the majority answer over the repeated runs.\n")

    print("1. Agreement and correctness\n")
    print("| suggester | dataset | runs | graded gaps | decided | majority right | unanimous: gaps | right | 95% "
          "| split: gaps | right | 95% |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for (label, name), (graded, decisions) in groups.items():
        runs = len(by_group[(label, name)])
        unanimous = [d for d in decisions if d["agreement"] == 1]
        split = [d for d in decisions if d["agreement"] < 1]
        row = {"suggester": label, "dataset": name, "runs": runs, "graded": graded, "decisions": decisions}
        out["groups"].append(row)
        cells = []
        for part in (unanimous, split):
            p = pairs_for(part, "agreement")
            cells += [str(len(part)), f"{accuracy(p):.0%}" if p else "-", interval(accuracy_interval(clusters(part, "agreement")), pct=True)]
        print(f"| {label} | {name} | {runs} | {graded} | {len(decisions)} | {accuracy(pairs_for(decisions, 'agreement')):.0%} | "
              + " | ".join(cells) + " |")

    print("\n2. Calibration of each score over the gap decisions (95% bootstrap over gaps)\n")
    print("| suggester | dataset | score | mean score | right | ECE | 95% | Brier |")
    print("|---|---|---|---|---|---|---|---|")
    for (label, name), (_, decisions) in groups.items():
        for s in SCORES:
            p = pairs_for(decisions, s)
            print(f"| {label} | {name} | {s} | {sum(c for c, _ in p) / len(p):.2f} | {accuracy(p):.0%} | {fmt(ece(p))} "
                  f"| {interval(bootstrap(clusters(decisions, s), ece))} | {fmt(brier(p))} |")

    print(f"\n3. Transfer: threshold chosen on one dataset (strict: no wrong write; tolerant: at most "
          f"{args.max_wrong_rate:.0%} wrong), applied to the other\n")
    print("| suggester | score | chosen on | tested on | strict threshold | test: written / wrong "
          "| tolerant threshold | test: written / wrong | test: wrong share |")
    print("|---|---|---|---|---|---|---|---|---|")
    for label in sorted({l for l, _ in groups}):
        names = [n for l, n in groups if l == label and "(" not in n]
        for train_name in names:
            for test_name in (n for n in names if n != train_name):
                for s in SCORES:
                    g_train, d_train = groups[(label, train_name)]
                    g_test, d_test = groups[(label, test_name)]
                    train, test = [(g_train, pairs_for(d_train, s))], [(g_test, pairs_for(d_test, s))]
                    strict = threshold_transfer(train, test)
                    loose = threshold_transfer(train, test, args.max_wrong_rate)
                    out["transfer"].append({"suggester": label, "score": s, "train": train_name, "test": test_name,
                                            "strict": strict, "tolerant": loose})
                    print(f"| {label} | {s} | {train_name} | {test_name} | {show(strict['threshold'])} "
                          f"| {strict['written']:.0f} / {strict['wrong']:.0f} | {show(loose['threshold'])} "
                          f"| {loose['written']:.0f} / {loose['wrong']:.0f} | {rate(loose)} |")

    print(f"\nAgreement costs one model call per run: {MIN_RUNS}+ calls per gap instead of one.")
    if args.out:
        args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Saved {args.out}")


if __name__ == "__main__":
    main()
