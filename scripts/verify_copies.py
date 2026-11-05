"""Phase 4, step 2b: does checking the model's "copied" claim in code make its confidence more trustworthy? Offline.

    python scripts/verify_copies.py --since 20261023
    python scripts/verify_copies.py --since 20261023 --suggester agent-v3 --suggester llm: --close --out runs/verify.json

For every graded proposal of an evidence-mode run whose stated basis is "copied", agent/verify.py checks the claim
against the items the model was shown (the run's sources_found): a literal copy, a variant swap (the source's value
with the differing title tokens replaced), or unverified.

1. How often each kind is right (95% bootstrap over gaps).
2. What it does to the confidence: the evidence mode's fixed mapping (copied 0.8, pattern 0.7, inferred 0.3,
   guess 0.1) against the same mapping with unverified copies demoted to --demote (default 0.3, as "inferred"):
   ECE per dataset, and a tolerant threshold (at most --max-wrong-rate wrong) chosen on one dataset and applied
   to the other, as in calibration.py.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.offline import DatasetTenant  # noqa: E402
from agent.verify import LITERAL, SWAPPED, UNVERIFIED, verify_copy  # noqa: E402
from scripts.calibration import (FIXED, MAX_WRONG_RATE, accuracy, accuracy_interval, bootstrap, by_gap, ece, fmt,  # noqa: E402
                                 interval, rate, remap, selected, threshold_transfer)
from scripts.compare import graded_results, load_runs  # noqa: E402
from scripts.evaluate import run_group, run_truth  # noqa: E402
from scripts.threshold import show  # noqa: E402

DEMOTE = 0.3
VERIFIED = (LITERAL, SWAPPED)


def checked_rows(run: dict, truth: dict, items_by_title: dict[str, dict], *, close: bool = False) -> list[dict]:
    """The run's graded proposals with their basis; a "copied" basis carries the check's verdict."""
    _, proposed, scores = graded_results(run["results"], truth)
    rows = []
    for r, s in zip(proposed, scores):
        llm = r.get("llm") or {}
        basis, check = llm.get("basis"), None
        if basis == "copied":
            sources = [items_by_title[t] for t in llm.get("sources_found") or [] if t in items_by_title]
            check, _ = verify_copy(r["proposal"]["value"], r["gap"]["title"], r["gap"]["field"], sources)
        rows.append({"confidence": r["proposal"]["confidence"], "correct": bool(s["close" if close else "normalized"]),
                     "basis": basis, "check": check, "field": r["gap"]["field"],
                     "gap": f"{r['gap']['title']}|{r['gap']['field']}"})
    return rows


def demoted(rows: list[dict]) -> list[dict]:
    """Unverified copies get their own basis, so a mapping can treat them apart."""
    return [{**r, "basis": "copied-unverified"} if r["check"] == UNVERIFIED else r for r in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="*", type=Path)
    parser.add_argument("--since", help="include runs/run-*.json from this timestamp on, e.g. 20261023")
    parser.add_argument("--suggester", action="append", default=[], metavar="TEXT")
    parser.add_argument("--close", action="store_true", help="a near match (half the words shared) counts as correct")
    parser.add_argument("--demote", type=float, default=DEMOTE, help=f"confidence of an unverified copy (default {DEMOTE})")
    parser.add_argument("--max-wrong-rate", type=float, default=MAX_WRONG_RATE)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    runs = [r for _, r in load_runs(args.runs, args.since)
            if r.get("dataset") and "evidence" in run_group(r)[0] and selected(run_group(r)[0], args.suggester)]
    if not runs:
        raise SystemExit("No offline evidence-mode run files match")
    datasets, tenants, groups = {}, {}, defaultdict(list)  # (label, dataset) -> [(graded gaps, rows)] per run
    for run in runs:
        if run["dataset"] not in tenants:
            dataset = json.loads((ROOT / run["dataset"]).read_text(encoding="utf-8"))
            tenants[run["dataset"]] = {i["title"]: i for i in DatasetTenant(dataset).items.values()}  # visible values only
        truth = run_truth(run, datasets)
        graded, _, _ = graded_results(run["results"], truth)
        groups[run_group(run)].append((len(graded), checked_rows(run, truth, tenants[run["dataset"]], close=args.close)))

    measure = "close match" if args.close else "exact match (ignoring case and punctuation)"
    fixed = {**FIXED, "*": 0.3, "copied-unverified": FIXED["copied"]}  # the claim taken at its word
    checked = {**fixed, "copied-unverified": args.demote}
    out = {"correct": measure, "demote": args.demote, "checks": [], "calibration": [], "transfer": []}
    print(f"Correct = {measure}. Unverified copies demoted to {args.demote:.2f}.\n")

    print('1. "Copied" answers by what the code could verify (95% bootstrap over gaps)\n')
    print("| suggester | dataset | check | gaps | answers | right | 95% |")
    print("|---|---|---|---|---|---|---|")
    for (label, name), group in sorted(groups.items()):
        copies = [r for _, rows in group for r in rows if r["check"]]
        for check in (LITERAL, SWAPPED, UNVERIFIED):
            part = [r for r in copies if r["check"] == check]
            if not part:
                continue
            pairs = [(r["confidence"], r["correct"]) for r in part]
            ci = accuracy_interval(by_gap(part))
            out["checks"].append({"suggester": label, "dataset": name, "check": check, "gaps": len(by_gap(part)),
                                  "answers": len(part), "accuracy": accuracy(pairs), "ci": ci})
            print(f"| {label} | {name} | {check} | {len(by_gap(part))} | {len(part)} | {accuracy(pairs):.0%} "
                  f"| {interval(ci, pct=True)} |")

    print("\n2. Calibration with and without the check\n")
    print("| suggester | dataset | mapping | ECE | 95% |")
    print("|---|---|---|---|---|")
    for (label, name), group in sorted(groups.items()):
        rows = demoted([r for _, rs in group for r in rs])
        for kind, mapping in (("fixed", fixed), ("checked", checked)):
            pairs = remap(rows, mapping)
            clusters = defaultdict(list)
            for r, p in zip(rows, pairs):
                clusters[r["gap"]].append(p)
            ci = bootstrap(list(clusters.values()), ece)
            out["calibration"].append({"suggester": label, "dataset": name, "mapping": kind, "ece": ece(pairs), "ci": ci})
            print(f"| {label} | {name} | {kind} | {fmt(ece(pairs))} | {interval(ci)} |")

    print(f"\n3. Transfer: tolerant threshold (at most {args.max_wrong_rate:.0%} wrong) chosen on one dataset, "
          "applied to the other\n")
    print("| suggester | mapping | chosen on | tested on | threshold | test: written / wrong per run | test: wrong share |")
    print("|---|---|---|---|---|---|---|")
    for label in sorted({l for l, _ in groups}):
        names = [n for l, n in groups if l == label and "(" not in n]
        for train_name in names:
            for test_name in (n for n in names if n != train_name):
                for kind, mapping in (("fixed", fixed), ("checked", checked)):
                    train = [(g, remap(demoted(rows), mapping)) for g, rows in groups[(label, train_name)]]
                    test = [(g, remap(demoted(rows), mapping)) for g, rows in groups[(label, test_name)]]
                    t = threshold_transfer(train, test, args.max_wrong_rate)
                    out["transfer"].append({"suggester": label, "mapping": kind, "train": train_name, "test": test_name, **t})
                    print(f"| {label} | {kind} | {train_name} | {test_name} | {show(t['threshold'])} "
                          f"| {t['written']:.1f} / {t['wrong']:.1f} | {rate(t)} |")

    if args.out:
        args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nSaved {args.out}")


if __name__ == "__main__":
    main()
