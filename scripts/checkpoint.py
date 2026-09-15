"""Phase 2 checkpoint: log in, list items in a collab space, patch one item's description.

    python scripts/checkpoint.py             # live
    python scripts/checkpoint.py --record    # live, saves tests/cassettes/checkpoint.yaml
    python scripts/checkpoint.py --offline   # replays that cassette, no network or credentials
"""
import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plm_client import Engineering, PLMSession, Settings  # noqa: E402
from plm_client.recording import CASSETTE_DIR, recorder  # noqa: E402

CASSETTE = "checkpoint.yaml"
META = CASSETTE_DIR / "checkpoint.meta.json"  # non-secret settings needed to replay offline


def run(cfg: Settings, search: str, collabspace: str, target: str, description: str) -> tuple[list[dict], dict]:
    eng = Engineering(PLMSession(cfg))
    items = [i for i in eng.iter_search(search) if not collabspace or i.get("collabspace") == collabspace]

    print(f"{len(items)} items matching {search!r} in {collabspace or 'any collab space'}:")
    for item in items:
        print(f"  {item.get('title', ''):<30} {item.get('name', ''):<25} {item.get('description', '<no description>')}")

    match = next((i for i in items if target in (i.get("title"), i.get("name"))), None)
    if match is None:
        raise SystemExit(f"{target!r} not in the search results")
    updated = eng.patch_item(match["id"], {"description": description}, cestamp=match.get("cestamp"))
    print(f"\nPatched {target}: description = {updated.get('description')!r}")
    return items, updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--search", default="API_TEST")
    parser.add_argument("--collabspace", default="API_development")
    parser.add_argument("--target", default="API_TEST_001")
    parser.add_argument("--description", default="Updated by plm_client checkpoint")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--record", action="store_true")
    mode.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    run_args = (args.search, args.collabspace, args.target, args.description)

    if args.offline:
        meta = json.loads(META.read_text(encoding="utf-8"))
        cfg = Settings(**meta["settings"], username="offline", password="offline")
        with recorder("none").use_cassette(CASSETTE):
            run(cfg, *meta["args"])
        return

    cfg = Settings.from_env()
    if not args.record:
        run(cfg, *run_args)
        return

    (CASSETTE_DIR / CASSETTE).unlink(missing_ok=True)
    with recorder("all").use_cassette(CASSETTE):
        run(cfg, *run_args)
    settings = {k: v for k, v in asdict(cfg).items() if k not in ("username", "password")}
    META.write_text(json.dumps({"settings": settings, "args": run_args}, indent=2), encoding="utf-8")
    print(f"Recorded {CASSETTE_DIR / CASSETTE}")


if __name__ == "__main__":
    main()
