"""Building blocks shared by every rule module: the hit tuple and regex fragments."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import NamedTuple

from pii_guard.types import EntityType


class _Hit(NamedTuple):
    start: int
    end: int
    entity_type: EntityType
    score: float


#: A rule takes the whole text and yields validated hits.
Rule = Callable[[str], Iterator[_Hit]]

# A number must not continue a longer digit run, directly or through a date/decimal separator
# ("2026-10-26", "1.234.567"), or be followed by a currency (an amount, not an identifier).
NUM_START = r"(?<!\d)(?<!\d[-./,])"
NUM_END = r"(?!\d)(?![-./,]\d)"
NOT_AMOUNT = r"(?!\s?(?:Ft|HUF|forint|EUR|€)(?!\w))"
# Space-grouped numbers must not be part of a longer space-grouped number ("1 234 567 890").
NO_GROUP_BEFORE = r"(?<!\d )"
NO_GROUP_AFTER = r"(?! \d)"


def context_before(text: str, start: int, keywords: tuple[str, ...], window: int = 40) -> bool:
    """True if one of ``keywords`` (lowercase) appears in the ``window`` chars before ``start``."""
    before = text[max(0, start - window) : start].casefold()
    return any(k in before for k in keywords)
