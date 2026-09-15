"""Suggesters turn a gap plus evidence from the snapshot into a proposal.

RuleBasedSuggester needs no AI and is the Phase 4 baseline. An LLM suggester goes behind the
same interface later, so run_agent.py and the review flow do not change when it is added.
"""
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol

from .gaps import PROPOSED_PREFIX, Gap
from .snapshot import Snapshot, part_number


@dataclass
class Proposal:
    item_id: str
    title: str
    field: str
    value: str
    confidence: float  # 0..1, the suggester's own estimate; reviewers and Phase 4 decide if it is calibrated
    method: str
    evidence: list[str] = field(default_factory=list)


class Suggester(Protocol):
    name: str

    def suggest(self, gap: Gap, snapshot: Snapshot) -> Proposal | None: ...


class ClaudeSuggester:
    """Slot for the LLM suggester (needs an Anthropic API key).

    Plan: give the model the gap and the same evidence the rules use (similar items, parents,
    siblings, children), let it call the read-only Engineering methods as tools, and return a
    Proposal with method="llm:<model id>" and the evidence it relied on.
    """

    name = "claude"

    def __init__(self, *args, **kwargs):
        raise NotImplementedError("LLM suggester not implemented yet: use RuleBasedSuggester")


TITLE_PREFIXES = ("API",)  # naming prefixes that carry no meaning about the part
ABBREVIATIONS = {"ASM": "assembly", "AL": "aluminium", "SS": "stainless steel", "S235": "S235 steel"}
_PART_NUMBER = re.compile(r"^(.*?)(\d+)$")


def title_tokens(title: str) -> list[str]:
    tokens = [t for t in title.upper().split("_") if t]
    while tokens and tokens[0] in TITLE_PREFIXES:
        tokens.pop(0)
    return tokens


def match_case(old: str, new: str) -> str:
    """Write `new` in the casing `old` had in the text: DRIVE/Drive/drive, M8x25 -> M6x16."""
    if old.islower():
        return new.lower()
    if old.isupper():
        return new.upper()
    if len(old) == len(new):
        return "".join(n.lower() if o.islower() else n.upper() for o, n in zip(old, new))
    return new.capitalize()


def replace_token(text: str, old: str, new: str) -> tuple[str, int]:
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(old)}(?![A-Za-z0-9])", re.IGNORECASE)
    return pattern.subn(lambda m: match_case(m.group(0), new), text)


class RuleBasedSuggester:
    name = "rules"

    def suggest(self, gap: Gap, snapshot: Snapshot) -> Proposal | None:
        if gap.field == "description":
            return self._description_by_analogy(gap, snapshot) or self._description_from_title(gap)
        if gap.field == "partNumber":
            return self._part_number_from_siblings(gap, snapshot)
        return None

    def _description_by_analogy(self, gap: Gap, snapshot: Snapshot) -> Proposal | None:
        """Copy the description of a same-family item whose title differs only in variant tokens.

        API_NUT_M8_ISO4032 "Hex nut M8 ISO 4032" -> API_NUT_M6_ISO4032 "Hex nut M6 ISO 4032".
        Two differing tokens are allowed only when both are dimensions/specs (contain a digit).
        """
        target = title_tokens(gap.title)
        best = None
        for other in snapshot.items.values():
            description = other.get("description") or ""
            if other["id"] == gap.item_id or not description or description.startswith(PROPOSED_PREFIX):
                continue
            source = title_tokens(other.get("title", ""))
            if len(source) != len(target) or not target or source[0] != target[0]:
                continue
            diffs = [(s, t) for s, t in zip(source, target) if s != t]
            specs = all(any(c.isdigit() for c in s + t) for s, t in diffs)
            if not diffs or len(diffs) > 2 or (len(diffs) == 2 and not specs):
                continue

            value = description
            for old, new in diffs:
                value, count = replace_token(value, old, new)
                if not count:  # the description does not mention what differs, so it may not apply
                    break
            else:
                confidence = 0.7 if len(diffs) == 2 else 0.8 if specs else 0.6
                if best is None or confidence > best.confidence:
                    changes = ", ".join(f"{s}->{t}" for s, t in diffs)
                    best = Proposal(
                        gap.item_id, gap.title, gap.field, value, confidence, "description-analogy",
                        [f"{other.get('title')} has description {description!r}", f"titles differ only in {changes}"],
                    )
        return best

    def _description_from_title(self, gap: Gap) -> Proposal | None:
        tokens = title_tokens(gap.title)
        if not tokens:
            return None
        words = [ABBREVIATIONS.get(t) or (t if any(c.isdigit() for c in t) else t.lower()) for t in tokens]
        if words[0] == "assembly":
            words = words[1:] + ["assembly"]
        text = " ".join(words)
        return Proposal(
            gap.item_id, gap.title, gap.field, text[:1].upper() + text[1:], 0.3, "title-expansion",
            [f"no similar item with a description; expanded the title {gap.title!r}"],
        )

    def _part_number_from_siblings(self, gap: Gap, snapshot: Snapshot) -> Proposal | None:
        """Fill the one number missing from the siblings' sequence: GRD-3001, GRD-3003, GRD-3004 -> GRD-3002.

        BOM order is not used: the tenant returns instances in no particular order. When more than
        one sibling is unnumbered, nothing tells which number belongs to which part, so no proposal.
        """
        used = {part_number(i) for i in snapshot.items.values()} - {""}
        for parent_id in snapshot.parents(gap.item_id):
            siblings = snapshot.children(parent_id)
            unnumbered = [sid for sid in siblings if not part_number(snapshot.item(sid))]
            if unnumbered != [gap.item_id]:
                continue
            matches = [m for m in (_PART_NUMBER.match(part_number(snapshot.item(sid))) for sid in siblings) if m]
            if not matches:
                continue
            # Siblings numbered in another family (a shared standard part) say nothing about this sequence
            prefix = Counter(m.group(1) for m in matches).most_common(1)[0][0]
            family = [m for m in matches if m.group(1) == prefix]
            numbers = sorted(int(m.group(2)) for m in family)
            width = max(len(m.group(2)) for m in family)

            missing = [n for n in range(numbers[0] + 1, numbers[-1]) if n not in numbers]
            if len(missing) == 1:
                number, confidence, reason = missing[0], 0.7, "the only number missing from the sequence"
            elif not missing:
                number, confidence, reason = numbers[-1] + 1, 0.4, "no gap in the sequence; next after the highest"
            else:
                continue
            value = f"{prefix}{number:0{width}d}"
            if value in used:
                continue
            listing = ", ".join(f"{prefix}{n:0{width}d}" for n in numbers)
            parent_title = snapshot.item(parent_id).get("title", parent_id)
            return Proposal(
                gap.item_id, gap.title, gap.field, value, confidence, "sibling-numbers",
                [f"other parts under {parent_title}: {listing}", reason],
            )
        return None
