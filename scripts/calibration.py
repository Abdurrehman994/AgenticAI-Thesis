"""Phase 4: how well does each suggester's confidence match how often it is right? Offline, from run files.

    python scripts/calibration.py --since 20261023
    python scripts/calibration.py --since 20261023 --suggester agent-v3 --suggester llm: --suggester rules
    python scripts/calibration.py --since 20261023 --close                 # near matches count as correct
    python scripts/calibration.py --since 20261023 --plot runs/reliability.png --out runs/calibration.json

Three tables:
1. Calibration per suggester and dataset: mean confidence against accuracy of the graded proposals, Brier score
   and expected calibration error (ECE: the gap between confidence and accuracy, averaged over confidence bins of
   width 0.2, weighted by how many proposals fall in each).
2. Accuracy per basis: what the evidence-mode suggesters state ("copied", "pattern", "inferred", "guess") and
   which rule fired for the rule-based one, with a 95% Wilson interval. The samples are small; the interval
   shows how small.
3. Transfer: the evidence mode maps each basis to a fixed confidence (0.8 / 0.7 / 0.3 / 0.1). Here the mapping is
   also learned, as each basis's accuracy on one dataset (smoothed: (correct + 1) / (n + 2)), and applied
   unchanged to the other. For both mappings: ECE on the test dataset, and two thresholds chosen on the training
   dataset with what they write per run on the test dataset:
   - strict: the lowest threshold with no wrong write on the training data (as threshold.py);
   - tolerant: the lowest threshold whose written values are at most --max-wrong-rate wrong on the training data.
     With 50+ proposals a single wrong answer makes the strict threshold "write nothing", which hides whether the
     mapping transfers; the tolerant one shows it.

Correct means equal ignoring case and punctuation (evaluate.score "normalized"), as in compare.py; with --close
a description sharing at least half its words with the truth also counts (evaluate.CLOSE_OVERLAP), closer to what
a reviewer would accept with a small edit. Repeated runs are pooled for tables 1 and 2; they are not independent
samples, so the intervals are optimistic.

--plot draws the reliability diagram (one panel per dataset, a line per suggester; points are confidence bins,
their size the number of proposals) as PNG or PDF, from the suggesters selected with --suggester.
"""
import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.compare import graded_results, load_runs  # noqa: E402
from scripts.evaluate import run_group, run_truth  # noqa: E402
from scripts.threshold import at, choose, curve, show  # noqa: E402

BIN_WIDTH = 0.2
MAX_WRONG_RATE = 0.1
FIXED = {"copied": 0.8, "pattern": 0.7, "inferred": 0.3, "guess": 0.1}  # agent.llm evidence mode
SELF_RATED = "self-rated"


def proposal_rows(run: dict, truth: dict, *, close: bool = False) -> list[dict]:
    """One row per graded proposal: confidence, correct, and the basis it came from."""
    _, proposed, scores = graded_results(run["results"], truth)
    rows = []
    for r, s in zip(proposed, scores):
        llm = r.get("llm") or {}
        basis = llm.get("basis") or (SELF_RATED if llm else r["proposal"]["method"])
        rows.append({"confidence": r["proposal"]["confidence"], "correct": bool(s["close" if close else "normalized"]),
                     "basis": basis, "field": r["gap"]["field"]})
    return rows


def _bins(pairs: list[tuple[float, bool]], width: float) -> dict[int, list[tuple[float, bool]]]:
    bins = defaultdict(list)
    for c, ok in pairs:
        bins[min(int(c / width), int(1 / width) - 1)].append((c, ok))  # confidence 1.0 goes in the top bin
    return bins


def ece(pairs: list[tuple[float, bool]], width: float = BIN_WIDTH) -> float | None:
    """Expected calibration error: sum over bins of (share of proposals) * |accuracy - mean confidence|."""
    if not pairs:
        return None
    return sum(len(b) / len(pairs) * abs(sum(ok for _, ok in b) / len(b) - sum(c for c, _ in b) / len(b))
               for b in _bins(pairs, width).values())


def reliability(pairs: list[tuple[float, bool]], width: float = BIN_WIDTH) -> list[dict]:
    """Per confidence bin: proposals, mean confidence, accuracy (the points of a reliability diagram)."""
    return [{"bin": f"{k * width:.1f}-{(k + 1) * width:.1f}", "n": len(b),
             "confidence": sum(c for c, _ in b) / len(b), "accuracy": sum(ok for _, ok in b) / len(b)}
            for k, b in sorted(_bins(pairs, width).items())]


def brier(pairs: list[tuple[float, bool]]) -> float | None:
    return sum((c - ok) ** 2 for c, ok in pairs) / len(pairs) if pairs else None


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% interval for a proportion; sensible for small n, unlike the normal approximation."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def learn_mapping(rows: list[dict]) -> dict[str, float]:
    """basis -> smoothed accuracy (correct + 1) / (n + 2), with the pooled accuracy for an unseen basis."""
    counts = defaultdict(lambda: [0, 0])
    for r in rows:
        counts[r["basis"]][0] += r["correct"]
        counts[r["basis"]][1] += 1
    mapping = {b: (k + 1) / (n + 2) for b, (k, n) in counts.items()}
    total = sum(n for _, n in counts.values())
    mapping["*"] = (sum(k for k, _ in counts.values()) + 1) / (total + 2)
    return mapping


