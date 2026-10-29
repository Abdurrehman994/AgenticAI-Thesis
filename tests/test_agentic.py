import json

import requests

from agent.agentic import AgenticSuggester, SnapshotTools, agent_prompt
from agent.snapshot import Snapshot
from tests.test_llm import SETTINGS, FakeResponse, FakeSession, gap_for


def reply(obj) -> FakeResponse:
    return FakeResponse(200, json.dumps(obj))


def tool(name, **args) -> FakeResponse:
    return reply({"tool": name, "args": args})


def test_prompt_keeps_the_fixed_context_rules():
    prompt = agent_prompt("evidence", 4)
    assert "at most 4 tool calls" in prompt
    assert "never reuse a part number" in prompt and '"basis"' in prompt
    assert "Final answer: only a JSON object" in prompt


def test_agent_gathers_evidence_then_answers(tenant):
    snapshot = Snapshot(tenant, tenant.iter_search("*"))
    session = FakeSession(
        tool("find_items", text="ROLLER"),
        reply({"value": "Idler roller", "confidence": 0.7, "evidence": ["API_ROLLER_DRIVE_D50"]}),
    )
    agent = AgenticSuggester(SETTINGS, session=session)
    proposal = agent.suggest(gap_for(snapshot, "API_ROLLER_IDLER_D50", "description"), snapshot)

    assert (proposal.value, proposal.confidence, proposal.method) == ("Idler roller", 0.7, "agent-v3:gpt-oss-120b")
    assert agent.last_call["steps"] == [{"tool": "find_items", "args": {"text": "ROLLER"}}]
    first, second = (r["json"]["messages"] for r in session.requests)
    assert "API_ROLLER_DRIVE_D50" not in first[1]["content"]  # starts with the item and its structure, no sibling values
    assert "API_ROLLER_DRIVE_D50" in second[-1]["content"]  # the tool result
    assert agent.last_call["prompt_tokens"] == 1800  # both requests count


def test_agent_must_answer_after_the_step_limit(tenant):
    snapshot = Snapshot(tenant, tenant.iter_search("*"))
    session = FakeSession(tool("get_item", title="API_ROLLER_IDLER_D50"), tool("get_parents", title="API_ROLLER_IDLER_D50"),
                          reply({"value": None, "confidence": 0}))
    agent = AgenticSuggester(SETTINGS, session=session, max_steps=2)
    assert agent.suggest(gap_for(snapshot, "API_ROLLER_IDLER_D50", "description"), snapshot) is None
    assert len(agent.last_call["steps"]) == 2
    messages = session.requests[-1]["json"]["messages"]
    assert messages[-2]["content"].startswith("No more tool calls")  # [-1] is the answer, appended afterwards


def test_tools_report_errors_instead_of_failing(tenant):
    snapshot = Snapshot(tenant, tenant.iter_search("*"))
    tools = SnapshotTools(snapshot, gap_for(snapshot, "API_ROLLER_IDLER_D50", "description"))
    assert "error" in tools.call("delete_item", {})
    assert "error" in tools.call("get_item", {"title": "NO_SUCH_ITEM"})
    assert "error" in tools.call("get_item", {"name": "x"})
    parents = tools.call("get_parents", {"title": "API_ROLLER_IDLER_D50"})
    assert parents and tools.seen == {p["title"] for p in parents}


def test_evidence_sources_must_have_been_looked_at(tenant):
    snapshot = Snapshot(tenant, tenant.iter_search("*"))
    gap = gap_for(snapshot, "API_ROLLER_IDLER_D50", "description")
    claim = {"value": "Idler roller", "basis": "copied", "sources": ["API_ROLLER_DRIVE_D50"], "evidence": []}

    unseen = AgenticSuggester(SETTINGS, confidence="evidence", session=FakeSession(reply(claim)))
    assert unseen.suggest(gap, snapshot).confidence == 0.3  # names an item it never looked at: inferred

    looked = AgenticSuggester(SETTINGS, confidence="evidence",
                              session=FakeSession(tool("find_items", text="ROLLER DRIVE"), reply(claim)))
    assert looked.suggest(gap, snapshot).confidence == 0.8


