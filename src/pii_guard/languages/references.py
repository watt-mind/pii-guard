"""Reference words: labels that make a number a business number, not personal data.

An order, invoice, tracking or SKU label right before a validated number (a checksum-valid
tax ID, a Luhn-valid card) makes it a business reference, not personal data
(:func:`pii_guard.detect.rules._base.reference_or_amount_before`); an NER number right after
one is dropped by :mod:`pii_guard.detect.ner_numbers` (LAB-1293). Both lists used to live in
code (:data:`~pii_guard.detect.rules._base._REFERENCE_WORD`,
:data:`~pii_guard.detect.ner_numbers._NEGATIVE`); they are language-pack data now
(``references.tsv`` next to ``cues.tsv``), so a new pack's reference words reach both checks
(LAB-1345, ADR 0008).

File format (one entry per line, ``#`` comments, blank lines ignored)::

    order*
    sygn. akt
    Betrag*	weak

- a trailing ``*`` lets the word take suffixes (``order*``: ``orders``, ``Bestellnummer``)
  and a leading ``*`` lets it follow word characters (``*rendelés*``: ``megrendelés``,
  ``előrendelés``); the NER check reads explicit stems only, so prefix forms it needs are
  listed separately;
- entries may hold spaces and dots (``sygn. akt``); digits are rejected;
- an optional second column scopes the entry: ``both`` (the default: the rules check and the
  NER check), ``rules`` (the rules check only) or ``ner`` (the NER check only).

Amount words (``amount``, ``Betrag``, ``összeg``) and generic reference words (``reference``,
``case``) are poor negative cues in real text (LAB-1293): an account or ID number often
follows those words (``payment reference: <IBAN>``). They are marked ``weak``: the NER check
ignores them (as before), while the rules check still honors them, because pinned
reference-cue tests require ``Reference:``/``Total:``/``Amount`` skips and dropping them
would newly mask previously skipped spans. A trailing ``.`` matches with or without the dot
(``sygn``/``sygn.``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib.resources.abc import Traversable

__all__ = [
    "Reference",
    "accent_pattern",
    "load_references",
    "pack_references",
    "parse_references",
    "reference_alternation",
]

#: Scopes of a reference entry: both checks, the rules check only, the NER check only.
SCOPES = ("both", "rules", "ner")


@dataclass(frozen=True, slots=True)
class Reference:
    """One line of ``references.tsv``: the word, its affixes and its scope."""

    text: str
    #: a leading ``*`` in the file: the word may follow word characters (``*rendelés*``).
    prefix: bool = False
    #: a trailing ``*`` in the file: the word takes suffixes (``order*``).
    suffix: bool = False
    #: ``weak`` in the file: a poor negative cue (LAB-1293), honored by the rules check only.
    weak: bool = False
    #: ``rules``/``ner`` in the file (``both`` by default): which checks read the entry.
    scope: str = "both"


_REFERENCE_TEXT_RE = re.compile(r"^[^\W\d_](?:[^\W\d]|[ .'\-/#])*(?:[^\W\d_]|[.#])?$")


def parse_references(text: str) -> tuple[Reference, ...]:
    """Parse a ``references.tsv``: ``word[*][<TAB>scope]``; ``#`` comments.

    The scope is ``both``, ``rules``, ``ner`` or ``weak`` (``weak`` is ``rules`` plus the
    LAB-1293 poor-cue mark). Raises :class:`ValueError` (with the line number) on a malformed
    line or an entry listed twice.
    """
    out: list[Reference] = []
    seen: dict[tuple[str, bool, bool, str], int] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in raw.split("\t")]
        if len(parts) > 2 or not parts[0]:
            raise ValueError(f"line {number}: expected 'word[*][<TAB>scope]'")
        word, scope = parts[0], (parts[1] if len(parts) == 2 else "both")
        weak = scope == "weak"
        if weak:
            scope = "rules"
        if scope not in SCOPES:
            raise ValueError(f"line {number}: scope must be one of {', '.join([*SCOPES, 'weak'])}")
        suffix = word.endswith("*")
        word = word.removesuffix("*")
        prefix = word.startswith("*")
        word = word.removeprefix("*").strip()
        if not _REFERENCE_TEXT_RE.match(word):
            raise ValueError(f"line {number}: entry must start with a letter and hold no digits")
        key = (word.casefold(), prefix, suffix, scope)
        if key in seen:
            raise ValueError(f"line {number}: entry already listed on line {seen[key]}")
        seen[key] = number
        out.append(Reference(word, prefix, suffix, weak, scope))
    return tuple(out)


def load_references(resource: Traversable) -> tuple[Reference, ...]:
    """Read a language pack's ``references.tsv`` (see :func:`parse_references`)."""
    return parse_references(resource.read_text(encoding="utf-8"))