def remap(rows: list[dict], mapping: dict[str, float]) -> list[tuple[float, bool]]:
    return [(mapping.get(r["basis"], mapping["*"]), r["correct"]) for r in rows]


def choose_tolerant(rows: list[dict], max_wrong_rate: float) -> dict:
    """The lowest threshold whose written values are at most max_wrong_rate wrong (mean over runs)."""
    return next((r for r in rows if r["written"] and r["wrong"] / r["written"] <= max_wrong_rate), rows[-1])


def threshold_transfer(train: list[tuple[int, list[tuple[float, bool]]]],
                       test: list[tuple[int, list[tuple[float, bool]]]], max_wrong_rate: float = 0.0) -> dict:
    """A threshold chosen on the training runs (no wrong write, or at most max_wrong_rate wrong) and what it
    writes on the test runs."""
    train_curve = curve(train)
    chosen = (choose(train_curve) if max_wrong_rate == 0 else choose_tolerant(train_curve, max_wrong_rate))["threshold"]
    row = at(curve(test), chosen)
    return {"threshold": chosen, "written": row["written"], "wrong": row["wrong"], "correct_coverage": row["correct_coverage"]}


def selected(label: str, patterns: list[str]) -> bool:
    return not patterns or any(p in label for p in patterns)


def fmt(x: float | None) -> str:
    return "-" if x is None else f"{x:.2f}"


def rate(t: dict) -> str:
    return f"{t['wrong'] / t['written']:.0%}" if t["written"] else "-"


def display_name(label: str) -> str:
    """'agent-v3:gpt-oss-120b+evidence' -> 'Tool-using agent v3, evidence-based' for figure legends."""
    if label == "rules":
        return "Rules"
    kind, _, rest = label.partition(":")
    mode = "evidence-based" if rest.endswith("+evidence") else "self-rated"
    name = {"llm": "LLM"}.get(kind) or ("Tool-using agent " + kind.split("-")[1] if "-" in kind else "Tool-using agent v1")
    return f"{name}, {mode}"


