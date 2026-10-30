"""Person names inside Hungarian company names: ``Tóth és Társa Bt.``, ``Horváth Emese e.v.``.

A sole trader's business name *is* the person's name (``Horváth Emese e.v.``, ``Balogh Ernő
egyéni vállalkozó``), and small partnerships and companies are often named after their members
(``Tóth és Társa Bt.``, ``Balogh és Fia Kkt.``, ``Kiss-Lukács Kft.``, ``Molnár Péter Bt.``).
The NER tags the whole name ``ORGANIZATION``, which policy keeps, so without this rule the
person's name would reach the upstream model unmasked in fast mode. The rule emits a
``PERSON`` span for the **name part only**; the resolver gives it priority over the kept
organisation (``detect/pipeline.py``), so the text becomes ``[[PERSON_x]] és Társa Bt.``.

The rule is anchored on a legal form (``e.v.``, ``ev.``, ``egyéni vállalkozó``, ``Bt.``,
``Kkt.``, ``Kft.``, ``Zrt.``, ``Nyrt.``, ``Kht.``, ``Nonprofit Kft.``, with or without the
full stop, any case, also inflected: ``Bt.-nek``, ``Kft-vel``, ``egyéni vállalkozónak``) and
looks at the capitalised words right before it, with the pack's surname and given-name
lexicons:

- **Sole traders** always name a person: a surname + given name is masked at 0.9; without a
  lexicon match the (up to three) words before the form are masked at 0.7, the legal form is
  evidence enough.
- **Surname + given name** (``Molnár Péter Bt.``, ``Fekete Anna Kft.``): 0.9, in any form.
- **A family connector** (``és Társa``, ``és Fia``, ``& Társa``): the surname before it, 0.85;
  an unknown word before ``és Fia`` / ``és Lánya`` still names a parent, 0.7. Two surnames
  joined by ``és`` (``Varga és Kiss Kkt.``): both, 0.85.
- **A bare surname** (``Horváth Bt.``, ``Kiss-Lukács Kft.``) or a surname leading a business
  name (``Mészáros Építő Kft.``): 0.8 / 0.75.

**False positives: surnames that are ordinary words.** ``Nagy``, ``Kis``, ``Fekete``,
``Magyar``, ``Szép``, occupational names (``Szabó``, ``Molnár``, ``Kovács``, ``Varga``),
demonyms and place adjectives (``Lengyel``, ``Budai``, ``Pécsi``) are everyday brand words:
``Fekete Kavics Kft.``, ``Magyar Kalapács Zrt.``, ``Pécsi Kerámia Kft.``. Such a word alone is
**not** taken as a person unless there is person evidence: a given name next to it (``Fekete
Anna Kft.``, but not a given name that is itself a common word: ``Vörös Rózsa Kft.``), a family
connector (``Szabó és Fiai Kkt.``), a sole-trader form, or a partnership form on a bare
surname (``Kis Bt.``, 0.7: a Bt./Kkt. name traditionally carries a member's name, a Kft./Zrt.
name does not). So ``Fekete Kft.`` and ``Kovács Autószerviz Kft.`` stay unmasked: a miss when
they *are* named after a person, accepted to keep ordinary company names intact. Lower-case
names (``kovács bt.``) are left to the NER and the LLM.

**Law, notary and patent attorney offices** (LAB-1175): ``Somogyi Ügyvédi Iroda``, ``Dr. Takács
Közjegyzői Iroda``, ``Mintás és Társa Ügyvédi Iroda``, ``Szilágyi Szabadalmi Ügyvivői Iroda``,
also inflected (``Ügyvédi Irodával``) and in lower case (``Somogyi ügyvédi irodát``). Such an
office is named after its members, so the office words are person evidence the way a
sole-trader form is: a common-word surname (``Somogyi``, ``Kovács``) is masked at 0.8, and an
unknown word that is not an everyday or place word (``Mintás``) at 0.7. A place adjective or
ordinary word alone (``Budapesti Ügyvédi Iroda``) and the office words without a name
(``Tisztelt Ügyvédi Iroda!``, ``Ügyvédi Kamara``) stay kept. Without the rule the NER keeps the
whole office as an ``ORGANIZATION`` and the lawyer's masked surname reaches the model.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from functools import cache

from pii_guard.detect.rules._base import _Hit
from pii_guard.lang import LexiconUnavailable, lexicon
from pii_guard.types import EntityType

__all__ = ["family_word_in_firm", "find_company_person"]

_UPPER = "A-ZÁÉÍÓÖŐÚÜŰ"

# The legal form. Not part of a longer word; a hyphenated case suffix may follow ("Bt.-nek").
_FORM_RE = re.compile(
    r"(?<![\w.\-])"
    r"(?:"
    r"(?P<company>(?:nonprofit[ \t]+)?(?:kft|zrt|nyrt|kht)\.?)"
    r"|(?P<partnership>(?:bt|kkt)\.?)"
    r"|(?P<sole>e\.[ \t]?v\.|ev\.|egyéni[ \t]+vállalkoz[óo]\w*)"
    r"|(?P<office>(?:ügyvédi|közjegyzői|szabadalmi[ \t]+ügyvivői)[ \t]+irod\w*)"
    r")"
    r"(?![^\W_])",
    re.IGNORECASE,
)

# The capitalised words right before the form, on the same line, with at most one connector.
_WORD = rf"[{_UPPER}][^\W\d_]*(?:-[{_UPPER}][^\W\d_]*)*"
_CONNECTOR = r"(?:és|ÉS|És|&|\+)"
_NAME_PART_RE = re.compile(
    rf"(?<![\w\-])(?P<part>{_WORD}(?:[ \t]+(?:{_CONNECTOR}[ \t]+)?{_WORD}){{0,5}})"
    r"(?:[ \t]*,[ \t]*|[ \t]+)$"
)
_TOKEN_RE = re.compile(rf"{_WORD}|{_CONNECTOR}")
_WINDOW = 160

# Capitalised words that end a name part: articles, salutations and legal-form words.
_STOP = frozenset(
    {"a", "az", "egy", "tisztelt", "kedves", "alulírott", "kft", "bt", "kkt", "zrt", "nyrt"}
    | {"kht", "nonprofit", "ev", "dr", "ifj", "id", "özv"}
)
_FAMILY = frozenset(
    {"társa", "társai", "testvérei", "testvérek", "utóda", "utódai", "partnere", "partnerei"}
)
_CHILDREN = frozenset({"fia", "fiai", "lánya", "lányai", "fiaik"})

# Surnames that are also everyday words, beyond the pack's ``common_word_surnames`` list:
# demonyms, regions and adjectives that name businesses as often as people.
_ALSO_COMMON = frozenset(
    {
        "lengyel", "orosz", "török", "cseh", "székely", "kun", "oláh", "budai", "pesti",
        "erdélyi", "somogyi", "szilágyi", "zalai", "alföldi", "hosszú", "csonka", "nemes",
        "tompa", "madár", "varjú", "darázs", "oroszlán", "polgár", "huszár", "kalmár",
        "kőműves", "jámbor", "lovas", "mezei", "erdős", "földes", "szarka", "gyenes", "vidám",
    }
)  # fmt: skip
# Given names that are also common nouns (flowers, colours): no person evidence next to a
# common-word surname ("Vörös Rózsa Kft." is a flower shop, "Fekete Anna Kft." a person).
_COMMON_GIVEN = frozenset(
    {"rózsa", "ibolya", "viola", "virág", "barna", "hajnal", "szende", "jázmin", "liliom"}
)

SCORE_FULL_NAME = 0.9
SCORE_FAMILY = 0.85
SCORE_BARE_SURNAME = 0.8
SCORE_LEADING_SURNAME = 0.75
SCORE_WEAK = 0.7


@cache
def _lexicons() -> tuple[frozenset[str], frozenset[str], frozenset[str], frozenset[str]]:
    """Surnames, given names, common-word surnames and settlements, case-folded."""

    def load(kind: str) -> frozenset[str]:
        try:
            return frozenset(e.casefold() for e in lexicon(kind, "hu"))
        except LexiconUnavailable:  # pragma: no cover - the lists ship with the package
            return frozenset()

    given = load("given_names_m") | load("given_names_f")
    return load("surnames"), given, load("common_word_surnames"), load("settlements")


def _parts(word: str) -> list[str]:
    return [p for p in word.casefold().split("-") if p]


def _is_surname(word: str) -> bool:
    surnames = _lexicons()[0]
    return all(p in surnames for p in _parts(word))


def _is_common(word: str) -> bool:
    """Every part of ``word`` is also an ordinary word or a place adjective (``Pécsi``)."""
    _, _, common, settlements = _lexicons()
    return all(
        p in common or p in _ALSO_COMMON or (p.endswith("i") and p[:-1] in settlements)
        for p in _parts(word)
    )


def _is_given(word: str) -> bool:
    given = _lexicons()[1]
    folded = word.casefold()
    # A married name: "Jánosné" (Mrs János ...).
    return folded in given or (folded.endswith("né") and folded[:-2] in given)


def _is_member(word: str) -> bool:
    """A word an office name takes as a member's surname: any surname, or no everyday word."""
    return _is_surname(word) or not _is_common(word)


