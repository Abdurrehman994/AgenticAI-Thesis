"""Phase 4: how well does each suggester's confidence match how often it is right? Offline, from run files.

    python scripts/calibration.py --since 20261023
    python scripts/calibration.py --since 20261023 --suggester agent-v3 --suggester llm: --suggester rules
    python scripts/calibration.py --since 20261023 --by-field              # descriptions and part numbers apart
    python scripts/calibration.py --since 20261023 --close                 # near matches count as correct
    python scripts/calibration.py --since 20261023 --plot runs/reliability.png --out runs/calibration.json

Three tables:
1. Calibration per suggester and dataset: mean confidence against accuracy of the graded proposals, Brier score
   and expected calibration error (ECE: the gap between confidence and accuracy, averaged over confidence bins of
   width 0.2, weighted by how many proposals fall in each).
2. Accuracy per basis: what the evidence-mode suggesters state ("copied", "pattern", "inferred", "guess") and
   which rule fired for the rule-based one.
3. Transfer: the evidence mode maps each basis to a fixed confidence (0.8 / 0.7 / 0.3 / 0.1). Here the mapping is
   also learned, as each basis's accuracy on one dataset (smoothed: (correct + 1) / (n + 2)), and applied
   unchanged to the other. For both mappings: ECE on the test dataset, and two thresholds chosen on the training
   dataset with what they write per run on the test dataset:
   - strict: the lowest threshold with no wrong write on the training data (as threshold.py);
   - tolerant: the lowest threshold whose written values are at most --max-wrong-rate wrong on the training data.
     With 50+ proposals a single wrong answer makes the strict threshold "write nothing", which hides whether the
     mapping transfers; the tolerant one shows it.

Intervals (95%) are a bootstrap over gaps: a gap answered in six repeated runs is one sample, not six, so whole
gaps are resampled with all their repeats (2000 times, fixed seed). With fewer than 5 distinct gaps no interval is
given; when every gap has the same outcome, the rule of three gives the bound. --by-field splits every table by field: descriptions fail as near-paraphrases, part numbers as numbers
guessed from a family pattern, and their confidence need not behave the same.

Correct means equal ignoring case and punctuation (evaluate.score "normalized"), as in compare.py; with --close
a description sharing at least half its words with the truth also counts (evaluate.CLOSE_OVERLAP), closer to what
a reviewer would accept with a small edit.

--plot draws the reliability diagram (one panel per dataset, and per field with --by-field; a line per
suggester; points are confidence bins, their size the number of proposals) as PNG or PDF.
"""
import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.compare import graded_results, load_runs  # noqa: E402
from scripts.evaluate import run_group, run_truth  # noqa: E402
from scripts.threshold import at, choose, curve, show  # noqa: E402

BIN_WIDTH = 0.2
MAX_WRONG_RATE = 0.1
BOOTSTRAP = 2000
SEED = 2026
MIN_GAPS = 5  # fewer distinct gaps: no interval, it would only look precise
ALL = "all"
FIXED = {"copied": 0.8, "pattern": 0.7, "inferred": 0.3, "guess": 0.1}  # agent.llm evidence mode
SELF_RATED = "self-rated"


def proposal_rows(run: dict, truth: dict, *, close: bool = False) -> list[dict]:
    """One row per graded proposal: confidence, correct, the basis it came from, and which gap it answers."""
    _, proposed, scores = graded_results(run["results"], truth)
    rows = []
    for r, s in zip(proposed, scores):
        llm = r.get("llm") or {}
        basis = llm.get("basis") or (SELF_RATED if llm else r["proposal"]["method"])
        rows.append({"confidence": r["proposal"]["confidence"], "correct": bool(s["close" if close else "normalized"]),
                     "basis": basis, "field": r["gap"]["field"], "gap": f"{r['gap']['title']}|{r['gap']['field']}"})
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


def accuracy(pairs: list[tuple[float, bool]]) -> float | None:
    return sum(ok for _, ok in pairs) / len(pairs) if pairs else None


def by_gap(rows: list[dict]) -> list[list[tuple[float, bool]]]:
    """The proposals grouped per gap: the unit a bootstrap resamples."""
    clusters = defaultdict(list)
    for r in rows:
        clusters[r["gap"]].append((r["confidence"], r["correct"]))
    return list(clusters.values())


def bootstrap(clusters: list[list[tuple[float, bool]]], stat, *, n: int = BOOTSTRAP, seed: int = SEED,
              min_clusters: int = MIN_GAPS) -> tuple[float, float] | None:
    """95% interval of stat(pairs) when whole clusters (gaps with all their repeats) are resampled."""
    if len(clusters) < min_clusters:
        return None
    rng = random.Random(seed)
    values = sorted(v for v in (stat([p for c in rng.choices(clusters, k=len(clusters)) for p in c]) for _ in range(n))
                    if v is not None)
    return values[int(0.025 * len(values))], values[int(0.975 * len(values)) - 1]


