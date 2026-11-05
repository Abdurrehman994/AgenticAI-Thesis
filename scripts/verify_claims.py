"""Phase 4, step 2: does checking the model's claims in code make its confidence more trustworthy? Offline.

    python scripts/verify_claims.py --since 20261023
    python scripts/verify_claims.py --since 20261023 --suggester agent-v3 --suggester llm: --close --out runs/verify.json

The evidence mode's two highest bases are claims the code can check (agent/verify.py):
- "copied": against the items the model was shown (the run's sources_found): a literal copy, a variant swap (the
  source's value with the differing title tokens replaced), or unverified;
- "pattern" for a part number: against the numbers in use in the collab space: the only hole in its family's
  sequence (verified), one of several holes, the next number, a new variant of a used family, already used, or
  breaking the pattern. A "pattern" description is not checked: there is no rule to check it against.

1. How often each kind of claim is right, per check result (95% bootstrap over gaps).
2. What the checks do to the confidence. Four mappings: fixed (copied 0.8, pattern 0.7, inferred 0.3, guess 0.1,
   every claim taken at its word), copies checked, numbers checked, and both: a claim the code cannot confirm is
   demoted to --demote (default 0.3, as "inferred"). ECE per dataset, and a tolerant threshold (at most
   --max-wrong-rate wrong) chosen on one dataset and applied to the other, as in calibration.py.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.offline import DatasetTenant  # noqa: E402
from agent.snapshot import part_number  # noqa: E402
from agent.verify import LITERAL, SWAPPED, VERIFIED_NUMBERS, verify_copy, verify_pattern_number  # noqa: E402
from scripts.calibration import (FIXED, MAX_WRONG_RATE, accuracy, accuracy_interval, bootstrap, by_gap, ece, fmt,  # noqa: E402
                                 interval, rate, remap, selected, threshold_transfer)
from scripts.compare import graded_results, load_runs  # noqa: E402
from scripts.evaluate import run_group, run_truth  # noqa: E402
from scripts.threshold import show  # noqa: E402

DEMOTE = 0.3
COPY, NUMBER = "copied", "pattern part number"


def checked_rows(run: dict, truth: dict, items_by_title: dict[str, dict], *, close: bool = False) -> list[dict]:
    """The run's graded proposals with their basis; a checkable claim carries the check's result."""
    _, proposed, scores = graded_results(run["results"], truth)
    used = [part_number(i) for i in items_by_title.values()]  # visible numbers: blanked ones are not in use
    rows = []
    for r, s in zip(proposed, scores):
        llm = r.get("llm") or {}
        basis, claim, check, verified = llm.get("basis"), None, None, None
        value, field = r["proposal"]["value"], r["gap"]["field"]
        if basis == "copied":
            sources = [items_by_title[t] for t in llm.get("sources_found") or [] if t in items_by_title]
            claim, (check, _) = COPY, verify_copy(value, r["gap"]["title"], field, sources)
            verified = check in (LITERAL, SWAPPED)
        elif basis == "pattern" and field == "partNumber":
            claim, (check, _) = NUMBER, verify_pattern_number(value, used)
            verified = check in VERIFIED_NUMBERS
        rows.append({"confidence": r["proposal"]["confidence"], "correct": bool(s["close" if close else "normalized"]),
                     "basis": basis, "claim": claim, "check": check, "verified": verified, "field": field,
                     "gap": f"{r['gap']['title']}|{field}"})
    return rows


def demoted(rows: list[dict], claims: tuple[str, ...]) -> list[dict]:
    """Claims of the given kinds that the code could not confirm get their own basis, '<basis>-unverified'."""
    return [{**r, "basis": f"{r['basis']}-unverified"} if r["claim"] in claims and r["verified"] is False else r
            for r in rows]


def mappings(demote: float) -> dict[str, tuple[tuple[str, ...], dict[str, float]]]:
    """name -> (claims checked, basis -> confidence). Unchecked claims keep the model's basis."""
    base = {**FIXED, "*": 0.3}
    down = {"copied-unverified": demote, "pattern-unverified": demote}
    return {
        "fixed": ((), base),
        "copies checked": ((COPY,), {**base, **down}),
        "numbers checked": ((NUMBER,), {**base, **down}),
        "both checked": ((COPY, NUMBER), {**base, **down}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="*", type=Path)
    parser.add_argument("--since", help="include runs/run-*.json from this timestamp on, e.g. 20261023")
    parser.add_argument("--suggester", action="append", default=[], metavar="TEXT")
    parser.add_argument("--close", action="store_true", help="a near match (half the words shared) counts as correct")
    parser.add_argument("--demote", type=float, default=DEMOTE, help=f"confidence of an unconfirmed claim (default {DEMOTE})")
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
    maps = mappings(args.demote)
    out = {"correct": measure, "demote": args.demote, "checks": [], "calibration": [], "transfer": []}
    print(f"Correct = {measure}. Claims the code cannot confirm are demoted to {args.demote:.2f}.\n")

    print("1. Checkable claims by what the code found (95% bootstrap over gaps)\n")
    print("| suggester | dataset | claim | check | verified | gaps | answers | right | 95% |")
    print("|---|---|---|---|---|---|---|---|---|")
    for (label, name), group in sorted(groups.items()):
        claims = [r for _, rows in group for r in rows if r["claim"]]
        for key in sorted({(r["claim"], r["check"]) for r in claims}, key=lambda k: (k[0], k[1])):
            part = [r for r in claims if (r["claim"], r["check"]) == key]
            pairs = [(r["confidence"], r["correct"]) for r in part]
            ci = accuracy_interval(by_gap(part))
            out["checks"].append({"suggester": label, "dataset": name, "claim": key[0], "check": key[1],
                                  "verified": part[0]["verified"], "gaps": len(by_gap(part)), "answers": len(part),
                                  "accuracy": accuracy(pairs), "ci": ci})
            print(f"| {label} | {name} | {key[0]} | {key[1]} | {'yes' if part[0]['verified'] else 'no'} "
                  f"| {len(by_gap(part))} | {len(part)} | {accuracy(pairs):.0%} | {interval(ci, pct=True)} |")

    print("\n2. Calibration with and without the checks\n")
    print("| suggester | dataset | mapping | ECE | 95% |")
    print("|---|---|---|---|---|")
    for (label, name), group in sorted(groups.items()):
        for kind, (claims, mapping) in maps.items():
            rows = demoted([r for _, rs in group for r in rs], claims)
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
                for kind, (claims, mapping) in maps.items():
                    train = [(g, remap(demoted(rows, claims), mapping)) for g, rows in groups[(label, train_name)]]
                    test = [(g, remap(demoted(rows, claims), mapping)) for g, rows in groups[(label, test_name)]]
                    t = threshold_transfer(train, test, args.max_wrong_rate)
                    out["transfer"].append({"suggester": label, "mapping": kind, "train": train_name, "test": test_name, **t})
                    print(f"| {label} | {kind} | {train_name} | {test_name} | {show(t['threshold'])} "
                          f"| {t['written']:.1f} / {t['wrong']:.1f} | {rate(t)} |")

    if args.out:
        args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nSaved {args.out}")


if __name__ == "__main__":
    main()
