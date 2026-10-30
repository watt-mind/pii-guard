"""Detection pipeline: run several detectors and resolve their spans into one set.

``DetectionPipeline(["rules", "llm"])`` runs each detector on the same text and merges the
results (the "resolver" in ``docs/architecture.md``):

1. **Same type, overlapping** spans are merged into their union, so no character that any
   detector flagged is left out. Exception: a span from an *authoritative* detector (default
   ``rules``) for a *structured* type (checksum- or format-validated identifiers such as
   ``EMAIL``, ``BANK_ACCOUNT``, ``NATIONAL_ID_HU_TAX``) keeps its exact boundaries and absorbs
   the part of an overlapping same-type span from another detector that it covers. The rest
   of that span is kept when it can be the rest of the value (it holds a digit, or continues
   the span without a space): a longer detection such as ``user@example.xn--p1ai`` against a
   rule's ``user@example.xn``, or a phone number with its extension, never un-masks text,
   while a label word the other detector took along (``(mobil)``) stays unmasked.
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

   One exception comes first (fail closed, ADR 0006): an authoritative span of a ``keep``
   type (the rules' ``COMPANY_ID_HU`` on an adószám) that a span of a masked type from any
   detector overlaps keeps its boundaries but takes that masked type, so a sole trader's
   tax number the adjudicator calls ``NATIONAL_ID_HU_TAX`` is masked, not kept. The masked
   type comes from an authoritative span first, then the adjudicator, then the largest
   overlap, the higher score and detector order; ``Span.forced_by`` names its detector.
   Only an explicit ``keep`` policy for that type too (``keep_types``) leaves it kept.

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
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Sequence
from copy import copy
from dataclasses import dataclass

from pii_guard.detect.normalize import NormalizedText, normalize_for_detection
from pii_guard.detect.suffix_trim import trim_name_suffixes
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
        EntityType.PAYMENT_CARD,
        EntityType.COMPANY_ID_HU,
        EntityType.VEHICLE_PLATE,
        EntityType.SECRET,
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
    forced_by: str | None = None  # detector whose masked type replaced a kept type
    subtype: str | None = None  # Span.subtype, carried through unchanged


def _is_authoritative(span: Span, authoritative: frozenset[str]) -> bool:
    return span.detector in authoritative and span.entity_type in STRUCTURED_TYPES


class _Intervals:
    """Candidates sorted by start, with the running maximum of their ends.

    Answers "which (or does any) candidate overlap ``[start, end)``" without scanning them
    all: only candidates starting before ``end`` can overlap, and the walk back over them
    stops where even the furthest end so far does not reach past ``start``. That is a binary
    search plus the overlaps found for spans that do not nest, as one detector's never do.
    """

    __slots__ = ("_items", "_reach", "_starts")

    def __init__(self, cands: Iterable[_Cand]) -> None:
        # The position in the input breaks ties, so ``overlapping`` can keep the input order.
        self._items = sorted(enumerate(cands), key=lambda item: item[1].start)
        self._starts = [c.start for _, c in self._items]
        self._reach: list[int] = []
        furthest = -1
        for _, c in self._items:
            furthest = max(furthest, c.end)
            self._reach.append(furthest)

    def any_overlap(self, start: int, end: int) -> bool:
        i = bisect_left(self._starts, end)
        return i > 0 and self._reach[i - 1] > start

    def overlapping(self, start: int, end: int) -> list[_Cand]:
        """The candidates overlapping ``[start, end)``, in input order."""
        found: list[tuple[int, _Cand]] = []
        i = bisect_left(self._starts, end) - 1
        while i >= 0 and self._reach[i] > start:
            pos, c = self._items[i]
            if c.end > start:
                found.append((pos, c))
            i -= 1
        found.sort(key=lambda item: item[0])
        return [c for _, c in found]


class _Taken:
    """Disjoint ``[start, end)`` ranges, sorted: what accepted spans already cover.

    Being disjoint, the ranges are sorted by end as well as by start, so the ones a new span
    overlaps are a contiguous run found by binary search.
    """

    __slots__ = ("_ends", "_starts")

    def __init__(self) -> None:
        self._starts: list[int] = []
        self._ends: list[int] = []

    def add(self, start: int, end: int) -> None:
        i = bisect_left(self._starts, start)
        self._starts.insert(i, start)
        self._ends.insert(i, end)

    def subtract(self, start: int, end: int) -> list[tuple[int, int]]:
        """The parts of ``[start, end)`` no range covers, left to right."""
        pieces: list[tuple[int, int]] = []
        i = bisect_right(self._ends, start)
        while i < len(self._starts) and self._starts[i] < end:
            if start < self._starts[i]:
                pieces.append((start, self._starts[i]))
            start = max(start, self._ends[i])
            i += 1
        if start < end:
            pieces.append((start, end))
        return pieces


def _merge_same_type(text: str, cands: list[_Cand]) -> list[_Cand]:
    """Union overlapping same-type candidates; authoritative ones absorb what they cover."""
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
        index = _Intervals(auth)
        pieces: list[_Cand] = []
        for c in rest:
            covering = index.overlapping(c.start, c.end)
            for a in covering:
                a.score = max(a.score, c.score)
            pieces.extend(_outside(text, c, covering))
        rest = pieces
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


def _force_mask(cands: list[_Cand], keep: frozenset[EntityType], adjudicator: str | None) -> None:
    """Fail closed: retype authoritative keep-type spans that a masked-type span overlaps.

    The validated span keeps its boundaries (checksum rules are better at them) and takes the
    masked type of the strongest overlapping candidate; ``forced_by`` records its detector.
    Overriding spans are left out: they win every conflict anyway.
    """
    held = [c for c in cands if c.authoritative and not c.overriding and c.entity_type in keep]
    if not held:
        return
    index = _Intervals(c for c in cands if not c.overriding and c.entity_type not in keep)
    for c in held:
        forcing = index.overlapping(c.start, c.end)
        if not forcing:
            continue
        best = min(
            forcing,
            key=lambda f: (
                not f.authoritative,
                f.detector != adjudicator,
                -(min(c.end, f.end) - max(c.start, f.start)),
                -f.score,
                f.rank,
                f.start,
            ),
        )
        c.entity_type = best.entity_type
        c.score = max(c.score, best.score)
        c.forced_by = best.detector


def _outside(text: str, cand: _Cand, auth: list[_Cand]) -> list[_Cand]:
    """``cand`` without the characters the same-type ``auth`` spans cover.

    What is left of ``cand`` is kept (trimmed) when it can be the rest of the value the
    validated span cut short: it holds a digit (a phone extension ``/ 123``), or it continues
    the authoritative span without a space (a punycode TLD ``--p1ai``). A word set off by a
    space (``(mobil)``, ``E-mail:``) is the other detector's over-reach and is dropped, and so
    is an inflectional suffix right after the span (``...@example.com-ra``), which stays
    outside the placeholder as the vault keeps it.
    """
    covering = [a for a in auth if cand.start < a.end and a.start < cand.end]
    if not covering:
        return [cand]
    pieces: list[_Cand] = []
    for ps, pe in _subtract(cand.start, cand.end, [(a.start, a.end) for a in covering]):
        trimmed = _trim(text, ps, pe)
        if trimmed is None:
            continue
        ts, te = trimmed
        if not any(ch.isdigit() for ch in text[ts:te]) and not any(
            _continues(text, a, ts, te) for a in covering
        ):
            continue
        piece = copy(cand)
        piece.start, piece.end = ts, te
        pieces.append(piece)
    return pieces


def _continues(text: str, a: _Cand, start: int, end: int) -> bool:
    """``text[start:end]`` is joined to span ``a`` without a space, and is not a suffix of it."""
    if a.end <= start:
        if a.end + len(following_suffix(text, a.end)) >= end:
            return False
        gap = text[a.end : start]
    elif end <= a.start:
        gap = text[end : a.start]
    else:
        return False
    return not any(ch.isspace() for ch in gap)


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
                subtype=s.subtype,
            )
        )

    cands = _merge_same_type(text, cands)
    _force_mask(cands, keep, adjudicator)

    by_type: dict[EntityType, list[_Cand]] = {}
    if adjudicator is not None and any(c.detector == adjudicator for c in cands):
        for c in cands:
            by_type.setdefault(c.entity_type, []).append(c)
    indexes = {t: _Intervals(group) for t, group in by_type.items()}

    def disagrees(c: _Cand) -> bool:
        """Another candidate of a different type overlaps ``c``."""
        return any(
            t != c.entity_type and index.any_overlap(c.start, c.end) for t, index in indexes.items()
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
    taken = _Taken()
    # Where an overriding span ends inside a word: the suffix after it is not a remainder.
    stems_end = {
        c.end
        for c in cands
        if c.overriding and 0 < c.end < len(text) and _word(text[c.end - 1]) and _word(text[c.end])
    }
    for c in sorted(cands, key=priority):
        for ps, pe in taken.subtract(c.start, c.end):
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
                    c.forced_by,
                    c.subtype,
                )
            )
            taken.add(ps, pe)

    accepted.sort(key=lambda c: (c.start, c.end))
    return [
        Span(
            c.start,
            c.end,
            c.entity_type,
            text[c.start : c.end],
            c.score,
            c.detector,
            c.forced_by,
            c.subtype,
        )
        for c in accepted
    ]


def _to_original(norm: NormalizedText, text: str, span: Span) -> Span:
    """``span`` over ``norm.text`` mapped onto the original ``text``; fail closed on a misfit."""
    if not 0 <= span.start < span.end <= len(norm.text) or (
        norm.text[span.start : span.end] != span.text
    ):
        raise DetectionError(f"detector {span.detector!r} returned a span that does not fit")
    start, end = norm.to_original(span.start, span.end)
    return Span(
        start,
        end,
        span.entity_type,
        text[start:end],
        span.score,
        span.detector,
        span.forced_by,
        span.subtype,
    )


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
        return self._detect_texts([text], language, batched=False)[0]

    def detect_many(self, texts: Sequence[str], language: str = "hu") -> list[list[Span]]:
        """``[detect(t, language) for t in texts]``, letting detectors batch (LAB-1279).

        A detector with ``detect_batch(texts, language)`` (the NER detector: one batched model
        run) gets all texts in one call; the others are called per text. Normalisation, the
        mapping back to the original text and :func:`resolve_spans` stay per text. Fail closed:
        any detector error raises :class:`DetectionError` for the whole call.
        """
        return self._detect_texts(list(texts), language, batched=True)

    def _detect_texts(self, texts: list[str], language: str, *, batched: bool) -> list[list[Span]]:
        norms = [normalize_for_detection(text) for text in texts]
        seen = [n.text if n.changed else t for n, t in zip(norms, texts, strict=True)]
        spans: list[list[Span]] = [[] for _ in texts]
        for detector in self.detectors:
            batch = getattr(detector, "detect_batch", None) if batched else None
            try:
                if batch is not None:
                    found_all = batch(seen, language)
                    if not isinstance(found_all, list) or len(found_all) != len(seen):
                        raise DetectionError(
                            f"detector {detector.name!r} returned the wrong number of results"
                        )
                else:
                    found_all = [detector.detect(t, language) for t in seen]
            except DetectionError:
                raise
            except Exception as exc:
                # Unknown failure: block, without the exception text (it may hold raw values).
                raise DetectionError(
                    f"detector {detector.name!r} failed ({type(exc).__name__})"
                ) from exc
            for i, found in enumerate(found_all):
                kept = [s for s in found if s.score >= self.min_score]
                if norms[i].changed:
                    kept = [_to_original(norms[i], texts[i], s) for s in kept]
                spans[i].extend(kept)
        order = [d.name for d in self.detectors]
        out: list[list[Span]] = []
        for text, candidates in zip(texts, spans, strict=True):
            resolved = resolve_spans(
                text,
                candidates,
                detector_order=order,
                authoritative=self.authoritative,
                adjudicator=self.adjudicator,
                keep_types=self.keep_types,
                overriding=self.overriding,
            )
            # A name found whole with its case ending ends at its stem (LAB-1174).
            resolved = trim_name_suffixes(text, resolved, language)
            logger.debug(
                "pipeline resolved %d candidate spans into %d", len(candidates), len(resolved)
            )
            out.append(resolved)
        return out
