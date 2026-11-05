"""Check a model's claim that it copied a value. Plain code: a confidence can then rest on what the code verified
instead of on what the model says.

The evidence mode asks the model for its basis; "copied" means taken from a near-identical item, and is mapped to
the highest confidence. On dataset.json most such answers are not literal copies but adaptations (the M8 nut's
description with M8 changed to M6), so the check accepts two forms:
- literal copy: the value equals a source item's value (ignoring case and punctuation);
- variant swap: the value equals a source item's value after replacing the title tokens in which the two items
  differ (at most MAX_SWAPS, each of which the source value must mention), as RuleBasedSuggester's
  description-analogy does. Titles are split on any non-alphanumeric character, so CAD titles such as
  "SWC-Upper Washer sprinkler" work as well as API_NUT_M8_ISO4032.
Anything else is unverified: the model may still be right, but its claim is not what the code can confirm.
"""
import re
from collections import Counter
from collections.abc import Iterable

from .gaps import PROPOSED_PREFIX
from .snapshot import field_value
from .suggest import replace_token

LITERAL, SWAPPED, UNVERIFIED = "literal copy", "variant swap", "unverified"
MAX_SWAPS = 2

# Part numbers claimed as following a "pattern"
ONLY_HOLE = "only hole in the sequence"  # verified: the one number missing in its family
ONE_OF_HOLES = "one of several holes"  # fits the pattern, but nothing tells which hole is this part's
NEXT_NUMBER = "next after the highest"
NEW_VARIANT = "new variant of an existing family"  # 504-0804-00 next to 504-0702-00: not derivable
ALREADY_USED = "already used"
BREAKS_PATTERN = "breaks the pattern"
VERIFIED_NUMBERS = (ONLY_HOLE,)


def normalize(text: str) -> str:
    """Ignore case, punctuation and spacing (as scripts/evaluate.normalize)."""
    return " ".join(re.sub(r"[^\w]+", " ", text.lower()).split())


def title_tokens(title: str) -> list[str]:
    """'SWC-Upper Washer sprinkler' -> ['SWC', 'Upper', 'Washer', 'sprinkler']; API_NUT_M8 -> ['API', 'NUT', 'M8']."""
    return [t for t in re.split(r"[^0-9A-Za-z]+", title) if t]


def variant_swap(source_value: str, source_title: str, target_title: str) -> str | None:
    """The source's value with the tokens only its title has replaced by those only the target's title has, in
    order; None if the titles differ in no token, in more than MAX_SWAPS, or in a token the value does not mention."""
    source, target = title_tokens(source_title), title_tokens(target_title)
    source_lower, target_lower = {t.lower() for t in source}, {t.lower() for t in target}
    source_only = [t for t in source if t.lower() not in target_lower]
    target_only = [t for t in target if t.lower() not in source_lower]
    if not source_only or len(source_only) != len(target_only) or len(source_only) > MAX_SWAPS:
        return None
    value = source_value
    for old, new in zip(source_only, target_only):
        value, count = replace_token(value, old, new)
        if not count:
            return None
    return value


def verify_copy(value: str, target_title: str, field: str, sources: Iterable[dict]) -> tuple[str, str | None]:
    """(LITERAL, source title), (SWAPPED, source title) or (UNVERIFIED, None) for a value claimed as copied."""
    usable = [(s.get("title", ""), field_value(s, field)) for s in sources]
    usable = [(t, v) for t, v in usable if v and not v.startswith(PROPOSED_PREFIX)]  # unapproved AI values are no source
    wanted = normalize(value)
    for title, source_value in usable:
        if normalize(source_value) == wanted:
            return LITERAL, title
    for title, source_value in usable:
        swapped = variant_swap(source_value, title, target_title)
        if swapped is not None and normalize(swapped) == wanted:
            return SWAPPED, title
    return UNVERIFIED, None


def _parse(number: str) -> tuple[str, str, list[str]]:
    """'507-0702-00' -> ('999-9999-99', '--', ['507', '0702', '00']); 'GRD-3002' -> ('AAA-9999', 'GRD-', ['3002'])."""
    shape = re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", number))
    return shape, re.sub(r"\d+", "", number), re.findall(r"\d+", number)


def verify_pattern_number(value: str, existing: Iterable[str]) -> tuple[str, str]:
    """Is a part number claimed as following a pattern derivable from the numbers already in use?

    The numbers with the same shape and the same letters form the family (CNV-1000..1005; 501-0601-00..518-0601-00).
    The sequence is the numeric segment with the most distinct values (the only one in CNV-1003, the first in
    507-0702-00); the other segments must equal the family's most common ones. A number that fills the one hole
    in the sequence is verified; any other hole, the next number or a new variant of a used family only fits.
    """
    used = {n for n in existing if n}
    if value in used:
        return ALREADY_USED, value
    shape, letters, numbers = _parse(value)
    family = [p for p in (_parse(n) for n in used) if p[0] == shape and p[1] == letters]
    if not family or not numbers:
        return BREAKS_PATTERN, f"no number in use is shaped like {value}"
    segment = max(range(len(numbers)), key=lambda i: (len({p[2][i] for p in family}), -i))
    sequence = sorted({int(p[2][segment]) for p in family})
    rest = Counter(tuple(s for i, s in enumerate(p[2]) if i != segment) for p in family).most_common(1)[0][0]
    mine = int(numbers[segment])
    if mine in sequence:
        return NEW_VARIANT, f"{numbers[segment]} is already a family in use"
    if tuple(s for i, s in enumerate(numbers) if i != segment) != rest:
        return BREAKS_PATTERN, f"the other segments of {value} differ from the family's"
    holes = [n for n in range(sequence[0] + 1, sequence[-1]) if n not in sequence]
    if mine in holes:
        return (ONLY_HOLE, "the only missing number") if len(holes) == 1 else (ONE_OF_HOLES, f"one of {len(holes)} missing numbers")
    if mine == sequence[-1] + 1:
        return NEXT_NUMBER, "one after the highest in use"
    return BREAKS_PATTERN, f"{numbers[segment]} is outside the sequence {sequence[0]}-{sequence[-1]}"
