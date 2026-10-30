"""The ``known`` detector: every occurrence of the values pre-loaded into a session.

Deterministic, score ``1.0``, detector name ``known``. Occurrences are matched with the
vault's own rules (case- and whitespace-insensitive; per language, inflected forms: Hungarian
suffixes and stem changes, the English possessive), and a span covers the value's stem only,
so ``Próba Zsuzsannának`` gives the span ``Próba Zsuzsanná`` and the vault keys it on the
lemma ``Próba Zsuzsanna``: a value that is pre-loaded *and* detected by another detector
gets one placeholder.

In the resolver (:func:`~pii_guard.detect.pipeline.resolve_spans`) ``known`` spans win every
conflict; :func:`merge_known` adds them to spans another analyzer already resolved, which is
how ``/v1/mask`` and the gateway use it whenever the session has known values.

:func:`widen_to_known` repairs a name a detector found only in part (``1,Jane Placeholder``
in a CSV row, where NER returns ``Placeholder``): a full value already known (the session's,
or found elsewhere in the same request) that occurs around the span replaces it, so the whole
name gets one placeholder before masking instead of ``Jane [[PERSON_x]]`` (LAB-1284).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from pii_guard.detect.pipeline import DEFAULT_KEEP_TYPES, resolve_spans
from pii_guard.types import EntityType, Span
from pii_guard.vault.fold import FoldedText, fold_text, fold_value, fold_views
from pii_guard.vault.inflection import inflection_for
from pii_guard.vault.known import KnownValue, KnownValues

__all__ = [
    "KNOWN_DETECTOR",
    "WIDENED_TYPES",
    "KnownValuesDetector",
    "merge_known",
    "widen_request",
    "widen_to_known",
]

KNOWN_DETECTOR = "known"


class KnownValuesDetector:
    """Find the occurrences of ``values`` (a session's :class:`KnownValues`, or a list)."""

    name = KNOWN_DETECTOR

    def __init__(self, values: KnownValues | Iterable[KnownValue] = ()) -> None:
        if isinstance(values, KnownValues):
            self._values = values
        else:
            self._values = KnownValues()
            self._values.add(list(values), max_values=10**9)

    def __repr__(self) -> str:
        return f"KnownValuesDetector(values={len(self._values)})"

    def detect(
        self,
        text: str,
        language: str = "hu",
        views: tuple[FoldedText, ...] | None = None,
    ) -> list[Span]:
        if not self._values:
            return []
        taken = bytearray(len(text))
        spans: list[Span] = []
        # Longest values first, so "Teszt Elek" wins over a separately loaded "Elek".
        for item, start, end in self._values.occurrences(text, language, views):
            if end <= start or any(taken[start:end]):
                continue
            taken[start:end] = b"\x01" * (end - start)
            spans.append(Span(start, end, item.entity_type, text[start:end], 1.0, KNOWN_DETECTOR))
        spans.sort(key=lambda s: s.start)
        return spans


def merge_known(
    text: str,
    spans: Sequence[Span],
    known: KnownValuesDetector | KnownValues,
    language: str = "hu",
    *,
    keep_types: Iterable[EntityType] = DEFAULT_KEEP_TYPES,
    views: tuple[FoldedText, ...] | None = None,
) -> list[Span]:
    """``spans`` (already resolved) plus the known values' spans, resolved again.

    Known spans win their conflicts; the characters of a losing span that no known span
    covers stay a span of the loser's type, except an inflectional suffix that directly
    follows a known stem (it stays outside the placeholder, as in the vault).
    """
    detector = known if isinstance(known, KnownValuesDetector) else KnownValuesDetector(known)
    found = detector.detect(text, language, views)
    if not found:
        return list(spans)
    return resolve_spans(
        text,
        [*found, *spans],
        detector_order=[KNOWN_DETECTOR],
        keep_types=keep_types,
    )


#: Entity types whose partly detected spans :func:`widen_to_known` widens: names, the only type
#: a detector routinely finds in part (one word of a multi-word value).
WIDENED_TYPES: frozenset[EntityType] = frozenset({EntityType.PERSON})


def _full_value_pattern(folded: str, entity_type: EntityType, language: str) -> re.Pattern[str]:
    """The vault's occurrence pattern of a folded value (stem only, suffix by lookahead).

    Not cached across requests: like the vault's own patterns, it holds personal data.
    """
    from pii_guard.vault.vault import _compile, _forms  # the vault's own occurrence rules

    return _compile(_forms(inflection_for(language), folded, entity_type))


def _folded_values(values: Iterable[str]) -> list[tuple[str, ...]]:
    """The folded tokens of each value of two or more words, once each."""
    out: dict[tuple[str, ...], None] = {}
    for value in values:
        tokens = tuple(fold_value(value).split())
        if len(tokens) >= 2:
            out.setdefault(tokens)
    return list(out)


def _may_occur(tokens: Sequence[str], folded_text: str) -> bool:
    """Cheap prefilter: every token, less its last letter (a stem change), is in the text."""
    return all(token[: max(1, len(token) - 1)] in folded_text for token in tokens)


def _is_suffix(text: str, start: int, end: int) -> bool:
    """``text[start:end]`` is empty or letters run on from the previous one (``…nak``)."""
    return all(ch.isalnum() for ch in text[start:end])


def _stops_before_suffix(text: str, span: Span, end: int, language: str) -> bool:
    """``span`` ends where ``text[span.end:end]`` is an inflectional suffix of its value.

    The known detector, the vault and LLM alignment cut a span at the stem on purpose
    (``Gyakorló Tihamér|nak``); a widening must not move that end over the suffix.
    """
    if span.end >= end or not text[span.end - 1].isalnum():
        return False
    pattern = inflection_for(language).suffix_pattern(fold_value(span.text), span.entity_type)
    if not pattern:
        return False
    return re.fullmatch(pattern, fold_value(text[span.end : end]), re.IGNORECASE) is not None


def widen_to_known(
    text: str,
    spans: Sequence[Span],
    values: Iterable[str],
    language: str = "hu",
    *,
    entity_types: Iterable[EntityType] = WIDENED_TYPES,
) -> list[Span]:
    """``spans`` with each partly detected value widened to a full value that contains it.

    ``values`` are full values already known (the session's confirmed and pre-loaded values,
    the values found elsewhere in the same request). Where one of them occurs in ``text``
    (the vault's occurrence rules: word boundaries, case-, whitespace- and Unicode-folded,
    inflected forms with the suffix outside) and that occurrence covers a shorter span of one
    of ``entity_types`` (``Placeholder`` in ``1,Jane Placeholder``, ``János`` in ``Minta
    János``), the span becomes the occurrence: ``Jane Placeholder``. Several fragments of the
    value (``Jane`` and ``Placeholder``) become one span. Longest values first.

    A span ending in a suffix keeps it (``Minta Jánosnak``; the vault splits it); a span that
    stops at a stem before a suffix keeps its end (``Tihamér|nak`` with the value ``Gyakorló
    Tihamérnak`` becomes ``Gyakorló Tihamér|nak``: the suffix stays outside). An
    occurrence that would take in or cut through any other span (another person, an e-mail
    address) is not used, so a widening never joins two values. Values of one word widen
    nothing. Returns the spans in order; ``spans`` themselves are never changed.
    """
    return _widen(text, spans, _folded_values(values), language, frozenset(entity_types))


def _widen(
    text: str,
    spans: Sequence[Span],
    values: Sequence[tuple[str, ...]],
    language: str,
    types: frozenset[EntityType],
) -> list[Span]:
    """:func:`widen_to_known` with the values already folded (:func:`_folded_values`)."""
    if not values or not any(s.entity_type in types for s in spans):
        return list(spans)
    folded_text = fold_text(text).text
    candidates = [
        (entity_type, " ".join(tokens))
        for tokens in values
        if _may_occur(tokens, folded_text)
        for entity_type in types
    ]
    if not candidates:
        return list(spans)
    views = fold_views(text)
    occurrences: dict[tuple[int, int, EntityType], None] = {}
    for entity_type, folded in candidates:
        pattern = _full_value_pattern(folded, entity_type, language)
        for view in views:
            for match in pattern.finditer(view.text):
                if match.end() > match.start():
                    occurrences.setdefault((*view.to_original(*match.span()), entity_type))
    if not occurrences:
        return list(spans)
    result = list(spans)
    # Longest occurrence first, so "Jane Ann Placeholder" wins over "Ann Placeholder".
    for start, end, entity_type in sorted(occurrences, key=lambda o: (o[0] - o[1], o[0])):
        overlapping = [s for s in result if s.start < end and start < s.end]
        seeds = [
            s
            for s in overlapping
            if s.entity_type is entity_type
            and s.start >= start
            and (s.end <= end or _is_suffix(text, end, s.end))
        ]
        if not seeds or len(seeds) != len(overlapping):
            continue  # nothing to widen, or the occurrence would take in another value
        last = max(seeds, key=lambda s: s.end)
        # The value is itself an inflected surface (``Gyakorló Tihamérnak``, confirmed whole in
        # an earlier turn) and the seed already stops at its stem: the end stays (LAB-1182).
        new_end = (
            last.end if _stops_before_suffix(text, last, end, language) else max(end, last.end)
        )
        if len(seeds) == 1 and seeds[0].start == start and seeds[0].end >= new_end:
            continue  # already the whole value
        widened = Span(
            start,
            new_end,
            entity_type,
            text[start:new_end],
            max(s.score for s in seeds),
            seeds[0].detector,
        )
        drop = {id(s) for s in seeds}
        result = [s for s in result if id(s) not in drop]
        result.append(widened)
    result.sort(key=lambda s: (s.start, s.end))
    return result


def widen_request(
    texts: Sequence[str],
    spans: Sequence[Sequence[Span]],
    known: Iterable[str] = (),
    language: str = "hu",
    *,
    entity_types: Iterable[EntityType] = WIDENED_TYPES,
) -> list[list[Span]]:
    """:func:`widen_to_known` for every text of one request.

    The full values are ``known`` (the session's) plus every span of ``entity_types`` found in
    any of ``texts``: a name detected whole in the client letter repairs the same name
    detected in part in a CSV row of another message.
    """
    types = frozenset(entity_types)
    values = dict.fromkeys(known)
    for found in spans:
        values.update(dict.fromkeys(s.text for s in found if s.entity_type in types))
    folded = _folded_values(values)  # once per request, not once per text
    return [
        _widen(text, found, folded, language, types)
        for text, found in zip(texts, spans, strict=True)
    ]
