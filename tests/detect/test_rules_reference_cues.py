"""Context-free checksum hits next to a reference cue (LAB-1227, after LAB-1205's TAJ guard).

A short number with a check digit but no cue of its own (a Hungarian tax ID: mod 11 and a
leading 8; a payment card: an issuer prefix and Luhn) is a reference, not personal data, right
after an order, ticket, SKU, tracking, invoice or reference label, an ID prefix (``INV-``,
``#``, ``SKU-``) or a currency. A four-digit number before a settlement that belongs to a
company name (``1999 Budapest Kft.``) is not a postcode. A cued value always wins.

Every value is fictional: the tax IDs are built from made-up payloads, the cards are the card
networks' published test numbers or Luhn-completed made-up payloads (ADR 0005).
"""

from __future__ import annotations

import pytest

from pii_guard.detect.checksums import hu_tax_id_check_digit
from pii_guard.detect.pipeline import DetectionPipeline
from pii_guard.detect.rules import RuleDetector, common
from pii_guard.detect.rules._base import legal_form_after
from pii_guard.types import EntityType

E = EntityType


def make_tax_id(payload: str) -> str:
    check = hu_tax_id_check_digit("8" + payload)
    assert check is not None
    return f"8{payload}{check}"


def make_card(payload: str) -> str:
    return payload + str(common.luhn_check_digit(payload))


TAX_ID = make_tax_id("12345678")  # 8123456786
TAX_ID_2 = make_tax_id("98765431")
VISA = "4111111111111111"  # the networks' published test numbers
# 5555 5555 5555 4444 is also a valid 16-digit giro number, which this guard leaves alone.
MASTERCARD = "5105105105105100"
CARD = make_card("401288888888188")


def _types(text: str, language: str = "en", *, cued: bool = True) -> set[EntityType]:
    return {s.entity_type for s in RuleDetector(cued_numbers=cued).detect(text, language)}


# --- The reviewers' probe (detect/probe3.py) -----------------------------------


@pytest.mark.parametrize(
    ("language", "text"),
    [
        ("en", f"Tracking 1Z 999 AA1 01 2345 6784 ; ticket {TAX_ID}"),
        ("en", f"SKU {VISA}"),
        ("hu", "1999 Budapest Kft. 2000 forint"),
    ],
)
def test_probe3_cases_are_not_masked(language: str, text: str) -> None:
    pipeline = DetectionPipeline([RuleDetector()])
    assert pipeline.detect(text, language) == []


# --- Tax ID ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("language", "text"),
    [
        ("en", f"ticket {TAX_ID}"),
        ("en", f"Ticket #{TAX_ID}"),
        ("en", f"Order #{TAX_ID} shipped"),
        ("en", f"Order number: {TAX_ID}"),
        ("en", f"Tracking number {TAX_ID_2}"),
        ("en", f"Invoice INV-{TAX_ID}"),
        ("en", f"Item SKU-{TAX_ID}"),
        ("en", f"Reference: {TAX_ID_2}"),
        ("hu", f"Rendelésszám: {TAX_ID}"),
        ("hu", f"Számla: SZ-{TAX_ID}"),
        ("hu", f"Ügyszám {TAX_ID_2}"),
        ("de", f"Bestellnummer {TAX_ID}"),
        ("de", f"Rechnung RE-{TAX_ID}"),
        ("en", f"Total: ${TAX_ID}"),
        ("en", f"Amount EUR {TAX_ID}"),
    ],
)
def test_tax_id_after_a_reference_is_not_masked(language: str, text: str) -> None:
    assert E.NATIONAL_ID_HU_TAX not in _types(text, language, cued=False)


@pytest.mark.parametrize(
    "text",
    [
        f"Adóazonosító jel: {TAX_ID}",
        f"Rendelés 2026-0042, adóazonosító: {TAX_ID}",  # its cue wins over the order label
        f"Ticket for tax ID {TAX_ID}",
        f"Teszt Elek, {TAX_ID}, Szeged",  # no cue at all: still masked
        f"A rendelést Teszt Elek adta le, {TAX_ID}",  # the label must end right before it
    ],
)
def test_tax_id_with_a_cue_or_without_a_reference_is_masked(text: str) -> None:
    assert E.NATIONAL_ID_HU_TAX in _types(text, "hu")


def test_tax_id_scores_are_unchanged() -> None:
    [cued] = RuleDetector().detect(f"Adóazonosító jel: {TAX_ID}", "hu")
    [bare] = RuleDetector().detect(f"Teszt Elek, {TAX_ID}", "hu")
    assert (cued.score, bare.score) == (0.99, 0.95)


# --- Payment cards --------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        f"SKU {VISA}",
        f"SKU-{VISA}",
        f"Item #{MASTERCARD}",
        f"Order number: {CARD}",
        f"Tracking {MASTERCARD}",
        f"Ticket {VISA}",
        f"Invoice INV-{CARD}",
        f"Total: ${VISA}",
        f"Cikkszám: {MASTERCARD}",
        f"Bestellnummer {CARD}",
    ],
)
def test_card_after_a_reference_is_not_masked(text: str) -> None:
    assert E.BANK_ACCOUNT not in _types(text, cued=False)


