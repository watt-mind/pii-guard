"""Context-cued numbers (LAB-1170): cue data, matching, scoring, the setting and negatives."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pii_guard.config import Settings, get_settings
from pii_guard.detect.rules import RuleDetector
from pii_guard.languages import LanguagePack, get_pack, packs
from pii_guard.languages.conformance import check_structure
from pii_guard.languages.cues import (
    CUED_SCORE,
    SHAPES,
    CueMatcher,
    fold,
    load_cues,
    parse_cues,
)
from pii_guard.types import EntityType as E

REPO_ROOT = Path(__file__).resolve().parents[2]
NEGATIVES = sorted((REPO_ROOT / "eval" / "fixtures" / "negative").glob("*.jsonl"))


@pytest.fixture(scope="module")
def cued() -> RuleDetector:
    return RuleDetector(cued_numbers=True)


@pytest.fixture(scope="module")
def plain() -> RuleDetector:
    return RuleDetector(cued_numbers=False)


def found(detector: RuleDetector, text: str, language: str) -> list[tuple[str, E, float]]:
    return [(s.text, s.entity_type, s.score) for s in detector.detect(text, language=language)]


# --- Cue data -------------------------------------------------------------------------------


@pytest.mark.parametrize("code", ["hu", "en", "de"])
def test_every_built_in_pack_ships_valid_cues(code: str) -> None:
    pack = get_pack(code)
    assert pack is not None and pack.cues is not None
    cues = load_cues(pack.cues, code)
    assert {c.entity_type for c in cues if c.entity_type} <= set(SHAPES)
    assert any(c.entity_type is None for c in cues), "no '-' cue ends a window"


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("telefon", "expected"),
        ("telefon\tPHONE\textra", "expected"),
        ("telefon\tNOT_A_TYPE", "unknown entity type"),
        ("név\tPERSON", "no value shape"),
        ("123\tPHONE", "start with a letter"),
        ("tel2\tPHONE", "start with a letter"),
        ("tel\tPHONE\nTel\tPHONE", "already listed"),
    ],
)
def test_malformed_cue_files_are_rejected(line: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_cues(line, "xx")


def test_comments_dashes_and_suffixes_parse() -> None:
    cues = parse_cues("# comment\n\nkártyaszám*\tBANK_ACCOUNT\nrendelésszám*\t-\n", "hu")
    assert [(c.text, c.entity_type, c.suffix) for c in cues] == [
        ("kártyaszám", E.BANK_ACCOUNT, True),
        ("rendelésszám", None, True),
    ]


def test_fold_keeps_offsets() -> None:
    text = "Kártyaszám\u2011ÉS Straße İ \u2019"
    assert len(fold(text)) == len(text)
    assert fold("Kártyaszám\u2011ÉS") == "kartyaszam-es"


def test_conformance_reports_broken_and_missing_cue_files(tmp_path: Path) -> None:
    base = get_pack("de")
    assert base is not None
    broken = tmp_path / "cues.tsv"
    broken.write_text("telefon\tPERSON\n", encoding="utf-8")
    only_dash = tmp_path / "dash.tsv"
    only_dash.write_text("bestellnummer\t-\n", encoding="utf-8")
    no_dash = tmp_path / "nodash.tsv"
    no_dash.write_text("telefon\tPHONE\n", encoding="utf-8")

    def findings(cues: object) -> list[str]:
        pack = LanguagePack(**{**_fields(base), "cues": cues})
        return [
            f"{f.severity} {f.message}"
            for f in check_structure(pack)
            if f.check == "structure.cues"
        ]

    assert findings(None) == [findings(None)[0]] and findings(None)[0].startswith("info")
    assert findings(broken)[0].startswith("error cues.tsv is invalid")
    assert findings(only_dash) == ["error cues.tsv has no cue for a personal-data type"]
    assert findings(no_dash)[0].startswith("warning")
    assert findings(base.cues) == []


def _fields(pack: LanguagePack) -> dict[str, object]:
    return {name: getattr(pack, name) for name in pack.__dataclass_fields__}


# --- Matching -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "language", "value", "entity_type"),
    [
        # Checksum-failing identifiers after their cue.
        ("Kártyaszám: 4111 1111 1111 1112", "hu", "4111 1111 1111 1112", E.BANK_ACCOUNT),
        ("adóazonosító jel: 8123456780", "hu", "8123456780", E.NATIONAL_ID_HU_TAX),
        ("TAJ-szám: 123 456 780", "hu", "123 456 780", E.NATIONAL_ID_HU_TAJ),
        ("TAJ/VA: 084 277 153", "hu", "084 277 153", E.NATIONAL_ID_HU_TAJ),
        ("személyi szám: 17103041238", "hu", "17103041238", E.ID_DOCUMENT),
        ("Jogosítvány száma (ha van): DKRE0I1WMY", "hu", "DKRE0I1WMY", E.ID_DOCUMENT),
        ("útlevélszámom 1234567", "hu", "1234567", E.ID_DOCUMENT),
        # Unknown numbering plans after a phone cue.
        ("Telefon: 0729 11192898", "hu", "0729 11192898", E.PHONE),
        ("hívja a 0136.42246 9041 számot", "hu", "0136.42246 9041", E.PHONE),
        # Hungarian national formats without a prefix, next to a phone cue (LAB-1094).
        ("Hívjon a 30/123-4567 számon", "hu", "30/123-4567", E.PHONE),
        ("Telefon: 30 123 4567", "hu", "30 123 4567", E.PHONE),
        ("Handy: 0158.609.792.0528", "de", "0158.609.792.0528", E.PHONE),
        ("Tel. (95)-7613 3737", "hu", "(95)-7613 3737", E.PHONE),
        ("call us at 0198.08.725 3693", "en", "0198.08.725 3693", E.PHONE),
        # A few words between the cue and the value.
        ("credit card ending in 6454444872996095850", "en", "6454444872996095850", E.BANK_ACCOUNT),
        ("Kreditkarte mit der Nummer 5279587050642870", "de", "5279587050642870", E.BANK_ACCOUNT),
        ("Social security no.: 971 206 970", "en", "971 206 970", E.ID_DOCUMENT),
        ("Steuer\u2011ID: 35-6140468", "de", "35-6140468", E.ID_DOCUMENT),
        ("Steueridentifikationsnummer (CHE-947.235.321)", "de", "CHE-947.235.321", E.ID_DOCUMENT),
        # Accents typed without, other casing.
        ("KARTYASZAM 4111111111111112", "hu", "4111111111111112", E.BANK_ACCOUNT),
    ],
)
def test_a_cued_number_is_masked_as_the_cued_type(
    cued: RuleDetector, plain: RuleDetector, text: str, language: str, value: str, entity_type: E
) -> None:
    assert (value, entity_type, CUED_SCORE) in found(cued, text, language)
    assert value not in [v for v, _, _ in found(plain, text, language)]  # no checksum passes


def test_the_text_language_wins_a_cue_two_packs_map_differently(cued: RuleDetector) -> None:
    text = "Social security: 971 206 970"
    assert found(cued, text, "hu") == [("971 206 970", E.NATIONAL_ID_HU_TAJ, CUED_SCORE)]
    assert found(cued, text, "en") == [("971 206 970", E.ID_DOCUMENT, CUED_SCORE)]


def test_every_packs_cues_run_for_every_language(cued: RuleDetector) -> None:
    # A Hungarian form with English labels, and a language without a pack.
    assert found(cued, "Passport: 004471902", "hu") == [("004471902", E.ID_DOCUMENT, CUED_SCORE)]
    assert found(cued, "Telefon: 0729 11192898", "fr") == [("0729 11192898", E.PHONE, CUED_SCORE)]


def test_a_validated_hit_keeps_its_span_and_score(cued: RuleDetector, plain: RuleDetector) -> None:
    text = "adóazonosító jel: 8123456786, telefon: +36 30 123 4567"
    assert found(cued, text, "hu") == found(plain, text, "hu")
    assert all(score > CUED_SCORE for _, _, score in found(cued, text, "hu"))


def test_cued_scores_are_below_every_validated_rule() -> None:
    assert CUED_SCORE < 0.7  # the lowest validated score (bare ID card numbers)


@pytest.mark.parametrize(
    "text",
    [
        "30/123-4567",  # no cue at all: left to the LLM (LAB-1094)
        "A szám 30/123-4567 volt.",
        "Rendelés 30/123-4567 szám",  # a reference cue: a reference, not a phone
    ],
)
def test_an_uncued_prefix_less_phone_is_not_masked(cued: RuleDetector, text: str) -> None:
    assert [s for s in cued.detect(text, "hu") if s.entity_type is E.PHONE] == []


@pytest.mark.parametrize(
    ("text", "language"),
    [
        # A "-" cue or a conjunction ends the window.
        ("Telefonos rendelésszám: 123456789012", "hu"),
        ("kártyaszám és a 123456789012 számú megrendelés", "hu"),
        ("phone and order number 1234567890", "en"),
        ("Kreditkarte oder Bestellnummer 4500123456789", "de"),
        # Dates, amounts, too short, too long, inside a longer run, a sentence later.
        ("Telefon: 2026-10-27", "hu"),
        ("telefonon egyeztettünk 2026. 10. 27-én", "hu"),
        ("Phone call on 28.10.2026", "en"),
        ("Kártyás fizetés: 125 000 000 000 Ft", "hu"),
        ("card number: $3508721121192569", "en"),
        ("Kreditkarte 1.249,00 €", "de"),
        ("passport 12345", "en"),
        ("TAJ: 1234567890", "hu"),
        ("telefon: 1234567890123456", "hu"),
        ("passport ABCDEFGH", "en"),
        ("tel: 06301234567890123/5", "hu"),
        ("A kártya lejárt. Másnap 4111111111111112 forintot utaltak.", "hu"),
        ("telefon\n4111111111111112", "hu"),
        # A cue inside another word, or a word that only starts like one.
        ("hotel 1234567", "en"),
        ("cardiology 1234567890123", "en"),
        ("Telefonnummer und Faxnummer folgen, Bestellnummer 1234567890123", "de"),
    ],
)
def test_look_alikes_after_or_near_a_cue_are_not_masked(
    cued: RuleDetector, plain: RuleDetector, text: str, language: str
) -> None:
    assert found(cued, text, language) == found(plain, text, language)


def test_an_empty_matcher_finds_nothing() -> None:
    assert list(CueMatcher([]).find("telefon: 1234567")) == []


# --- Setting --------------------------------------------------------------------------------


def test_the_setting_defaults_on_and_turns_the_rule_off(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings().rules_cued_numbers is True
    text = "Kártyaszám: 4111 1111 1111 1112"
    monkeypatch.setenv("PII_GUARD_RULES_CUED_NUMBERS", "false")
    get_settings.cache_clear()
    try:
        off = RuleDetector()
        assert off.cued_numbers is False and off.detect(text, "hu") == []
        monkeypatch.setenv("PII_GUARD_RULES_CUED_NUMBERS", "true")
        get_settings.cache_clear()
        assert RuleDetector().detect(text, "hu")
    finally:
        get_settings.cache_clear()


def test_a_pack_without_cues_contributes_none() -> None:
    assert all(pack.cues is not None for pack in packs().values())  # built-ins all have cues
    detector = RuleDetector(cued_numbers=True)
    assert detector.cue_matcher("hu") is detector.cue_matcher("HU-hu")
    assert RuleDetector(cued_numbers=False).cue_matcher("hu") is None


# --- Negative fixture set -------------------------------------------------------------------


def _negative_documents() -> list[dict[str, object]]:
    docs = []
    for path in NEGATIVES:
        docs += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return docs


def test_the_negative_set_covers_every_built_in_language() -> None:
    languages = {doc["language"] for doc in _negative_documents()}
    assert languages >= {"hu", "en", "de"}
    assert all(doc["spans"] == [] for doc in _negative_documents())


@pytest.mark.parametrize("doc", _negative_documents(), ids=lambda d: str(d["id"]))
def test_uncued_order_numbers_amounts_dates_and_postcodes_are_never_masked(
    cued: RuleDetector, doc: dict[str, object]
) -> None:
    assert cued.detect(str(doc["text"]), language=str(doc["language"])) == []
