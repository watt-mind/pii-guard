"""The German pack: checksums, rules, the genitive matcher. All values are fictional."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pii_guard.detect.rules import RuleDetector
from pii_guard.languages.de.checksums import (
    is_valid_steuer_id,
    is_valid_sv_number,
    steuer_id_check_digit,
    sv_number_check_digit,
)
from pii_guard.languages.de.inflection import GermanGenitiveMatcher
from pii_guard.types import EntityType as E
from pii_guard.types import Span
from pii_guard.vault import Vault

# Made-up payloads with computed check digits (issued to nobody).
STEUER_ID = "4710382946" + str(steuer_id_check_digit("4710382946"))
SV_NUMBER = "12150885M01" + str(sv_number_check_digit("12150885M01"))


@pytest.fixture(scope="module")
def detector() -> RuleDetector:
    return RuleDetector()


def _found(detector: RuleDetector, text: str, language: str = "de") -> list[tuple[str, str]]:
    return [(s.entity_type.value, s.text) for s in detector.detect(text, language)]


# --- Checksums ---------------------------------------------------------------------------


def test_published_algorithm_examples() -> None:
    # The worked examples printed in the public descriptions of both algorithms.
    assert is_valid_sv_number("15 070649 C 10 3")
    assert is_valid_sv_number("65180539W001")
    assert is_valid_steuer_id("86095742719")


@pytest.mark.parametrize(
    "value",
    [
        "0" + STEUER_ID[1:],  # leading zero
        "1234567890" + "1",  # every digit once: no repeated digit
        "1112345678" + str(steuer_id_check_digit("1112345678")),  # three in a row
        STEUER_ID[:10] + str((int(STEUER_ID[10]) + 1) % 10),  # wrong check digit
        STEUER_ID[:10],
    ],
)
def test_invalid_steuer_ids(value: str) -> None:
    assert not is_valid_steuer_id(value)


@given(st.text("0123456789", min_size=10, max_size=10))
def test_a_wrong_steuer_id_check_digit_is_rejected(payload: str) -> None:
    good = steuer_id_check_digit(payload)
    assert not is_valid_steuer_id(payload + str((good + 1) % 10))


@pytest.mark.parametrize(
    "value",
    [
        SV_NUMBER[:11] + str((int(SV_NUMBER[11]) + 1) % 10),  # check digit
        "00" + SV_NUMBER[2:],  # area number
        SV_NUMBER[:2] + "32" + SV_NUMBER[4:],  # day 32
        SV_NUMBER[:4] + "13" + SV_NUMBER[6:],  # month 13
        SV_NUMBER[:8] + "1" + SV_NUMBER[9:],  # no letter
    ],
)
def test_invalid_sv_numbers(value: str) -> None:
    assert not is_valid_sv_number(value)


def test_check_digit_arguments_are_validated() -> None:
    with pytest.raises(ValueError):
        steuer_id_check_digit("12345")
    with pytest.raises(ValueError):
        sv_number_check_digit("12150885101")
    with pytest.raises(ValueError):
        sv_number_check_digit("1215088XM01")


# --- Rules -------------------------------------------------------------------------------


def test_identifiers(detector: RuleDetector) -> None:
    grouped = f"{STEUER_ID[:2]} {STEUER_ID[2:5]} {STEUER_ID[5:8]} {STEUER_ID[8:]}"
    spaced = f"{SV_NUMBER[:2]} {SV_NUMBER[2:8]} {SV_NUMBER[8]} {SV_NUMBER[9:11]} {SV_NUMBER[11]}"
    assert _found(detector, f"Steuer-ID: {grouped}") == [("ID_DOCUMENT", grouped)]
    assert _found(detector, f"Nummer {STEUER_ID} angeben") == [("ID_DOCUMENT", STEUER_ID)]
    assert _found(detector, f"SV-Nr. {spaced}") == [("ID_DOCUMENT", spaced)]
    assert _found(detector, f"RVNR {SV_NUMBER}") == [("ID_DOCUMENT", SV_NUMBER)]


def test_scopes(detector: RuleDetector) -> None:
    # A labelled Steuer-ID and a Sozialversicherungsnummer are found in any language ...
    assert _found(detector, f"Steuer-ID {STEUER_ID}", "en") == [("ID_DOCUMENT", STEUER_ID)]
    assert _found(detector, f"no. {SV_NUMBER}", "hu") == [("ID_DOCUMENT", SV_NUMBER)]
    # ... a bare 11-digit number or a German address only in German text.
    for text in (f"Nummer {STEUER_ID}", "Musterstraße 12, 10115 Berlin"):
        assert _found(detector, text, "en") == []
        assert _found(detector, text, "de") != []


@pytest.mark.parametrize(
    "text", ["030 12345678", "(0221) 4567890", "0171/2345678", "089 1234567", "0221-123456"]
)
def test_phone_numbers(detector: RuleDetector, text: str) -> None:
    assert _found(detector, f"Tel.: {text}.") == [("PHONE", text)]


@pytest.mark.parametrize(
    "text",
    [
        "Musterstraße 12, 10115 Berlin",
        "Am Beispielweg 3a",
        "Lange Straße 7",
        "Hauptstr. 101, 80331 München",
        "Lindenallee 7 04109 Leipzig",
    ],
)
def test_addresses(detector: RuleDetector, text: str) -> None:
    assert _found(detector, f"wohnhaft {text}.") == [("ADDRESS", text)]


def test_postcode_on_an_address_line(detector: RuleDetector) -> None:
    assert _found(detector, "Lena Testmann\n50667 Köln") == [("ADDRESS", "50667 Köln")]


@pytest.mark.parametrize(
    "text",
    [
        "Die Studie mit 20000 Teilnehmern lief über 18 Monate.",
        "Am 01.02.2026 wurden 12500 Euro überwiesen.",
        "Bestellnummer 4711-0815, Rechnung 2026-0815.",
        "Aktenzeichen 12 150885 M 01 0.",  # SV-like, wrong check digit
        "Die Miete steigt zum 01.01.2027 um 2,5 Prozent.",
        "\n12500 Euro sind fällig.",
    ],
)
def test_hard_negatives(detector: RuleDetector, text: str) -> None:
    assert _found(detector, text) == []


# --- Genitive ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "pattern"),
    [("Anna", "(?:['\u2019]s|s|['\u2019])"), ("Hans", "(?:['\u2019])"), ("A-123", "")],
)
def test_genitive_suffixes(value: str, pattern: str) -> None:
    assert GermanGenitiveMatcher().suffix_pattern(value, E.PERSON) == pattern


def test_genitive_forms_are_masked_and_restored() -> None:
    session = Vault(b"de-pack-test-key-01").session()
    text = "Anna Probst zieht um. Anna Probsts Wohnung, Hans und Hans' Rad, Anna Probst's Hof."
    spans = [
        Span(0, 11, E.PERSON, "Anna Probst", 1.0, "t"),
        Span(text.index("Hans"), text.index("Hans") + 4, E.PERSON, "Hans", 1.0, "t"),
    ]
    masked = session.mask(text, spans, language="de")
    assert "Probst" not in masked and "Hans" not in masked
    assert masked.count("]]s ") == 1 and "]]' Rad" in masked and "]]'s Hof" in masked
    assert session.unmask(masked) == text


def test_llm_profile_and_prompt() -> None:
    from pii_guard.detect.llm import build_messages, language_profile

    profile = language_profile("de-AT")
    assert (profile.code, profile.name, profile.allow_suffix) == ("de", "German", True)
    assert not any("_HU" in t.value for t in profile.entity_types)
    system = build_messages("Text", "de")[0]["content"]
    assert "Steuer-ID" in system and "genitive" in system
