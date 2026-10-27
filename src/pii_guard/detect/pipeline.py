"""Detection pipeline: run several detectors and resolve their spans into one set.

``DetectionPipeline(["rules", "llm"])`` runs each detector on the same text and merges the
results (the "resolver" in ``docs/architecture.md``):

1. **Same type, overlapping** spans are merged into their union, so no character that any
   detector flagged is left out. Exception: a span from an *authoritative* detector (default
   ``rules``) for a *structured* type (checksum- or format-validated identifiers such as
   ``EMAIL``, ``BANK_ACCOUNT``, ``NATIONAL_ID_HU_TAX``) keeps its exact boundaries and absorbs
   overlapping same-type spans from other detectors.
2. **Different types, overlapping** spans are resolved greedily by priority:

   0. spans of an *overriding* detector (default ``known``, the values an application
      pre-loaded into the session, see :mod:`pii_guard.detect.known`): they win every
      conflict, also against same-type spans, which are not merged into them;
   1. authoritative structured spans;
   2. types that are masked by default over ``keep`` types (``ORGANIZATION``,
      ``COMPANY_ID_HU``), so a person's name inside a sole trader's company name stays a
      ``PERSON``;
   3. the *adjudicator's* span (default ``llm``) when detectors disagree on the type;
   4. longer spans, then higher scores, then detector order.

   A losing span is not simply dropped: the characters it covers that no winner covers are
   kept as a span of the loser's type, so a conflict never un-masks text. The one exception
   is an inflectional suffix directly after an overriding span's stem (``Próba Zsuzsanná|nak``):
   it stays outside the placeholder, as the vault keeps it.

Agreement (several detectors on the same span) keeps the winner's ``detector`` name and the
highest score. Fail closed: if any detector raises, :class:`DetectionError` propagates and no
partial result is returned.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from pii_guard.detect.normalize import NormalizedText, normalize_for_detection
from pii_guard.registry import create_detector
from pii_guard.types import DetectionError, Detector, EntityType, Span
from pii_guard.vault.inflection import following_suffix

__all__ = [
    "DEFAULT_KEEP_TYPES",
    "STRUCTURED_TYPES",
    "DetectionPipeline",
    "resolve_spans",
]

logger = logging.getLogger(__name__)

#: Types whose rule detections are validated (checksums, formats) and therefore win.
STRUCTURED_TYPES: frozenset[EntityType] = frozenset(
    {
        EntityType.EMAIL,
        EntityType.PHONE,
        EntityType.NATIONAL_ID_HU_TAX,
        EntityType.NATIONAL_ID_HU_TAJ,
        EntityType.BANK_ACCOUNT,
        EntityType.COMPANY_ID_HU,
        EntityType.VEHICLE_PLATE,
    }
)

#: Types kept (not masked) by default policy, see docs/entities.md. They lose type conflicts.
DEFAULT_KEEP_TYPES: frozenset[EntityType] = frozenset(
    {EntityType.ORGANIZATION, EntityType.COMPANY_ID_HU}
)

# Punctuation and dashes (incl. en/em dash) trimmed off the ends of a split remainder.
_TRIM = " \t\r\n.,;:!?()[]{}\"'\u00ab\u00bb\u201e\u201d-\u2013\u2014/"


@dataclass(slots=True)
class _Cand:
    start: int
    end: int
    entity_type: EntityType
    score: float
    detector: str
    authoritative: bool
    rank: int  # detector order, lower first
    overriding: bool = False


def _is_authoritative(span: Span, authoritative: frozenset[str]) -> bool:
    return span.detector in authoritative and span.entity_type in STRUCTURED_TYPES


def _merge_same_type(cands: list[_Cand]) -> list[_Cand]:
    """Union overlapping same-type candidates; authoritative ones absorb the others."""
    out: list[_Cand] = []
    by_type: dict[EntityType, list[_Cand]] = {}
    for c in cands:
        if c.overriding:  # kept exactly; the cross-type pass subtracts them from the rest
            out.append(c)
            continue
        by_type.setdefault(c.entity_type, []).append(c)
    for group in by_type.values():
        auth = [c for c in group if c.authoritative]
        rest = [c for c in group if not c.authoritative]
        for a in auth:
            for c in rest:
                if c.start < a.end and a.start < c.end:
                    a.score = max(a.score, c.score)
        rest = [c for c in rest if not any(c.start < a.end and a.start < c.end for a in auth)]
        # Authoritative spans of the same type never overlap each other in practice; if they
        # do, keep both and let the cross-type pass split them.
        out.extend(auth)
        rest.sort(key=lambda c: (c.start, -c.end))
        merged: list[_Cand] = []
        for c in rest:
            if merged and c.start < merged[-1].end:
                m = merged[-1]
                # The union's provenance is the stronger contributor.
                if (c.end - c.start, c.score, -c.rank) > (m.end - m.start, m.score, -m.rank):
                    m.detector, m.rank = c.detector, c.rank
                m.end = max(m.end, c.end)
                m.score = max(m.score, c.score)
            else:
                merged.append(c)
        out.extend(merged)
    return out


def _subtract(start: int, end: int, taken: list[tuple[int, int]]) -> list[tuple[int, int]]:
    pieces = [(start, end)]
    for ts, te in taken:
        nxt: list[tuple[int, int]] = []
        for ps, pe in pieces:
            if te <= ps or pe <= ts:
                nxt.append((ps, pe))
                continue
            if ps < ts:
                nxt.append((ps, ts))
            if te < pe:
                nxt.append((te, pe))
        pieces = nxt
    return pieces


def _word(char: str) -> bool:
    return char.isalnum() or char == "_"


def _trim(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start] in _TRIM:
        start += 1
    while end > start and text[end - 1] in _TRIM:
        end -= 1
    if start >= end or not any(ch.isalnum() for ch in text[start:end]):
        return None
    return start, end


def resolve_spans(
    text: str,
    spans: Iterable[Span],
    *,
    detector_order: Sequence[str] = (),
    authoritative: Iterable[str] = ("rules",),
    adjudicator: str | None = "llm",
    keep_types: Iterable[EntityType] = DEFAULT_KEEP_TYPES,
    overriding: Iterable[str] = ("known",),
) -> list[Span]:
    """Merge possibly overlapping spans from several detectors into non-overlapping spans.

    The result is sorted by ``start``; every returned span satisfies
    ``span.text == text[span.start:span.end]``. See the module docstring for the rules.
    """
    auth = frozenset(authoritative)
    keep = frozenset(keep_types)
    override = frozenset(overriding)
    order = {name: i for i, name in enumerate(detector_order)}
    cands: list[_Cand] = []
    for s in spans:
        if s.end > len(text) or text[s.start : s.end] != s.text:
            raise DetectionError(f"detector {s.detector!r} returned a span that does not fit")
        cands.append(
            _Cand(
                s.start,
                s.end,
                s.entity_type,
                s.score,
                s.detector,
                _is_authoritative(s, auth),
                order.get(s.detector, len(order)),
                s.detector in override,
            )
        )

    cands = _merge_same_type(cands)

    def disagrees(c: _Cand) -> bool:
        return any(
            o is not c and o.entity_type != c.entity_type and o.start < c.end and c.start < o.end
            for o in cands
        )

    def priority(c: _Cand) -> tuple[object, ...]:
        adjudicates = adjudicator is not None and c.detector == adjudicator and disagrees(c)
        return (
            not c.overriding,
            not c.authoritative,
            c.entity_type in keep,
            not adjudicates,
            -(c.end - c.start),
            -c.score,
            c.rank,
            c.start,
        )

    accepted: list[_Cand] = []
    taken: list[tuple[int, int]] = []
    # Where an overriding span ends inside a word: the suffix after it is not a remainder.
    stems_end = {
        c.end
        for c in cands
        if c.overriding and 0 < c.end < len(text) and _word(text[c.end - 1]) and _word(text[c.end])
    }
    for c in sorted(cands, key=priority):
        for ps, pe in _subtract(c.start, c.end, taken):
            if not c.overriding and ps in stems_end:
                ps = min(pe, ps + len(following_suffix(text, ps)))
                if ps >= pe:
                    continue
            if (ps, pe) != (c.start, c.end):
                trimmed = _trim(text, ps, pe)
                if trimmed is None:
                    continue
                ps, pe = trimmed
            accepted.append(
                _Cand(
                    ps,
                    pe,
                    c.entity_type,
                    c.score,
                    c.detector,
                    c.authoritative,
                    c.rank,
                    c.overriding,
                )
            )
            taken.append((ps, pe))

    accepted.sort(key=lambda c: (c.start, c.end))
    return [
        Span(c.start, c.end, c.entity_type, text[c.start : c.end], c.score, c.detector)
        for c in accepted
    ]


def _to_original(norm: NormalizedText, text: str, span: Span) -> Span:
    """``span`` over ``norm.text`` mapped onto the original ``text``; fail closed on a misfit."""
    if not 0 <= span.start < span.end <= len(norm.text) or (
        norm.text[span.start : span.end] != span.text
    ):
        raise DetectionError(f"detector {span.detector!r} returned a span that does not fit")
    start, end = norm.to_original(span.start, span.end)
    return Span(start, end, span.entity_type, text[start:end], span.score, span.detector)


class DetectionPipeline:
    """Run detectors in order and resolve their spans. Itself a :class:`Detector`.

    ``detectors`` are instances or registry names (``"rules"``, ``"llm"``); names are built
    with :func:`pii_guard.registry.create_detector` and no arguments. The other keyword
    arguments are passed to :func:`resolve_spans`.
    """

    name = "pipeline"

    def __init__(
        self,
        detectors: Sequence[Detector | str],
        *,
        authoritative: Iterable[str] = ("rules",),
        adjudicator: str | None = "llm",
        keep_types: Iterable[EntityType] = DEFAULT_KEEP_TYPES,
        min_score: float = 0.0,
        overriding: Iterable[str] = ("known",),
    ) -> None:
        if not detectors:
            raise ValueError("a pipeline needs at least one detector")
        self.detectors: list[Detector] = [
            create_detector(d) if isinstance(d, str) else d for d in detectors
        ]
        self.authoritative = frozenset(authoritative)
        self.adjudicator = adjudicator
        self.keep_types = frozenset(keep_types)
        self.min_score = min_score
        self.overriding = frozenset(overriding)

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        """Resolved spans over ``text``.

        Every detector sees :func:`~pii_guard.detect.normalize.normalize_for_detection`'s
        cleaned text (invisible characters dropped, lookalikes folded), so an obfuscated value
        is found whole by all of them; their spans are mapped back to ``text``, covering any
        invisible characters inside a value. Text with nothing to clean is passed unchanged.
        """
        norm = normalize_for_detection(text)
        seen = norm.text if norm.changed else text
        spans: list[Span] = []
        for detector in self.detectors:
            try:
                found = detector.detect(seen, language)
            except DetectionError:
                raise
            except Exception as exc:
                # Unknown failure: block, without the exception text (it may hold raw values).
                raise DetectionError(
                    f"detector {detector.name!r} failed ({type(exc).__name__})"
                ) from exc
            kept = [s for s in found if s.score >= self.min_score]
            if norm.changed:
                kept = [_to_original(norm, text, s) for s in kept]
            spans.extend(kept)
        resolved = resolve_spans(
            text,
            spans,
            detector_order=[d.name for d in self.detectors],
            authoritative=self.authoritative,
            adjudicator=self.adjudicator,
            keep_types=self.keep_types,
            overriding=self.overriding,
        )
        logger.debug("pipeline resolved %d candidate spans into %d", len(spans), len(resolved))
        return resolved