def _full_name(words: Sequence[str], i: int) -> int:
    """End (exclusive) of a surname + given name(s) run starting at ``i``, or ``i``."""
    j = i + 1
    while j < len(words) and j - i <= 2 and _is_given(words[j]):
        j += 1
    if j == i + 1:
        return i
    if _is_common(words[i]) and all(w.casefold() in _COMMON_GIVEN for w in words[i + 1 : j]):
        return i
    return j


def _persons(words: Sequence[str], kind: str) -> list[tuple[int, int, float]]:
    """Person runs ``(first, end, score)`` in ``words`` (no connectors) before a ``kind`` form."""
    n = len(words)
    runs: list[tuple[int, int, float]] = []
    i = 0
    while i < n:
        end = _full_name(words, i)
        if end > i and _is_surname(words[i]):
            runs.append((i, end, SCORE_FULL_NAME))
            i = end
        else:
            i += 1
    if runs:
        return runs
    # An unknown surname with a given name, as the whole name: "Ördögh Tamás Bt.".
    if n >= 2 and _full_name(words, 0) == n:
        return [(0, n, SCORE_BARE_SURNAME)]
    if kind == "sole":
        return [(max(0, n - 3), n, SCORE_WEAK)]
    if kind == "office":  # named after its members: every name-like word is one
        return [
            (k, k + 1, SCORE_BARE_SURNAME if _is_surname(w) else SCORE_WEAK)
            for k, w in enumerate(words)
            if _is_member(w)
        ]
    first = words[0]
    if not _is_surname(first):
        return []
    if not _is_common(first):
        return [(0, 1, SCORE_BARE_SURNAME if n == 1 else SCORE_LEADING_SURNAME)]
    if n == 1 and kind == "partnership":
        return [(0, 1, SCORE_WEAK)]
    return []


