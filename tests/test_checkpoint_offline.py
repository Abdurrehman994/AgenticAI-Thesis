import json

import pytest

from plm_client import Settings
from plm_client.recording import recorder
from scripts.checkpoint import CASSETTE, META, run

pytestmark = pytest.mark.skipif(
    not META.exists(), reason="no cassette yet: run python scripts/checkpoint.py --record"
)


def test_checkpoint_replays_offline():
    meta = json.loads(META.read_text(encoding="utf-8"))
    cfg = Settings(**meta["settings"], username="offline", password="offline")
    search, collabspace, target, description = meta["args"]

    with recorder("none").use_cassette(CASSETTE):
        items, updated = run(cfg, search, collabspace, target, description)

    assert any(target in (i.get("title"), i.get("name")) for i in items)
    assert updated.get("description") == description
