"""Reference words live in language packs, not in code (LAB-1345).

``references.tsv`` in each pack replaced the hard-coded ``_REFERENCE_WORD`` (rules) and
``_NEGATIVE`` (NER numbers) lists. Both checks read every pack's entries (``rules``/``ner``
scopes); a language without a pack keeps the built-in fallbacks. A new pack's reference
words reach both checks: registering a pack with ``references.tsv`` is enough. All words
are business labels, never personal data.
"""

from __future__ import annotations

import re

import pytest

from pii_guard.detect.ner_numbers import _NEGATIVE, _fold, _pack_negatives
from pii_guard.detect.rules._base import (
    _REFERENCE_BEFORE_TEMPLATE,
    _REFERENCE_WORD,
    reference_or_amount_before,
)
from pii_guard.languages import LanguagePack, register_pack, unregister_pack
from pii_guard.languages.references import (
    Reference,
    accent_pattern,
    load_references,
    pack_references,
    parse_references,
    reference_alternation,
)

TAX_ID = "8123456786"  # fictional, checksum-valid (tests/detect/test_rules_reference_cues.py)


def _fallback_before_re() -> re.Pattern[str]:
    return re.compile(_REFERENCE_BEFORE_TEMPLATE.format(words=_REFERENCE_WORD))


# (text with the number at the end, expected outcome with the built-in packs)
PROBES: list[tuple[str, bool]] = [
    (f"Order {TAX_ID}", True),
    (f"Reference: {TAX_ID}", True),  # weak, but pinned by the reference-cue tests
    (f"Total: {TAX_ID}", True),
    (f"Amount EUR {TAX_ID}", True),
    (f"SKU {TAX_ID}", True),
    (f"Tracking {TAX_ID}", True),
    (f"Account {TAX_ID}", False),
    (f"Rendelésszám: {TAX_ID}", True),
    (f"rendeles: {TAX_ID}", True),  # unaccented spelling
    (f"Megrendelés: {TAX_ID}", True),
    (f"Előrendelés: {TAX_ID}", True),  # leading-* prefix form
    (f"Számla: SZ-{TAX_ID}", True),
    (f"Összeg: {TAX_ID}", True),  # weak, but pinned
    (f"oszeg {TAX_ID}", False),  # the misspelling never matched, and still does not
    (f"Ügyszám {TAX_ID}", True),
    (f"Bestellnummer {TAX_ID}", True),
    (f"bestellnummer {TAX_ID}", True),
    (f"Rechnung RE-{TAX_ID}", True),
    (f"Betrag: {TAX_ID}", True),  # weak, but pinned
    (f"beträgt {TAX_ID}", False),  # the verb is not the noun (LAB-1345)
    (f"Gesamtsumme beträgt {TAX_ID}", False),
    (f"Vorgang {TAX_ID}", True),
    (f"Sendung {TAX_ID}", False),  # ner-only scope
    (f"Faktura nr {TAX_ID}", True),
    (f"sygn. akt {TAX_ID}", True),
    (f"sygn. {TAX_ID}", True),
    (f"sygn {TAX_ID}", True),  # the dot is optional
    (f"klienta {TAX_ID}", True),
    (f"sledzenie {TAX_ID}", False),  # ner-only scope
]


def test_pack_negatives_match_the_fallback() -> None:
    # Set equality: pack entries may repeat a key (`sygn.`/`sygn akt`/`sygn. akt` all fold
    # to `sygn`); the lexicon deduplicates, like the list it replaces.
    assert set(_pack_negatives() or []) == set(_NEGATIVE)


def test_rules_references_match_the_fallback_on_probes() -> None:
    fallback = _fallback_before_re()
    for text, expected in PROBES:
        start = len(text) - len(TAX_ID)
        old = fallback.search(text, max(0, start - 40), start) is not None
        assert reference_or_amount_before(text, start) == old == expected, text


def test_accent_pattern_covers_unaccented_spellings() -> None:
    assert accent_pattern("rendelés", "hu") == accent_pattern("rendeles", "hu")
    pattern = re.compile(
        reference_alternation([Reference("rendelés", suffix=True)], "hu"), re.IGNORECASE
    )
    assert pattern.search("rendelés") and pattern.search("rendeles")
    # German umlauts are distinct letters: Betrag never matches the verb beträgt.
    de_pattern = re.compile(
        reference_alternation([Reference("Betrag", suffix=True)], "de"), re.IGNORECASE
    )
    assert de_pattern.search("Betrag") and not de_pattern.search("beträgt")


def test_parse_references_validates() -> None:
    assert parse_references("order*\nref\tweak\nuuid\tner\n")[1] == Reference(
        "ref", False, False, True, "rules"
    )
    for bad in ("abc123\n", "ok\tbogus\n", "dup*\ndup*\n", "*\n"):
        with pytest.raises(ValueError):
            parse_references(bad)


def test_a_new_packs_reference_words_reach_both_checks(tmp_path) -> None:
    resource = tmp_path / "references.tsv"
    resource.write_text("xxorder*\nxxuuid\tner\nxxamount\tweak\n", encoding="utf-8")
    pack = LanguagePack(code="xx", name="Xx", references=resource)
    register_pack(pack)
    try:
        assert any(code == "xx" for code, _ in pack_references())
        probe = f"xxorder {TAX_ID}"
        assert reference_or_amount_before(probe, len(probe) - len(TAX_ID))
        negatives = _pack_negatives()
        assert negatives is not None
        assert _fold("xxorder") + "*" in negatives
        assert _fold("xxuuid") in negatives
        assert _fold("xxamount") not in negatives  # weak: the NER check ignores it
    finally:
        unregister_pack("xx")


def test_pack_files_parse() -> None:
    for _, entries in pack_references():
        assert entries
        re.compile(reference_alternation(list(entries)))
    assert load_references  # every pack file above parsed without raising
