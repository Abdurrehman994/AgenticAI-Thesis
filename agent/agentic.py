"""Tool-using LLM suggester: the model gathers its own evidence from the product structure before answering.

LLMSuggester (agent/llm.py) hands the model one fixed bundle of context. AgenticSuggester starts the model with the
item, its empty field and the titles around it, and lets it call tools over the same snapshot (similar items,
siblings, parents, children, search by words) until it has enough evidence or runs out of steps. Rules, answer
format and confidence modes are the same as LLMSuggester's, so the two differ only in who chooses the evidence:
the Phase 4 comparison.

The tools are declared natively (OpenAI "tools"), which gpt-oss is trained for, and native tool_calls are read
directly. An endpoint that rejects "tools" (no tool parser) gets the same tools as a plain JSON protocol in the
prompt ({"tool": ..., "args": ...}). In evidence mode a source only counts if the agent looked at that item's values.
"""
import json
import re

import requests

from .gaps import Gap
from .llm import EVIDENCE_PROMPT, SYSTEM_PROMPT, LLMSettings, LLMSuggester, parse_answer, shown_for
from .snapshot import Snapshot
from .suggest import Proposal

MAX_STEPS = 6  # tool calls per gap; then the model must answer
MAX_FOUND = 20  # items per find_items result
MAX_LISTED = 300  # titles per list_items result
MAX_SIMILAR = 10  # items per find_similar result
# v1 (29 Oct 2026): start with the item only; four tools. v2: the start shows the item's own record (parents and
# children titles), get_siblings and list_items are added, and native tool calls are read.
# v3: tools are declared natively (v2's failures were empty answers: the native call had nowhere to go) and
# find_similar is added (v2's wrong descriptions missed the same-family item whose wording they should follow).
# v2 and v3 were shaped on dataset.json traces. Every version stays in the comparison under its own label.
VERSION = 3

_TITLE = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}
_TEXT = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
TOOL_SCHEMAS = [
    {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}
    for name, description, parameters in [
        ("find_similar", "items whose titles share the most words with the title (same family, other sizes or variants)", _TITLE),
        ("get_siblings", "the other parts in the assemblies that use the item, with their known values", _TITLE),
        ("get_item", "an item's known values, the assemblies that use it and its children", _TITLE),
        ("get_parents", "the assemblies that use the item, with their known values", _TITLE),
        ("get_children", "the item's children, with their known values", _TITLE),
        ("find_items", f"items whose title or description contains every word of text (at most {MAX_FOUND})", _TEXT),
        ("list_items", "the titles of all items in the project, to see what exists before you name an item",
         {"type": "object", "properties": {}}),
    ]
]
TOOL_NAMES = {schema["function"]["name"] for schema in TOOL_SCHEMAS}

AGENT_INTRO = """\
You fill in missing attributes of Engineering Items in a PLM system (3DEXPERIENCE).
You get one item with an empty field, the assemblies that use it and its children. Gather evidence from the
product structure with tools before you answer.

Tools (one call per turn):
{tools}

Call a tool through function calling, or answer with only a JSON object such as
{"tool": "get_siblings", "args": {"title": "<title>"}}. You have at most {max_steps} tool calls.
Similar items (same family, other sizes or variants) and the other parts in the same assemblies are usually
the best evidence: follow the wording of the most similar item exactly. Only cite items you have looked at.
When you have enough evidence, or there is none to find, give your final answer.

"""


def agent_prompt(confidence: str, max_steps: int) -> str:
    """The tool list (from TOOL_SCHEMAS), then the fixed-context prompt's rules and answer format."""
    tools = "\n".join(
        f"- {f['name']}({', '.join(f['parameters']['properties'])}): {f['description']}"
        for f in (schema["function"] for schema in TOOL_SCHEMAS)
    )
    rules = (EVIDENCE_PROMPT if confidence == "evidence" else SYSTEM_PROMPT).split("Rules:", 1)[1]
    intro = AGENT_INTRO.replace("{tools}", tools).replace("{max_steps}", str(max_steps))
    return intro + "Rules:" + rules.replace("Answer with only a JSON object", "Final answer: only a JSON object")


def title_words(title: str) -> set[str]:
    """API_NUT_M8_ISO4032 -> {api, nut, m8, iso4032}; SWC-Gasket-jet sprinkler -> {swc, gasket, jet, sprinkler}."""
    return {w for w in re.split(r"[^0-9a-z]+", title.lower()) if w}


