"""ASCII format variants the rules used to miss (LAB-1216).

A code review's probe found identifiers printed in formats the rules did not accept: a
lower-case IBAN, an IBAN with runs of spaces between its groups, a giro account in groups of
four or with a dot, a TAJ number with dots or slashes, and an international phone number with
its country code in parentheses. Every value is fictional and passes its checksum (ADR 0005):
``DE89 3704 0044 0532 0130 00`` is the textbook example IBAN, the giro and TAJ numbers are
built from made-up payloads.
"""

from __future__ import annotations

import pytest

from pii_guard.detect.checksums import giro_check_digit, iban_check_digits, taj_check_digit
from pii_guard.detect.pipeline import DetectionPipeline
from pii_guard.detect.rules import RuleDetector
from pii_guard.types import EntityType

E = EntityType

IBAN_DE = "DE89370400440532013000"
GIRO = "1177301" + str(giro_check_digit("1177301")) + "1111101" + str(giro_check_digit("1111101"))
TAJ = "12345678" + str(taj_check_digit("12345678"))


def _groups(value: str, size: int, sep: str = " ") -> str:
    return sep.join(value[i : i + size] for i in range(0, len(value), size))


@pytest.fixture(scope="module")
def detector() -> RuleDetector:
    # Cued numbers off: these must be found by the validated rules themselves.
    return RuleDetector(cued_numbers=False)


def found(detector: RuleDetector, text: str, language: str = "hu") -> list[tuple[E, str]]:
    spans = detector.detect(text, language)
    for span in spans:
        assert text[span.start : span.end] == span.text
    return sorted((s.entity_type, s.text) for s in spans)


# --- The reviewers' probe inputs, through the full rules pipeline ------------


@pytest.mark.parametrize(
    ("language", "text", "expected"),
    [
        ("en", "IBAN de89370400440532013000", "de89370400440532013000"),
        ("en", "IBAN DE89  3704 0044 0532 0130 00", "DE89  3704 0044 0532 0130 00"),
        ("hu", "Számla: 1177 3016 1111 1018", "1177 3016 1111 1018"),
        ("hu", "Számla: 11773016.11111018", "11773016.11111018"),
        ("hu", "TAJ: 123.456.788", "123.456.788"),
        ("hu", "TAJ: 123/456/788", "123/456/788"),
        ("en", "Call (+44) 20 7946 0958", "(+44) 20 7946 0958"),
        ("en", 'Mail me at "john doe"@example.com', '"john doe"@example.com'),
        ("en", "Mail me at user@example.xn--p1ai", "user@example.xn--p1ai"),
    ],
)
def test_probe_inputs_are_found_whole(language: str, text: str, expected: str) -> None:
    spans = DetectionPipeline([RuleDetector()]).detect(text, language)
    assert [s.text for s in spans] == [expected]
    start = text.index(expected)
    assert (spans[0].start, spans[0].end) == (start, start + len(expected))


# --- IBAN --------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        IBAN_DE.lower(),
        _groups(IBAN_DE.lower(), 4),
        "gb82west12345698765432",  # letters in the BBAN, lower case too
        "DE89  3704  0044  0532  0130  00",
        "DE89   3704 0044 0532 0130 00",
        "GB82 WEST  1234 5698 7654 32",
    ],
)
def test_iban_case_and_space_runs(detector: RuleDetector, value: str) -> None:
    assert found(detector, f"Pay to {value} please", "en") == [(E.BANK_ACCOUNT, value)]


@pytest.mark.parametrize(
    "text",
    [
        "De89370400440532013000",  # mixed case is not how an IBAN is printed
        "de89370400440532013000".replace("de", "dE"),
        "GB82west12345698765432",
        "de89370400440532013001",  # checksum still required
        "made89370400440532013000",  # inside a word
        "DE89 3704 0044 0532 0130 001",  # runs on
    ],
)
def test_iban_variants_still_need_a_valid_shape(detector: RuleDetector, text: str) -> None:
    assert E.BANK_ACCOUNT not in {s.entity_type for s in detector.detect(text, "en")}


def test_iban_space_run_does_not_join_a_following_number(detector: RuleDetector) -> None:
    text = f"{_groups(IBAN_DE, 4)}  12"
    assert found(detector, text, "en") == [(E.BANK_ACCOUNT, _groups(IBAN_DE, 4))]


