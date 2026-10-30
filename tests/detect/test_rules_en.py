"""English language pack, language-independent card rule and rule-pack registry (LAB-1096).

Every value is fictional: card numbers are built from test payloads with a computed Luhn
digit, phone numbers use the Ofcom drama ranges and NANP 555-01xx, postcodes and plates are
made up (ADR 0005).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pii_guard.detect import rules
from pii_guard.detect.rules import RuleDetector, RulePack, primary_language, register_rule_pack
from pii_guard.detect.rules.common import is_valid_card_number, luhn_check_digit
from pii_guard.detect.rules.en import is_valid_nino, is_valid_ssn
from pii_guard.types import EntityType

E = EntityType
PREFIX = "Dear tenant, for the record: "
SUFFIX = " — kind regards."


def make_card(payload: str) -> str:
    return payload + str(luhn_check_digit(payload))


def grouped(value: str, size: int = 4, sep: str = " ") -> str:
    return sep.join(value[i : i + size] for i in range(0, len(value), size))


def broken(value: str) -> str:
    return value[:-1] + str((int(value[-1]) + 1) % 10)


VISA = make_card("400000000000000")  # 16 digits
MASTERCARD = make_card("555555000000000")
AMEX = make_card("37000000000000")  # 15 digits


@pytest.fixture(scope="module")
def detector() -> RuleDetector:
    # The validated rules on their own: a cue word before a checksum-failing number masks it
    # anyway (cued numbers, tests/languages/test_cues.py), which the look-alikes here exclude.
    return RuleDetector(cued_numbers=False)


def found(detector: RuleDetector, text: str, language: str = "en") -> list[tuple[EntityType, str]]:
    spans = detector.detect(text, language=language)
    for span in spans:
        assert text[span.start : span.end] == span.text
    return sorted((s.entity_type, s.text) for s in spans)


def assert_detects(
    detector: RuleDetector, value: str, entity_type: EntityType, language: str = "en"
) -> None:
    text = PREFIX + value + SUFFIX
    spans = [s for s in detector.detect(text, language=language) if s.entity_type is entity_type]
    assert len(spans) == 1, spans
    assert (spans[0].start, spans[0].end) == (len(PREFIX), len(PREFIX) + len(value))


def types_in(detector: RuleDetector, text: str, language: str = "en") -> set[EntityType]:
    return {s.entity_type for s in detector.detect(text, language=language)}


# --- Pack registry ----------------------------------------------------------


@pytest.mark.parametrize(
    ("tag", "code"), [("en", "en"), ("en-GB", "en"), ("EN_us", "en"), ("", "und"), ("hu", "hu")]
)
def test_primary_language(tag: str, code: str) -> None:
    assert primary_language(tag) == code


def test_built_in_packs() -> None:
    packs = rules.rule_packs()
    assert {"hu", "en"} <= set(packs)
    assert packs["en"].everywhere and packs["en"].rules


def test_language_scoped_rules_only_run_for_their_language(detector: RuleDetector) -> None:
    hu_only = set(detector.rules_for("hu")) - set(detector.rules_for("en"))
    en_only = set(detector.rules_for("en")) - set(detector.rules_for("hu"))
    assert hu_only and en_only
    # An unknown language gets exactly the shared rules.
    assert set(detector.rules_for("fi")) == set(detector.rules_for("hu")) - hu_only


def test_register_rule_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    def find_word(text: str) -> Iterator[rules._Hit]:
        start = text.find("Zorblax")
        if start >= 0:
            yield rules._Hit(start, start + 7, E.PERSON, 0.5)

    monkeypatch.setattr(rules, "_PACKS", dict(rules._PACKS))
    register_rule_pack(RulePack("xx", rules=(find_word,)))
    detector = RuleDetector()
    assert found(detector, "Hi Zorblax", language="xx-YY") == [(E.PERSON, "Zorblax")]
    assert found(detector, "Hi Zorblax", language="en") == []


# --- Payment cards (language-independent) -----------------------------------


@pytest.mark.parametrize(
    "value",
    [
        VISA,
        grouped(VISA),
        grouped(VISA, sep="-"),
        grouped(MASTERCARD),
        f"{AMEX[:4]} {AMEX[4:10]} {AMEX[10:]}",
        AMEX,
        make_card("401288888888188"),
        make_card("601100000000000"),  # Discover
        make_card("622126000000000"),  # UnionPay
        make_card("353000000000000"),  # JCB
        make_card("3000000000000"),  # Diners Club, 14 digits
        make_card("67590000000000"),  # Maestro, 15 digits
    ],
)
@pytest.mark.parametrize("language", ["en", "hu", "de"])
def test_payment_card(detector: RuleDetector, value: str, language: str) -> None:
    assert_detects(detector, value, E.PAYMENT_CARD, language)


def test_payment_card_has_its_own_type(detector: RuleDetector) -> None:
    # LAB-1102: a card is a PAYMENT_CARD, not a BANK_ACCOUNT, so a policy can treat it apart.
    assert found(detector, "card 4000 0000 0000 0002") == [(E.PAYMENT_CARD, "4000 0000 0000 0002")]


@pytest.mark.parametrize(
    "text",
    [
        broken(VISA),
        grouped(broken(VISA)),
        "Order 4417-2209-3301 shipped",  # 12 digits, not a card
        make_card("123456789012345"),  # no issuer starts with 1
        make_card("90000000000000"),  # unknown issuer
        make_card("4000000000000"),  # Visa is 13, 16 or 19 digits, never 14
        make_card("5555550000000"),  # Mastercard is always 16 digits
        make_card("3700000000000"),  # Amex is always 15 digits
        f"{grouped(VISA)} 1234",  # part of a longer grouped number
        f"{VISA}5",  # longer digit run
        f"{grouped(VISA[:8], sep='-')} {VISA[8:]}",  # mixed separators
        "tracking number 1Z999AA10123456784",
    ],
)
def test_payment_card_look_alikes(detector: RuleDetector, text: str) -> None:
    assert not {E.PAYMENT_CARD, E.BANK_ACCOUNT} & types_in(detector, text)


def test_luhn() -> None:
    assert luhn_check_digit("7992739871") == 3  # the textbook example
    assert is_valid_card_number(VISA) and not is_valid_card_number(broken(VISA))
    with pytest.raises(ValueError):
        luhn_check_digit("12a4")


@settings(max_examples=50)
@given(payload=st.text(alphabet="0123456789", min_size=14, max_size=14))
def test_card_property(payload: str) -> None:
    value = make_card("4" + payload)
    spans = RuleDetector().detect(PREFIX + grouped(value) + SUFFIX, language="en")
    assert [(s.entity_type, s.text) for s in spans] == [(E.PAYMENT_CARD, grouped(value))]


# --- US SSN -----------------------------------------------------------------


@pytest.mark.parametrize("language", ["en", "hu"])
def test_ssn_dashed_runs_everywhere(detector: RuleDetector, language: str) -> None:
    assert_detects(detector, "123-45-6789", E.ID_DOCUMENT, language)


def test_ssn_context_raises_score(detector: RuleDetector) -> None:
    plain = detector.detect("ref 123-45-6789", language="en")[0]
    labelled = detector.detect("SSN: 123-45-6789", language="en")[0]
    assert labelled.score > plain.score


@pytest.mark.parametrize(
    "text",
    [
        "000-12-3456",
        "666-12-3456",
        "912-34-5678",
        "123-00-4567",
        "123-45-0000",
        "1123-45-6789",
        "123-45-67890",
        "2026-10-26",
        "123-45-6789-1",
    ],
)
def test_ssn_structural_look_alikes(detector: RuleDetector, text: str) -> None:
    assert E.ID_DOCUMENT not in types_in(detector, text)


@pytest.mark.parametrize("value", ["123 45 6789", "123456789"])
def test_ssn_without_dashes_needs_context(detector: RuleDetector, value: str) -> None:
    assert found(detector, f"Social Security number {value}.") == [(E.ID_DOCUMENT, value)]
    assert E.ID_DOCUMENT not in types_in(detector, f"Invoice {value}.")
    assert E.ID_DOCUMENT not in types_in(detector, f"SSN {value}.", language="hu")


def test_ssn_validation() -> None:
    assert is_valid_ssn("123", "45", "6789")
    assert not is_valid_ssn("12", "345", "6789")
    assert not is_valid_ssn("12a", "45", "6789")


# --- UK National Insurance number -------------------------------------------


@pytest.mark.parametrize("value", ["AB 12 34 56 C", "AB123456C", "JG 10 20 30 A", "CE 99 88 77 D"])
@pytest.mark.parametrize("language", ["en", "hu"])
def test_nino(detector: RuleDetector, value: str, language: str) -> None:
    assert_detects(detector, value, E.ID_DOCUMENT, language)


@pytest.mark.parametrize(
    "text",
    [
        "DA 12 34 56 C",  # D never first
        "AO 12 34 56 C",  # O never second
        "QQ 12 34 56 C",  # Q never used (the HMRC example)
        "GB 12 34 56 C",  # reserved prefix
        "NK 12 34 56 C",
        "TN 12 34 56 C",
        "AB 12 34 56 E",  # suffix A-D only
        "AB 12 3456 C",  # inconsistent spacing
        "ab 12 34 56 c",
        "XAB123456C",
    ],
)
def test_nino_look_alikes(detector: RuleDetector, text: str) -> None:
    assert E.ID_DOCUMENT not in types_in(detector, text)


def test_nino_validation() -> None:
    assert is_valid_nino("AB123456C")
    assert not is_valid_nino("AB12345C")
    assert not is_valid_nino("ÁB123456C")


# --- Phone numbers ----------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "020 7946 0000",
        "(020) 7946 0000",
        "0161 496 0000",
        "07700 900123",
        "07700900123",
        "0113 496 0000",
        "(202) 555-0143",
        "202-555-0143",
        "202.555.0143",
        "1-202-555-0143",
        "+44 20 7946 0123",
        "+1 202 555 0143",
    ],
)
def test_english_phone(detector: RuleDetector, value: str) -> None:
    assert_detects(detector, value, E.PHONE)


@pytest.mark.parametrize(
    "text",
    [
        "0123456789",  # 10 digits without separators
        "05 1234 5678",  # 05 is not a geographic or mobile range
        "00 1234 56789",
        "(911) 555-0143",  # N11 area code
        "202-411-0143",  # N11 exchange
        "102-555-0143",  # area code starts with 1
        "2026-10-26",
        "02/07/1991",
        "4417-2209-3301",
        "Room 101, Building 7",
    ],
)
def test_english_phone_look_alikes(detector: RuleDetector, text: str) -> None:
    assert E.PHONE not in types_in(detector, text)


def test_national_formats_are_english_only(detector: RuleDetector) -> None:
    assert E.PHONE not in types_in(detector, "Tel: 020 7946 0000", language="hu")
    assert E.PHONE not in types_in(detector, "Tel: (202) 555-0143", language="hu")


# --- Postcodes and ZIP codes ------------------------------------------------


@pytest.mark.parametrize(
    "value", ["SW1A 1AA", "EX1 2AB", "M1 1AE", "B33 8TH", "CR2 6XH", "DN55 1PT", "EC1A1BB"]
)
def test_uk_postcode(detector: RuleDetector, value: str) -> None:
    assert_detects(detector, value, E.ADDRESS)


@pytest.mark.parametrize(
    "text", ["EX1 2CB", "QX1 2AB", "SW1A 1A", "sw1a 1aa", "EX12 MPL", "GB85 EXMP", "ISO 9001"]
)
def test_uk_postcode_look_alikes(detector: RuleDetector, text: str) -> None:
    assert E.ADDRESS not in types_in(detector, text)


@pytest.mark.parametrize(
    ("text", "zip_code"),
    [
        ("12 Example Street, Springfield, IL 62704", "62704"),
        ("Exampleville, NY 10001-1234", "10001-1234"),
        ("ZIP code: 90210", "90210"),
        ("zip 30301", "30301"),
    ],
)
def test_us_zip_in_address_context(detector: RuleDetector, text: str, zip_code: str) -> None:
    assert found(detector, text) == [(E.ADDRESS, zip_code)]


@pytest.mark.parametrize(
    "text", ["Order 62704 shipped", "In 2019 Robin moved", "IL 627041", "ZIP 1234", "ILL 62704"]
)
def test_us_zip_look_alikes(detector: RuleDetector, text: str) -> None:
    assert E.ADDRESS not in types_in(detector, text)


def test_hungarian_postcode_is_hungarian_only(detector: RuleDetector) -> None:
    assert E.ADDRESS in types_in(detector, "1051 Budapest", language="hu")
    assert E.ADDRESS not in types_in(detector, "In 2019 Robin moved", language="en")
    assert E.ADDRESS not in types_in(detector, "In 2019 Robin moved", language="de")


# --- Vehicle plates ---------------------------------------------------------


@pytest.mark.parametrize("value", ["EX12 MPL", "AB51 CDE", "YY26XYZ", "LA02 ABC"])
def test_uk_plate(detector: RuleDetector, value: str) -> None:
    assert_detects(detector, value, E.VEHICLE_PLATE)


@pytest.mark.parametrize(
    "text", ["EX50 MPL", "EX01 MPL", "IX12 MPL", "EX12 MIL", "ex12 mpl", "EX12 MPLX", "EX123 MPL"]
)
def test_uk_plate_look_alikes(detector: RuleDetector, text: str) -> None:
    assert E.VEHICLE_PLATE not in types_in(detector, text)


def test_plate_formats_follow_the_language(detector: RuleDetector) -> None:
    assert E.VEHICLE_PLATE not in types_in(detector, "EX12 MPL", language="hu")
    assert E.VEHICLE_PLATE not in types_in(detector, "ABC-123", language="en")
    assert E.VEHICLE_PLATE in types_in(detector, "ABC-123", language="hu")


# --- ID documents in context ------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Your passport X1234567 is ready", "X1234567"),
        ("Jonathan's passport number is 123456789 and", "123456789"),
        ("Passport No. 987654321", "987654321"),
        ("driving licence: EXAMP801019AB9CD", "EXAMP801019AB9CD"),
        ("Driver's license #D1234567", "D1234567"),
    ],
)
def test_id_document_in_context(detector: RuleDetector, text: str, value: str) -> None:
    assert (E.ID_DOCUMENT, value) in found(detector, text)


@pytest.mark.parametrize(
    "text",
    [
        "Bring your passport to the office.",
        "passport ABCDEFGH",  # no digit
        "passport 12345",  # too short
        "X1234567 is ready",  # no label
    ],
)
def test_id_document_look_alikes(detector: RuleDetector, text: str) -> None:
    assert E.ID_DOCUMENT not in types_in(detector, text)


# --- Whole documents --------------------------------------------------------


def test_english_letter(detector: RuleDetector) -> None:
    card = grouped(VISA)
    text = (
        "Dear Ms Testwood,\n\nYour passport X1234567 is ready at 400 Imaginary Avenue, "
        "Springfield, IL 62704. Call (202) 555-0143 or 020 7946 0000. NI number "
        f"AB 12 34 56 C, SSN 123-45-6789, card {card}, car EX12 MPL, flat in EX1 2AB.\n"
        "Order 4417-2209-3301 shipped on 3 November 2026."
    )
    assert found(detector, text) == sorted(
        [
            (E.ID_DOCUMENT, "X1234567"),
            (E.ADDRESS, "62704"),
            (E.PHONE, "(202) 555-0143"),
            (E.PHONE, "020 7946 0000"),
            (E.ID_DOCUMENT, "AB 12 34 56 C"),
            (E.ID_DOCUMENT, "123-45-6789"),
            (E.PAYMENT_CARD, card),
            (E.VEHICLE_PLATE, "EX12 MPL"),
            (E.ADDRESS, "EX1 2AB"),
        ]
    )


@settings(max_examples=200)
@given(text=st.text())
def test_never_crashes_and_offsets_hold_in_english(text: str) -> None:
    for span in RuleDetector().detect(text, language="en-GB"):
        assert text[span.start : span.end] == span.text
