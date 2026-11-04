"""Duplicate detection: is this part already in PLM under another title or part number?

Plain code and read-only, like the readiness check. Two items are compared on the words of their titles and
descriptions, each word weighted by how rare it is in the collab space (idf: a word every item has, such as a
project prefix, counts for nothing). Rules on top of the score:
- spec words (with a digit: M8, 6204, 22mm, 1+1/4, iso4032) must agree: when each item has a spec the other
  lacks (an M6 and an M8 nut), they are variants of one family, not duplicates. Specs come from the
  description when there is one, since titles are often file names or automatic numbers;
- a different material (when both are known) rules a pair out;
- parts are compared with parts and assemblies with assemblies; two assemblies with the same children are
  duplicates whatever they are called.
A description still marked [PROPOSED] is ignored: an AI value nobody approved is not evidence.

Two uses:
- `find_duplicates(snapshot)`: every candidate pair in the collab space (data clean-up);
- `find_existing(snapshot, title, description)`: before a new item is created, the existing items it may
  duplicate (part reuse).
Two items with the same part number are reported by the readiness check (agent/readiness.py).

`plant` builds the evaluation data: a dataset with known duplicates added, so recall and precision can be
measured the same way as the suggesters' accuracy.
"""
import copy
import math
import random
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass

from .gaps import MATERIAL, PROPOSED_PREFIX
from .snapshot import Snapshot, field_value

MIN_SCORE = 0.5
MAX_REASON_WORDS = 6
_MIXED_FRACTION = re.compile(r"(\d+)\s+(\d+/\d+)")  # 1 1/4" -> 1+1/4, so it stays apart from 1"
_UNIT = re.compile(r"(\d)\s+(mm|cm|m|kw|w|v|kg|g)\b", re.IGNORECASE)  # 22 mm -> 22mm
_WORD = re.compile(r"\d+(?:[./+]\d+)+|[0-9a-z]+")


def words(text: str) -> set[str]:
    """'Hex nut M8 ISO 4032, zinc plated' -> {hex, nut, m8, iso, 4032, zinc, plated}; 1 1/4" -> {1+1/4}."""
    text = _UNIT.sub(r"\1\2", _MIXED_FRACTION.sub(r"\1+\2", text))
    return set(_WORD.findall(text.lower()))


def specs(word_set: set[str]) -> set[str]:
    return {w for w in word_set if any(c.isdigit() for c in w)}


def description_of(item: dict) -> str:
    description = field_value(item, "description")
    return "" if description.startswith(PROPOSED_PREFIX) else description


@dataclass
class Profile:
    """What an item is compared on."""
    words: set[str]
    description_words: set[str]
    specs: set[str]
    material: str
    children: frozenset[str]


@dataclass
class Candidate:
    item_id: str
    title: str
    other_id: str
    other_title: str
    score: float
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def profile(title: str, description: str, material: str = "", children=()) -> Profile:
    description_words = words(description)
    all_words = words(title) | description_words
    return Profile(all_words, description_words, specs(description_words or all_words), material.strip().lower(),
                   frozenset(children))


class Index:
    """Profiles and word weights of every item in a snapshot."""

    def __init__(self, snapshot: Snapshot):
        self.snapshot = snapshot
        self.profiles = {
            item_id: profile(item.get("title", ""), description_of(item), field_value(item, MATERIAL),
                             snapshot.children(item_id))
            for item_id, item in snapshot.items.items()
        }
        self.n = len(self.profiles)
        df = Counter(w for p in self.profiles.values() for w in p.words)
        self.idf = {w: math.log(self.n / c) for w, c in df.items()}  # a word in every item weighs 0
        self.postings = defaultdict(set)  # word -> items, to compare only pairs sharing a word that weighs
        for item_id, p in self.profiles.items():
            for w in p.words:
                if self.idf[w] > 0:
                    self.postings[w].add(item_id)

    def weight(self, word: str) -> float:
        return self.idf.get(word, math.log(self.n + 1))  # a word no item has is as rare as it gets

    def similarity(self, a: set[str], b: set[str]) -> float:
        """Weighted Jaccard: the weight of the shared words over the weight of all words."""
        union = sum(self.weight(w) for w in a | b)
        return sum(self.weight(w) for w in a & b) / union if union else 0.0

    def title(self, item_id: str) -> str:
        return self.snapshot.item(item_id).get("title", item_id)

    def compare(self, a: Profile, b: Profile, *, same_kind: bool = True) -> tuple[float, list[str]] | None:
        """(score, reasons), or None when a rule says the two cannot be the same item."""
        if same_kind and bool(a.children) != bool(b.children):
            return None
        if a.specs - b.specs and b.specs - a.specs:
            return None  # variants: each has a spec the other lacks
        if a.material and b.material and a.material != b.material:
            return None

        text = self.similarity(a.words, b.words)
        if a.description_words and b.description_words:  # a new title (file name, number) should not hide it
            text = max(text, self.similarity(a.description_words, b.description_words))
        structure = len(a.children & b.children) / len(a.children | b.children) if a.children and b.children else 0.0

        reasons = []
        shared = sorted(a.words & b.words, key=lambda w: (-self.weight(w), w))
        shared = [w for w in shared if self.weight(w) > 0][:MAX_REASON_WORDS]
        if shared:
            reasons.append(f"shared words: {', '.join(shared)}")
        if structure:
            reasons.append(f"same children: {len(a.children & b.children)} of {len(a.children | b.children)}")
        if a.material and a.material == b.material:
            reasons.append(f"same material: {a.material}")
        if a.specs & b.specs:
            reasons.append(f"same specs: {', '.join(sorted(a.specs & b.specs))}")
        return max(text, structure), reasons


