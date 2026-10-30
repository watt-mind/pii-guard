"""Language-independent rules: they run for every text, whatever its language.

IBAN (any country, mod-97), email addresses, international phone numbers (``+`` and a
country code; ``+36`` is left to the Hungarian pack, which validates the area code) and
payment card numbers (issuer prefix + Luhn).

Payment cards are reported as ``BANK_ACCOUNT``: there is no card type in the taxonomy yet,
and a card number is a financial account identifier with the same policy (mask).
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from pii_guard.detect.checksums import IBAN_LENGTHS, is_valid_iban
from pii_guard.detect.rules._base import (
    NOT_IN_WORD_AFTER,
    Rule,
    _Hit,
    context_before,
    reference_or_amount_before,
)
from pii_guard.types import EntityType

__all__ = ["RULES", "is_valid_card_number", "luhn_check_digit"]


# --- IBAN -------------------------------------------------------------------

_IBAN_START_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2}|[a-z]{2})(\d{2})")


def _find_iban(text: str) -> Iterator[_Hit]:
    """IBANs, compact or printed in groups, in upper or lower case.

    Spaces between characters are allowed, also several in a row (``DE89  3704 ...``). Every
    letter must have the case of the country code: ``de89...`` and ``gb82west...`` are IBANs
    typed in lower case, ``De89...`` is not how one is printed.
    """
    for m in _IBAN_START_RE.finditer(text):
        country = m.group(1)
        expected = IBAN_LENGTHS.get(country.upper())
        if expected is None:
            continue
        lower = country.islower()
        chars = [country, m.group(2)]
        count, pos = 4, m.end()
        while count < expected and pos < len(text):
            ch = text[pos]
            if ch == " ":
                run_end = pos
                while run_end < len(text) and text[run_end] == " ":
                    run_end += 1
                if run_end < len(text) and _is_iban_char(text[run_end], lower):
                    pos = run_end
                    continue
                break
            if not _is_iban_char(ch, lower):
                break
            chars.append(ch)
            count += 1
            pos += 1
        if count != expected:
            continue
        # The IBAN must end here, not run on into more account characters.
        if pos < len(text) and text[pos].isalnum():
            continue
        if is_valid_iban("".join(chars).upper()):
            yield _Hit(m.start(), pos, EntityType.BANK_ACCOUNT, 0.99)


def _is_iban_char(ch: str, lower: bool = False) -> bool:
    return ch.isascii() and (ch.isdigit() or (ch.islower() if lower else ch.isupper()))


# --- Email ------------------------------------------------------------------

# Pragmatic, not RFC 5322: Unicode letters allowed, the TLD is letters only or an IDN in
# punycode (``xn--p1ai``). A quoted local part (``"john doe"@example.com``) is matched with its
# quotes. A Hungarian case suffix attached with a hyphen ("…@example.com-ra") is not part of
# the address.
_EMAIL_RE = re.compile(
    r"(?:(?<![\w.%+-])[\w%+-](?:[\w.%+-]*[\w%+-])?"
    r'|(?<![\w"])"(?:[^"\\\r\n]|\\[^\r\n]){1,64}")'
    r"@"
    r"(?:[^\W_](?:[\w-]*[^\W_])?\.)+"
    r"(?:[xX][nN]--[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?|[^\W\d_]{2,})"
    r"(?!\w)(?!\.[^\W_])"
)


# ``scheme://user:`` right before a match: the "local part" is a URL password, not a mailbox
# (``postgres://app:pw@db.example.com``); the secret rules mask it.
_URL_USERINFO_BEFORE_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s:/?#@]+:$")


def _find_email(text: str) -> Iterator[_Hit]:
    for m in _EMAIL_RE.finditer(text):
        if _URL_USERINFO_BEFORE_RE.search(text, max(0, m.start() - 160), m.start()):
            continue
        local, _, domain = m.group().rpartition("@")
        # Consecutive dots are invalid, except inside a quoted local part.
        if ".." in domain or (not local.startswith('"') and ".." in local):
            continue
        yield _Hit(m.start(), m.end(), EntityType.EMAIL, 0.99)


# --- International phone numbers --------------------------------------------

# "+" and a country code, 8-15 digits in total (E.164). +36 is handled by the Hungarian pack.
# The country code may stand in parentheses, ``(+44) 20 7946 0958``: the span then starts at
# the opening parenthesis, so it stays balanced.
_INTL_PHONE_RE = re.compile(
    r"(?:(?<![\w+(])\(\+(?!36)[1-9]\d{0,2}\)|(?<![\w+])\+(?!36)[1-9]\d{0,2})"
    r"(?:[ \-./]?(?:\(\d{1,4}\)|\d{1,4})){2,6}(?!\d)" + NOT_IN_WORD_AFTER
)


def _find_intl_phone(text: str) -> Iterator[_Hit]:
    for m in _INTL_PHONE_RE.finditer(text):
        if 8 <= sum(ch.isdigit() for ch in m.group()) <= 15:
            yield _Hit(m.start(), m.end(), EntityType.PHONE, 0.85)


# --- Payment cards ----------------------------------------------------------


def luhn_check_digit(payload: str) -> int:
    """The Luhn (mod 10) check digit for ``payload`` (digits, without the check digit)."""
    if not payload or not (payload.isascii() and payload.isdigit()):
        raise ValueError("expected digits")
    total = 0
    for i, d in enumerate(reversed(payload)):
        n = int(d)
        if i % 2 == 0:  # doubled: these become every second digit once the check is appended
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return (10 - total % 10) % 10


def _card_issuer_ok(digits: str) -> bool:
    """A known issuer prefix with a length that issuer uses."""
    n = len(digits)
    two, four = int(digits[:2]), int(digits[:4])
    if digits[0] == "4":  # Visa
        return n in (13, 16, 19)
    if 51 <= two <= 55 or 2221 <= four <= 2720:  # Mastercard
        return n == 16
    if two in (34, 37):  # American Express
        return n == 15
    if four == 6011 or two == 65 or 644 <= int(digits[:3]) <= 649:  # Discover
        return 16 <= n <= 19
    if two == 62:  # UnionPay
        return 16 <= n <= 19
    if 3528 <= four <= 3589:  # JCB
        return 16 <= n <= 19
    if two in (36, 38, 39) or 300 <= int(digits[:3]) <= 305:  # Diners Club
        return 14 <= n <= 19
    if two in (50, 56, 57, 58) or four in (6304, 6759, 6761, 6762, 6763):  # Maestro
        return 12 <= n <= 19
    return False


def is_valid_card_number(digits: str) -> bool:
    """12-19 digits, a known issuer prefix and length, and a valid Luhn check digit."""
    if not (12 <= len(digits) <= 19 and digits.isascii() and digits.isdigit()):
        return False
    return _card_issuer_ok(digits) and luhn_check_digit(digits[:-1]) == int(digits[-1])


# A card or account label anywhere shortly before the number: it is then a card number even
# after a reference word ("Kártyaszám (rendelés): 4111 ..."). Hungarian "számla" alone is an
# invoice, "számlaszám" / "bankszámla" an account.
_CARD_CONTEXT = (
    "card", "kártya", "kartya", "karte", "carte", "tarjeta", "visa", "mastercard", "maestro",
    "amex", "american express", "discover", "jcb", "unionpay", "diners", "credit", "debit",
    "account", "számlaszám", "szamlaszam", "bankszámla", "bankszamla", "konto",
)  # fmt: skip

# Printed in groups of 4 ("4111 1111 1111 1111", Amex "3782 822463 10005") with one consistent
# separator, or compact. Never part of a longer number. A comma on either side separates CSV
# fields, not thousands: only a comma before 1-3 trailing digits blocks, as for other numbers
# (LAB-1367), so a card in a CSV field ("name,4111111111111111,x") is found (LAB-1381).
_CARD_RE = re.compile(
    r"(?<![\w\-./])(?:(?<!\d,)|(?=\d{4}))(?<!\d )"
    r"(?:"
    r"(?P<grouped>\d{4}(?P<sep>[ -])\d{4}(?:(?P=sep)\d{4}){1,2}(?:(?P=sep)\d{1,3})?)"
    r"|(?P<amex>3[47]\d{2}(?P<asep>[ -])\d{6}(?P=asep)\d{5})"
    r"|(?P<compact>\d{12,19})"
    r")"
    r"(?!\d)(?![-./]\d)(?!,\d{1,3}(?!\d))" + NOT_IN_WORD_AFTER + r"(?! \d)"
)


def _find_payment_card(text: str) -> Iterator[_Hit]:
    for m in _CARD_RE.finditer(text):
        digits = "".join(ch for ch in m.group() if ch.isdigit())
        if is_valid_card_number(digits):
            # A Luhn check passes for 1 in 10 numbers: right after an order, SKU or ticket
            # label, an ID prefix or a currency it is that number, unless a card cue says
            # otherwise (LAB-1227).
            if not context_before(text, m.start(), _CARD_CONTEXT) and (
                reference_or_amount_before(text, m.start())
            ):
                continue
            score = 0.9 if m.group("compact") else 0.95
            yield _Hit(m.start(), m.end(), EntityType.BANK_ACCOUNT, score)


RULES: tuple[Rule, ...] = (_find_iban, _find_email, _find_intl_phone, _find_payment_card)