def pack_references() -> tuple[tuple[str, tuple[Reference, ...]], ...]:
    """``(code, references)`` for every pack with a ``references.tsv``, in pack order."""
    from pii_guard.languages import packs

    return tuple(
        (code, load_references(pack.references))
        for code, pack in packs().items()
        if pack.references is not None
    )


#: Accent classes per language code: the unaccented spellings a pack word also matches.
#: Kept to what the hard-coded lists matched (LAB-1345): Hungarian ``rendelés``/``rendeles``,
#: Polish ``zamówieni``/``zamowieni``. German umlauts are distinct letters (``Betrag`` never
#: matches the verb ``beträgt``), so ``de`` (and ``en``) expand nothing. A new pack uses
#: :data:`_DEFAULT_EXPANSION`.
_EXPANSION: dict[str, dict[str, str]] = {
    "hu": {"a": "[aá]", "e": "[eé]", "o": "[oó]"},
    "pl": {"o": "[oó]", "l": "[lł]"},
    "de": {},
    "en": {},
}

#: Expansion for a pack in a new language: every base letter matches its accented forms.
_DEFAULT_EXPANSION = {
    "a": "[aáàâäãą]",
    "c": "[cćč]",
    "d": "[dď]",
    "e": "[eéèêëę]",
    "i": "[iíìîï]",
    "l": "[lł]",
    "n": "[nńň]",
    "o": "[oóòôöőõ]",
    "r": "[rř]",
    "s": "[sśš]",
    "u": "[uúùûüűů]",
    "y": "[yýÿ]",
    "z": "[zźżž]",
}

#: Accented letters folded to their base before expanding, per language code: only what
#: the hard-coded lists matched. Anything else stays literal (``ö`` in Hungarian, umlauts in
#: German), so the expansion never matches a word the lists did not.
_FOLD_MAP: dict[str, dict[str, str]] = {
    "hu": {"á": "a", "é": "e", "ó": "o"},
    "pl": {"ó": "o", "ł": "l"},
    "de": {},
    "en": {},
}


def expansion_for(code: str) -> tuple[dict[str, str], dict[str, str]]:
    """The accent classes and fold map of the pack ``code`` (see :data:`_EXPANSION`)."""
    from pii_guard.languages import primary_language

    code = primary_language(code)
    return _EXPANSION.get(code, _DEFAULT_EXPANSION), _FOLD_MAP.get(code, {})


def accent_pattern(word: str, language: str = "und") -> str:
    """``word`` as a regex fragment matching its accented and unaccented spellings.

    ``language`` picks the pack's accent classes (see :data:`_EXPANSION`); ``"und"``
    expands every base letter. Either spelling in the file expands the same.
    """
    classes, fold_map = expansion_for(language)
    parts = []
    for index, char in enumerate(word):
        if char == ".":
            # A trailing dot is optional ("sygn"/"sygn."); inside a word it is literal.
            parts.append(r"\.?" if index == len(word) - 1 else re.escape(char))
        elif char == " ":
            parts.append(r"[ \t]+")
        else:
            alternate = classes.get(fold_map.get(char, char).casefold())
            parts.append(alternate if alternate is not None else re.escape(char))
    return "".join(parts)


def reference_alternation(entries: list[Reference], language: str = "und") -> str:
    """One alternation for the rules check covering ``entries``, longest first.

    A ``*`` entry takes word suffixes (and a leading ``*`` word prefixes); a plain entry
    matches the word as written. Entries match their accented and unaccented spellings in
    ``language``'s accent classes (see :data:`_EXPANSION`). Like the list it replaces,
    entries match inside a longer word only through the caller's own boundaries.
    """
    ordered = sorted(entries, key=lambda e: len(e.text), reverse=True)
    return "|".join(
        (r"\w*" if e.prefix else "")
        + accent_pattern(e.text, language)
        + (r"\w*" if e.suffix else "")
        for e in ordered
    )
