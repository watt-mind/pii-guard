"""A structured, placeholder-only summary of a document image, for the upstream model.

The labelled image tells the model *where* a value was; the summary tells it *what the
document is*, without a single raw value::

    {"document_type": "id_card", "holder": "[[PERSON_a1b2c3]]", "holder_match": "fuzzy",
     "document_number": "[[ID_DOCUMENT_d4e5f6]]", "issuing_country": "UTO",
     "expiry": null, "expired": false, "mrz_present": true, "mrz_valid": true,
     "fields_found": {"surname": "[[PERSON_a1b2c3]]", ...}, "fields_uncertain": []}

Values are placeholders of the request's vault session. The only plain values are
non-identifying derived facts: the document type, the issuing state code of the MRZ, whether
the document is ``expired`` (against :func:`datetime.date.today`, or the ``today`` given) and
whether the MRZ check digits are valid (``mrz_valid``; ``None`` without an MRZ). The expiry
date itself is reduced to ``expired`` by default (``expiry="reduce"``); ``expiry="keep"``
reports it as ``YYYY-MM-DD``.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pii_guard.types import EntityType
from pii_guard.visual.captions import CaptionValue
from pii_guard.visual.fuzzy import fold, parse_date
from pii_guard.visual.mrz import MrzData

__all__ = [
    "DOCUMENT_TYPES",
    "ExpiryPolicy",
    "SummaryField",
    "build_summary",
    "document_type",
    "field_name",
]

ExpiryPolicy = Literal["reduce", "keep"]

#: Words that identify a document type, folded (no accents, lower case), in any language.
DOCUMENT_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("passport", ("passport", "utlevel", "reisepass", "passeport")),
    (
        "driving_licence",
        ("driving licence", "driving license", "vezetoi engedely", "fuhrerschein", "fahrerlaubnis"),
    ),
    ("residence_permit", ("residence permit", "aufenthaltstitel", "tartozkodasi")),
    (
        "id_card",
        (
            "identity card",
            "id card",
            "azonosito kartya",
            "szemelyazonosito igazolvany",
            "szemelyi igazolvany",
            "personalausweis",
            "ausweiskarte",
            "carte d'identite",
        ),
    ),
)
_MRZ_CODES = {"P": "passport", "I": "id_card", "A": "id_card", "C": "id_card"}
#: ID documents (a holder is looked for on these only).
ID_DOCUMENTS = frozenset({"passport", "driving_licence", "residence_permit", "id_card"})

#: Caption words (folded) -> the summary field of the value next to them.
_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("given_names", ("given", "utonev", "vorname", "first name", "forename", "keresztnev")),
    ("surname", ("surname", "family name", "csaladi nev", "nachname", "familienname")),
    ("date_of_birth", ("date of birth", "szuletesi ido", "geburtsdatum", "born")),
    ("place_of_birth", ("place of birth", "szuletesi hely", "geburtsort")),
    ("personal_number", ("personal", "szemelyi azonosito", "steuer", "insurance", "taj")),
    ("document_number", ("document", "okmany", "ausweisnummer", "card no", "passport no")),
    ("document_number", ("licence number", "card number", "id number")),
    ("address", ("address", "lakcim", "anschrift", "residence")),
    ("expiry", ("expir", "ervenyes", "gultig", "valid until", "expires")),
)


def field_name(caption: str | None, entity_type: EntityType | None = None) -> str | None:
    """The summary field a caption's value fills (``"surname"``), or ``None``."""
    if caption is not None:
        folded = fold(caption)
        for name, words in _FIELDS:
            if any(word in folded for word in words):
                return name
    if entity_type is EntityType.PERSON:
        return "name"
    if entity_type is EntityType.DATE_OF_BIRTH:
        return "date_of_birth"
    return None


def document_type(text: str, mrz: MrzData | None = None) -> str | None:
    """The document type from its printed title or MRZ document code, or ``None``."""
    folded = fold(text)
    for name, words in DOCUMENT_TYPES:
        if any(word in folded for word in words):
            return name
    if mrz is not None and mrz.document_code:
        return _MRZ_CODES.get(mrz.document_code[0])
    return None


@dataclass(frozen=True, slots=True)
class SummaryField:
    """A summary field's placeholder and how sure its vault match was."""

    name: str
    placeholder: str
    status: str


@dataclass(slots=True)
class _Summary:
    document_type: str | None = None
    holder: str | None = None
    holder_match: str | None = None
    holder_confidence: float | None = None
    document_number: str | None = None
    issuing_country: str | None = None
    expiry: str | None = None
    expired: bool | None = None
    mrz_present: bool = False
    mrz_valid: bool | None = None
    fields_found: dict[str, str] = field(default_factory=dict)
    fields_uncertain: list[str] = field(default_factory=list)


def _expiry_date(fields: Sequence[CaptionValue], mrz: MrzData | None) -> dt.date | None:
    for value in fields:
        if field_name(value.caption) == "expiry":
            parsed = parse_date(value.text)
            if parsed is not None:
                return parsed
    if mrz is not None:
        return parse_date(mrz.expiry, yymmdd=True)
    return None


def build_summary(
    *,
    text: str,
    fields: Sequence[SummaryField],
    caption_fields: Sequence[CaptionValue],
    mrz: MrzData | None,
    holder: SummaryField | None,
    holder_confidence: float | None = None,
    expiry: ExpiryPolicy = "reduce",
    today: dt.date | None = None,
) -> dict[str, Any]:
    """The summary dict (see the module doc). ``text`` is the OCR text, read for the title
    only; nothing of it is copied into the summary."""
    summary = _Summary()
    summary.document_type = document_type(text, mrz)
    if holder is not None:
        summary.holder = holder.placeholder
        summary.holder_match = holder.status
        summary.holder_confidence = holder_confidence
        if holder.status == "uncertain":
            summary.fields_uncertain.append("holder")
    for item in fields:
        summary.fields_found.setdefault(item.name, item.placeholder)
        if item.status == "uncertain" and item.name not in summary.fields_uncertain:
            summary.fields_uncertain.append(item.name)
    summary.document_number = summary.fields_found.get("document_number")
    if mrz is not None:
        summary.mrz_present = True
        summary.mrz_valid = mrz.valid
        summary.issuing_country = mrz.issuing_state or None
    expires = _expiry_date(caption_fields, mrz)
    if expires is not None:
        summary.expired = expires < (today or dt.datetime.now(dt.UTC).date())
        if expiry == "keep":
            summary.expiry = expires.isoformat()
    return {
        "document_type": summary.document_type,
        "holder": summary.holder,
        "holder_match": summary.holder_match,
        "holder_confidence": summary.holder_confidence,
        "document_number": summary.document_number,
        "issuing_country": summary.issuing_country,
        "expiry": summary.expiry,
        "expired": summary.expired,
        "mrz_present": summary.mrz_present,
        "mrz_valid": summary.mrz_valid,
        "fields_found": dict(sorted(summary.fields_found.items())),
        "fields_uncertain": summary.fields_uncertain,
    }
