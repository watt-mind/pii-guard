"""Hungarian inflection: case suffixes and the stem changes they cause (vault, LLM alignment).

Part of the Hungarian language pack. The protocol and the module-level helpers that use these
optional methods live in :mod:`pii_guard.languages.inflection` and
:mod:`pii_guard.vault.inflection`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

from pii_guard.languages.inflection import Split
from pii_guard.types import EntityType

__all__ = ["HungarianSuffixMatcher"]


# Case endings that attach to the unchanged stem (vowel-harmony variants listed together).
_HU_SUFFIXES: tuple[str, ...] = (
    "nak", "nek",                      # dative
    "ban", "ben", "ba", "be",          # inessive, illative
    "ból", "ből",                      # elative
    "hoz", "hez", "höz",               # allative
    "nál", "nél",                      # adessive
    "tól", "től",                      # ablative
    "ra", "re", "ról", "ről",          # sublative, delative
    "on", "en", "ön", "n",             # superessive
    "ig", "ért", "ként",               # terminative, causal-final, formal
    "ot", "et", "öt", "at", "t",       # accusative
    "éig", "ék", "éi", "é",            # possessive / family
)  # fmt: skip
_HU_VOWELS = frozenset("aáeéiíoóöőuúüű")
# Digraphs double their first letter (``Kovács`` -> ``Kováccsal``), so the stem changes.
_HU_DIGRAPHS = ("cs", "dz", "gy", "ly", "ny", "sz", "ty", "zs")
# Old-orthography endings (``Tóth``, ``Kovácz``) sound like ``t``/``c``: the assimilated
# ``-val``/``-vel`` is ``-tal`` (``Tóthtal``) / ``-cal`` (``Kováczcal``), not ``-hal``/``-zal``.
_HU_OLD_DIGRAPHS = ("th", "cz")


# Suffixes after a lengthened final vowel (``Zsuzsanná|nak``, ``Kendé|t``). ``-ként`` keeps
# the short vowel (``Annaként``) and is matched by the unchanged stem.
_HU_LENGTHENING: tuple[str, ...] = (
    "nak", "nek", "ban", "ben", "ba", "be", "ból", "ből", "hoz", "hez", "höz", "nál", "nél",
    "tól", "től", "ra", "re", "ról", "ről", "n", "ig", "ért", "t", "val", "vel", "vá", "vé",
    "é", "ék", "éi", "éig", "k", "i",
)  # fmt: skip
# Lengthened suffixes that are safe to split on their own (no Hungarian name ends in
# ``-ának``, ``-ével`` ...), by the vowel harmony of the lemma's final vowel.
_HU_STRONG = {
    "a": frozenset({"nak", "ban", "ból", "hoz", "nál", "tól", "ról", "val", "ért"}),
    "e": frozenset({"nek", "ben", "ből", "hez", "höz", "nél", "től", "ről", "vel", "ért"}),
}
_HU_LONG = {"a": "á", "e": "é", "A": "Á", "E": "É"}
_HU_SHORT = {v: k for k, v in _HU_LONG.items()}
# Endings after a doubled final consonant or digraph (``Elek|kel``, ``Kováccs|al``).
_HU_DOUBLED_ENDINGS = ("al", "el", "á", "é")
_HU_HYPHENATED = ("val", "vel", "vá", "vé")
_MIN_LEMMA_LETTERS = 2
# Stacked suffixes (LAB-1337): the possessive ``-é`` (``Ottóé``, "Ottó's"), the family plural
# ``-ék`` (``Ottóék``, "the Ottós") and the plural possessive ``-éi`` (``Ottóéi``) take a case
# ending of their own: ``Kerekes Ottóéknál``, ``Teszt Hajnáéknak``, ``Tihaméréit``. The ending
# keeps the name's vowel harmony (``Ottóéknál``, ``Péteréknél``), so both are listed. After the
# vowel of ``-é``/``-éi`` the instrumental keeps its ``v`` (``Ottóéval``); after ``-ék`` it
# doubles the ``k`` (``Ottóékkal``) and the accusative takes a linking vowel (``Ottóékat``).
_HU_AFTER_VOWEL: tuple[str, ...] = (
    "nak", "nek", "ban", "ben", "ba", "be", "ból", "ből", "hoz", "hez", "höz", "nál", "nél",
    "tól", "től", "ra", "re", "ról", "ről", "n", "ig", "ért", "ként", "t", "val", "vel", "vá",
    "vé",
)  # fmt: skip
_HU_AFTER_EK: tuple[str, ...] = (
    "nak", "nek", "ban", "ben", "ba", "be", "ból", "ből", "hoz", "hez", "höz", "nál", "nél",
    "tól", "től", "ra", "re", "ról", "ről", "on", "en", "ön", "ig", "ért", "ként", "at", "et",
    "kal", "kel", "ká", "ké", "é",
)  # fmt: skip
# Case endings after an unchanged stem that no Hungarian name ends in, so a detector span
# ending in one is trimmed without a confirmed lemma (LAB-1174). Not ``-nél`` (Kornél),
# ``-ért`` (Gellért), ``-ra``/``-re`` (Klára, Imre), ``-on``/``-en`` (Márton, Kelemen),
# ``-t`` (Bálint), ``-val``/``-vel`` (Percival): those need a lexicon name or a confirmed lemma.
_HU_UNAMBIGUOUS_ENDINGS = frozenset({
    "nak", "nek", "ban", "ben", "ból", "ből", "hoz", "hez", "höz",
    "nál", "tól", "től", "ról", "ről", "ként",
})  # fmt: skip


def _alternation(suffixes: Iterable[str]) -> str:
    return "|".join(re.escape(s) for s in sorted(set(suffixes), key=len, reverse=True))


#: ``-é``/``-ék``/``-éi`` with an optional case ending after them (no capturing group).
_HU_STACKED = (
    f"é(?:k(?:{_alternation(_HU_AFTER_EK)})?|i(?:{_alternation(_HU_AFTER_VOWEL)})?"
    f"|(?:{_alternation(_HU_AFTER_VOWEL)}))?"
)
_HU_LENGTHENING_RE = re.compile(f"{_HU_STACKED}|{_alternation(_HU_LENGTHENING)}")
_HU_STACKED_RE = re.compile(_HU_STACKED)


def _hu_digraph(value: str) -> str | None:
    folded = value.casefold()
    for digraph in _HU_DIGRAPHS:
        if folded.endswith(digraph) and len(value) > len(digraph):
            return digraph
    return None


def _hu_old_digraph(value: str) -> str | None:
    folded = value.casefold()
    for digraph in _HU_OLD_DIGRAPHS:
        if folded.endswith(digraph) and len(value) > len(digraph):
            return digraph
    return None


# Case endings by vowel harmony: (back, front unrounded, front rounded). Used to re-inflect a
# suffix whose harmony disagrees with the lemma (a model's slip, or context generalization
# writing every suffix in its back form, LAB-1152): Teszt Elek + nak -> Teszt Eleknek.
_HU_HARMONY: dict[str, tuple[str, str, str]] = {
    form: group
    for group in (
        ("nak", "nek", "nek"), ("ban", "ben", "ben"), ("ba", "be", "be"),
        ("ból", "ből", "ből"), ("hoz", "hez", "höz"), ("nál", "nél", "nél"),
        ("tól", "től", "től"), ("ra", "re", "re"), ("ról", "ről", "ről"),
        ("val", "vel", "vel"), ("vá", "vé", "vé"), ("on", "en", "ön"), ("ot", "et", "öt"),
    )
    for form in group
}  # fmt: skip
_HU_BACK_VOWELS = frozenset("aáoóuú")
_HU_ROUNDED_VOWELS = frozenset("öőüű")


def _hu_harmony_class(lemma: str) -> int | None:
    """0 back, 1 front unrounded, 2 front rounded, ``None`` when unsure.

    ``i``/``í`` are neutral: the vowel before them decides (``Emil`` -> front). A lemma whose
    last vowel is a neutral one after a back vowel (``Márti``, ``Dávid``) is ``None``: both
    ``-nak`` and ``-nek`` occur in writing, so the suffix as written is kept.
    """
    word = lemma.split()[-1].casefold() if lemma.split() else ""
    vowels = [c for c in word if c in _HU_VOWELS]
    if not vowels:
        return None
    for v in reversed(vowels):
        if v in _HU_BACK_VOWELS:
            return 0 if v == vowels[-1] else None
        if v in _HU_ROUNDED_VOWELS:
            return 2
        if v in "eé":
            return 1
    return 1  # only i/í: front (Kitti -> Kittinek)


def _reharmonize(lemma: str, suffix: str) -> str:
    """``suffix`` in the vowel harmony of ``lemma`` (case endings only; others unchanged)."""
    group = _HU_HARMONY.get(suffix.casefold())
    harmony = _hu_harmony_class(lemma) if group else None
    if group is None or harmony is None:
        return suffix
    form = group[harmony]
    return form.upper() if suffix.isupper() else form


def _is_consonant(char: str) -> bool:
    return char.isalpha() and char.casefold() not in _HU_VOWELS and char.casefold() != "y"


def _hu_doubled(value: str) -> bool:
    """``value`` ends in a doubled consonant (``Kiss``, ``Bernadett``, ``Mariann``)."""
    return (
        len(value) >= 2
        and _is_consonant(value[-1])
        and value[-1].casefold() == value[-2].casefold()
    )


#: Entity types whose values inflect like words, so a suffix can change their stem.
_STEM_CHANGE_TYPES = frozenset({EntityType.PERSON, EntityType.ADDRESS, EntityType.ORGANIZATION})


def _word_like(value: str) -> bool:
    """A name-like last token: letters only (no digits, no e-mail address), 3+ of them."""
    tokens = value.split()
    last = tokens[-1] if tokens else ""
    return (
        "@" not in value
        and not any(ch.isdigit() for ch in last)
        and _last_token_letters(value) >= 3
    )


def _last_token_letters(value: str) -> int:
    tokens = value.split()
    return sum(ch.isalpha() for ch in tokens[-1]) if tokens else 0


class HungarianSuffixMatcher:
    """Hungarian case suffixes, with the stem changes they cause.

    Suffixes that leave the value intact: the common case endings, instrumental and
    translative forms with consonant doubling when the value ends in a single consonant
    (``Elek`` -> ``Elekkel``, ``Elekké``) and without one after a doubled consonant (``Kiss``
    -> ``Kissel``, ``Bernadett`` -> ``Bernadetté``), ``-val``/``-vel`` after a vowel, and
    hyphenated suffixes after codes and numbers (``ABC-123-nak``).

    Stem changes (:meth:`variant_stems`, :meth:`splits`, :meth:`restore`): a final ``a``/``e``
    lengthens before most suffixes (``Zsuzsanna`` -> ``Zsuzsannának``, ``Zsuzsannát``) and a
    final digraph doubles before ``-al``/``-el``/``-á``/``-é`` (``Kovács`` -> ``Kováccsal``).
    """

    def suffix_pattern(self, value: str, entity_type: EntityType) -> str:
        suffixes = set(_HU_SUFFIXES)
        hyphenated = {"val", "vel", "vá", "vé"}
        last = value[-1:].casefold()
        if last in _HU_VOWELS:
            suffixes |= {"val", "vel", "vá", "vé"}
        elif _hu_old_digraph(value) is not None:
            sound = value.casefold()[-2]  # Tóth -> t, Kovácz -> c
            suffixes |= {f"{sound}al", f"{sound}el", f"{sound}á", f"{sound}é"}
        elif _hu_doubled(value):
            # Kiss -> Kissel, Bernadett -> Bernadettel: the v assimilates, no third letter.
            suffixes |= set(_HU_DOUBLED_ENDINGS)
        elif last.isalpha() and not value.casefold().endswith(_HU_DIGRAPHS):
            suffixes |= {f"{last}al", f"{last}el", f"{last}á", f"{last}é"}
        plain = (
            _HU_STACKED
            + "|"
            + "|".join(re.escape(s) for s in sorted(suffixes, key=len, reverse=True))
        )
        after_hyphen = "|".join(
            re.escape(s) for s in sorted(suffixes | hyphenated, key=len, reverse=True)
        )
        return f"(?:-(?:{after_hyphen})|(?:{plain}))"

    def variant_stems(self, value: str, entity_type: EntityType) -> list[tuple[str, str]]:
        """``(changed stem as written, regex of the suffixes that must follow it)``."""
        value = value.strip()
        if not value or not value[-1].isalpha() or not _word_like(value):
            return []
        variants: list[tuple[str, str]] = []
        long_vowel = _HU_LONG.get(value[-1])
        if long_vowel is not None:
            variants.append(
                (value[:-1] + long_vowel, f"{_HU_STACKED}|{_alternation(_HU_LENGTHENING)}")
            )
        digraph = _hu_digraph(value)
        if digraph is not None:
            stem = value[:-2] + value[-2] + value[-2:]  # Kovács -> Kováccs (case kept)
            variants.append((stem, _alternation(_HU_DOUBLED_ENDINGS)))
        return variants

    def splits(self, surface: str, entity_type: EntityType) -> list[Split]:
        """Readings of ``surface`` as an inflected form, most specific first.

        Strong: a lengthened final vowel before a three-letter case ending in vowel harmony
        (``Zsuzsannának``, ``Kendével``). Weak, applied only when the lemma is confirmed: other
        lengthened forms (``Zsuzsannát``: ``Donát`` and ``Zoltán`` look the same), consonant and
        digraph doubling (``Elekkel``, ``Kováccsal``; ``Bernadettel`` is read both as
        ``Bernadet`` + ``tel`` and as ``Bernadett`` + ``el``, like ``Kissel`` as ``Kis`` and
        ``Kiss``), unchanged stems (``Eleknek``: ``Kornél`` looks the same) and hyphenated
        suffixes after codes (``ABC-123-nak``).
        """
        surface = surface.strip()
        if not surface or not surface[-1].isalpha():
            return []
        found: list[Split] = []
        folded = surface.casefold()
        hyphen = surface.rfind("-")
        if hyphen > 0 and surface[hyphen - 1].isalnum():
            head, tail = surface[:hyphen], surface[hyphen:]
            if tail[1:].casefold() in set(_HU_SUFFIXES) | set(_HU_HYPHENATED) and (
                head[-1].isdigit() or head.split("-")[-1].isupper()
            ):
                found.append(Split(head, head, tail))
        if not _word_like(surface):
            return found
        for suffix in sorted(set(_HU_LENGTHENING), key=len, reverse=True):
            cut = len(surface) - len(suffix)
            if cut < 1 or not folded.endswith(suffix):
                continue
            short = _HU_SHORT.get(surface[cut - 1])
            if short is None:
                continue
            stem, lemma = surface[:cut], surface[: cut - 1] + short
            if _last_token_letters(lemma) < _MIN_LEMMA_LETTERS + 1:
                continue
            strong = suffix in _HU_STRONG[short.casefold()]
            found.append(Split(lemma, stem, surface[cut:], strong))
        # Stacked: Kerekes Ottó|éknál, Teszt Hajná|éknak -> Teszt Hajna, Tihamér|éit (LAB-1337).
        last_start = len(surface) - len(surface.split()[-1])
        for cut in range(len(surface) - 2, last_start, -1):
            if folded[cut] != "é" or not _HU_STACKED_RE.fullmatch(folded[cut:]):
                continue
            stem = surface[:cut]
            if not stem[-1].isalpha():
                continue
            short = _HU_SHORT.get(stem[-1])
            lemma = stem if short is None else stem[:-1] + short
            if _last_token_letters(lemma) >= _MIN_LEMMA_LETTERS + 1:
                found.append(Split(lemma, stem, surface[cut:]))
        for ending in _HU_DOUBLED_ENDINGS:
            if not folded.endswith(ending):
                continue
            stem = surface[: len(surface) - len(ending)]
            digraph = _hu_digraph(stem)
            # Kováccs|al -> Kovács: the digraph's first letter is doubled.
            if digraph is not None and stem[-3:-2].casefold() == digraph[0]:
                lemma = stem[:-3] + stem[-2:]
                if _last_token_letters(lemma) >= _MIN_LEMMA_LETTERS + 1:
                    found.append(Split(lemma, stem, surface[len(stem) :]))
                continue
            # Tóth|tal -> Tóth, Kovácz|cal -> Kovácz: the sound of the old digraph is doubled.
            lemma = stem[:-1]
            old = _hu_old_digraph(lemma)
            if old is not None and stem[-1].casefold() == old[0]:
                if _last_token_letters(lemma) >= _MIN_LEMMA_LETTERS + 1:
                    found.append(Split(lemma, lemma, surface[len(lemma) :]))
                continue
            if _hu_doubled(stem):
                # Elek|kel -> Elek: a single final consonant doubled into the suffix.
                lemma = stem[:-1]
                if (
                    lemma[-2:-1].casefold() != lemma[-1].casefold()
                    and _hu_digraph(lemma) is None
                    and _last_token_letters(lemma) >= _MIN_LEMMA_LETTERS + 1
                ):
                    found.append(Split(lemma, lemma, surface[len(lemma) :]))
                # Bernadett|el -> Bernadett, Kiss|el -> Kiss: the value already ends doubled.
                if _last_token_letters(stem) >= _MIN_LEMMA_LETTERS + 1:
                    found.append(Split(stem, stem, surface[len(stem) :]))
        for suffix in sorted(set(_HU_SUFFIXES) | set(_HU_HYPHENATED), key=len, reverse=True):
            cut = len(surface) - len(suffix)
            if cut < 1 or not folded.endswith(suffix) or not surface[cut - 1].isalpha():
                continue
            lemma = surface[:cut]
            if suffix in _HU_HYPHENATED and lemma[-1].casefold() not in _HU_VOWELS:
                continue
            if _last_token_letters(lemma) < _MIN_LEMMA_LETTERS + 1:
                continue
            found.append(Split(lemma, lemma, surface[cut:]))
        # Strong readings first; otherwise keep the order above (most specific first).
        unique = list(dict.fromkeys(found))
        return sorted(unique, key=lambda split: not split.strong)

    def confident_split(
        self, surface: str, entity_type: EntityType, is_name: Callable[[str], bool]
    ) -> Split | None:
        """The reading of a name a detector found whole (``Kerekes Ottótól``) safe to apply now.

        Used before the vault sees the span (:mod:`pii_guard.detect.suffix_trim`), when no
        lemma is confirmed yet. ``is_name(word)`` says whether ``word`` is a known given name
        or surname (the pack's lexicons). Only PERSON values; ``None`` unless one of:

        - the last word is not a name itself (``Márton``, ``Kornél``, ``Simon`` stay whole)
          and exactly one reading's lemma ends in a name (``Ottó`` + ``tól``, ``Béla`` + ``t``,
          ``Zoltán`` + ``t``, ``Jakab`` + ``bal``);
        - a strong reading (``Hajnának``), a doubled digraph (``Szabolccsal``,
          ``Gergellyel``), or a long case ending after an unchanged stem that no Hungarian
          name ends in (``Tihamérnak``, ``Ödönhöz``; not ``-nél``/``-ért``: ``Kornél``,
          ``Gellért``).
        """
        if entity_type is not EntityType.PERSON:
            return None
        words = surface.split()
        if not words or is_name(words[-1]):
            return None
        candidates = [c for c in self.splits(surface, entity_type) if c.stem and c.suffix]
        if not candidates:
            return None
        named = {c.lemma: c for c in candidates if c.lemma.split() and is_name(c.lemma.split()[-1])}
        if len(named) == 1:
            return next(iter(named.values()))
        if len(named) > 1:
            return None  # Kissel: Kis or Kiss, both surnames
        for c in candidates:
            if c.strong:
                return c
            folded = c.suffix.casefold()
            if c.stem == c.lemma and folded in _HU_UNAMBIGUOUS_ENDINGS:
                return c
            digraph = _hu_digraph(c.lemma)
            if (
                digraph is not None
                and c.stem.casefold().endswith(digraph[0] + digraph)
                and folded in _HU_DOUBLED_ENDINGS
            ):
                return c
        return None

    def restore(self, lemma: str, suffix: str, entity_type: EntityType) -> str:
        """``lemma`` inflected for ``suffix`` as it follows a placeholder: ``stem + suffix``.

        ``Próba Zsuzsanna`` + ``nak`` -> ``Próba Zsuzsannának`` (also when the model already
        wrote the long vowel: ``ának``); ``Kovács`` + ``al`` or ``val`` -> ``Kováccsal``;
        ``Kiss Tóth`` + ``val`` -> ``Kiss Tóthtal``; ``Elek`` + ``vel`` -> ``Elekkel``. Anything
        else is ``lemma + suffix``. A case ending in the wrong vowel harmony is re-inflected
        first (``Teszt Elek`` + ``nak`` -> ``Teszt Eleknek``, LAB-1152).

        Known limitation: a value the detector only saw inflected (``Teszt Zoltánt``) has no
        confirmed lemma, so a suffix the model adds is appended to the whole word. Choosing
        between candidate lemmas (``Zoltán`` vs ``Zoltánt``) is a guess; it is not made here.
        """
        if not suffix or suffix.startswith("-") or not lemma or not lemma[-1].isalpha():
            return lemma + suffix
        # Stem changes belong to names, as in variant_stems/splits: an e-mail address or an
        # ID keeps its spelling (anna@firma.de + re -> anna@firma.dere, not ...dére).
        if entity_type not in _STEM_CHANGE_TYPES or not _word_like(lemma):
            return lemma + suffix
        suffix = _reharmonize(lemma, suffix)
        folded = suffix.casefold()
        long_vowel = _HU_LONG.get(lemma[-1])
        wrote_long = long_vowel is not None and suffix[0].casefold() == long_vowel.casefold()
        if wrote_long and folded[1:] in _HU_AFTER_VOWEL:
            # The model wrote the long vowel itself (Kende + ének -> Kendének), not the
            # possessive -é before a case ending (Kendéének): that reading needs the input.
            return lemma[:-1] + suffix
        if long_vowel is not None and _HU_LENGTHENING_RE.fullmatch(folded):
            return lemma[:-1] + long_vowel + suffix
        if wrote_long and _HU_LENGTHENING_RE.fullmatch(folded[1:]):
            return lemma[:-1] + suffix  # the model wrote the long vowel itself (áéknak)
        if _hu_old_digraph(lemma) is not None and folded in {
            "al", "el", "á", "val", "vel", "vá", "vé",
        }:  # fmt: skip
            ending = suffix[1:] if folded.startswith("v") else suffix
            return lemma + lemma[-2] + ending  # Tóth + val -> Tóthtal
        digraph = _hu_digraph(lemma)
        if digraph is not None and folded in {"al", "el", "á", "val", "vel", "vá", "vé"}:
            ending = suffix[1:] if folded.startswith("v") else suffix
            return lemma[:-2] + lemma[-2] + lemma[-2:] + ending
        if folded in {"val", "vel", "vá", "vé"} and _is_consonant(lemma[-1]):
            if len(lemma) >= 2 and lemma[-2].casefold() == lemma[-1].casefold():
                return lemma + suffix[1:]  # Kiss + vel -> Kissel
            return lemma + lemma[-1] + suffix[1:]  # Elek + vel -> Elekkel
        return lemma + suffix
