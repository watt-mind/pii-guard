"""Core types shared by every pii-guard component.

Detectors, the vault, the API and the evaluation harness all speak in terms of these types.
They are a public contract: see ``docs/contracts.md`` before changing anything here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

__all__ = [
    "TEXT_ENTITY_TYPES",
    "VISUAL_ENTITY_TYPES",
    "Analyzer",
    "DetectionError",
    "Detector",
    "EntityType",
    "MaskingError",
    "PayloadTooLargeError",
    "PiiGuardError",
    "Span",
    "VaultNotConfiguredError",
]


class EntityType(StrEnum):
    """Every entity type in ``docs/entities.md``.

    Values equal names, so ``EntityType("PERSON") is EntityType.PERSON`` and the JSON form
    of a type is its name.
    """

    # Text entities
    PERSON = "PERSON"
    ADDRESS = "ADDRESS"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    DATE_OF_BIRTH = "DATE_OF_BIRTH"
    NATIONAL_ID_HU_TAX = "NATIONAL_ID_HU_TAX"
    NATIONAL_ID_HU_TAJ = "NATIONAL_ID_HU_TAJ"
    ID_DOCUMENT = "ID_DOCUMENT"
    BANK_ACCOUNT = "BANK_ACCOUNT"
    COMPANY_ID_HU = "COMPANY_ID_HU"
    ORGANIZATION = "ORGANIZATION"
    PARCEL_NUMBER_HU = "PARCEL_NUMBER_HU"
    VEHICLE_PLATE = "VEHICLE_PLATE"
    SECRET = "SECRET"  # noqa: S105 - the type name, not a credential

    # Visual entities (image regions, not text spans)
    FACE = "FACE"
    SIGNATURE = "SIGNATURE"
    ID_PHOTO = "ID_PHOTO"
    STAMP = "STAMP"

    @property
    def is_visual(self) -> bool:
        """True for image-region types (``FACE``, ``SIGNATURE``, ``ID_PHOTO``, ``STAMP``)."""
        return self in VISUAL_ENTITY_TYPES


VISUAL_ENTITY_TYPES: frozenset[EntityType] = frozenset(
    {EntityType.FACE, EntityType.SIGNATURE, EntityType.ID_PHOTO, EntityType.STAMP}
)
TEXT_ENTITY_TYPES: frozenset[EntityType] = frozenset(EntityType) - VISUAL_ENTITY_TYPES


@dataclass(frozen=True, slots=True)
class Span:
    """A detected piece of personal data in a text.

    ``start`` and ``end`` are Python string offsets (code points) into the analysed text,
    half-open: ``text == source[start:end]``. ``score`` is the detector's confidence in
    ``[0, 1]``; ``detector`` is the registry name of the detector that produced it.

    ``repr()`` never includes ``text``, so a span can be logged or put in an exception
    message without leaking the raw value.

    ``forced_by`` is debugging metadata set by the resolver: the detector whose masked type
    replaced a kept type on this span (fail closed, LAB-1228). It does not take part in
    equality or hashing and is not in :meth:`to_public_dict`.

    ``subtype`` refines the type where one type covers several shapes: a ``SECRET`` span says
    which rule found it (``"github_token"``, ``"url_password"``, ``"assignment"``, see
    ``docs/contracts.md``). It does not take part in equality or hashing; :meth:`to_public_dict`
    includes it only when it is set.
    """

    start: int
    end: int
    entity_type: EntityType
    text: str
    score: float
    detector: str
    forced_by: str | None = field(default=None, compare=False)
    subtype: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.entity_type, EntityType):
            # Accept the plain string form ("PERSON") and normalize it.
            try:
                object.__setattr__(self, "entity_type", EntityType(self.entity_type))
            except ValueError:
                raise ValueError(f"unknown entity_type {self.entity_type!r}") from None
        if self.start < 0 or self.end <= self.start:
            raise ValueError(f"invalid span offsets start={self.start} end={self.end}")
        if len(self.text) != self.end - self.start:
            raise ValueError("span text length does not match end - start")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score must be in [0, 1], got {self.score}")
        if not self.detector:
            raise ValueError("detector name must not be empty")

    def __repr__(self) -> str:
        return (
            f"Span(start={self.start}, end={self.end}, "
            f"entity_type={self.entity_type.value}, score={self.score:.3f}, "
            f"detector={self.detector!r}, "
            + (f"forced_by={self.forced_by!r}, " if self.forced_by else "")
            + (f"subtype={self.subtype!r}, " if self.subtype else "")
            + "text=<redacted>)"
        )

    __str__ = __repr__

    @property
    def length(self) -> int:
        return self.end - self.start

    def overlaps(self, other: Span) -> bool:
        """True if the two spans share at least one character."""
        return self.start < other.end and other.start < self.end

    def to_public_dict(self) -> dict[str, object]:
        """The span without its raw value, as returned by ``POST /v1/analyze``."""
        out: dict[str, object] = {
            "start": self.start,
            "end": self.end,
            "entity_type": self.entity_type.value,
            "score": self.score,
            "detector": self.detector,
        }
        if self.subtype:
            out["subtype"] = self.subtype
        return out


@runtime_checkable
class Detector(Protocol):
    """Anything that finds personal data in text.

    Implementations must be safe to call repeatedly, must return spans whose offsets refer
    to ``text`` exactly as given, and must raise :class:`DetectionError` (never return a
    partial result silently) when they cannot complete. See ADR 0006 (fail closed).
    """

    name: str

    def detect(self, text: str, language: str = "hu") -> list[Span]: ...


@runtime_checkable
class Analyzer(Protocol):
    """Detection as the API sees it: non-overlapping spans sorted by ``start``."""

    def analyze(self, text: str, language: str) -> list[Span]: ...


class PiiGuardError(Exception):
    """Base class for every error pii-guard raises on purpose.

    ``code`` is a stable, machine-readable identifier used in API error bodies.
    Messages must never contain raw personal data: describe entity types, counts or
    placeholder ids instead.
    """

    code: str = "internal_error"
    status_code: int = 500

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    @property
    def message(self) -> str:
        return str(self.args[0]) if self.args and self.args[0] else self.code


class DetectionError(PiiGuardError):
    """A detector failed or timed out. The request must be blocked."""

    code = "detection_failed"
    status_code = 503


class MaskingError(PiiGuardError):
    """Masking or re-identification could not complete. The request must be blocked."""

    code = "masking_failed"
    status_code = 500


class VaultNotConfiguredError(PiiGuardError):
    """The tenant key is unset, not hex or too short. Misconfiguration, not a bug."""

    code = "vault_not_configured"
    status_code = 503


class PayloadTooLargeError(PiiGuardError):
    """The request body, a text or an image is larger than the configured limit."""

    code = "payload_too_large"
    status_code = 413