def plot(rows: list[dict], path: Path, close: bool) -> None:
    """Reliability diagram: one panel per dataset, one line per suggester."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = sorted({r["dataset"] for r in rows if "(" not in r["dataset"]})  # description and part number data
    fig, axes = plt.subplots(1, len(names), figsize=(5.2 * len(names), 5.6), squeeze=False)
    for ax, name in zip(axes[0], names):
        ax.plot([0, 1], [0, 1], color="#9aa5ae", linestyle="--", linewidth=1, label="perfect calibration")
        for r in sorted((r for r in rows if r["dataset"] == name), key=lambda r: r["suggester"]):
            points = r["reliability"]
            ax.plot([p["confidence"] for p in points], [p["accuracy"] for p in points], marker=None, linewidth=1.5,
                    label=f"{display_name(r['suggester'])} (ECE {r['ece']:.2f})")
            ax.scatter([p["confidence"] for p in points], [p["accuracy"] for p in points],
                       s=[12 + 6 * p["n"] for p in points], alpha=0.8)
        ax.set_title(name, fontsize=11)
        ax.set_xlim(0, 1)
        ax.set_ylim(-0.02, 1.02)
        ax.set_xlabel("confidence given")
        ax.set_ylabel("share correct" + (" (close match)" if close else ""))
        ax.grid(alpha=0.25)
        ax.legend(fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=1, frameon=False)  # below: never on the data
    fig.suptitle("Reliability of the suggesters' confidence (points: confidence bins, size: proposals)", fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="*", type=Path)
    parser.add_argument("--since", help="include runs/run-*.json from this timestamp on, e.g. 20261023")
    parser.add_argument("--suggester", action="append", default=[], metavar="TEXT",
                        help="only suggesters whose label contains TEXT (repeatable), e.g. agent-v3, llm:, rules")
    parser.add_argument("--close", action="store_true", help="a near match (half the words shared) counts as correct")
    parser.add_argument("--max-wrong-rate", type=float, default=MAX_WRONG_RATE,
                        help=f"tolerant threshold: share of wrong writes allowed (default {MAX_WRONG_RATE})")
    parser.add_argument("--plot", type=Path, help="draw the reliability diagram to this PNG or PDF")
    parser.add_argument("--out", type=Path, help="also save every table (and the reliability bins) as JSON")
    args = parser.parse_args()

    runs = [(p, r) for p, r in load_runs(args.runs, args.since)
            if r.get("dataset") and selected(run_group(r)[0], args.suggester)]  # offline runs only
    if not runs:
        raise SystemExit("No offline run files match: pass paths or --since, and check --suggester")

    datasets, groups = {}, defaultdict(list)  # (label, dataset) -> [(graded gaps, rows)] one entry per run
    for _, run in runs:
        truth = run_truth(run, datasets)
        graded, _, _ = graded_results(run["results"], truth)
        groups[run_group(run)].append((len(graded), proposal_rows(run, truth, close=args.close)))
    measure = "close match" if args.close else "exact match (ignoring case and punctuation)"
    out = {"correct": measure, "max_wrong_rate": args.max_wrong_rate, "calibration": [], "basis": [], "transfer": []}

    print(f"Correct = {measure}.\n")
    print("1. Calibration per suggester and dataset (graded proposals pooled over repeats)\n")
    print("| suggester | dataset | runs | proposals | mean confidence | accuracy | over-confidence | Brier | ECE |")
    print("|---|---|---|---|---|---|---|---|---|")
    for (label, name), group in sorted(groups.items()):
        pairs = [(r["confidence"], r["correct"]) for _, rows in group for r in rows]
        if not pairs:
            continue
        conf, acc = sum(c for c, _ in pairs) / len(pairs), sum(ok for _, ok in pairs) / len(pairs)
        row = {"suggester": label, "dataset": name, "runs": len(group), "proposals": len(pairs), "confidence": conf,
               "accuracy": acc, "brier": brier(pairs), "ece": ece(pairs), "reliability": reliability(pairs)}
        out["calibration"].append(row)
        print(f"| {label} | {name} | {len(group)} | {len(pairs)} | {conf:.2f} | {acc:.0%} | {conf - acc:+.2f} "
              f"| {fmt(row['brier'])} | {fmt(row['ece'])} |")

    print("\n2. Accuracy per basis (evidence mode) and per rule (rules), 95% Wilson interval\n")
    print("| suggester | dataset | basis | proposals | confidence given | accuracy | 95% interval |")
    print("|---|---|---|---|---|---|---|")
    for (label, name), group in sorted(groups.items()):
        by_basis = defaultdict(list)
        for _, rows in group:
            for r in rows:
                by_basis[r["basis"]].append(r)
        if set(by_basis) == {SELF_RATED}:
            continue  # one basis only: table 1 already says it
        for basis, rows in sorted(by_basis.items(), key=lambda kv: -sum(r["confidence"] for r in kv[1]) / len(kv[1])):
            k, n = sum(r["correct"] for r in rows), len(rows)
            low, high = wilson(k, n)
            conf = sum(r["confidence"] for r in rows) / n
            out["basis"].append({"suggester": label, "dataset": name, "basis": basis, "n": n, "confidence": conf,
                                 "accuracy": k / n, "low": low, "high": high})
            print(f"| {label} | {name} | {basis} | {n} | {conf:.2f} | {k / n:.0%} | {low:.0%}-{high:.0%} |")

    tolerant = f"at most {args.max_wrong_rate:.0%} wrong"
    print("\n3. Transfer: basis -> confidence fixed (0.8/0.7/0.3/0.1) or learned on one dataset, tested on the other\n")
    print(f"Thresholds are chosen on the training dataset: strict = no wrong write, tolerant = {tolerant}.\n")
    print("| suggester | learned on | tested on | mapping | ECE on test | strict threshold | test: written / wrong "
          "| tolerant threshold | test: written / wrong | test: wrong share |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for label in sorted({label for label, _ in groups}):
        names = [n for l, n in groups if l == label and "(" not in n]  # dataset.json, dataset_cad.json
        if len(names) < 2:
            continue
        for train_name in names:
            train_rows = [r for _, rows in groups[(label, train_name)] for r in rows]
            if not any(r["basis"] in FIXED for r in train_rows):
                continue  # only the evidence mode states a basis
            learned = learn_mapping(train_rows)
            for test_name in (n for n in names if n != train_name):
                for kind, mapping in (("fixed", {**FIXED, "*": 0.3}), ("learned", learned)):
                    train = [(g, remap(rows, mapping)) for g, rows in groups[(label, train_name)]]
                    test = [(g, remap(rows, mapping)) for g, rows in groups[(label, test_name)]]
                    strict = threshold_transfer(train, test)
                    loose = threshold_transfer(train, test, args.max_wrong_rate)
                    e = ece([p for _, pairs in test for p in pairs])
                    out["transfer"].append({"suggester": label, "train": train_name, "test": test_name, "mapping": kind,
                                            "map": {k: round(v, 3) for k, v in mapping.items()}, "ece_test": e,
                                            "strict": strict, "tolerant": loose})
                    print(f"| {label} | {train_name} | {test_name} | {kind} | {fmt(e)} "
                          f"| {show(strict['threshold'])} | {strict['written']:.1f} / {strict['wrong']:.1f} "
                          f"| {show(loose['threshold'])} | {loose['written']:.1f} / {loose['wrong']:.1f} | {rate(loose)} |")

    print("\nRepeats are pooled in tables 1 and 2 and are not independent: read the intervals as optimistic.")
    if args.plot:
        plot(out["calibration"], args.plot, args.close)
        print(f"Saved {args.plot}")
    if args.out:
        args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Saved {args.out}")


if __name__ == "__main__":
    main()
