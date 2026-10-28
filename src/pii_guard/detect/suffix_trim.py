"""Trim an inflectional suffix off name spans before the vault stores them (LAB-1174).

A detector that finds a Hungarian name whole often includes its case ending: NER returns
``Tihamérnak``, an LLM returns ``Kerekes Ottótól``. The vault narrows such a span to its stem
only for an unambiguous reading or a lemma it has already confirmed (``Zoltánt`` may be
``Zoltán`` + ``t`` or a name of its own), so otherwise the inflected word becomes the value
and a bare placeholder restores ``Kerekes Ottótól`` in an English answer.

:func:`trim_name_suffixes` runs after the detectors (in
:class:`~pii_guard.detect.pipeline.DetectionPipeline`, so for every detector and mode) and
ends such a span at its stem, ``Kerekes Ottó|tól``, when the language pack's matcher has a
confident reading of it (its optional ``confident_split``: the Hungarian pack checks its name
lexicons and the suffix's form, see
:class:`~pii_guard.languages.hu.inflection.HungarianSuffixMatcher`).
The vault then keys the lemma from the split that agrees with that stem (``Minta Hajná|nak``
-> ``Minta Hajna``), and the suffix stays outside the placeholder. Languages whose matcher
has no ``confident_split`` are unchanged.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from pii_guard.lang import Lexicon, LexiconUnavailable, available_kinds, lexicon
from pii_guard.types import EntityType, Span
from pii_guard.vault.inflection import inflection_for

__all__ = ["TRIMMED_TYPES", "trim_name_suffixes"]

#: Entity types whose detector spans are trimmed: names inflect; other values (an e-mail
#: address, an ID) keep their spelling.
TRIMMED_TYPES: frozenset[EntityType] = frozenset({EntityType.PERSON})

_NAME_KINDS = (
    "given_names_m",
    "given_names_f",
    "recent_given_names_m",
    "recent_given_names_f",
    "surnames",
)


def _word_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _is_name(language: str) -> Callable[[str], bool]:
    """Whether a word is a given name or surname in ``language``'s pack lexicons (cached there)."""
    kinds = set(available_kinds(language))
    lexicons: list[Lexicon] = []
    for kind in _NAME_KINDS:
        if kind in kinds:
            try:
                lexicons.append(lexicon(kind, language))
            except LexiconUnavailable:
                continue
    return lambda word: any(word in names for names in lexicons)


def trim_name_suffixes(text: str, spans: Sequence[Span], language: str = "hu") -> list[Span]:
    """``spans`` with each whole-word name span ending at its stem where that is confident.

    Only spans of :data:`TRIMMED_TYPES` that end at a word boundary (a span that already ends
    inside a word chose its stem) and whose matcher has a ``confident_split``. A trimmed span
    keeps its start, type, score and detector. Spans stay in order and never grow.
    """
    if not any(s.entity_type in TRIMMED_TYPES for s in spans):
        return list(spans)
    method = getattr(inflection_for(language), "confident_split", None)
    if method is None:
        return list(spans)
    is_name: Callable[[str], bool] | None = None
    out: list[Span] = []
    for span in spans:
        value = span.text
        if (
            span.entity_type not in TRIMMED_TYPES
            or not value
            or not value[-1].isalpha()
            or (span.end < len(text) and _word_char(text[span.end]))
        ):
            out.append(span)
            continue
        if is_name is None:
            is_name = _is_name(language)
        split = method(value, span.entity_type, is_name)
        if (
            split is None
            or not 0 < len(split.stem) < len(value)
            or not value.startswith(split.stem)
        ):
            out.append(span)
            continue
        end = span.start + len(split.stem)
        out.append(
            Span(
                span.start,
                end,
                span.entity_type,
                text[span.start : end],
                span.score,
                span.detector,
                span.forced_by,
                span.subtype,
            )
        )
    return out