class SnapshotTools:
    """The agent's view of the snapshot. Records which items' values it was shown (`seen`)."""

    def __init__(self, snapshot: Snapshot, gap: Gap):
        self.snapshot = snapshot
        self.show = shown_for(gap)
        self.by_title = {item.get("title"): item_id for item_id, item in snapshot.items.items() if item.get("title")}
        self.words = {title: title_words(title) for title in self.by_title}
        # Words in every title (a project prefix such as "api") say nothing about similarity
        self.common = set.intersection(*self.words.values()) if self.words else set()
        self.seen: set[str] = set()

    def call(self, name: str, args: dict) -> dict | list:
        """Run one tool. Errors go back to the model as a result, so it can correct the call."""
        if name not in TOOL_NAMES:
            return {"error": f"unknown tool {name!r}, use one of {', '.join(sorted(TOOL_NAMES))}"}
        if "title" in args:
            if args["title"] not in self.by_title:
                return {"error": f"no item titled {args['title']!r}, call list_items to see the titles"}
            args = {**args, "title": self.by_title[args["title"]]}  # handlers take the item id
        try:
            return getattr(self, name)(**args)
        except TypeError:
            return {"error": f"wrong arguments for {name}: {args}"}

    def structure(self, item_id: str) -> dict:
        """Titles of the assemblies that use the item and of its children (no values: not counted as seen)."""
        return {
            "usedIn": [self._title(p) for p in self.snapshot.parents(item_id)],
            "children": [self._title(c) for c in self.snapshot.children(item_id)],
        }

    def _view(self, item_id: str) -> dict:
        item = self.snapshot.item(item_id)
        self.by_title.setdefault(item.get("title"), item_id)
        self.seen.add(item.get("title"))
        return self.show(item)

    def _title(self, item_id: str) -> str:
        return self.snapshot.item(item_id).get("title", item_id)

    def get_item(self, title: str) -> dict:
        return {**self._view(title), **self.structure(title)}

    def get_siblings(self, title: str) -> list:
        return [
            {"assembly": self._title(p), "otherParts": [self._view(s) for s in self.snapshot.children(p) if s != title]}
            for p in self.snapshot.parents(title)
        ]

    def get_parents(self, title: str) -> list:
        return [self._view(p) for p in self.snapshot.parents(title)]

    def get_children(self, title: str) -> list:
        return [self._view(c) for c in self.snapshot.children(title)]

    def find_similar(self, title: str) -> list:
        """Ranked by shared title words (Jaccard), only items sharing a word that not every title has."""
        target = self.snapshot.item(title).get("title", "")
        words = self.words.get(target) or title_words(target)
        ranked = sorted(
            (-len(words & other_words) / len(words | other_words), other)
            for other, other_words in self.words.items()
            if other != target and (words & other_words) - self.common
        )
        return [self._view(self.by_title[other]) for _, other in ranked[:MAX_SIMILAR]]

    def find_items(self, text: str) -> list:
        words = str(text).lower().split()
        if not words:
            return []
        found = [
            item_id for item_id, item in self.snapshot.items.items()
            if all(w in f"{item.get('title', '')} {item.get('description', '')}".lower() for w in words)
        ]
        return [self._view(i) for i in found[:MAX_FOUND]]

    def list_items(self) -> list:
        """Titles only: shows what exists without counting as having looked at the items' values."""
        return sorted(self.by_title)[:MAX_LISTED]


class AgenticSuggester(LLMSuggester):
    name = "agent"

    def __init__(self, settings: LLMSettings, *, confidence: str = "self", max_steps: int = MAX_STEPS, **kwargs):
        super().__init__(settings, confidence=confidence, **kwargs)
        self.max_steps = max_steps
        self.prompt = agent_prompt(confidence, max_steps)
        self.native_tools = True  # set to False for the rest of the run if the endpoint rejects "tools"
        self.method = self.method.replace("llm:", f"agent-v{VERSION}:", 1)

    def suggest(self, gap: Gap, snapshot: Snapshot) -> Proposal | None:
        tools = SnapshotTools(snapshot, gap)
        start = {"item": tools.show(snapshot.item(gap.item_id)), "missingField": gap.field, **tools.structure(gap.item_id)}
        messages = [
            {"role": "system", "content": self.prompt},
            {"role": "user", "content": (
                f"Propose the {gap.field} of {gap.title!r}.\n\n" + json.dumps(start, indent=1, ensure_ascii=False)
            )},
        ]
        self.last_call = {"model": self.settings.model, "steps": []}
        try:
            for step in range(self.max_steps + 1):
                if step == self.max_steps:
                    messages.append({"role": "user", "content": "No more tool calls. Give your final answer now."})
                text, action = self._ask(messages, tools_allowed=step < self.max_steps)
                messages.append({"role": "assistant", "content": text})
                if action is None:
                    try:
                        action = parse_answer(text)
                    except ValueError:
                        self.last_call["unparsed"] = text[:500]  # in the run file, to see what the model sent instead
                        if self.last_call.get("retried"):
                            raise
                        self.last_call["retried"] = True  # one retry per gap, as in LLMSuggester
                        messages.append({"role": "user", "content": "That was not a valid JSON object. Answer with only the JSON object."})
                        continue
                if "tool" not in action or step == self.max_steps:
                    answer = action.get("answer", action)  # also accept {"answer": {...}}
                    return self._proposal(gap, snapshot, answer, tools.seen if self.confidence == "evidence" else None)
                args = action.get("args") if isinstance(action.get("args"), dict) else {}
                result = tools.call(str(action["tool"]), args)
                self.last_call["steps"].append({"tool": action["tool"], "args": args})
                messages.append({"role": "user", "content": "Result:\n" + json.dumps(result, indent=1, ensure_ascii=False)})
        except (requests.RequestException, ValueError, KeyError) as exc:
            self.last_call["error"] = f"{type(exc).__name__}: {exc}"
            return None
        self.last_call["error"] = "no final answer"  # the last turn was spent on a retry
        return None

    def _ask(self, messages: list[dict], *, tools_allowed: bool) -> tuple[str, dict | None]:
        """One model turn: its text for the history, and the tool call if it made one natively."""
        if tools_allowed and self.native_tools:
            try:
                message = self._message(messages, {"tools": TOOL_SCHEMAS, "tool_choice": "auto"})
            except requests.HTTPError as exc:
                if exc.response is None or exc.response.status_code != 400:
                    raise
                self.native_tools = False  # no tool parser on this endpoint: the JSON protocol in the prompt only
                self.last_call["native_tools"] = f"rejected: {exc}"
            else:
                content = message.get("content") or ""
                if content.strip() or not message.get("tool_calls"):
                    return content, None
                function = message["tool_calls"][0].get("function") or {}
                try:
                    args = json.loads(function.get("arguments") or "{}")
                except ValueError:
                    args = {"unreadable_arguments": function.get("arguments")}  # the model sees the error and retries
                action = {"tool": function.get("name", "").removeprefix("functions."), "args": args}
                return json.dumps(action), action
        return self._chat(messages), None
