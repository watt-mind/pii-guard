"""Entity-label mapping from the baseline tools to pii-guard's :class:`EntityType`.

All three baselines speak Presidio's label vocabulary (LLM Guard and PrivAiTe are built on
Presidio), plus a few labels of their own. One table covers them, so a label means the same
thing whichever tool emits it. The table and the reasoning are in ``docs/evaluation.md``.

Labels mapped to ``None`` (and labels missing from the table) are **unmapped**: they are
left out of precision/recall and over-masking, because pii-guard has no type to compare them
with, but the tool still masks them, so the leak rate sees exactly what the tool sent. The
scorecard counts them per label.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence

from pii_guard.detect.pipeline import resolve_spans
from pii_guard.types import EntityType, Span

__all__ = ["LABEL_MAP", "RawSpan", "map_label", "to_spans"]

#: ``(start, end, tool label, score)`` with offsets into the analysed text.
RawSpan = tuple[int, int, str, float]

_E = EntityType

LABEL_MAP: dict[str, EntityType | None] = {
    # People and contact details
    "PERSON": _E.PERSON,
    "EMAIL_ADDRESS": _E.EMAIL,
    "PHONE_NUMBER": _E.PHONE,
    # Places: Presidio's LOCATION covers cities, countries and street names; the closest
    # pii-guard type is ADDRESS (overlap matching credits a city inside an address).
    "LOCATION": _E.ADDRESS,
    # Dates: no tool tells a birth date from any other date. DATE_TIME is scored as
    # DATE_OF_BIRTH, so a tool gets recall for the birth dates it masks and a false
    # positive for every other date it masks.
    "DATE_TIME": _E.DATE_OF_BIRTH,
    # Money: payment cards are BANK_ACCOUNT in pii-guard's taxonomy (docs/entities.md).
    "IBAN_CODE": _E.BANK_ACCOUNT,
    "CREDIT_CARD": _E.BANK_ACCOUNT,
    "US_BANK_NUMBER": _E.BANK_ACCOUNT,
    "FINANCIAL": _E.BANK_ACCOUNT,  # PrivAiTe: the privacy-filter model's account_number
    # National identifiers without a type of their own are ID_DOCUMENT (docs/entities.md).
    "US_SSN": _E.ID_DOCUMENT,
    "US_ITIN": _E.ID_DOCUMENT,
    "US_PASSPORT": _E.ID_DOCUMENT,
    "US_DRIVER_LICENSE": _E.ID_DOCUMENT,
    "UK_NHS": _E.ID_DOCUMENT,
    "UK_NINO": _E.ID_DOCUMENT,
    "UK_PASSPORT": _E.ID_DOCUMENT,
    # Organisations
    "ORGANIZATION": _E.ORGANIZATION,
    "ORG": _E.ORGANIZATION,
    # No pii-guard counterpart: unmapped.
    "URL": None,
    "IP_ADDRESS": None,
    "MAC_ADDRESS": None,
    "CRYPTO": None,
    "UUID": None,
    "NRP": None,  # nationality, religious or political group
    "MEDICAL_LICENSE": None,
    "SECRET": None,  # PrivAiTe: credentials
    "CUSTOM": None,  # LLM Guard: user-supplied hidden names (none by default)
}


def map_label(label: str) -> EntityType | None:
    """The pii-guard type for a tool label, or ``None`` if it has none.

    LLM Guard's regex variants (``EMAIL_ADDRESS_RE``, ``CREDIT_CARD_RE``, ``US_SSN_RE``) map
    like the label without the suffix.
    """
    if label in LABEL_MAP:
        return LABEL_MAP[label]
    if label.endswith("_RE"):
        return LABEL_MAP.get(label[:-3])
    return None


def to_spans(
    text: str, raw: Iterable[Sequence[object]], detector: str
) -> tuple[list[Span], Counter[str]]:
    """Mapped, non-overlapping spans plus the per-label count of unmapped ones.

    Overlaps are resolved by pii-guard's own resolver (:func:`resolve_spans`, as in
    :class:`~pii_guard.detect.pipeline.DetectionPipeline`), with no detector treated as
    authoritative or adjudicating: same-type overlaps merge, otherwise ``keep`` types lose,
    then longer spans and higher scores win. LLM Guard and PrivAiTe already return
    non-overlapping spans; Presidio's analyzer does not.
    """
    spans: list[Span] = []
    unmapped: Counter[str] = Counter()
    for item in raw:
        start, end, label, score = int(item[0]), int(item[1]), str(item[2]), float(item[3])
        start, end = max(0, start), min(len(text), end)
        if end <= start:
            continue
        entity_type = map_label(label)
        if entity_type is None:
            unmapped[label] += 1
            continue
        spans.append(
            Span(
                start=start,
                end=end,
                entity_type=entity_type,
                text=text[start:end],
                score=min(1.0, max(0.0, score)),
                detector=detector,
            )
        )
    return resolve_spans(text, spans, authoritative=(), adjudicator=None), unmapped
