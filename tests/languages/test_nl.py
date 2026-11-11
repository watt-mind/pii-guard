"""The Dutch pack (LAB-1777): BSN elfproef, rules, scopes, hard negatives, cues, genitive. All
values are fictional or the published examples of the algorithm."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pii_guard.detect.checksums import is_valid_taj, taj_check_digit
from pii_guard.detect.ner_numbers import number_verdict
from pii_guard.detect.rules import RuleDetector
from pii_guard.detect.rules._base import reference_or_amount_before
from pii_guard.languages.nl.checksums import bsn_check_digit, is_valid_bsn
from pii_guard.languages.nl.inflection import DutchGenitiveMatcher
from pii_guard.types import EntityType as E
from pii_guard.types import Span
from pii_guard.vault import Vault


def _bsn(payload8: str) -> str:
    check = bsn_check_digit(payload8)
    assert check is not None
    return payload8 + str(check)


def _bump(value: str, index: int = -1) -> str:
    i = index % len(value)
    return value[:i] + str((int(value[i]) + 1) % 10) + value[i + 1 :]


# The published examples, and made-up payloads with computed check digits (issued to nobody).
BSN = "123456782"
BSN_2 = _bsn("23456789")
# A Polish mobile number (prefix 512) that happens to pass the elfproef.
PL_PHONE = "512345600"
FULL_WIDTH = "".join(chr(0xFF10 + int(d)) for d in BSN)  # the BSN in full-width digits


def _taj_and_bsn() -> str:
    """The first Hungarian TAJ (from a made-up payload) that also passes the elfproef."""
    for n in range(10_000_000, 10_100_000):
        value = f"{n}{taj_check_digit(str(n))}"
        if is_valid_bsn(value):
            return value
    raise AssertionError("no such number")


HU_TAJ = _taj_and_bsn()


@pytest.fixture(scope="module")
def detector() -> RuleDetector:
    return RuleDetector()


def _found(detector: RuleDetector, text: str, language: str = "nl") -> list[tuple[str, str]]:
    return [(s.entity_type.value, s.text) for s in detector.detect(text, language)]


# --- Checksums ---------------------------------------------------------------------------


def test_published_examples() -> None:
    # RvIG's test number and the example of the elfproef in public descriptions.
    for value in ("111222333", "123456782"):
        assert is_valid_bsn(value), value
    assert bsn_check_digit("12345678") == 2


def test_cross_language_numbers_pass_the_elfproef() -> None:
    # The premise of the scope tests below: these really are valid BSN shapes.
    assert is_valid_bsn(PL_PHONE) and is_valid_bsn(HU_TAJ) and is_valid_taj(HU_TAJ)


@pytest.mark.parametrize(
    "value",
    [_bump(BSN), "000000000", BSN[:8], BSN + "0", BSN[:8] + "x", FULL_WIDTH],
)
def test_invalid_bsns(value: str) -> None:
    assert not is_valid_bsn(value)


def test_a_remainder_of_ten_has_no_check_digit() -> None:
    # The last payload digit weighs 2: 5 * 2 = 10, which no digit can match.
    assert bsn_check_digit("00000005") is None


@given(st.text("0123456789", min_size=8, max_size=8))
def test_a_wrong_check_digit_is_rejected(payload: str) -> None:
    check = bsn_check_digit(payload)
    if check is None:
        assert not any(is_valid_bsn(payload + str(d)) for d in range(10))
    else:
        assert is_valid_bsn(payload + str(check)) or payload + str(check) == "000000000"
        assert not is_valid_bsn(payload + str((check + 1) % 10))


def test_check_arguments_are_validated() -> None:
    with pytest.raises(ValueError):
        bsn_check_digit("1234")


# --- Rules -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("BSN", BSN),
        ("BSN-nummer:", BSN),
        ("burgerservicenummer", BSN),
        ("sofinummer", BSN),
        ("sofi-nr.", BSN),
        ("BSN", "1234.56.782"),
        ("BSN:", "123 456 782"),
    ],
)
def test_labelled_bsn(detector: RuleDetector, label: str, value: str) -> None:
    text = f"{label} {value}"
    spans = detector.detect(text, "nl")
    assert [(s.entity_type, s.text, s.score) for s in spans] == [(E.ID_DOCUMENT, value, 0.97)]


def test_scopes(detector: RuleDetector) -> None:
    # A labelled BSN is found in any language ...
    for language in ("en", "de", "hu", "pl"):
        assert _found(detector, f"BSN {BSN_2}", language) == [("ID_DOCUMENT", BSN_2)]
    # ... an unlabelled one, a postcode or an address only in Dutch text (a landline like
    # "020-555 0123" is also a UK number, which the English rules find).
    for text in (
        f"Patiënt nummer {BSN_2} gezien.",
        "Lindelaan 42, 3521 AB Utrecht",
        "wonende te 3521 AB Utrecht",
    ):
        assert _found(detector, text, "en") == []
        assert _found(detector, text, "nl") != []


@pytest.mark.parametrize("language", ["pl", "hu", "en", "de"])
def test_an_unlabelled_elfproef_number_is_not_a_bsn_outside_dutch(
    detector: RuleDetector, language: str
) -> None:
    # One nine-digit number in eleven passes the elfproef (LAB-1433's lesson for the TAJ).
    for value in (PL_PHONE, HU_TAJ):
        spans = detector.detect(f"Numer {value} jest zapisany. Szám: {value}", language)
        assert not [s for s in spans if s.entity_type is E.ID_DOCUMENT], (language, value)
    # In Dutch text the same number is a BSN.
    assert _found(detector, f"Het nummer {PL_PHONE} staat in het dossier.", "nl") == [
        ("ID_DOCUMENT", PL_PHONE)
    ]


def test_bad_check_digits_and_documents_are_masked_after_a_cue(detector: RuleDetector) -> None:
    for label, value in (
        ("BSN", _bump(BSN)),
        ("burgerservicenummer", _bump(BSN)),
        ("paspoortnummer", "NX12345K7"),
        ("identiteitskaart", "IX98765K4"),
        ("rijbewijsnummer", "5123456789"),
    ):
        spans = detector.detect(f"{label} {value}.", "nl")
        assert [(s.entity_type, s.text, s.score) for s in spans] == [(E.ID_DOCUMENT, value, 0.6)], (
            label
        )


@pytest.mark.parametrize(
    "text",
    [
        "06-12345678",
        "06 12345678",
        "06 1234 5678",
        "06 12 34 56 78",
        "(06) 12345678",
        "0612345678",
        "020-555 0123",
        "020 555 0123",
        "020-5550123",
        "(010) 555 0147",
        "0471-555012",
        "+31 6 23456789",
        "+31 20 555 0193",
    ],
)
def test_phone_numbers(detector: RuleDetector, text: str) -> None:
    assert _found(detector, f"Bereikbaar op {text}.") == [("PHONE", text)]


@pytest.mark.parametrize("text", ["0800-1234567", "0900 123 4567"])
def test_service_numbers_are_companies(detector: RuleDetector, text: str) -> None:
    assert ("PHONE", text) not in _found(detector, f"Klantenservice {text}.")


@pytest.mark.parametrize(
    "text",
    [
        "Lindelaan 42, 3521 AB Utrecht",
        "Lindelaan 42",
        "Havenweg 3, 4381 LL Vlissingen",
        "Van Goghstraat 7-II, 1071 AB Amsterdam",
        "Burgemeester de Withstraat 12a",
        "Prins Hendrikkade 21-H, 1012 TM Amsterdam",
        "Oude Gracht 3",
        "Dorpsstraat 12 hs, 2511 CV Den Haag",
        "Kerkweg 5 4611 AA Bergen op Zoom",
    ],
)
def test_addresses(detector: RuleDetector, text: str) -> None:
    assert _found(detector, f"wonende {text}.") == [("ADDRESS", text)]


def test_an_address_over_two_lines(detector: RuleDetector) -> None:
    text = "Joris Testkamp\nBurgemeester de Withstraat 3\n5211 AB Den Bosch"
    assert _found(detector, text) == [
        ("ADDRESS", "Burgemeester de Withstraat 3\n5211 AB Den Bosch")
    ]


@pytest.mark.parametrize(
    "text",
    ["3521 AB Utrecht", "5211 AB 's-Hertogenbosch", "2611AB Delft", "1012 TM Amsterdam"],
)
def test_postcode_and_place(detector: RuleDetector, text: str) -> None:
    assert _found(detector, f"verhuisd naar {text}.") == [("ADDRESS", text)]


def test_a_bare_postcode_needs_its_label(detector: RuleDetector) -> None:
    assert _found(detector, "Postcode: 3521 AB") == [("ADDRESS", "3521 AB")]
    assert _found(detector, "Code 3521 AB is verlopen.") == []


@pytest.mark.parametrize(
    "text",
    [
        "Op de beurs kwamen\n20000 Bezoekers uit het hele land.",
        "Vergadering op 05-11-2026 van 08.30-12.30 uur, verplaatst naar 06-12-2026.",
        "Factuurnummer 2026-00932, bedrag 1.450,00 EUR, te betalen binnen 14 dagen.",
        f"Bestelnummer {BSN} en factuur nr. {BSN_2}.",
        f"Klantnummer {BSN}, kenmerk {BSN_2}.",
        "Ingeschreven bij de KvK onder 12345678, btw-nummer NL001234567B01.",
        "De begroting van 1.250.000,00 EUR loopt van 2026-2030.",
        "Het bestand is 1000 KB groot en de 2026 EU-richtlijn geldt.",
        "We liepen de weg 3 keer op en neer.",
        "In Amsterdam 2026 werd het feest gevierd.",
        "Het adres 3521 SA Utrecht bestaat niet.",  # SA, SD and SS are never issued
        "Gevestigd te 3521 AB Utrecht B.V. Holding.",
        "Klantenservice 0800-1234567 of 0900-1234567.",
        "Totaal 123 456 782 euro, waarvan 1234.56.782 in 2026.",
    ],
)
def test_hard_negatives(detector: RuleDetector, text: str) -> None:
    assert _found(detector, text) == []


# --- Cues and reference words ------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "Factuurnummer:",
        "Factuur nr.",
        "Bestelnummer",
        "bestelling",
        "Ordernummer",
        "Klantnummer",
        "Kenmerk",
        "Betalingskenmerk",
        "Dossiernummer",
        "Zaaknummer",
        "KvK",
        "KvK-nummer",
        "Creditnota",
    ],
)
def test_dutch_reference_labels_are_shared(label: str) -> None:
    text = f"{label} 123456789"
    assert reference_or_amount_before(text, len(text) - 9)


@pytest.mark.parametrize(
    "text",
    [
        "Bestelnummer 0201234567",
        "Factuurnummer 0201234567",
        "Klantnummer 0201234567",
        "Kenmerk 0201234567",
        "Telefoon of bestelnummer 0201234567",
        "KvK-nummer 0201234567",
    ],
)
def test_negative_cues_keep_business_numbers(detector: RuleDetector, text: str) -> None:
    assert _found(detector, text) == []


def test_and_or_are_no_cues(detector: RuleDetector) -> None:
    # "en" and "of" are no "-" cues: they would end the window in French, Spanish and English
    # text, where they are other words ("téléphone en cas d'urgence", "phone number of").
    assert _found(detector, "phone of the office: 0201234567", "en") == [("PHONE", "0201234567")]
    assert _found(detector, "telefoon en fax 0201234567") == [("PHONE", "0201234567")]


def test_dutch_reference_words_stay_out_of_the_ner_check() -> None:
    # Scoped to the rules check until the NER negatives may grow beyond the built-in list
    # (LAB-1788): a Dutch label alone does not drop an NER number yet.
    from pii_guard.detect.ner_numbers import _pack_negatives

    assert not {"factuur*", "kenmerk*", "klantnummer*"} & set(_pack_negatives() or [])


def test_ner_keeps_an_identifier_after_its_dutch_label() -> None:
    for label in ("BSN", "burgerservicenummer", "paspoort", "rijbewijs"):
        text = f"{label} 5550123456"
        assert number_verdict(text, len(label) + 1, len(text)), label


# --- Genitive, names, prompt -------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "pattern"),
    [
        ("Pieter", "(?:['\u2019]s|s|['\u2019])"),
        ("Anna", "(?:['\u2019]s|s|['\u2019])"),
        ("Van Dijk", "(?:['\u2019]s|s|['\u2019])"),
        ("Joris", "(?:['\u2019])"),
        ("Max", "(?:['\u2019])"),
        ("Bush", "(?:['\u2019])"),
        ("Beatrice", "(?:['\u2019])"),
        ("NX12345K7", ""),
        ("", ""),
    ],
)
def test_genitive_pattern(value: str, pattern: str) -> None:
    assert DutchGenitiveMatcher().suffix_pattern(value, E.PERSON) == pattern


def test_genitive_names_are_masked_and_restored() -> None:
    session = Vault(b"nl-pack-test-key-01").session()
    text = "Pieters fiets staat bij Anna's huis; Joris' auto en Pieterse niet."
    spans = [
        Span(0, 6, E.PERSON, "Pieter", 1.0, "t"),
        Span(24, 28, E.PERSON, "Anna", 1.0, "t"),
        Span(37, 42, E.PERSON, "Joris", 1.0, "t"),
    ]
    masked = session.mask(text, spans, language="nl")
    assert "Pieters fiets" not in masked and "Anna" not in masked and "Joris" not in masked
    assert "]]s fiets" in masked and "]]'s huis" in masked and "]]' auto" in masked
    assert "Pieterse" in masked  # another surname, not a genitive
    assert session.unmask(masked) == text


def test_llm_profile_and_prompt() -> None:
    from pii_guard.detect.llm import build_messages, language_profile

    profile = language_profile("nl-NL")
    assert (profile.code, profile.name, profile.allow_suffix) == ("nl", "Dutch", True)
    system = build_messages("Tekst", "nl")[0]["content"]
    assert "burgerservicenummer" in system and "van der" in system
