"""Check digits of Polish identifiers (pure functions, no I/O).

- **PESEL** (national identification number): 11 digits ``YYMMDDZZZXQ``: the date of birth,
  a serial number (its last digit even for women, odd for men) and a check digit. The century
  is encoded in the month: 1-12 for 1900-1999, 21-32 for 2000-2099, 41-52 for 2100-2199,
  61-72 for 2200-2299 and 81-92 for 1800-1899. The check digit makes the sum of the digits
  weighted ``1 3 7 9 1 3 7 9 1 3 1`` a multiple of 10.
- **NIP** (tax identification number): 10 digits, the last a check digit: the first nine
  weighted ``6 5 7 2 3 4 5 6 7``, modulo 11. A remainder of 10 is never issued.
- **REGON** (business register number): 9 digits (weights ``8 9 2 3 4 5 6 7``) or 14 digits
  for a local unit (the nine digits of its parent, four of its own and a check digit, weights
  ``2 4 8 5 0 9 7 3 6 1 2 4 8``), modulo 11, a remainder of 10 counting as 0.
- **Dowód osobisty** (ID card): three letters and six digits, ``ABA300000``. The first digit
  is the check digit. Letters count as ``A`` = 10 ... ``Z`` = 35; with the weights
  ``7 3 1 9 7 3 1 7 3`` the sum is a multiple of 10.
- **Passport**: two letters and seven digits, the first digit the check digit, weighted the
  same way: ``7 3 9 1 7 3 1 7 3``.

Every function takes the value without separators and never raises on bad input.
"""

from __future__ import annotations

import calendar

__all__ = [
    "id_card_check_digit",
    "is_valid_id_card",
    "is_valid_nip",
    "is_valid_passport",
    "is_valid_pesel",
    "is_valid_regon",
    "nip_check_digit",
    "passport_check_digit",
    "pesel_birth_date",
    "pesel_check_digit",
    "regon_check_digit",
]

_PESEL_WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
_NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)
_REGON9_WEIGHTS = (8, 9, 2, 3, 4, 5, 6, 7)
_REGON14_WEIGHTS = (2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8)
# Without the check digit's own weight (9): the check digit is the weighted sum modulo 10.
_ID_CARD_WEIGHTS = (7, 3, 1, 7, 3, 1, 7, 3)
_PASSPORT_WEIGHTS = (7, 3, 1, 7, 3, 1, 7, 3)
# Month offset -> the century it encodes.
_PESEL_CENTURIES = {80: 1800, 0: 1900, 20: 2000, 40: 2100, 60: 2200}


def _digits(value: str, n: int) -> bool:
    return len(value) == n and value.isascii() and value.isdigit()


def _letters(value: str) -> bool:
    return value.isascii() and value.isalpha() and value.isupper()


def pesel_check_digit(payload10: str) -> int:
    """The check digit for the first ten digits of a PESEL."""
    if not _digits(payload10, 10):
        raise ValueError("expected 10 digits")
    total = sum(int(d) * w for d, w in zip(payload10, _PESEL_WEIGHTS, strict=True))
    return (10 - total % 10) % 10


def pesel_birth_date(digits: str) -> tuple[int, int, int] | None:
    """``(year, month, day)`` encoded in a PESEL's first six digits, ``None`` if impossible."""
    if len(digits) < 6 or not _digits(digits[:6], 6):
        return None
    yy, mm, dd = int(digits[:2]), int(digits[2:4]), int(digits[4:6])
    offset = (mm - 1) // 20 * 20 if mm > 0 else -1
    century = _PESEL_CENTURIES.get(offset)
    month = mm - offset
    if century is None or not 1 <= month <= 12:
        return None
    year = century + yy
    if not 1 <= dd <= calendar.monthrange(year, month)[1]:
        return None
    return year, month, dd


def is_valid_pesel(digits: str) -> bool:
    """True for an 11-digit PESEL with a possible date of birth and a valid check digit."""
    if not _digits(digits, 11) or pesel_birth_date(digits) is None:
        return False
    return pesel_check_digit(digits[:10]) == int(digits[10])


def nip_check_digit(payload9: str) -> int | None:
    """The NIP check digit for nine digits, ``None`` when the remainder is 10 (never issued)."""
    if not _digits(payload9, 9):
        raise ValueError("expected 9 digits")
    check = sum(int(d) * w for d, w in zip(payload9, _NIP_WEIGHTS, strict=True)) % 11
    return None if check == 10 else check


def is_valid_nip(digits: str) -> bool:
    """True for a 10-digit NIP (separators removed) with a valid check digit."""
    if not _digits(digits, 10) or digits[:3] == "000":
        return False
    return nip_check_digit(digits[:9]) == int(digits[9])


def regon_check_digit(payload: str) -> int:
    """The REGON check digit for 8 (short REGON) or 13 (local unit) digits."""
    weights = {8: _REGON9_WEIGHTS, 13: _REGON14_WEIGHTS}.get(len(payload))
    if weights is None or not _digits(payload, len(payload)):
        raise ValueError("expected 8 or 13 digits")
    return sum(int(d) * w for d, w in zip(payload, weights, strict=True)) % 11 % 10


def is_valid_regon(digits: str) -> bool:
    """True for a 9- or 14-digit REGON with valid check digits.

    A 14-digit REGON starts with its parent's 9-digit REGON, which must be valid too.
    """
    if not (_digits(digits, 9) or _digits(digits, 14)):
        return False
    if regon_check_digit(digits[:8]) != int(digits[8]):
        return False
    return len(digits) == 9 or regon_check_digit(digits[:13]) == int(digits[13])


def _alnum_value(ch: str) -> int:
    return int(ch) if ch.isdigit() else ord(ch) - 55  # A = 10 ... Z = 35


def id_card_check_digit(letters3: str, digits5: str) -> int:
    """The ID card check digit for its three letters and the five digits after the check."""
    if len(letters3) != 3 or not _letters(letters3) or not _digits(digits5, 5):
        raise ValueError("expected three capital letters and five digits")
    chars = letters3 + digits5
    return sum(_alnum_value(c) * w for c, w in zip(chars, _ID_CARD_WEIGHTS, strict=True)) % 10


def is_valid_id_card(value: str) -> bool:
    """True for a dowód osobisty number ``AAA9DDDDD`` (separators removed)."""
    if len(value) != 9 or not _letters(value[:3]) or not _digits(value[3:], 6):
        return False
    return id_card_check_digit(value[:3], value[4:]) == int(value[3])


def passport_check_digit(letters2: str, digits6: str) -> int:
    """The passport check digit for its two letters and the six digits after the check."""
    if len(letters2) != 2 or not _letters(letters2) or not _digits(digits6, 6):
        raise ValueError("expected two capital letters and six digits")
    chars = letters2 + digits6
    return sum(_alnum_value(c) * w for c, w in zip(chars, _PASSPORT_WEIGHTS, strict=True)) % 10


def is_valid_passport(value: str) -> bool:
    """True for a Polish passport number ``AA9DDDDDD`` (separators removed)."""
    if len(value) != 9 or not _letters(value[:2]) or not _digits(value[2:], 7):
        return False
    return passport_check_digit(value[:2], value[3:]) == int(value[2])