def _trailing_person(words: Sequence[str], children: bool) -> tuple[int, float] | None:
    """The person at the end of ``words`` before ``és Társa`` / ``és Fia``: (first, score)."""
    if (
        len(words) >= 2
        and _is_surname(words[-2])
        and _full_name(words, len(words) - 2) == len(words)
    ):
        return len(words) - 2, SCORE_FULL_NAME
    if _is_surname(words[-1]):
        return len(words) - 1, SCORE_FAMILY
    if children:
        return len(words) - 1, SCORE_WEAK
    return None


# A family word's left and right context in a firm name: a connector right before it, then up
# to two capitalised business words and a legal form after it ("és Fia Építő Kft.").
_CONNECTOR_BEFORE_RE = re.compile(rf"(?<![\w\-]){_CONNECTOR}[ \t]+$")
_WORDS_BEFORE_FORM_RE = re.compile(rf"[ \t]+(?:{_WORD}[ \t]+){{0,2}}")


def family_word_in_firm(text: str, start: int, end: int) -> bool:
    """Whether ``text[start:end]`` is the family word of a firm name (``és Fia Kkt.``).

    ``Fia`` / ``Fiai`` / ``Társa`` in ``Balogh és Fia Kkt.`` say "and son(s)" / "and partner":
    a relation, not a person's name (LAB-1220). True only for the bare word (any case), with
    a connector (``és``, ``&``, ``+``) right before it and a legal form after it, optionally
    after up to two capitalised business words (``és Lánya Építő Kft.``).
    """
    if text[start:end].casefold() not in _FAMILY | _CHILDREN:
        return False
    if _CONNECTOR_BEFORE_RE.search(text, max(0, start - 8), start) is None:
        return False
    gap = _WORDS_BEFORE_FORM_RE.match(text, end, min(len(text), end + 60))
    if gap is None:
        return False
    form = _FORM_RE.match(text, gap.end())
    return form is not None and _kind(form) in ("partnership", "company", "office")


