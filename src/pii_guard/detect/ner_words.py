"""Snap NER spans of the text types to whole words (LAB-1338).

With token aggregation the model labels sub-word tokens, so a span can start or end inside a
word: ``Te|szt| Eleknek`` or ``Próba Ti|hamér|ért``. The vault masks only that fragment and
the rest of the name goes upstream in clear text (``Te[[PERSON_x]] Eleknek``).

:func:`snap_to_words` runs in :meth:`~pii_guard.detect.ner.NerDetector.to_spans`, before the
spans leave the detector, for :data:`SNAPPED_TYPES`:

- **Start.** A span that starts inside a word starts at the word's start.
- **End.** Token aggregation exists so that a span can end at a stem before a case ending
  (``Péter|t``). An end inside a word is kept when the language pack reads the rest of the word
  as a suffix of exactly that stem (its matcher's ``splits``). Otherwise the span ends at the
  end of the word (``Teszt Pirosk|áról`` -> ``Teszt Piroskáról``), so it never masks less than
  the model did. No other stem is guessed here: a weak reading (``Kelem`` + ``en``) would cut
  the name.
- Spans of the same type that overlap after snapping are merged.

A span extended to the end of an inflected word is then handled like any name found whole:
the pipeline's suffix trim (:mod:`pii_guard.detect.suffix_trim`, LAB-1174) ends it at its stem
where that is confident, and the vault keys the lemma (LAB-1337).

:func:`snap_to_tokens` does the same for the structured types in :data:`TOKEN_TYPES`
(LAB-1367). The model labels sub-word pieces of a number too (``84|61|269|322``) and returned
``846`` or ``8461269`` of a ten-digit tax number in a CSV row, so the last digits went upstream
next to the placeholder (``[[NATIONAL_ID_HU_TAX_x]]322``). A number has no case ending, so a
span that starts or ends inside a run of letters and digits takes the whole run, also across
a ``.``, ``-`` or ``/`` between two digits (``812.754.113.91``). It runs before the number
checks (:mod:`pii_guard.detect.ner_numbers`), which then judge the whole token.
"""

from __future__ import annotations

from collections.abc import Sequence

from pii_guard.types import EntityType, Span
from pii_guard.vault.inflection import inflection_for, splits

__all__ = ["SNAPPED_TYPES", "TOKEN_TYPES", "snap_to_tokens", "snap_to_words"]

#: Entity types whose spans are words of running text, so a boundary inside a word is a
#: tokenisation artefact rather than the value's edge.
SNAPPED_TYPES: frozenset[EntityType] = frozenset(
    {EntityType.PERSON, EntityType.ORGANIZATION, EntityType.ADDRESS}
)

#: Structured types: a boundary inside a run of letters and digits cuts the value.
TOKEN_TYPES: frozenset[EntityType] = frozenset(
    {
        EntityType.PHONE,
        EntityType.ID_DOCUMENT,
        EntityType.BANK_ACCOUNT,
        EntityType.NATIONAL_ID_HU_TAX,
        EntityType.NATIONAL_ID_HU_TAJ,
    }
)

#: Characters that join digit groups inside one identifier.
_JOINERS = ".-/"


def _word(char: str) -> bool:
    return char.isalnum() or char == "_"


def _inside(text: str, pos: int) -> bool:
    """Whether ``pos`` falls between two word characters."""
    return 0 < pos < len(text) and _word(text[pos - 1]) and _word(text[pos])


def _snap_end(text: str, start: int, end: int, entity_type: EntityType, language: str) -> int:
    word_end = end
    while word_end < len(text) and _word(text[word_end]):
        word_end += 1
    surface = text[start:word_end]
    stems = {
        len(s.stem)
        for s in splits(inflection_for(language), surface, entity_type)
        if s.stem and surface.startswith(s.stem)
    }
    return end if end - start in stems else word_end


