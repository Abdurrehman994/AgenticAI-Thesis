import json

import pytest
import requests

from agent import llm
from agent.gaps import find_gaps
from agent.llm import LLMSettings, LLMSuggester, build_context, parse_answer
from agent.snapshot import Snapshot
from scripts.run_agent import run


class FakeResponse:
    def __init__(self, status_code: int, content: str = ""):
        self.status_code = status_code
        self._content = content

    def json(self):
        message = {"content": self._content, "reasoning_content": "thinking about it"}
        return {"choices": [{"message": message}], "usage": {"prompt_tokens": 900, "completion_tokens": 40}}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


class FakeSession:
    """Answers chat requests from a list, and keeps the requests for inspection."""

    def __init__(self, *responses: FakeResponse):
        self.responses = list(responses)
        self.requests = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.requests.append({"url": url, "json": json, "headers": headers})
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def answer(value, confidence=0.8, evidence=("API_NUT_M8_ISO4032 has a similar description",)) -> FakeResponse:
    return FakeResponse(200, json.dumps({"value": value, "confidence": confidence, "evidence": list(evidence)}))


SETTINGS = LLMSettings(base_url="https://llm.example/v1", model="azsydsttjnlbfjbgqnwd", api_key="k", label="gpt-oss-120b")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)


def gap_for(snapshot, title, field):
    return next(g for g in find_gaps(snapshot.items.values()) if (g.title, g.field) == (title, field))


def test_context_has_structure_and_skips_proposed_values(tenant):
    tenant.items["ID-API_ROLLER_DRIVE_D50"]["description"] = "[PROPOSED] Drive roller"
    snapshot = Snapshot(tenant, tenant.iter_search("*"))
    context = build_context(gap_for(snapshot, "API_ROLLER_IDLER_D50", "description"), snapshot)

    assert context["missingField"] == "description"
    assert context["item"] == {"title": "API_ROLLER_IDLER_D50"}
    (parent,) = context["usedIn"]
    assert parent["title"] == "API_ASM_CONVEYOR_MODULE"
    siblings = {s["title"]: s for s in parent["otherParts"]}
    assert "API_ROLLER_IDLER_D50" not in siblings
    assert siblings["API_ROLLER_DRIVE_D50"] == {"title": "API_ROLLER_DRIVE_D50", "partNumber": "CNV-1002"}
    listed = {parent["title"], *siblings}
    assert not listed & {i["title"] for i in context["otherItemsInProject"]}


def test_proposal_from_answer(tenant):
    snapshot = Snapshot(tenant, tenant.iter_search("*"))
    session = FakeSession(answer("Hex nut M6 ISO 4032, zinc plated", confidence=1.7))
    proposal = LLMSuggester(SETTINGS, session=session).suggest(gap_for(snapshot, "API_NUT_M6_ISO4032", "description"), snapshot)

    assert proposal.value == "Hex nut M6 ISO 4032, zinc plated"
    assert proposal.method == "llm:gpt-oss-120b"
    assert proposal.confidence == 1.0  # clamped
    assert proposal.evidence == ["API_NUT_M8_ISO4032 has a similar description"]
    (request,) = session.requests
    assert request["url"] == "https://llm.example/v1/chat/completions"
    assert request["json"]["model"] == "azsydsttjnlbfjbgqnwd"
    assert request["headers"] == {"Authorization": "Bearer k"}


def test_parse_answer_in_code_fence_or_prose():
    assert parse_answer('```json\n{"value": "x", "confidence": 0.5}\n```') == {"value": "x", "confidence": 0.5}
    assert parse_answer('Here it is: {"value": null} hope that helps')["value"] is None
    with pytest.raises(ValueError):
        parse_answer("I cannot tell")


def test_no_proposal_for_null_or_used_part_number(tenant):
    snapshot = Snapshot(tenant, tenant.iter_search("*"))
    gap = gap_for(snapshot, "API_GUARD_HINGE_AL", "partNumber")

    assert LLMSuggester(SETTINGS, session=FakeSession(answer(None))).suggest(gap, snapshot) is None
    suggester = LLMSuggester(SETTINGS, session=FakeSession(answer("GRD-3001")))
    assert suggester.suggest(gap, snapshot) is None
    assert suggester.last_call["rejected"] == "part number GRD-3001 is already used"


def test_server_errors_are_retried_then_reported(tenant):
    snapshot = Snapshot(tenant, tenant.iter_search("*"))
    gap = gap_for(snapshot, "API_GUARD_HINGE_AL", "partNumber")

    session = FakeSession(FakeResponse(503), answer("GRD-3002"))
    assert LLMSuggester(SETTINGS, session=session).suggest(gap, snapshot).value == "GRD-3002"
    assert len(session.requests) == 2

    suggester = LLMSuggester(SETTINGS, session=FakeSession(FakeResponse(503)), retries=1)
    assert suggester.suggest(gap, snapshot) is None
    assert suggester.last_call["error"] == "HTTPError: 503 error"

    suggester = LLMSuggester(SETTINGS, session=FakeSession(FakeResponse(200, "no idea")))
    assert suggester.suggest(gap, snapshot) is None
    assert suggester.last_call["error"].startswith("ValueError")


def test_run_with_llm_records_usage(tenant, tmp_path):
    from agent.writeback import ProposalLog

    suggester = LLMSuggester(SETTINGS, session=FakeSession(answer("Some value", confidence=0.4)))
    results = run(tenant, collabspace="API_development", log=ProposalLog(tmp_path / "log.jsonl"), suggester=suggester)

    assert len(results) == 12
    first = results[0]
    assert first["llm"]["prompt_tokens"] == 900 and first["llm"]["model"] == "azsydsttjnlbfjbgqnwd"
    assert "elapsed_s" in first


def test_settings_from_env(monkeypatch):
    monkeypatch.setattr(llm, "load_dotenv", lambda: None)
    for name, value in {"LLM_BASE_URL": "http://localhost:11434/v1/", "LLM_MODEL": "m1", "LLM_LABEL": "nice"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    settings = LLMSettings.from_env()
    assert (settings.base_url, settings.model, settings.label, settings.api_key) == ("http://localhost:11434/v1", "m1", "nice", "")
    assert LLMSettings.from_env("m2").label == ""  # an overriding model is reported by its id

    monkeypatch.delenv("LLM_BASE_URL")
    with pytest.raises(RuntimeError):
        LLMSettings.from_env()
