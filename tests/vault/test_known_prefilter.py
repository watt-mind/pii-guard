"""Known-values literal prefilter changes no output, only the cost (LAB-1289).

Same shape as the vault's own prefilter (LAB-1277): every known value's pattern is skipped
when none of its literal needles is in the text, and a caller that already folded the text
(the session's fold memo) passes its views instead of re-folding. All values fictional.
"""

from __future__ import annotations

from pii_guard.types import EntityType
from pii_guard.vault.fold import fold_views
from pii_guard.vault.known import KnownValue, KnownValues

VALUES = [
    ("Teszt Elek", EntityType.PERSON),
    ("Próba Zsuzsanna", EntityType.PERSON),
    ("Gyakorló Tihamér", EntityType.PERSON),
    ("Minta Mária", EntityType.PERSON),
    ("Kovács Béla", EntityType.PERSON),
    ("1052 Budapest, Próba utca 12.", EntityType.ADDRESS),
    ("teszt.elek@example.com", EntityType.EMAIL),
    ("+36 30 123 4567", EntityType.PHONE),
]

TEXTS = [
    "Teszt Elek írta, hogy Próba Zsuzsannának küldi.",
    "Semmi személyes adat ebben a mondatban, csak egy rendelésszám: 12345.",
    "Gyakorló Tihamérnak és Minta Máriának is szóltunk; Kovács Bélával jönnek.",
    "Az e-mail cím teszt.elek@example.com, telefon +36 30 123 4567.",
    "Kovácscsal és Zsuzsannát is hívjuk holnap.",
]


def _known() -> KnownValues:
    known = KnownValues()
    known.add([KnownValue(v, t) for v, t in VALUES])
    return known


def test_prefilter_matches_unfiltered_output() -> None:
    known = _known()
    for text in TEXTS:
        for language in ("hu", "en"):
            assert known.occurrences(text, language) == known.occurrences(
                text, language, fold_views(text)
            )


def test_needles_cover_variant_stems() -> None:
    known = _known()
    known.patterns("hu")
    # Every cached needle list filters the value's own pattern, never to an empty scan
    # of a text holding an inflected form: variant stems are needles too.
    assert known.occurrences("Próba Zsuzsannát hívjuk.", "hu")
    assert known.occurrences("Kovács Bélával jött.", "hu")