def test_lower_case_hungarian_iban(detector: RuleDetector) -> None:
    value = ("HU" + iban_check_digits("HU", GIRO + "00000000") + GIRO + "00000000").lower()
    assert found(detector, f"IBAN: {_groups(value, 4)}") == [(E.BANK_ACCOUNT, _groups(value, 4))]


# --- Giro account ------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        _groups(GIRO, 4),
        _groups(GIRO, 4, "-"),
        f"{GIRO[:8]}.{GIRO[8:]}",
    ],
)
def test_giro_groups_of_four_and_dot(detector: RuleDetector, value: str) -> None:
    assert found(detector, f"Számla: {value}, köszönöm") == [(E.BANK_ACCOUNT, value)]


def test_giro_24_digits_in_groups_of_four(detector: RuleDetector) -> None:
    giro24 = "1177301" + str(giro_check_digit("1177301"))
    payload = "123456789012345"
    giro24 += payload + str(giro_check_digit(payload))
    for value in (_groups(giro24, 4), f"{giro24[:8]}.{giro24[8:16]}.{giro24[16:]}"):
        assert found(detector, f"Számla: {value}") == [(E.BANK_ACCOUNT, value)]


@pytest.mark.parametrize(
    "text",
    [
        _groups(GIRO[:-1] + str((int(GIRO[-1]) + 1) % 10), 4),  # checksum still required
        f"{GIRO[:4]} {GIRO[4:8]}-{GIRO[8:12]} {GIRO[12:]}",  # mixed separators
        f"1 {_groups(GIRO, 4)}",  # part of a longer grouped number
        f"{_groups(GIRO, 4)} 1234",
        f"{GIRO[:8]}.{GIRO[8:]}.5",  # a longer dotted number
        f"{GIRO[:4]}.{GIRO[4:8]}.{GIRO[8:12]}.{GIRO[12:]}",  # dotted groups of four
    ],
)
def test_giro_variant_look_alikes(detector: RuleDetector, text: str) -> None:
    assert E.BANK_ACCOUNT not in {s.entity_type for s in detector.detect(text)}


# --- TAJ ---------------------------------------------------------------------


@pytest.mark.parametrize("sep", [".", "/"])
@pytest.mark.parametrize(
    "template", ["TAJ: {}", "TAJ szám: {}", "társadalombiztosítási azonosító jel: {}"]
)
def test_taj_dot_and_slash_with_cue(detector: RuleDetector, sep: str, template: str) -> None:
    value = sep.join((TAJ[:3], TAJ[3:6], TAJ[6:]))
    assert found(detector, template.format(value)) == [(E.NATIONAL_ID_HU_TAJ, value)]


@pytest.mark.parametrize(
    "text",
    [
        # Without a TAJ cue a dotted nine-digit number is a thousands-grouped amount or count,
        # and a slashed one a reference: 1 in 10 of them pass the TAJ check.
        f"Lakosság: {TAJ[:3]}.{TAJ[3:6]}.{TAJ[6:]} fő",
        f"Population {TAJ[:3]}.{TAJ[3:6]}.{TAJ[6:]}",
        f"Ügyirat {TAJ[:3]}/{TAJ[3:6]}/{TAJ[6:]}",
        f"TAJ: {TAJ[:3]}.{TAJ[3:6]}/{TAJ[6:]}",  # mixed separators
        f"TAJ: {TAJ[:3]}.{TAJ[3:6]}.{TAJ[6:]}.000",  # a longer dotted number
        f"TAJ: 1.{TAJ[:3]}.{TAJ[3:6]}.{TAJ[6:]}",
        f"TAJ: {TAJ[:3]}.{TAJ[3:6]}.{TAJ[6:-1]}{(int(TAJ[-1]) + 1) % 10}",  # checksum
        f"TAJ: {TAJ[:3]}.{TAJ[3:6]}.{TAJ[6:]} Ft",  # an amount
    ],
)
def test_taj_dot_and_slash_look_alikes(detector: RuleDetector, text: str) -> None:
    assert E.NATIONAL_ID_HU_TAJ not in {s.entity_type for s in detector.detect(text)}


# --- International phone -----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Call (+44) 20 7946 0958 today", "(+44) 20 7946 0958"),
        ("Call (+1) 415 555 0123", "(+1) 415 555 0123"),
        ("Call +44 20 7946 0958 (office)", "+44 20 7946 0958"),
        ("(call +44 20 7946 0958)", "+44 20 7946 0958"),
    ],
)
def test_intl_phone_parenthesised_country_code(
    detector: RuleDetector, text: str, expected: str
) -> None:
    assert found(detector, text, "en") == [(E.PHONE, expected)]