def test_start_shows_structure_and_siblings_tool(tenant):
    snapshot = Snapshot(tenant, tenant.iter_search("*"))
    gap = gap_for(snapshot, "API_ROLLER_IDLER_D50", "description")
    session = FakeSession(tool("get_siblings", title="API_ROLLER_IDLER_D50"), reply({"value": None, "confidence": 0}))
    AgenticSuggester(SETTINGS, session=session).suggest(gap, snapshot)

    first, second = (r["json"]["messages"] for r in session.requests)
    start = json.loads(first[1]["content"].split("\n\n", 1)[1])
    assert start["usedIn"] and start["missingField"] == "description"
    siblings = json.loads(second[-2]["content"].removeprefix("Result:\n"))
    assert siblings[0]["assembly"] == start["usedIn"][0]
    assert "API_ROLLER_IDLER_D50" not in {p["title"] for p in siblings[0]["otherParts"]}


def test_list_items_does_not_count_as_looking(tenant):
    snapshot = Snapshot(tenant, tenant.iter_search("*"))
    tools = SnapshotTools(snapshot, gap_for(snapshot, "API_ROLLER_IDLER_D50", "description"))
    assert "API_ROLLER_DRIVE_D50" in tools.call("list_items", {}) and not tools.seen


def test_native_tool_call_is_read_as_json_protocol(tenant):
    class NativeToolCall(FakeResponse):
        def json(self):
            call = {"function": {"name": "find_items", "arguments": '{"text": "ROLLER"}'}}
            return {"choices": [{"message": {"content": None, "tool_calls": [call]}}], "usage": {}}

    snapshot = Snapshot(tenant, tenant.iter_search("*"))
    session = FakeSession(NativeToolCall(200), reply({"value": "Idler roller", "confidence": 0.5}))
    agent = AgenticSuggester(SETTINGS, session=session)
    assert agent.suggest(gap_for(snapshot, "API_ROLLER_IDLER_D50", "description"), snapshot).value == "Idler roller"
    assert agent.last_call["steps"] == [{"tool": "find_items", "args": {"text": "ROLLER"}}]


def test_tools_are_declared_natively_and_dropped_if_rejected(tenant):
    class Rejected(FakeResponse):
        def raise_for_status(self):
            raise requests.HTTPError("400 error", response=self)

    snapshot = Snapshot(tenant, tenant.iter_search("*"))
    gap = gap_for(snapshot, "API_ROLLER_IDLER_D50", "description")
    native = FakeSession(reply({"value": "Idler roller", "confidence": 0.5}))
    AgenticSuggester(SETTINGS, session=native).suggest(gap, snapshot)
    assert {t["function"]["name"] for t in native.requests[0]["json"]["tools"]} >= {"find_similar", "get_siblings"}

    session = FakeSession(Rejected(400), reply({"value": "Idler roller", "confidence": 0.5}))
    agent = AgenticSuggester(SETTINGS, session=session)
    assert agent.suggest(gap, snapshot).value == "Idler roller"
    assert "tools" in session.requests[0]["json"] and "tools" not in session.requests[1]["json"]
    assert agent.native_tools is False


def test_find_similar_ranks_the_same_family_first(tenant):
    snapshot = Snapshot(tenant, tenant.iter_search("*"))
    tools = SnapshotTools(snapshot, gap_for(snapshot, "API_ROLLER_IDLER_D50", "description"))
    similar = tools.call("find_similar", {"title": "API_NUT_M6_ISO4032"})
    assert similar[0]["title"] == "API_NUT_M8_ISO4032"  # shares nut and iso4032; "api" is in every title
    assert "API_NUT_M6_ISO4032" not in {s["title"] for s in similar}


def test_empty_answer_is_explained_in_the_run_file(tenant):
    class Empty(FakeResponse):
        def json(self):
            message = {"content": "", "reasoning_content": "I will call find_similar"}
            return {"choices": [{"message": message, "finish_reason": "stop"}], "usage": {}}

    snapshot = Snapshot(tenant, tenant.iter_search("*"))
    agent = AgenticSuggester(SETTINGS, session=FakeSession(Empty(200)))
    assert agent.suggest(gap_for(snapshot, "API_ROLLER_IDLER_D50", "description"), snapshot) is None
    assert agent.last_call["empty"] == {"finish_reason": "stop", "reasoning_tail": "I will call find_similar"}
