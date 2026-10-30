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

A span that ends inside a word chose its stem and is kept, except where it stops inside a
Hungarian ``-é``/``-ék``/``-éi`` chain (LAB-1384): NER often labels ``Teszt Hajnáék|nál`` or
``Minta Hubáé|val``, so the vault would key ``Teszt Hajnáék`` and the person would get a second
placeholder. Such a span is read together with the rest of its word as one stacked form and
ends at the name's stem, ``Teszt Hajná|éknál`` (lemma ``Teszt Hajna``).
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


#: Possessive/family suffixes a detector span may stop after, mid-chain (LAB-1384), by language.
_CHAIN_TAILS: dict[str, tuple[str, ...]] = {"hu": ("ék", "éi", "é")}


def _word_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _chain_stem(text: str, span: Span, language: str, is_name: Callable[[str], bool]) -> int | None:
    """Where a span that ends inside an ``-é``/``-ék``/``-éi`` chain should end, or ``None``.

    ``Teszt Hajnáék|nál`` -> the end of ``Teszt Hajná``: the span's value and the rest of the
    word must read as the stem + a stacked suffix (the matcher's ``splits``), the cut must fall
    right after the chain, and the span's last word must not be a name itself (``Máté|nak``).
    A bare ``-é`` needs a stem change or a lexicon name before it (``Hubá|éval``,
    ``Bélá|éval``), since names end in ``-é`` too.
    """
    value = span.text
    folded = value.casefold()
    tail = next((t for t in _CHAIN_TAILS.get(language, ()) if folded.endswith(t)), None)
    words = value.split()
    if tail is None or not words or is_name(words[-1]):
        return None
    end = span.end
    while end < len(text) and text[end].isalpha():
        end += 1
    if end < len(text) and _word_char(text[end]):
        return None
    splits = getattr(inflection_for(language), "splits", None)
    if splits is None:
        return None
    stem_length = len(value) - len(tail)
    for split in splits(text[span.start : end], span.entity_type):
        if len(split.stem) != stem_length or not value.startswith(split.stem):
            continue
        lemma_words = split.lemma.split()
        if (
            tail == "é"
            and split.lemma == split.stem
            and not (lemma_words and is_name(lemma_words[-1]))
        ):
            return None
        return span.start + stem_length
    return None


def _whole_chain_stem(span: Span, language: str, is_name: Callable[[str], bool]) -> int | None:
    """Where a whole-word span that ends in a stacked chain should end, or ``None``.

    ``Hajnáékat`` -> the end of ``Hajná``, ``Minta Hubáéit`` -> ``Minta Hubá``: used when the
    span has no confident split of its own. Without a detector boundary to go by, the stem
    must change (``Hajná`` -> ``Hajna``) or the lemma be a lexicon name, the last word must
    not be a name itself (``Máté``), and exactly one such reading may exist.
    """
    value = span.text
    words = value.split()
    splits = getattr(inflection_for(language), "splits", None)
    if splits is None or not words or is_name(words[-1]):
        return None
    last_start = len(value) - len(words[-1])
    stems: set[int] = set()
    for split in splits(value, span.entity_type):
        lemma_words = split.lemma.split()
        if (
            split.suffix.casefold().startswith("é")
            and len(split.stem) > last_start
            and value.startswith(split.stem)
            and (split.lemma != split.stem or (lemma_words and is_name(lemma_words[-1])))
        ):
            stems.add(len(split.stem))
    return span.start + stems.pop() if len(stems) == 1 else None


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
    inside a word chose its stem, unless it stops inside an ``-é``/``-ék``/``-éi`` chain) and
    whose matcher has a ``confident_split``. A trimmed span
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
        if span.entity_type not in TRIMMED_TYPES or not value or not value[-1].isalpha():
            out.append(span)
            continue
        if span.end < len(text) and _word_char(text[span.end]):
            if language not in _CHAIN_TAILS:
                out.append(span)
                continue
            if is_name is None:
                is_name = _is_name(language)
            chain_end = _chain_stem(text, span, language, is_name)
            out.append(span if chain_end is None else _ending_at(text, span, chain_end))
            continue
        if is_name is None:
            is_name = _is_name(language)
        split = method(value, span.entity_type, is_name)
        if (
            split is None
            or not 0 < len(split.stem) < len(value)
            or not value.startswith(split.stem)
        ):
            whole_end = (
                _whole_chain_stem(span, language, is_name)
                if language in _CHAIN_TAILS and split is None
                else None
            )
            out.append(span if whole_end is None else _ending_at(text, span, whole_end))
            continue
        trimmed = _ending_at(text, span, span.start + len(split.stem))
        # Teszt Elekékhez -> Teszt Elekék|hez: the stem itself may end in the chain.
        chain_end = _chain_stem(text, trimmed, language, is_name)
        out.append(trimmed if chain_end is None else _ending_at(text, span, chain_end))
    return out


def _ending_at(text: str, span: Span, end: int) -> Span:
    """``span`` cut to end at ``end``; start, type, score and detector are kept."""
    return Span(
        span.start,
        end,
        span.entity_type,
        text[span.start : end],
        span.score,
        span.detector,
        span.forced_by,
        span.subtype,
    )
