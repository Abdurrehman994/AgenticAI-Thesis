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

# Evidence-based confidence: the model names the kind of evidence and the items it used; the code checks the items
# and maps the kind to a fixed confidence on the rules' scale (analogy 0.8, sibling numbers 0.7, title expansion 0.3).
# The values were fixed before any run, not fitted, so the held-out set stays held out.
BASIS_CONFIDENCE = {"copied": 0.8, "pattern": 0.7, "inferred": 0.3, "guess": 0.1}
NEEDS_SOURCES = {"copied", "pattern"}

EVIDENCE_PROMPT = """\
You fill in missing attributes of Engineering Items in a PLM system (3DEXPERIENCE).
You get one item with an empty field, and context from the same product structure: the assemblies that use
the item, the other parts in those assemblies, the item's own children and other items in the same project.

Rules:
- Propose a value only when the context supports it. If it does not, answer with "value": null.
- Follow the conventions of the existing data: wording, abbreviations, units, language and numbering scheme.
- A part number is an identifier: never reuse a part number that another item already has.
- Do not add facts (materials, finishes, ratings) that no item in the context states.

Say what kind of evidence the value rests on, as "basis":
- "copied": adapted from one near-identical item whose title differs only in a size or variant
- "pattern": follows a pattern that several related items share, such as a gap in a numbering sequence
- "inferred": reasoned from the item's title or role, with no item to copy from
- "guess": anything weaker
List in "sources" the exact titles of the items the value is copied from or whose pattern it follows.

Answer with only a JSON object, no other text:
{"value": "<value>" or null, "basis": "copied" | "pattern" | "inferred" | "guess", "sources": ["<title>", ...],
 "evidence": ["<short reason>", ...]}"""

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

    def __init__(
        self, settings: LLMSettings, *, confidence: str = "self", session: requests.Session | None = None, retries: int = 2
    ):
        """confidence="self": the model's own probability; "evidence": mapped from the evidence it names."""
        if confidence not in ("self", "evidence"):
            raise ValueError(f"confidence must be 'self' or 'evidence', not {confidence!r}")
        self.settings = settings
        self.confidence = confidence
        self.session = session or requests.Session()
        self.retries = retries
        self.method = f"llm:{settings.label or settings.model}" + ("+evidence" if confidence == "evidence" else "")
        self.last_call: dict | None = None  # model, latency and tokens of the latest gap, for the run file

    def suggest(self, gap: Gap, snapshot: Snapshot) -> Proposal | None:
        context = build_context(gap, snapshot)
        messages = [
            {"role": "system", "content": EVIDENCE_PROMPT if self.confidence == "evidence" else SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"Propose the {FIELD_NAMES.get(gap.field, gap.field)} of {gap.title!r}.\n\n"
                + json.dumps(context, indent=1, ensure_ascii=False)
            )},
        ]
        self.last_call = {"model": self.settings.model}
        try:
            text = self._chat(messages)
            try:
                answer = parse_answer(text)
            except ValueError:  # one retry: show the model its answer and ask for the JSON only
                self.last_call["retried"] = True
                messages += [
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": "That was not a valid JSON object. Answer with only the JSON object."},
                ]
                answer = parse_answer(self._chat(messages))
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
        evidence = answer.get("evidence") or []
        evidence = [str(e) for e in evidence] if isinstance(evidence, list) else [str(evidence)]
        if self.confidence == "evidence":
            confidence, grounds = self._evidence_confidence(gap, snapshot, answer)
            evidence = grounds + evidence
        else:
            try:
                confidence = min(max(float(answer.get("confidence", 0)), 0.0), 1.0)
            except (TypeError, ValueError):
                confidence = 0.0
        return Proposal(gap.item_id, gap.title, gap.field, value, confidence, self.method, evidence)

    def _evidence_confidence(self, gap: Gap, snapshot: Snapshot, answer: dict) -> tuple[float, list[str]]:
        """Confidence from the stated basis. Copied or pattern needs at least one named source that exists."""
        stated = str(answer.get("basis", "")).strip().lower()
        basis = stated if stated in BASIS_CONFIDENCE else "guess"
        sources = answer.get("sources") or []
        sources = [str(s) for s in sources] if isinstance(sources, list) else [str(sources)]
        titles = {i.get("title") for i in snapshot.items.values()} - {gap.title}
        found = [s for s in sources if s in titles]
        if basis in NEEDS_SOURCES and not found:
            basis = "inferred"  # claims a source it does not name, or names items that do not exist
        self.last_call.update(basis=basis, stated_basis=stated, sources=sources, sources_found=found)
        grounds = [f"basis: {basis}" + (f" (stated {stated!r})" if basis != stated else "")]
        grounds += [f"source: {s}" for s in found]
        return BASIS_CONFIDENCE[basis], grounds

    def _chat(self, messages: list[dict]) -> str:
        s = self.settings
        headers = {"Authorization": f"Bearer {s.api_key}"} if s.api_key else {}
        body = {"model": s.model, "temperature": s.temperature, "messages": messages}
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
        call = self.last_call  # a retry adds to the first request's latency and tokens
        call["latency_s"] = round(call.get("latency_s", 0) + time.monotonic() - started, 2)
        for name in ("prompt_tokens", "completion_tokens"):
            if usage.get(name) is not None:
                call[name] = (call.get(name) or 0) + usage[name]
        # Reasoning models (gpt-oss) return their reasoning separately; only the final answer is parsed
        return data["choices"][0]["message"].get("content") or ""