@pytest.mark.parametrize(
    "text",
    [
        VISA,  # no cue at all: still a card
        f"Paid with {VISA} yesterday",
        "Card: 4111 1111 1111 1111",
        f"Card number (order {CARD}) on file",
        f"Visa ending order: {VISA}",  # a card cue in the window wins over the order label
        f"Kártyaszám (rendelés): {MASTERCARD}",
        f"Számlaszám: {VISA}",  # Hungarian "számlaszám" is an account number
        f"Kreditkarte, Bestellung {CARD}",
        f"Account ref {MASTERCARD}",
    ],
)
def test_card_with_a_cue_or_without_a_reference_is_masked(text: str) -> None:
    assert E.BANK_ACCOUNT in _types(text)


# --- Hungarian postcode before a company name ------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "1999 Budapest Kft. 2000 forint",
        "2000 Szentendre Kft.",
        "3300 Eger Zrt. közleménye",
        "6720 Szeged Bt.-vel",
        "1051 Budapest Bank Zrt.",  # one more word of the name before the form
        "4026 Debrecen Nonprofit Kft.",
        "1051 Budapest kft",
        "Order 1051 Budapest",  # a reference label right before it
        "Rendelés #3300 Eger",
    ],
)
def test_postcode_in_a_company_name_or_after_a_reference_is_not_masked(text: str) -> None:
    assert E.ADDRESS not in _types(text, "hu", cued=False)


@pytest.mark.parametrize(
    "text",
    [
        "3300 Eger",
        "Hívja a 06 1 234 5678 számot, vagy 2024 Szentendre",
        "Teszt Kft., 1051 Budapest",  # the company before the postcode, as usual
        "Számlázási cím: 1051 Budapest",
        "irányítószám: 1999 Budapest Kft.",  # its cue wins
        "H-1999 Budapest Kft.",  # so does the H- prefix
        "3300 Eger és Teszt Elek Kft.",  # the form belongs to another name
    ],
)
def test_postcode_with_a_cue_or_a_plain_place_is_masked(text: str) -> None:
    assert E.ADDRESS in _types(text, "hu")


def test_full_address_after_a_company_is_still_found() -> None:
    text = "Teszt Kft., 1051 Budapest, Minta utca 12."
    [span] = [s for s in RuleDetector().detect(text, "hu") if s.entity_type is E.ADDRESS]
    assert span.text == "1051 Budapest, Minta utca 12."


# --- German address line before a company name -----------------------------------


def test_german_postcode_line_in_a_company_name_is_not_masked() -> None:
    assert E.ADDRESS not in _types("Rechnung an\n10115 Berlin GmbH", "de", cued=False)
    assert E.ADDRESS in _types("Rechnung an\n10115 Berlin", "de", cued=False)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (" Kft.", True),
        (" Kft.-nek", True),
        (" Bank Zrt.", True),
        (" Minta Építő Kft", True),
        (" GmbH", True),
        (" Ltd", True),
        (" Kftxyz", False),
        (", Teszt Kft.", False),
        (" és Teszt Kft.", False),
        (" Egy Kettő Három Kft.", False),  # at most two words of the name in between
        (" utca 1.", False),
    ],
)
def test_legal_form_after(text: str, expected: bool) -> None:
    assert legal_form_after(text, 0) is expected


# --- Hungarian personal identification number (LAB-1327) -----------------------

PERSONAL_ID = "17103041237"  # sex/century 1, born 1971-03-04, serial 1237 (checksum-valid)
PERSONAL_ID_2 = "75302022056"  # the agent-traffic-dev docstring order number


@pytest.mark.parametrize(
    ("language", "text"),
    [
        ("hu", f'    """Order {PERSONAL_ID_2}'),
        ("en", f"Order {PERSONAL_ID}"),
        ("de", f"ticket: {PERSONAL_ID_2}"),
        ("hu", f"Rendelésszám: {PERSONAL_ID}"),
        ("hu", f"Számla: SZ-{PERSONAL_ID}"),
        ("de", f"Bestellnummer {PERSONAL_ID_2}"),
        ("en", f"Total: ${PERSONAL_ID}"),
    ],
)
def test_personal_id_after_a_reference_is_not_masked(language: str, text: str) -> None:
    assert E.ID_DOCUMENT not in _types(text, language, cued=False)


@pytest.mark.parametrize(
    "text",
    [
        f"Személyi azonosító: {PERSONAL_ID}",
        f"Rendelés 2026-0042, személyi szám: {PERSONAL_ID}",  # its cue wins over the order label
        f"Order for personal ID {PERSONAL_ID}",
        f"Teszt Elek, {PERSONAL_ID}, Szeged",  # no cue at all: still masked
        f"A rendelést Teszt Elek adta le, {PERSONAL_ID}",  # the label must end right before it
    ],
)
def test_personal_id_with_a_cue_or_without_a_reference_is_masked(text: str) -> None:
    assert E.ID_DOCUMENT in _types(text, "hu")


def test_personal_id_scores_are_unchanged() -> None:
    [cued] = RuleDetector().detect(f"Személyi azonosító: {PERSONAL_ID}", "hu")
    [bare] = RuleDetector().detect(f"Teszt Elek, {PERSONAL_ID}", "hu")
    assert (cued.score, bare.score) == (0.99, 0.85)
