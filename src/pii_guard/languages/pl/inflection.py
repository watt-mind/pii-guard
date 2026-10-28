"""Polish inflection: case endings that attach to a name without changing it (vault, LLM
alignment).

Polish declines names in seven cases. Many forms are the name as written plus an ending:
``Nowak`` -> ``Nowaka``, ``Nowakowi``, ``Nowakiem``, ``Nowaku``; ``Kowalski`` ->
``Kowalskiego``, ``Kowalskiemu``, ``Kowalskim``. The ending stays outside the placeholder
(``[[PERSON_7f3a]]a``). Forms whose stem changes (``Anna`` -> ``Annie``, ``Kowalska`` ->
``Kowalskiej``, ``Marek`` -> ``Marka``) are not matched from the base form: the NER and LLM
passes find each written form, and the vault masks each one it is given.

Values that end in a digit or another non-letter (codes, numbers) take no ending.
"""

from __future__ import annotations

from pii_guard.types import EntityType

__all__ = ["PolishCaseMatcher"]

# After a consonant: genitive/accusative -a, dative -owi, instrumental -em/-iem, locative and
# vocative -u/-ie, and the plural (the family: "Nowakowie", "u Nowaków", "z Nowakami").
_CONSONANT_ENDINGS = ("owie", "owi", "ami", "ach", "iem", "em", "ów", "om", "a", "u", "ie")
# After an adjectival -i/-y surname (Kowalski, Zielony): -ego, -emu, -m, plural -ch.
_ADJECTIVE_ENDINGS = ("ego", "emu", "m", "ch")
_VOWELS = frozenset("aąeęioóuy")


def _alternation(endings: tuple[str, ...]) -> str:
    return "(?:" + "|".join(sorted(endings, key=len, reverse=True)) + ")"


class PolishCaseMatcher:
    """The case endings that leave a name's written form intact."""

    def suffix_pattern(self, value: str, entity_type: EntityType) -> str:
        value = value.rstrip()
        if not value or not value[-1].isalpha():
            return ""
        last = value[-1].casefold()
        if last in "iy" and value.casefold().endswith(("ski", "cki", "dzki", "ny", "wy", "ty")):
            return _alternation(_ADJECTIVE_ENDINGS)
        if last in _VOWELS:
            return ""  # the stem changes (Anna -> Annie): no ending is safe to attach
        return _alternation(_CONSONANT_ENDINGS)
