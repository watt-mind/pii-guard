"""Romanian inflection: genitive/dative and vocative endings, and the stem change of a final
``-a`` (vault, LLM alignment).

Part of the Romanian language pack; the protocol is :mod:`pii_guard.languages.inflection`, and
:mod:`pii_guard.languages.hu.inflection` is the fuller example of the optional methods.

Romanian marks the genitive/dative of a name in two ways:

- a feminine name in ``-a`` changes its stem: ``Maria`` -> ``Mariei``, ``Ioana`` ->
  ``Ioanei``, ``Andreea`` -> ``Andreei``, and after ``c``/``g`` ``Monica`` -> ``Monicăi``,
  ``Olga`` -> ``Olgăi``; the vocative is ``Ioano``, ``Eleno``. :meth:`variant_stems`,
  :meth:`splits` and :meth:`restore` cover these, so every form maps to one vault entry
  keyed on the nominative: ``Mariei`` is ``[[PERSON_x]]ei`` and unmasks back to ``Mariei``;
  a suffix the model adds itself (``[[PERSON_x]]ei``) is re-inflected (``Mariei``, not
  ``Mariaei``).
- a masculine name or a surname takes the proclitic ``lui`` (``lui Popescu``), which needs no
  suffix, or the article ``-lui``/``-ului`` (``Popescului``, ``Radului``, ``Marinului``) and,
  colloquially, ``-l``/``-ul`` (``Popescul``); the vocative adds ``-le``/``-ule`` (``Radule``,
  ``Ionule``). These leave the name intact and stay outside the placeholder
  (:meth:`suffix_pattern`).

An acronym or code takes its ending after a hyphen (``SRL-ului``, ``BCR-ul``).

Limitation: only the *last* word of a value can change. A full name declines on its given
name (``Maria Popescu`` -> ``Mariei Popescu``), inside the value, which the vault's
``stem + suffix`` model cannot express without losing the round trip; a detected
``Mariei Popescu`` is masked as a value of its own, and ``Mariei`` alone, ``Popescu Mariei``
(surname first, as forms write it) and ``Popescului`` map onto their nominatives.

Values that end in a digit or another non-letter (numbers, e-mail addresses) take no ending.
"""

from __future__ import annotations

from pii_guard.languages.inflection import Split
from pii_guard.types import EntityType

__all__ = ["RomanianCaseMatcher"]

#: Entity types whose values decline like words, so their stem may change.
_STEM_CHANGE_TYPES = frozenset({EntityType.PERSON, EntityType.ADDRESS, EntityType.ORGANIZATION})
# After a final -u (Popescu, Radu): the article -l, the genitive/dative -lui, the vocative -le.
_AFTER_U = ("lui", "le", "l")
# After a consonant (Marin, Ion): -ul, -ului, -ule.
_AFTER_CONSONANT = ("ului", "ule", "ul")
# After an acronym or a code, with a hyphen: "SRL-ul", "SRL-ului", "BCR-ului".
_HYPHENATED = ("ului", "ul", "lui")
_VOWELS = frozenset("aăâeéiîouy")
# The shortest last word whose ending is read off by a split ("Ana" + "ei" -> "Anei", but a
# three-letter word ending in -ei, -ul ... is not split).
_MIN_SPLIT_LETTERS = 4


def _alternation(endings: tuple[str, ...]) -> str:
    return "(?:" + "|".join(sorted(endings, key=len, reverse=True)) + ")"


def _last_word(value: str) -> str:
    words = value.split()
    return words[-1] if words else ""


def _word_like(value: str) -> bool:
    """A name-like last word: letters (and hyphens) only, three or more letters, not capitals."""
    last = _last_word(value)
    letters = sum(ch.isalpha() for ch in last)
    return (
        "@" not in value
        and letters >= 3
        and all(ch.isalpha() or ch == "-" for ch in last)
        and not last.isupper()
    )


def _feminine_endings(value: str) -> tuple[str, list[str]] | None:
    """``(stem, endings)`` of a value whose last word ends in ``-a``, else ``None``.

    ``Maria`` -> ``("Mari", ["ei"])``, ``Ioana`` -> ``("Ioan", ["ei", "o"])``, ``Monica`` ->
    ``("Monic", ["ăi", "o"])``, ``Andreea`` -> ``("Andree", ["i"])``. Not the vocative ``-o``
    after ``-i``: ``Maria`` -> ``Mario`` and ``Antonia`` -> ``Antonio`` are other names.
    """
    folded = value.casefold()
    if not folded.endswith("a") or folded.endswith(("ăa", "âa")):
        return None
    stem = value[:-1]
    if folded.endswith("ea"):
        return stem, ["i"]
    if folded.endswith(("ca", "ga")):
        return stem, ["ăi", "o"]
    if folded.endswith("ia"):
        return stem, ["ei"]
    return stem, ["ei", "o"]


