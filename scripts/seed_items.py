"""Phase 3 test data: create the items and BOM in data/dataset.json, leaving each item's "blank" fields empty.

The full values stay in the dataset file as ground truth, so proposals can be scored in Phase 4.
Safe to re-run: items already created (tracked in data/seeded.json) and existing BOM links are skipped.

    python scripts/seed_items.py          # dry run: shows what would be created
    python scripts/seed_items.py --yes    # creates the items (with part numbers) and BOM links
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plm_client import Engineering, PLMSession, Settings  # noqa: E402

DATASET = ROOT / "data" / "dataset.json"
SEEDED = ROOT / "data" / "seeded.json"  # title -> id; search lags behind creation, so re-runs rely on this


def plm_attributes(entry: dict) -> dict:
    blank = set(entry.get("blank", []))
    attributes = {"title": entry["title"]}
    if "description" not in blank:
        attributes["description"] = entry["description"]
    if "partNumber" not in blank:
        attributes["dseng:EnterpriseReference"] = {"partNumber": entry["partNumber"]}
    return attributes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="actually create the items and BOM links")
    args = parser.parse_args()

    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    entries = dataset["items"]
    ids = json.loads(SEEDED.read_text(encoding="utf-8")) if SEEDED.exists() else {}

    if not args.yes:
        for entry in entries:
            attributes = plm_attributes(entry)
            part_number = attributes.get("dseng:EnterpriseReference", {}).get("partNumber", "BLANK")
            print(
                f"  {'exists' if entry['title'] in ids else 'create':<7} {entry['title']:<28} "
                f"description={'yes' if 'description' in attributes else 'BLANK':<6} "
                f"partNumber={part_number:<9} children={len(entry.get('children', []))}"
            )
        links = sum(len(e.get("children", [])) for e in entries)
        print(f"\nDry run: {len(entries)} items, {links} BOM links in {dataset['collabspace']}. Re-run with --yes.")
        return

    eng = Engineering(PLMSession(Settings.from_env()))
    for entry in entries:
        if entry["title"] in ids:
            continue
        # One item per call: in a batch, an item without a part number inherits the previous item's
        (item,) = eng.create_items([plm_attributes(entry)])
        ids[entry["title"]] = item["id"]
        SEEDED.write_text(json.dumps(ids, indent=2), encoding="utf-8")
        print(f"  created {entry['title']:<28} {item['id']}")

    for entry in entries:
        if not entry.get("children"):
            continue
        parent_id = ids[entry["title"]]
        existing = {inst["referencedObject"]["identifier"] for inst in eng.iter_instances(parent_id)}
        for child in entry["children"]:
            if ids[child] in existing:
                continue
            eng.add_instance(parent_id, ids[child], name=f"{child}.1")
            print(f"  linked  {entry['title']} -> {child}")

    print("\nDone. Search and where-used are index based: wait a few minutes before scripts/run_agent.py.")


if __name__ == "__main__":
    main()