def find_duplicates(snapshot: Snapshot, *, min_score: float = MIN_SCORE, index: Index | None = None) -> list[Candidate]:
    """Every pair of items that may be the same item, highest score first."""
    index = index or Index(snapshot)
    pairs = set()
    for item_id, p in index.profiles.items():
        for w in p.words:
            pairs.update((item_id, other) for other in index.postings.get(w, ()) if item_id < other)
    by_child = defaultdict(set)
    for item_id, p in index.profiles.items():
        for child in p.children:
            by_child[child].add(item_id)
    for parents in by_child.values():
        pairs.update((a, b) for a in parents for b in parents if a < b)

    found = []
    for a, b in pairs:
        result = index.compare(index.profiles[a], index.profiles[b])
        if result and result[0] >= min_score:
            found.append(Candidate(a, index.title(a), b, index.title(b), round(result[0], 3), result[1]))
    found.sort(key=lambda c: (-c.score, c.title, c.other_title))
    return found


def find_existing(snapshot: Snapshot, title: str = "", description: str = "", material: str = "", *,
                  min_score: float = MIN_SCORE, limit: int = 10, index: Index | None = None) -> list[Candidate]:
    """Existing items a new item (not yet in PLM) may duplicate, highest score first."""
    index = index or Index(snapshot)
    new = profile(title, description, material)
    found = []
    for item_id, p in index.profiles.items():
        result = index.compare(new, p, same_kind=False)  # the new item's children are not known yet
        if result and result[0] >= min_score:
            found.append(Candidate("", title or description, item_id, index.title(item_id), round(result[0], 3), result[1]))
    found.sort(key=lambda c: (-c.score, c.other_title))
    return found[:limit]


def render(candidates: list[Candidate], *, header: str) -> str:
    lines = [header]
    for c in candidates:
        left = f"{c.title}  <->  " if c.item_id else ""
        lines.append(f"  {c.score:.2f}  {left}{c.other_title}")
        lines.extend(f"        - {reason}" for reason in c.reasons)
    return "\n".join(lines)


def restyle(title: str) -> str:
    """API_NUT_M8_ISO4032 -> 'Nut m8 iso4032': the same words in another naming style, project prefix dropped."""
    parts = [p for p in re.split(r"[^0-9A-Za-z]+", title) if p]
    if len(parts) > 1 and parts[0].isupper() and len(parts[0]) <= 4:
        parts = parts[1:]
    return " ".join(parts).capitalize()


def plant(dataset: dict, n: int, seed: int = 2026) -> tuple[dict, list[tuple[str, str]]]:
    """A copy of the dataset with n parts created a second time: (dataset, [(copy title, original title)]).

    Simulates a designer who did not find the existing part. The copy has no part number and no place in a BOM;
    its description is lowercased with its last comma-separated detail left out ("Hex nut M8 ISO 4032, zinc
    plated" -> "hex nut m8 iso 4032"). Every second copy keeps the original's words in another naming style,
    the others get a title that says nothing (NEW PART A), so only the description can match.
    Only parts whose description is visible in the tenant (not blanked) are copied.
    """
    planted = copy.deepcopy(dataset)
    titles = {entry["title"] for entry in dataset["items"]}
    parts = [
        e for e in dataset["items"]
        if not e.get("children") and e.get("description") and "description" not in e.get("blank", [])
    ]
    rng = random.Random(seed)
    pairs = []
    for k, entry in enumerate(rng.sample(parts, min(n, len(parts)))):
        details = [d.strip() for d in entry["description"].split(",")]
        description = ", ".join(details[:-1] if len(details) > 1 else details).lower()
        title = restyle(entry["title"]) if k % 2 == 0 else f"NEW PART {chr(ord('A') + k // 2)}"
        while title in titles:
            title += " (2)"
        titles.add(title)
        copy_entry = {"title": title, "description": description}
        if entry.get(MATERIAL) and MATERIAL not in entry.get("blank", []):
            copy_entry[MATERIAL] = entry[MATERIAL]
        planted["items"].append(copy_entry)
        pairs.append((title, entry["title"]))
    return planted, pairs


def score_planted(candidates: list[Candidate], pairs: list[tuple[str, str]], thresholds) -> list[dict]:
    """Recall (planted pairs found) and precision (found pairs that were planted) at each threshold."""
    truth = {frozenset(p) for p in pairs}
    rows = []
    for t in thresholds:
        found = {frozenset((c.title, c.other_title)) for c in candidates if c.score >= t}
        hits = len(found & truth)
        rows.append({
            "threshold": t,
            "found": len(found),
            "planted_found": hits,
            "recall": hits / len(truth) if truth else 0.0,
            "precision": hits / len(found) if found else 1.0,
        })
    return rows
