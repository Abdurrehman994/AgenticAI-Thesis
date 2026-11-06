"""Phase 4 held-out data: turn data/cad_extract.json into a dataset file in the format of data/dataset.json.

    python scripts/cad_to_dataset.py                                   # -> data/dataset_cad.json
    python scripts/cad_to_dataset.py --blank-fraction 0.4 --seed 7 --out data/dataset_cad_b.json
    python scripts/cad_to_dataset.py --root SWC-OrbitalSprinkler --title-suffix _Default \
        --collabspace "CAD models for Agentic workflow" --out data/dataset_sprinkler.json   # one assembly, as imported

Titles are the CAD file names, the BOM is the assemblies' direct children, and the true values are the CAD
properties: Description from the Custom tab, else from a configuration; the part number from a property
named like Partnumber; the material from SolidWorks' Material property. A random share of the known values
is blanked (fixed seed, so the file can be rebuilt). Materials are blanked with their own random stream, so
adding them left the description and part number blanks of earlier runs unchanged. Fields with no CAD value are left out: in PLM they are real gaps with no ground truth.
None of this was used to write the rules, which is what makes it held out.
"""
import argparse
import json
import random
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.gaps import ALL_FIELDS, FIELDS, MATERIAL  # noqa: E402

DATA = ROOT / "data"
PART_NUMBER_KEYS = {"partnumber", "partno", "partnum", "pn"}


def find(properties: dict, keys: set[str]) -> str:
    for name, value in properties.items():
        if name.lower().replace(" ", "").replace("_", "") in keys and value.strip():
            return value.strip()
    return ""


def true_values(entry: dict) -> dict:
    """Custom tab first, then the configurations (Default first): the value a PLM item would get."""
    configurations = entry.get("configurations", {})
    tabs = [entry.get("properties", {}), *sorted(configurations.values(), key=lambda p: p is not configurations.get("Default"))]
    values = {}
    for field, keys in (("description", {"description"}), ("partNumber", PART_NUMBER_KEYS), (MATERIAL, {"material"})):
        value = next((v for v in (find(tab, keys) for tab in tabs) if v), "")
        if value:
            values[field] = value
    return values


def one_assembly(items: list[dict], root: str, title_suffix: str) -> list[dict]:
    """The items in root's BOM as the tenant holds them after import: titles with the suffix and every field empty."""
    by_title, kept = {item["title"]: item for item in items}, {}
    if root not in by_title:
        raise SystemExit(f"no item {root!r} in the extract")

    def visit(title: str) -> None:
        if title not in kept:
            kept[title] = by_title[title]
            for child in by_title[title].get("children", []):
                visit(child)

    visit(root)
    return [
        {
            **item,
            "title": item["title"] + title_suffix,
            **({"children": [c + title_suffix for c in item["children"]]} if "children" in item else {}),
            "blank": sorted(field for field in ALL_FIELDS if field in item),
        }
        for item in kept.values()
    ]


def convert(extract: dict, *, blank_fraction: float, seed: int, collabspace: str, root: str | None = None,
            title_suffix: str = "") -> dict:
    paths = {key: PurePosixPath(key) for key, entry in extract.items() if "error" not in entry}
    # Assemblies name their children by file name; resolve them within the same top-level folder
    by_file = {(p.parts[0], p.name.lower()): p.stem for p in paths.values()}

    items, unresolved = [], set()
    for key, path in sorted(paths.items(), key=lambda kv: kv[1].stem.lower()):
        entry = extract[key]
        item = {"title": path.stem, **true_values(entry)}
        children = []
        for child in entry.get("children", {}):
            title = by_file.get((path.parts[0], child.lower()))
            if title:
                children.append(title)
            else:
                unresolved.add(child)
        if children:
            item["children"] = children
        items.append(item)

    if root:
        return {
            "_comment": (
                f"Phase 5 test data built by scripts/cad_to_dataset.py: {root} as imported into the tenant. True values "
                "are the CAD properties; every known field is blank, as the import left them. Fields missing from an "
                "item have no CAD value: real gaps with no ground truth."
            ),
            "source": {"extract": "data/cad_extract.json", "root": root},
            "collabspace": collabspace,
            "items": one_assembly(items, root, title_suffix),
            "_unresolved_children": sorted(unresolved),
        }

    # Material has its own random stream (seed + 1), so adding it left the other fields' blanks unchanged
    for fields, rng in ((FIELDS, random.Random(seed)), ((MATERIAL,), random.Random(seed + 1))):
        known = [(item, field) for item in items for field in fields if field in item]
        for item, field in sorted(rng.sample(known, round(len(known) * blank_fraction)), key=lambda x: x[0]["title"]):
            item.setdefault("blank", []).append(field)
    for item in items:
        if "blank" in item:
            item["blank"].sort()

    return {
        "_comment": (
            "Phase 4 held-out data built by scripts/cad_to_dataset.py from data/cad_extract.json. True values "
            "are the CAD properties; 'blank' fields are left empty for the agent. Fields missing from an item "
            "have no CAD value: real gaps with no ground truth."
        ),
        "source": {"extract": "data/cad_extract.json", "blank_fraction": blank_fraction, "seed": seed},
        "collabspace": collabspace,
        "items": items,
        "_unresolved_children": sorted(unresolved),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--extract", type=Path, default=DATA / "cad_extract.json")
    parser.add_argument("--out", type=Path, default=DATA / "dataset_cad.json")
    parser.add_argument("--blank-fraction", type=float, default=0.3, help="share of known values to blank")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--collabspace", default="API_development")
    parser.add_argument("--root", help="only this assembly's BOM, with every known field blank (--blank-fraction is ignored)")
    parser.add_argument("--title-suffix", default="", help="with --root: added to each title, as the import does (_Default)")
    args = parser.parse_args()

    extract = json.loads(args.extract.read_text(encoding="utf-8"))
    dataset = convert(extract, blank_fraction=args.blank_fraction, seed=args.seed, collabspace=args.collabspace,
                      root=args.root, title_suffix=args.title_suffix)
    if not dataset["_unresolved_children"]:
        del dataset["_unresolved_children"]
    args.out.write_text(json.dumps(dataset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    items = dataset["items"]
    blanks = sum(len(i.get("blank", [])) for i in items)
    unknown = sum(1 for i in items for f in (*FIELDS, MATERIAL) if f not in i)
    print(f"{len(items)} items, {blanks} blanked values (ground truth), {unknown} fields with no CAD value -> {args.out}")
    if "_unresolved_children" in dataset:
        print(f"Children not found among the files: {', '.join(dataset['_unresolved_children'])}")


if __name__ == "__main__":
    sys.exit(main())
