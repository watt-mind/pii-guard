"""Rule detector. Every identifier is generated with a valid (or deliberately broken) checksum
from fictional payloads; none is a real person's or company's (ADR 0005)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pii_guard import registry
from pii_guard.detect import rules
from pii_guard.detect.checksums import (
    IBAN_LENGTHS,
    giro_check_digit,
    hu_tax_id_check_digit,
    hu_tax_number_check_digit,
    iban_check_digits,
    is_valid_giro,
    taj_check_digit,
)
from pii_guard.detect.rules import RuleDetector
from pii_guard.types import DetectionError, Detector, EntityType, Span

# Accented text around every value, so offsets are checked against non-ASCII code points.
PREFIX = "Árvíztűrő tükörfúrógép, ŐŰ: "
SUFFIX = " — köszönöm, üdvözlettel."

E = EntityType


# --- Synthetic value generators ---------------------------------------------


def make_tax_id(payload: str = "12345678") -> str:
    check = hu_tax_id_check_digit("8" + payload)
    assert check is not None
    return f"8{payload}{check}"


def make_taj(payload: str = "11122233") -> str:
    return payload + str(taj_check_digit(payload))


def make_giro(bank: str = "1177301", account: str = "123456789012345") -> str:
    return bank + str(giro_check_digit(bank)) + account + str(giro_check_digit(account))


def make_iban(country: str = "HU", bban: str | None = None) -> str:
    bban = bban if bban is not None else make_giro()
    return country + iban_check_digits(country, bban) + bban


def make_tax_number(payload: str = "1234567", vat: str = "2", area: str = "42") -> str:
    return f"{payload}{hu_tax_number_check_digit(payload)}-{vat}-{area}"


def broken(value: str, index: int = -1) -> str:
    """``value`` with one digit changed, so its checksum fails."""
    index = index % len(value)
    return value[:index] + str((int(value[index]) + 1) % 10) + value[index + 1 :]


def grouped(value: str, size: int = 4) -> str:
    return " ".join(value[i : i + size] for i in range(0, len(value), size))


# --- Helpers ----------------------------------------------------------------


@pytest.fixture(scope="module")
def detector() -> RuleDetector:
    return RuleDetector()


def found(detector: RuleDetector, text: str) -> list[tuple[EntityType, str]]:
    spans = detector.detect(text)
    for span in spans:
        assert text[span.start : span.end] == span.text
    return sorted((s.entity_type, s.text) for s in spans)


def assert_detects(detector: RuleDetector, value: str, entity_type: EntityType) -> Span:
    """``value`` embedded in accented text is found once, with exact offsets."""
    text = PREFIX + value + SUFFIX
    spans = [s for s in detector.detect(text) if s.entity_type is entity_type]
    assert len(spans) == 1, spans
    span = spans[0]
    assert (span.start, span.end) == (len(PREFIX), len(PREFIX) + len(value))
    assert span.text == value
    assert span.detector == "rules"
    return span


def assert_nothing(detector: RuleDetector, text: str) -> None:
    assert detector.detect(text) == []


# --- Protocol, registry, fail closed ----------------------------------------


def test_is_a_detector() -> None:
    detector = registry.create_detector("rules")
    assert isinstance(detector, RuleDetector)
    assert isinstance(detector, Detector)
    assert detector.name == "rules"
    assert rules.DETECTOR_CLASS is RuleDetector


def test_empty_and_plain_text(detector: RuleDetector) -> None:
    assert_nothing(detector, "")
    assert_nothing(detector, "Ez egy teljesen ártalmatlan mondat, számok nélkül.")


def test_rule_error_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = make_tax_id()

    def boom(text: str) -> Iterator[rules._Hit]:
        raise RuntimeError(f"broken rule saw {text}")

    detector = RuleDetector()
    monkeypatch.setattr(detector, "_rules", (*detector._rules, boom))
    with pytest.raises(DetectionError) as exc:
        detector.detect(f"Adóazonosító: {secret}")
    assert exc.value.code == "detection_failed"
    assert secret not in str(exc.value)


def test_non_str_input_fails_closed(detector: RuleDetector) -> None:
    with pytest.raises(DetectionError, match="expects str"):
        detector.detect(b"8123456786")  # type: ignore[arg-type]


def test_span_repr_does_not_leak(detector: RuleDetector) -> None:
    value = make_tax_id()
    (span,) = detector.detect(value)
    assert value not in repr(span)


# --- Hungarian personal tax ID ----------------------------------------------


def test_tax_id(detector: RuleDetector) -> None:
    span = assert_detects(detector, make_tax_id(), E.NATIONAL_ID_HU_TAX)
    with_context = detector.detect(f"Adóazonosító jele: {make_tax_id()}")[0]
    assert with_context.score > span.score


@pytest.mark.parametrize(
    "text",
    [
        broken(make_tax_id()),  # wrong check digit
        "7" + make_tax_id()[1:],  # must start with 8
        "1" + make_tax_id(),  # inside an 11-digit run
        make_tax_id() + "5",
        f"{make_tax_id()} Ft",  # an amount
        f"0.{make_tax_id()}",  # a decimal
    ],
)
def test_tax_id_look_alikes(detector: RuleDetector, text: str) -> None:
    assert E.NATIONAL_ID_HU_TAX not in {s.entity_type for s in detector.detect(text)}


@settings(max_examples=50)
@given(payload=st.text(alphabet="0123456789", min_size=8, max_size=8))
def test_tax_id_property(payload: str) -> None:
    if hu_tax_id_check_digit("8" + payload) is None:
        return
    assert_detects(RuleDetector(), make_tax_id(payload), E.NATIONAL_ID_HU_TAX)


# --- TAJ ---------------------------------------------------------------------


@pytest.mark.parametrize("fmt", ["{}{}{}", "{} {} {}", "{}-{}-{}"])
def test_taj_formats(detector: RuleDetector, fmt: str) -> None:
    taj = make_taj()
    assert_detects(detector, fmt.format(taj[:3], taj[3:6], taj[6:]), E.NATIONAL_ID_HU_TAJ)


def test_taj_context_raises_score(detector: RuleDetector) -> None:
    plain = detector.detect(make_taj())[0]
    with_context = detector.detect(f"TAJ szám: {make_taj()}")[0]
    assert with_context.score > plain.score


@pytest.mark.parametrize(
    "text",
    [
        broken(make_taj()),
        "4" + make_taj(),
        make_taj() + "4",
        f"{make_taj()[:3]} {make_taj()[3:6]}-{make_taj()[6:]}",  # mixed separators
        f"1 {make_taj()[:3]} {make_taj()[3:6]} {make_taj()[6:]}",  # a grouped 10-digit amount
        f"{make_taj()} HUF",
    ],
)
def test_taj_look_alikes(detector: RuleDetector, text: str) -> None:
    assert E.NATIONAL_ID_HU_TAJ not in {s.entity_type for s in detector.detect(text)}


@settings(max_examples=50)
@given(payload=st.text(alphabet="0123456789", min_size=8, max_size=8))
def test_taj_property(payload: str) -> None:
    assert_detects(RuleDetector(), make_taj(payload), E.NATIONAL_ID_HU_TAJ)


# --- IBAN ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        make_iban(),
        grouped(make_iban()),
        make_iban("DE", "123456781234567890"),
        grouped(make_iban("FR", "1234512345ABCDEFGHIJK12")),
        make_iban("NO", "12345678903"),
    ],
)
def test_iban(detector: RuleDetector, value: str) -> None:
    assert_detects(detector, value, E.BANK_ACCOUNT)


def test_iban_does_not_double_report_its_giro_digits(detector: RuleDetector) -> None:
    text = f"IBAN: {grouped(make_iban())}"
    assert found(detector, text) == [(E.BANK_ACCOUNT, grouped(make_iban()))]


def test_iban_followed_by_uppercase_word(detector: RuleDetector) -> None:
    value = grouped(make_iban())
    assert found(detector, f"{value} OTP") == [(E.BANK_ACCOUNT, value)]


@pytest.mark.parametrize(
    "text",
    [
        broken(make_iban()),
        make_iban()[:2] + broken(make_iban()[2:4]) + make_iban()[4:],  # wrong check digits
        "ZZ" + make_iban()[2:],  # unknown country
        make_iban()[:-1],  # too short
        make_iban()[:-1] + ".",
        make_iban() + "7",  # runs on
        make_iban().lower(),
    ],
)
def test_iban_look_alikes(detector: RuleDetector, text: str) -> None:
    assert E.BANK_ACCOUNT not in {s.entity_type for s in detector.detect(text)}


@settings(max_examples=50)
@given(
    country=st.sampled_from(["HU", "DE", "AT", "GB", "NL", "PL"]),
    data=st.data(),
)
def test_iban_property(country: str, data: st.DataObject) -> None:
    size = IBAN_LENGTHS[country] - 4
    bban = data.draw(st.text(alphabet="0123456789", min_size=size, max_size=size))
    value = make_iban(country, bban)
    if data.draw(st.booleans()):
        value = grouped(value)
    assert_detects(RuleDetector(), value, E.BANK_ACCOUNT)


# --- Giro account -------------------------------------------------------------


@pytest.mark.parametrize("sep", ["-", " ", ""])
@pytest.mark.parametrize("account", ["1234567", "123456789012345"])
def test_giro(detector: RuleDetector, sep: str, account: str) -> None:
    value = make_giro(account=account)
    text = sep.join(value[i : i + 8] for i in range(0, len(value), 8))
    assert_detects(detector, text, E.BANK_ACCOUNT)


@pytest.mark.parametrize(
    "text",
    [
        broken(make_giro()),
        broken(make_giro(), 3),  # bank block check fails
        "1" + make_giro(),
        make_giro() + "1",
        "-".join([make_giro(account="1234567")[:8], broken(make_giro(account="1234567")[8:])]),
    ],
)
def test_giro_look_alikes(detector: RuleDetector, text: str) -> None:
    assert E.BANK_ACCOUNT not in {s.entity_type for s in detector.detect(text)}


def test_giro_16_inside_unseparated_24_digit_run(detector: RuleDetector) -> None:
    value = make_giro(account="1234567")
    extra = next(f"{n:08d}" for n in range(10) if not is_valid_giro(value + f"{n:08d}"))
    assert E.BANK_ACCOUNT not in {s.entity_type for s in detector.detect(value + extra)}


def test_contained_hits_are_dropped() -> None:
    outer = rules._Hit(0, 10, E.BANK_ACCOUNT, 0.99)
    inner = rules._Hit(2, 6, E.ADDRESS, 0.75)
    partial = rules._Hit(8, 12, E.PHONE, 0.9)
    assert rules._drop_contained([inner, partial, outer, outer]) == [outer, partial]


def test_giro_16_followed_by_unrelated_block(detector: RuleDetector) -> None:
    value = make_giro(account="1234567")
    # A third block that does not make a valid 24-digit account.
    extra = next(f"{n:08d}" for n in range(10) if not is_valid_giro(value + f"{n:08d}"))
    text = f"{value[:8]}-{value[8:]}-{extra}"
    assert found(detector, text) == [(E.BANK_ACCOUNT, f"{value[:8]}-{value[8:]}")]


# --- Email ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "teszt.elek@example.com",
        "minta+hirlevel@mail.example.hu",
        "árvíz.tűrő@példa.hu",
        "a_b-c@sub-domain.example.org",
    ],
)
def test_email(detector: RuleDetector, value: str) -> None:
    assert_detects(detector, value, E.EMAIL)


def test_email_with_hungarian_suffix(detector: RuleDetector) -> None:
    text = "Írjon a teszt.elek@example.com-ra vagy a minta@example.hu címre."
    assert found(detector, text) == [
        (E.EMAIL, "minta@example.hu"),
        (E.EMAIL, "teszt.elek@example.com"),
    ]


@pytest.mark.parametrize(
    "text",
    ["teszt@localhost", "teszt@example", "@example.com", "teszt..elek@example.com", "a@b.c"],
)
def test_email_look_alikes(detector: RuleDetector, text: str) -> None:
    assert E.EMAIL not in {s.entity_type for s in detector.detect(text)}


# --- Phone ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "+36 30 123 4567",
        "+36-30-123-4567",
        "+36301234567",
        "0036 20 987 6543",
        "06 30 123 4567",
        "06-70-123-45-67",
        "06/30/123-4567",
        "06 1 234 5678",
        "+36 1 234 5678",
        "06-1-234-5678",
        "(06 1) 234-5678",
        "06 (30) 123 4567",
        "06 52 123 456",
        "+36 96 123-456",
        "+49 30 12345678",
        "+44 20 7946 0000",
        "+1 (555) 010-0000",
    ],
)
def test_phone(detector: RuleDetector, value: str) -> None:
    assert_detects(detector, value, E.PHONE)


@pytest.mark.parametrize(
    "text",
    [
        "06 40 123 4567",  # 40 is not a valid area or mobile code here
        "06 30 123 45",  # too short
        "06 52 123 4567",  # too long for a 6-digit subscriber area
        "0630123456789",  # too many digits in one run
        "1206 30 123 4567",  # prefix inside a longer number
        "+1 23",  # too few digits
        "2026-06-30",  # a date
        "2026.06.30.",
    ],
)
def test_phone_look_alikes(detector: RuleDetector, text: str) -> None:
    assert E.PHONE not in {s.entity_type for s in detector.detect(text)}


def test_phone_followed_by_other_number(detector: RuleDetector) -> None:
    assert found(detector, "Tel.: 06 30 123 4567 12 db") == [(E.PHONE, "06 30 123 4567")]


# --- Postcode -------------------------------------------------------------------


# A postcode inside a full address is covered by the address span (tests/detect/rules/).
@pytest.mark.parametrize(
    "text",
    [
        "3300 Eger",
        "Lakcím: 6720 Szeged.",
        "H-4026 Debrecen",
        "irányítószám: 8200",
    ],
)
def test_postcode(detector: RuleDetector, text: str) -> None:
    spans = [s for s in detector.detect(PREFIX + text) if s.entity_type is E.ADDRESS]
    assert len(spans) == 1
    assert spans[0].text.isdigit() and len(spans[0].text) == 4
    assert (PREFIX + text)[spans[0].start : spans[0].end] == spans[0].text


@pytest.mark.parametrize(
    "text",
    [
        "1500 Ft",
        "1500 forintot fizetett",
        "2026. október 26.",
        "1990 Január",
        "0123 Budapest",  # postcodes don't start with 0
        "12345 Budapest",
        "Összesen 4000 darab.",
        "1.051 Budapest",
    ],
)
def test_postcode_look_alikes(detector: RuleDetector, text: str) -> None:
    assert E.ADDRESS not in {s.entity_type for s in detector.detect(text)}


# --- Vehicle plates ---------------------------------------------------------------


@pytest.mark.parametrize("value", ["ABC-123", "AA BC-123", "AABC-123", "XYZ-987"])
def test_vehicle_plate(detector: RuleDetector, value: str) -> None:
    assert_detects(detector, value, E.VEHICLE_PLATE)


def test_vehicle_plate_with_suffix(detector: RuleDetector) -> None:
    assert found(detector, "Az ABC-123-as autó") == [(E.VEHICLE_PLATE, "ABC-123")]


@pytest.mark.parametrize(
    "text", ["abc-123", "ABC-1234", "AB-123", "ABC-12", "XABC-123-4", "ISO-9001"]
)
def test_vehicle_plate_look_alikes(detector: RuleDetector, text: str) -> None:
    assert E.VEHICLE_PLATE not in {s.entity_type for s in detector.detect(text)}


# --- Company identifiers --------------------------------------------------------


def test_company_registration(detector: RuleDetector) -> None:
    span = assert_detects(detector, "01-09-123456", E.COMPANY_ID_HU)
    text = "Cégjegyzékszám: Cg. 13-10-040000"
    assert found(detector, text) == [(E.COMPANY_ID_HU, "13-10-040000")]
    assert detector.detect(text)[0].score > span.score


@pytest.mark.parametrize(
    "text",
    ["21-09-123456", "01-24-123456", "00-09-123456", "01-09-1234567", "01-09-12345", "2026-10-26"],
)
def test_company_registration_look_alikes(detector: RuleDetector, text: str) -> None:
    assert E.COMPANY_ID_HU not in {s.entity_type for s in detector.detect(text)}


def test_company_tax_number(detector: RuleDetector) -> None:
    assert_detects(detector, make_tax_number(), E.COMPANY_ID_HU)
    assert_detects(detector, make_tax_number("7654321", "1", "13"), E.COMPANY_ID_HU)


@pytest.mark.parametrize(
    "text",
    [
        broken(make_tax_number(), 7),  # base check digit
        make_tax_number(vat="6"),
        make_tax_number(area="99"),
        "1" + make_tax_number(),
        make_tax_number() + "1",
    ],
)
def test_company_tax_number_look_alikes(detector: RuleDetector, text: str) -> None:
    assert E.COMPANY_ID_HU not in {s.entity_type for s in detector.detect(text)}


# --- Dates and mixed documents --------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "2026-10-26",
        "2026.10.26.",
        "2026. 10. 26.",
        "26/10/2026",
        "1990. május 12-én született.",
        "19900512",
        "2026-10-26T12:30:00",
    ],
)
def test_dates_are_not_identifiers(detector: RuleDetector, text: str) -> None:
    assert_nothing(detector, text)


def test_mixed_document_offsets(detector: RuleDetector) -> None:
    values = {
        make_tax_id(): E.NATIONAL_ID_HU_TAX,
        "111 222 337": E.NATIONAL_ID_HU_TAJ,
        grouped(make_iban()): E.BANK_ACCOUNT,
        "teszt.elek@example.com": E.EMAIL,
        "+36 30 123 4567": E.PHONE,
        "1051 Budapest, Kitalált utca 1.": E.ADDRESS,
        "AA BC-123": E.VEHICLE_PLATE,
        make_tax_number(): E.COMPANY_ID_HU,
    }
    v = list(values)
    text = (
        f"Alulírott Teszt Elek (adóazonosító jel: {v[0]}, TAJ: {v[1]}) "
        f"bankszámlája: {v[2]}. E-mail: {v[3]}, telefon: {v[4]}. "
        f"Lakcím: {v[5]} Gépjármű: {v[6]}. "
        f"A Példa Kft. adószáma {v[7]}, kelt 2026. október 26."
    )
    spans = detector.detect(text)
    assert sorted((s.text, s.entity_type) for s in spans) == sorted(values.items())
    for span in spans:
        assert text[span.start : span.end] == span.text


@settings(max_examples=200)
@given(text=st.text())
def test_never_crashes_and_offsets_hold(text: str) -> None:
    for span in RuleDetector().detect(text):
        assert text[span.start : span.end] == span.text