def accuracy_interval(clusters: list[list[tuple[float, bool]]]) -> tuple[float, float] | None:
    """Bootstrap interval of the accuracy. When every gap has the same outcome the bootstrap has no spread and
    would claim 0%-0%; then the rule of three gives the 95% bound instead (0 successes in n: at most about 3/n)."""
    ci = bootstrap(clusters, accuracy)
    if ci is None or ci[0] != ci[1] or ci[0] not in (0.0, 1.0):
        return ci
    bound = min(1.0, 3 / len(clusters))
    return (0.0, bound) if ci[0] == 0.0 else (1.0 - bound, 1.0)


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


def split_runs(group: list[tuple[Counter, list[dict]]], field: str) -> list[tuple[int, list[dict]]]:
    """Per run: graded gaps and proposals of one field (or of all)."""
    return [(sum(graded.values()) if field == ALL else graded[field],
             rows if field == ALL else [r for r in rows if r["field"] == field]) for graded, rows in group]


def selected(label: str, patterns: list[str]) -> bool:
    return not patterns or any(p in label for p in patterns)


def fmt(x: float | None) -> str:
    return "-" if x is None else f"{x:.2f}"


def interval(ci: tuple[float, float] | None, pct: bool = False) -> str:
    if ci is None:
        return "-"
    return f"{ci[0]:.0%}-{ci[1]:.0%}" if pct else f"{ci[0]:.2f}-{ci[1]:.2f}"


def rate(t: dict) -> str:
    return f"{t['wrong'] / t['written']:.0%}" if t["written"] else "-"


def display_name(label: str) -> str:
    """'agent-v3:gpt-oss-120b+evidence' -> 'Tool-using agent v3, evidence-based' for figure legends."""
    if label == "rules":
        return "Rules"
    kind, _, rest = label.partition(":")
    mode = {"+evidence": "evidence-based", "+checked": "evidence-based, checked",
            "+checked-v2": "evidence-based, checked v2"}.get(rest[rest.rfind("+"):], "self-rated") \
        if "+" in rest else "self-rated"
    name = {"llm": "LLM"}.get(kind) or ("Tool-using agent " + kind.split("-")[1] if "-" in kind else "Tool-using agent v1")
    return f"{name}, {mode}"


