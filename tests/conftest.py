import json
from pathlib import Path

import pytest

from agent import llm
from agent.offline import DatasetTenant

DATASET = Path(__file__).resolve().parents[1] / "data" / "dataset.json"


@pytest.fixture
def dataset() -> dict:
    return json.loads(DATASET.read_text(encoding="utf-8"))


@pytest.fixture
def tenant(dataset) -> DatasetTenant:
    return DatasetTenant(dataset)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """The LLM client backs off between retries; tests never wait."""
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