class RomanianCaseMatcher:
    """Romanian case endings, with the stem change of a final ``-a``."""

    def suffix_pattern(self, value: str, entity_type: EntityType) -> str:
        value = value.rstrip()
        if not value or not value[-1].isalpha():
            return ""
        last = _last_word(value)
        if last.isupper() and len(last) >= 2:
            return "-" + _alternation(_HYPHENATED)  # SRL-ului, BCR-ul
        final = value[-1].casefold()
        if final == "u":
            return _alternation(_AFTER_U)
        if final in _VOWELS:
            return ""  # -a changes its stem (variant_stems); -i, -e, -o take "lui" before them
        return _alternation(_AFTER_CONSONANT)

    def variant_stems(self, value: str, entity_type: EntityType) -> list[tuple[str, str]]:
        """``(changed stem as written, regex of the endings that must follow it)``."""
        value = value.strip()
        if entity_type not in _STEM_CHANGE_TYPES or not value or not _word_like(value):
            return []
        found = _feminine_endings(value)
        if found is None:
            return []
        stem, endings = found
        return [(stem, _alternation(tuple(endings)))]

    def splits(self, surface: str, entity_type: EntityType) -> list[Split]:
        """Readings of ``surface`` as an inflected form, strong ones first.

        Strong (unambiguous, no nominative name ends this way): ``-iei`` (``Mariei``),
        ``-eei`` (``Andreei``), ``-căi``/``-găi`` (``Monicăi``) and ``-escului``/``-eanului``
        (``Popescului``; ``Radului`` is weak). Weak, applied only when the lemma is
        confirmed: any other ``-ei`` (``Ioanei``; ``Andrei`` and ``Matei`` are nominatives) and
        the endings that leave the stem intact (``-lui``, ``-ului``, ``-ul``, ``-l``, ``-ule``,
        ``-le``). A vocative ``-o`` is not split (``Marco``, ``Bruno`` are names, and their
        ``-a`` readings ``marca``, ``Bruna`` are words or other names): the vault finds
        ``Ioano`` from a confirmed ``Ioana`` through :meth:`variant_stems`.
        """
        surface = surface.strip()
        if entity_type not in _STEM_CHANGE_TYPES or not surface or not _word_like(surface):
            return []
        if sum(ch.isalpha() for ch in _last_word(surface)) < _MIN_SPLIT_LETTERS:
            return []
        folded = surface.casefold()
        found: list[Split] = []

        def add(cut: int, lemma: str, strong: bool = False) -> None:
            if sum(ch.isalpha() for ch in _last_word(lemma)) >= 3:
                found.append(Split(lemma, surface[:cut], surface[cut:], strong))

        n = len(surface)
        if folded.endswith(("căi", "găi")):
            add(n - 2, surface[:-2] + "a", strong=True)  # Monic|ăi -> Monica
        elif folded.endswith("eei"):
            add(n - 1, surface[:-1] + "a", strong=True)  # Andree|i -> Andreea
        elif folded.endswith("ei"):
            # Mari|ei -> Maria (strong); Ioan|ei -> Ioana (weak: Andrei, Matei are names).
            add(n - 2, surface[:-2] + "a", strong=folded.endswith("iei"))
        # Endings after an unchanged stem.
        if folded.endswith(("escului", "eanului")):
            add(n - 3, surface[:-3], strong=True)  # Popescu|lui
        elif folded.endswith("ului"):
            add(n - 3, surface[:-3])  # Radu|lui
            add(n - 4, surface[:-4])  # Marin|ului
        elif folded.endswith("ule"):
            add(n - 2, surface[:-2])  # Radu|le
            add(n - 3, surface[:-3])  # Ion|ule
        elif folded.endswith("ul"):
            add(n - 1, surface[:-1])  # Popescu|l
            add(n - 2, surface[:-2])  # Marin|ul
        unique = list(dict.fromkeys(found))
        return sorted(unique, key=lambda split: not split.strong)

    def restore(self, lemma: str, suffix: str, entity_type: EntityType) -> str:
        """``lemma`` inflected for ``suffix`` as it follows a placeholder: ``stem + suffix``.

        ``Maria`` + ``ei`` -> ``Mariei``; ``Monica`` + ``ei`` or ``ăi`` -> ``Monicăi``;
        ``Andreea`` + ``ei`` or ``i`` -> ``Andreei``; ``Ioana`` + ``o`` -> ``Ioano``;
        ``Popescu`` + ``ului`` -> ``Popescului``; a hyphen the model put before the ending of a
        name is dropped (``Maria`` + ``-ei`` -> ``Mariei``). Anything else is ``lemma + suffix``.
        """
        if not suffix or not lemma or not lemma[-1].isalpha():
            return lemma + suffix
        if entity_type not in _STEM_CHANGE_TYPES or not _word_like(lemma):
            return lemma + suffix
        ending = suffix[1:] if suffix.startswith("-") else suffix
        folded = ending.casefold()
        found = _feminine_endings(lemma)
        if found is not None:
            stem, endings = found
            if folded in {"ei", "ăi", "i"} and folded not in endings:
                # The model wrote another genitive ending: use the one this name takes.
                written = next(e for e in endings if e != "o")
                return stem + (written.upper() if ending.isupper() else written)
            if folded in endings:
                return stem + ending
            return lemma + suffix
        if lemma[-1].casefold() == "u" and folded in {"ului", "ul", "ule"}:
            return lemma + ending[1:]  # Popescu + ului -> Popescului
        if ending != suffix and folded in {*_AFTER_U, *_AFTER_CONSONANT}:
            return lemma + ending
        return lemma + suffix
