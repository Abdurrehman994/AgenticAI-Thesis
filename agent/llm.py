"""LLM suggester for any OpenAI-compatible chat endpoint (Lehmus AI / vLLM, Ollama, commercial APIs).

The model gets the same evidence the rules use (the item, its parents and siblings, its children and the
other items in the collab space) in one request and answers with JSON. No tools: one call per gap keeps
runs comparable with the rules and cheap to repeat. Configuration comes from .env (see .env.example).
"""
import json
import os
import re
import time
from dataclasses import dataclass, field

import requests
from dotenv import load_dotenv

from .gaps import PROPOSED_PREFIX, Gap
from .snapshot import Snapshot, field_value, part_number
from .suggest import Proposal

SYSTEM_PROMPT = """\
You fill in missing attributes of Engineering Items in a PLM system (3DEXPERIENCE).
You get one item with an empty field, and context from the same product structure: the assemblies that use
the item, the other parts in those assemblies, the item's own children and other items in the same project.

Rules:
- Propose a value only when the context supports it. If it does not, answer with "value": null.
- Follow the conventions of the existing data: wording, abbreviations, units, language and numbering scheme.
- A part number is an identifier: never reuse a part number that another item already has.
- Confidence is your probability (0 to 1) that an engineer would accept the value as it is.

Answer with only a JSON object, no other text:
{"value": "<value>" or null, "confidence": <0..1>, "evidence": ["<item or pattern you relied on>", ...]}"""

FIELD_NAMES = {"description": "description", "partNumber": "part number"}


@dataclass
class LLMSettings:
    base_url: str  # e.g. https://<lehmus host>/v1 or http://localhost:11434/v1 (Ollama)
    model: str  # the model id the endpoint expects (for Lehmus: the "public model id")
    api_key: str = field(default="", repr=False)
    label: str = ""  # readable name for reports, e.g. gpt-oss-120b; defaults to the model id
    temperature: float = 0.0
    timeout: float = 120.0

    @classmethod
    def from_env(cls, model: str | None = None) -> "LLMSettings":
        """`model` overrides LLM_MODEL; LLM_LABEL then no longer applies, so reports show the model id."""
        load_dotenv()
        base_url = os.getenv("LLM_BASE_URL")
        if not base_url or not (model or os.getenv("LLM_MODEL")):
            raise RuntimeError("Set LLM_BASE_URL and LLM_MODEL in .env (see .env.example)")
        return cls(
            base_url=base_url.rstrip("/"),
            model=model or os.environ["LLM_MODEL"],
            api_key=os.getenv("LLM_API_KEY", ""),
            label="" if model else os.getenv("LLM_LABEL", ""),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
            timeout=float(os.getenv("LLM_TIMEOUT", "120")),
        )


def _shown(item: dict) -> dict:
    """Title and known values of an item. Unreviewed [PROPOSED] descriptions are not evidence."""
    description = field_value(item, "description")
    shown = {"title": item.get("title", "")}
    if description and not description.startswith(PROPOSED_PREFIX):
        shown["description"] = description
    if part_number(item):
        shown["partNumber"] = part_number(item)
    return shown


def build_context(gap: Gap, snapshot: Snapshot, max_items: int = 80) -> dict:
    target = snapshot.item(gap.item_id)
    listed = {gap.item_id}
    parents = []
    for parent_id in snapshot.parents(gap.item_id):
        siblings = [sid for sid in snapshot.children(parent_id) if sid != gap.item_id]
        parents.append({**_shown(snapshot.item(parent_id)), "otherParts": [_shown(snapshot.item(s)) for s in siblings]})
        listed.update([parent_id, *siblings])
    children = snapshot.children(gap.item_id)
    listed.update(children)
    others = [_shown(i) for iid, i in snapshot.items.items() if iid not in listed][:max_items]
    return {
        "item": _shown(target),
        "missingField": gap.field,
        "usedIn": parents,
        "children": [_shown(snapshot.item(c)) for c in children],
        "otherItemsInProject": others,
    }


def parse_answer(text: str) -> dict:
    """The JSON object in the model's answer, also when it is wrapped in a code fence or prose."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON object in the answer")
    return json.loads(match.group(0))


class LLMSuggester:
    name = "llm"

    def __init__(self, settings: LLMSettings, *, session: requests.Session | None = None, retries: int = 2):
        self.settings = settings
        self.session = session or requests.Session()
        self.retries = retries
        self.method = f"llm:{settings.label or settings.model}"
        self.last_call: dict | None = None  # model, latency and tokens of the latest gap, for the run file

    def suggest(self, gap: Gap, snapshot: Snapshot) -> Proposal | None:
        context = build_context(gap, snapshot)
        prompt = (
            f"Propose the {FIELD_NAMES.get(gap.field, gap.field)} of {gap.title!r}.\n\n"
            + json.dumps(context, indent=1, ensure_ascii=False)
        )
        self.last_call = {"model": self.settings.model}
        try:
            text = self._chat(prompt)
            answer = parse_answer(text)
        except (requests.RequestException, ValueError, KeyError) as exc:
            self.last_call["error"] = f"{type(exc).__name__}: {exc}"
            return None
        return self._proposal(gap, snapshot, answer)

    def _proposal(self, gap: Gap, snapshot: Snapshot, answer: dict) -> Proposal | None:
        value = answer.get("value")
        if not isinstance(value, str) or not value.strip():
            return None
        value = value.strip().removeprefix(PROPOSED_PREFIX).strip()
        if gap.field == "partNumber" and value in {part_number(i) for i in snapshot.items.values()}:
            self.last_call["rejected"] = f"part number {value} is already used"
            return None
        try:
            confidence = min(max(float(answer.get("confidence", 0)), 0.0), 1.0)
        except (TypeError, ValueError):
            confidence = 0.0
        evidence = answer.get("evidence") or []
        evidence = [str(e) for e in evidence] if isinstance(evidence, list) else [str(evidence)]
        return Proposal(gap.item_id, gap.title, gap.field, value, confidence, self.method, evidence)

    def _chat(self, prompt: str) -> str:
        s = self.settings
        headers = {"Authorization": f"Bearer {s.api_key}"} if s.api_key else {}
        body = {
            "model": s.model,
            "temperature": s.temperature,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
        }
        started = time.monotonic()
        for attempt in range(self.retries + 1):
            try:
                response = self.session.post(f"{s.base_url}/chat/completions", json=body, headers=headers, timeout=s.timeout)
                if response.status_code != 429 and response.status_code < 500:
                    break
            except requests.ConnectionError:
                if attempt == self.retries:
                    raise
            if attempt < self.retries:
                time.sleep(2**attempt)
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage") or {}
        self.last_call.update(
            latency_s=round(time.monotonic() - started, 2),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
        # Reasoning models (gpt-oss) return their reasoning separately; only the final answer is parsed
        return data["choices"][0]["message"].get("content") or ""