def _kind(form: re.Match[str]) -> str:
    return next(k for k in ("sole", "office", "partnership", "company") if form.group(k))


def find_company_person(text: str) -> Iterator[_Hit]:
    """``PERSON`` hits for the name part of company names with a Hungarian legal form."""
    for form in _FORM_RE.finditer(text):
        lo = max(0, form.start() - _WINDOW)
        part = _NAME_PART_RE.search(text, lo, form.start())
        if part is None:
            continue
        tokens = list(_TOKEN_RE.finditer(text, part.start("part"), part.end("part")))
        # Keep what follows the last article, salutation or legal-form word.
        for k in range(len(tokens) - 1, -1, -1):
            if tokens[k].group().casefold().rstrip(".") in _STOP:
                tokens = tokens[k + 1 :]
                break
        while tokens and re.fullmatch(_CONNECTOR, tokens[0].group()):
            tokens = tokens[1:]  # "Fodor Bt és Gulyás Kkt": "és" starts no name
        # The name part starts and ends with a word, so a connector has words on both sides.
        connectors = [k for k, t in enumerate(tokens) if re.fullmatch(_CONNECTOR, t.group())]
        spans: list[tuple[int, int, float]] = []  # token index ranges
        if connectors:
            c = connectors[-1]
            left = [t.group() for t in tokens[:c]]
            right = [t.group() for t in tokens[c + 1 :]]
            after = right[0].casefold() if len(right) == 1 else ""
            if after in _FAMILY or after in _CHILDREN:
                # An office's "és Társa" names a member even with an unknown surname.
                children = after in _CHILDREN or (_kind(form) == "office" and _is_member(left[-1]))
                found = _trailing_person(left, children=children)
                if found is not None:
                    spans.append((found[0], c, found[1]))
            elif len(right) == 1 and (
                (
                    _is_surname(left[-1])
                    and _is_surname(right[0])
                    and (
                        _kind(form) != "company"
                        or not (_is_common(left[-1]) and _is_common(right[0]))
                    )
                )
                or (_kind(form) == "office" and _is_member(left[-1]) and _is_member(right[0]))
            ):
                spans += [(c - 1, c, SCORE_FAMILY), (c + 1, c + 2, SCORE_FAMILY)]
            else:  # "Fodor Bt és Gulyás Kkt": only the words after the connector name this one
                offset = c + 1
                spans += [(offset + a, offset + b, s) for a, b, s in _persons(right, _kind(form))]
        elif tokens:
            spans = _persons([t.group() for t in tokens], _kind(form))
        for first, end, score in spans:
            yield _Hit(tokens[first].start(), tokens[end - 1].end(), EntityType.PERSON, score)