def snap_to_words(text: str, spans: Sequence[Span], language: str = "hu") -> list[Span]:
    """``spans`` with every :data:`SNAPPED_TYPES` span starting and ending on a word boundary.

    See the module docstring for the rule at the end of a span. Other spans are returned
    unchanged. A snapped span keeps its type, score and detector; same-type spans that overlap
    after snapping are merged (the higher score is kept). Sorted by ``(start, end, type)``.
    """
    if not any(s.entity_type in SNAPPED_TYPES for s in spans):
        return list(spans)
    out: list[Span] = []
    snapped: list[Span] = []
    for span in spans:
        if span.entity_type not in SNAPPED_TYPES:
            out.append(span)
            continue
        start, end = span.start, span.end
        while _inside(text, start):
            start -= 1
        if _inside(text, end):
            end = _snap_end(text, start, end, span.entity_type, language)
        if (start, end) == (span.start, span.end):
            snapped.append(span)
            continue
        snapped.append(_moved(text, span, start, end))
    return sorted(out + _merge(text, snapped), key=lambda s: (s.start, s.end, s.entity_type.value))


def _moved(text: str, span: Span, start: int, end: int) -> Span:
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


def _joined(text: str, pos: int) -> bool:
    """Whether ``text[pos]`` is a joiner between two digits."""
    return (
        0 < pos < len(text) - 1
        and text[pos] in _JOINERS
        and text[pos - 1].isdigit()
        and text[pos + 1].isdigit()
    )


def snap_to_tokens(text: str, spans: Sequence[Span]) -> list[Span]:
    """``spans`` with every :data:`TOKEN_TYPES` span covering whole runs of letters and digits.

    A span that starts or ends inside a run is extended to the run's edge, also across a
    joiner between two digits (see the module docstring), so it never masks less than the
    model did. Other spans are returned unchanged; same-type spans that overlap afterwards are
    merged (the higher score is kept), and of spans of different types that end up on the same
    range, the type whose pieces covered more of it is kept. Sorted by ``(start, end, type)``.
    """
    if not any(s.entity_type in TOKEN_TYPES for s in spans):
        return list(spans)
    out: list[Span] = []
    snapped: list[Span] = []
    for span in spans:
        if span.entity_type not in TOKEN_TYPES:
            out.append(span)
            continue
        start, end = span.start, span.end
        while True:
            if _inside(text, start):
                start -= 1
            elif start >= 2 and _joined(text, start - 1) and _word(text[start]):
                start -= 2
            else:
                break
        while True:
            if _inside(text, end):
                end += 1
            elif _joined(text, end) and _word(text[end - 1]):
                end += 2
            else:
                break
        snapped.append(
            span if (start, end) == (span.start, span.end) else _moved(text, span, start, end)
        )
    pieces = [s for s in spans if s.entity_type in TOKEN_TYPES]
    return sorted(
        out + _one_type_per_token(_merge(text, snapped), pieces),
        key=lambda s: (s.start, s.end, s.entity_type.value),
    )


def _one_type_per_token(snapped: Sequence[Span], pieces: Sequence[Span]) -> list[Span]:
    """Of snapped spans of different types on exactly one range, keep the model's majority.

    Pieces of one number can carry different labels (``846`` PHONE, ``126`` tax number). Once
    both cover the whole token, the type whose pieces covered more of it wins, then the higher
    score; otherwise the resolver would pick by score alone.
    """

    def share(span: Span) -> tuple[int, float]:
        chars = sum(
            max(0, min(p.end, span.end) - max(p.start, span.start))
            for p in pieces
            if p.entity_type is span.entity_type
        )
        return chars, span.score

    best: dict[tuple[int, int], Span] = {}
    for span in snapped:
        key = (span.start, span.end)
        if key not in best or share(span) > share(best[key]):
            best[key] = span
    return list(best.values())


def _merge(text: str, snapped: Sequence[Span]) -> list[Span]:
    merged: list[Span] = []
    for span in sorted(snapped, key=lambda s: (s.entity_type.value, s.start, -s.end)):
        last = merged[-1] if merged else None
        if last is not None and last.entity_type is span.entity_type and span.start < last.end:
            end = max(last.end, span.end)
            merged[-1] = Span(
                last.start,
                end,
                last.entity_type,
                text[last.start : end],
                max(last.score, span.score),
                last.detector,
                last.forced_by,
                last.subtype,
            )
        else:
            merged.append(span)
    return merged
