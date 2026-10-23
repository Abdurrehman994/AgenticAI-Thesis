import json
from pathlib import Path

import pytest

from agent.offline import DatasetTenant

DATASET = Path(__file__).resolve().parents[1] / "data" / "dataset.json"


@pytest.fixture
def dataset() -> dict:
    return json.loads(DATASET.read_text(encoding="utf-8"))


@pytest.fixture
def tenant(dataset) -> DatasetTenant:
    return DatasetTenant(dataset)