def plot(rows: list[dict], path: Path, close: bool) -> None:
    """Reliability diagram: one panel per dataset (and field), one line per suggester."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def panel(r: dict) -> str:
        return r["dataset"] + ("" if r.get("field", ALL) == ALL else f" · {r['field']}")

    names = sorted({panel(r) for r in rows if "(" not in r["dataset"]})  # description and part number data
    cols = min(len(names), 2)
    lines = (len(names) + cols - 1) // cols
    fig, axes = plt.subplots(lines, cols, figsize=(5.2 * cols, 5.6 * lines), squeeze=False)
    for ax in axes.flat[len(names):]:
        ax.set_visible(False)
    for ax, name in zip(axes.flat, names):
        ax.plot([0, 1], [0, 1], color="#9aa5ae", linestyle="--", linewidth=1, label="perfect calibration")
        for r in sorted((r for r in rows if panel(r) == name), key=lambda r: r["suggester"]):
            points = r["reliability"]
            ax.plot([p["confidence"] for p in points], [p["accuracy"] for p in points], linewidth=1.5,
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
    fig.tight_layout(rect=(0, 0, 1, 0.96))  # room for the title above the panels
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="*", type=Path)
    parser.add_argument("--since", help="include runs/run-*.json from this timestamp on, e.g. 20261023")
    parser.add_argument("--suggester", action="append", default=[], metavar="TEXT",
                        help="only suggesters whose label contains TEXT (repeatable), e.g. agent-v3, llm:, rules")
    parser.add_argument("--by-field", action="store_true", help="split every table by field")
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

    datasets, per_run = {}, defaultdict(list)  # (label, dataset) -> [(graded gaps per field, rows)] one per run
    for _, run in runs:
        truth = run_truth(run, datasets)
        graded, _, _ = graded_results(run["results"], truth)
        per_run[run_group(run)].append((Counter(r["gap"]["field"] for r in graded),
                                        proposal_rows(run, truth, close=args.close)))
    groups = {}  # (label, dataset, field) -> [(graded gaps, rows)] one entry per run
    for (label, name), group in per_run.items():
        fields = sorted({f for graded, _ in group for f in graded}) if args.by_field else [ALL]
        for field in fields:
            groups[(label, name, field)] = split_runs(group, field)

    measure = "close match" if args.close else "exact match (ignoring case and punctuation)"
    out = {"correct": measure, "by_field": args.by_field, "max_wrong_rate": args.max_wrong_rate,
           "bootstrap": {"resamples": BOOTSTRAP, "seed": SEED, "unit": "gap", "min_gaps": MIN_GAPS},
           "calibration": [], "basis": [], "transfer": []}

    print(f"Correct = {measure}. Intervals: 95%, bootstrap over gaps ({BOOTSTRAP} resamples), none below {MIN_GAPS} gaps.\n")
    print("1. Calibration per suggester and dataset\n")
    print("| suggester | dataset | field | runs | gaps | proposals | mean confidence | accuracy | 95% | "
          "over-confidence | Brier | ECE | 95% |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for (label, name, field), group in sorted(groups.items()):
        rows = [r for _, rs in group for r in rs]
        pairs = [(r["confidence"], r["correct"]) for r in rows]
        if not pairs:
            continue
        clusters = by_gap(rows)
        conf, acc = sum(c for c, _ in pairs) / len(pairs), accuracy(pairs)
        row = {"suggester": label, "dataset": name, "field": field, "runs": len(group), "gaps": len(clusters),
               "proposals": len(pairs), "confidence": conf, "accuracy": acc, "accuracy_ci": accuracy_interval(clusters),
               "brier": brier(pairs), "ece": ece(pairs), "ece_ci": bootstrap(clusters, ece), "reliability": reliability(pairs)}
        out["calibration"].append(row)
        print(f"| {label} | {name} | {field} | {len(group)} | {len(clusters)} | {len(pairs)} | {conf:.2f} | {acc:.0%} "
              f"| {interval(row['accuracy_ci'], pct=True)} | {conf - acc:+.2f} | {fmt(row['brier'])} | {fmt(row['ece'])} "
              f"| {interval(row['ece_ci'])} |")

    print("\n2. Accuracy per basis (evidence mode) and per rule (rules)\n")
    print("| suggester | dataset | field | basis | gaps | proposals | confidence given | accuracy | 95% |")
    print("|---|---|---|---|---|---|---|---|---|")
    for (label, name, field), group in sorted(groups.items()):
        by_basis = defaultdict(list)
        for _, rows in group:
            for r in rows:
                by_basis[r["basis"]].append(r)
        if set(by_basis) <= {SELF_RATED}:
            continue  # one basis only: table 1 already says it
        for basis, rows in sorted(by_basis.items(), key=lambda kv: -sum(r["confidence"] for r in kv[1]) / len(kv[1])):
            pairs = [(r["confidence"], r["correct"]) for r in rows]
            clusters = by_gap(rows)
            ci = accuracy_interval(clusters)
            conf = sum(c for c, _ in pairs) / len(pairs)
            out["basis"].append({"suggester": label, "dataset": name, "field": field, "basis": basis, "gaps": len(clusters),
                                 "n": len(pairs), "confidence": conf, "accuracy": accuracy(pairs), "ci": ci})
            print(f"| {label} | {name} | {field} | {basis} | {len(clusters)} | {len(pairs)} | {conf:.2f} "
                  f"| {accuracy(pairs):.0%} | {interval(ci, pct=True)} |")

    tolerant = f"at most {args.max_wrong_rate:.0%} wrong"
    print("\n3. Transfer: basis -> confidence fixed (0.8/0.7/0.3/0.1) or learned on one dataset, tested on the other\n")
    print(f"Thresholds are chosen on the training dataset: strict = no wrong write, tolerant = {tolerant}.\n")
    print("| suggester | field | learned on | tested on | mapping | ECE on test | strict threshold | test: written / wrong "
          "| tolerant threshold | test: written / wrong | test: wrong share |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for label, field in sorted({(l, f) for l, _, f in groups}):
        names = [n for l, n, f in groups if (l, f) == (label, field) and "(" not in n]  # dataset.json, dataset_cad.json
        if len(names) < 2:
            continue
        for train_name in names:
            train_rows = [r for _, rows in groups[(label, train_name, field)] for r in rows]
            if not any(r["basis"] in FIXED for r in train_rows):
                continue  # only the evidence mode states a basis
            learned = learn_mapping(train_rows)
            for test_name in (n for n in names if n != train_name):
                for kind, mapping in (("fixed", {**FIXED, "*": 0.3}), ("learned", learned)):
                    train = [(g, remap(rows, mapping)) for g, rows in groups[(label, train_name, field)]]
                    test = [(g, remap(rows, mapping)) for g, rows in groups[(label, test_name, field)]]
                    strict = threshold_transfer(train, test)
                    loose = threshold_transfer(train, test, args.max_wrong_rate)
                    e = ece([p for _, pairs in test for p in pairs])
                    out["transfer"].append({"suggester": label, "field": field, "train": train_name, "test": test_name,
                                            "mapping": kind, "map": {k: round(v, 3) for k, v in mapping.items()},
                                            "ece_test": e, "strict": strict, "tolerant": loose})
                    print(f"| {label} | {field} | {train_name} | {test_name} | {kind} | {fmt(e)} "
                          f"| {show(strict['threshold'])} | {strict['written']:.1f} / {strict['wrong']:.1f} "
                          f"| {show(loose['threshold'])} | {loose['written']:.1f} / {loose['wrong']:.1f} | {rate(loose)} |")

    if args.plot:
        plot(out["calibration"], args.plot, args.close)
        print(f"\nSaved {args.plot}")
    if args.out:
        args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Saved {args.out}")


if __name__ == "__main__":
    main()
