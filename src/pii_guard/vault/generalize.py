"""Opt-in context generalization: blur the readable context around placeholders (LAB-1152).

A placeholder hides a value, but the words around it still narrow down who or what it is:
``Ms [[PERSON_7f3a9c]]`` says the person is a woman, ``[[PERSON_7f3a9c]]nek`` says the
Hungarian name ends in a front vowel, ``42 years old`` pins the birth year to two candidates.
Against an attacker who already holds a short list of candidates (the ``decoys`` red-team
context, ``docs/evaluation.md``), such clues raise linkage well above chance.

:func:`generalize_context` rewrites the masked text (what goes upstream), never a
placeholder:

- ``gender_title``: gendered titles next to a ``PERSON`` placeholder are dropped (``Mr``,
  ``Mrs``, ``Ms``, ``Miss``, ``Sir``, ``Madam``; German ``Herr``/``Herrn``/``Frau``; Hungarian
  ``úr``/``asszony``/``kisasszony``/``hölgy`` after the name, keeping the case suffix). German
  salutations whose adjective is gendered become neutral ones (``Sehr geehrte Frau X`` ->
  ``Guten Tag X``, ``Lieber X`` -> ``Hallo X``).
- ``age``: an age in years is coarsened to its decade (``42 years old`` -> ``40-49 years old``,
  ``42 éves``, ``42 Jahre alt``, ``42-year-old``).
- ``hu_harmony`` (Hungarian only): a case ending attached to a ``PERSON`` placeholder is
  written in its back-vowel form (``[[PERSON_x]]nek`` -> ``[[PERSON_x]]nak``, ``-ről`` ->
  ``-ról``, ``-et``/``-öt`` -> ``-ot``), and an assimilated ``-val``/``-vá``
  (``[[PERSON_x]]csal``, which spells the name's last consonant) becomes ``-val``/``-vá``. The
  Hungarian matcher re-inflects a suffix the upstream model writes, so ``[[PERSON_x]]nak`` in
  an answer still restores ``Teszt Eleknek``.
- ``Kovácsné`` masked as ``[[PERSON_x]]né`` loses the married-name ``-né`` (``gender_title``).

The rewrite is one-way and lossy: the removed titles and the original suffix forms are not
restored in the answer. Gendered pronouns (``she``, ``his``), role words and organization
names are left alone; for the last, mask the default ``keep`` types too
(:data:`pii_guard.policy.LINKAGE_OVERRIDES`). The result reports how many rewrites each rule
made, never what was rewritten.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from pii_guard.vault.placeholders import PLACEHOLDER_RE

__all__ = ["RULES", "Generalized", "generalize_context"]

RULES = ("gender_title", "age", "hu_harmony")

_PERSON_AHEAD = r"(?=\[\[PERSON_[0-9a-f]{4,}\]\])"

# Capitalized forms only: lower-case "miss" is a verb ("I miss [[PERSON_x]]").
_EN_TITLE_RE = re.compile(
    r"\b(?:Mr|Mrs|Ms|Miss|Mister|Sir|Madam|Madame|Dame|Lady|Lord)\b\.?[ \t]+" + _PERSON_AHEAD
)
_DE_FORMAL_RE = re.compile(r"\bSehr geehrte[rs]?[ \t]+(?:(?:Herrn?|Frau)[ \t]+)?" + _PERSON_AHEAD)
_DE_INFORMAL_RE = re.compile(r"\bLieb(?:e|er|es)[ \t]+(?:(?:Herrn?|Frau)[ \t]+)?" + _PERSON_AHEAD)
_DE_TITLE_RE = re.compile(r"\b(?:Herrn?|Frau|Fräulein)[ \t]+" + _PERSON_AHEAD)
# "Kovácsné" masked as "[[PERSON_x]]né": the married-name suffix marks a woman.
_HU_NE_RE = re.compile(r"(\[\[PERSON_[0-9a-f]{4,}\]\])-?né(?!\w)")
# "[[PERSON_x]] úrnak" -> "[[PERSON_x]]-nak": the title's suffix moves onto the placeholder.
_HU_TITLE_RE = re.compile(
    r"(\[\[PERSON_[0-9a-f]{4,}\]\])[ \t]+(?:[úÚ]r|[aA]sszony|[kK]isasszony|[hH]ölgy)(\w*)"
)

_AGE_RE = re.compile(
    r"\b(\d{1,2}|1[01]\d|120)"
    r"(?=(?:[ \t]+|-)(?:years?[ \t]+old|year-old|éves|évesen|Jahre[ \t]+alt|jährig))"
)

# Case endings -> their back-vowel form (the Hungarian matcher re-inflects them on unmask).
_HU_BACK = {
    "nek": "nak",
    "ben": "ban",
    "be": "ba",
    "ből": "ból",
    "re": "ra",
    "ről": "ról",
    "nél": "nál",
    "hez": "hoz",
    "höz": "hoz",
    "től": "tól",
    "vel": "val",
    "vé": "vá",
    "en": "on",
    "ön": "on",
    "et": "ot",
    "öt": "ot",
}
_HU_SUFFIX_RE = re.compile(r"(?<=\[\[PERSON_)([0-9a-f]{4,}\]\])(\w+)")
# An assimilated -val/-vel or -vá/-vé spells the name's last consonant (Kováccsal, Elekkel).
_HU_ASSIMILATED_RE = re.compile(r"[bcdfghjklmnprstwxz]{1,3}(?:al|el|á|é)")
_HU_NOT_ASSIMILATED = frozenset({"nál", "nél", "tól", "ról", "ból", "hoz"})


@dataclass(frozen=True, slots=True)
class Generalized:
    """The rewritten text and how many rewrites each rule made (no text, no values)."""

    text: str
    rewrites: dict[str, int] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return any(self.rewrites.values())


def _decade(match: re.Match[str]) -> str:
    age = int(match.group(1))
    low = age - age % 10
    return f"{low}-{low + 9}"


def _hu_title(match: re.Match[str]) -> str:
    return match.group(1) + match.group(2)


def _hu_suffix(match: re.Match[str]) -> str:
    rest, suffix = match.group(1), match.group(2)
    folded = suffix.casefold()
    back = _HU_BACK.get(folded)
    if back is None and folded not in _HU_NOT_ASSIMILATED and _HU_ASSIMILATED_RE.fullmatch(folded):
        back = "val" if folded.endswith(("al", "el")) else "vá"
    if back is None or back == folded:
        return match.group(0)
    return rest + back


def generalize_context(text: str, language: str = "hu") -> Generalized:
    """Blur gender, age and inflection clues around the placeholders of a masked text.

    Placeholders are never changed: the result contains exactly the placeholders of
    ``text`` in the same order, so unmasking an answer works as before.
    """
    counts: Counter[str] = Counter()
    out = text
    for rule, pattern, repl in (
        ("gender_title", _DE_FORMAL_RE, "Guten Tag "),
        ("gender_title", _DE_INFORMAL_RE, "Hallo "),
        ("gender_title", _DE_TITLE_RE, ""),
        ("gender_title", _EN_TITLE_RE, ""),
        ("gender_title", _HU_NE_RE, r"\1"),
        ("gender_title", _HU_TITLE_RE, _hu_title),
        ("age", _AGE_RE, _decade),
    ):
        out, n = pattern.subn(repl, out)
        counts[rule] += n
    if language.split("-")[0].casefold() == "hu":
        changed = 0

        def harmonize(match: re.Match[str]) -> str:
            nonlocal changed
            new = _hu_suffix(match)
            changed += new != match.group(0)
            return new

        out = _HU_SUFFIX_RE.sub(harmonize, out)
        counts["hu_harmony"] += changed
    if [m.group(0) for m in PLACEHOLDER_RE.finditer(out)] != [
        m.group(0) for m in PLACEHOLDER_RE.finditer(text)
    ]:  # a rule touched a placeholder: a bug, never send the result
        raise RuntimeError("context generalization changed a placeholder")
    return Generalized(text=out, rewrites={rule: counts[rule] for rule in RULES})
