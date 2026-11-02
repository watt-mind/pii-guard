"""Check digits of Romanian identifiers (pure functions, no I/O).

Written from the published structure of the identifiers, not from another implementation.

- **CNP** (cod numeric personal): 13 digits ``SYYMMDDJJNNNC``. ``S`` is sex and century:
  1/2 born 1900-1999, 3/4 1800-1899, 5/6 2000-2099 (odd for men, even for women), 7/8 foreign
  residents and 9 foreign persons (no century: the date must exist in 1900-1999 or
  2000-2099). ``YYMMDD`` is the date of birth, ``JJ`` the county code (01-52: the 46 counties
  and Bucharest's sectors, 47/48 for the former sectors 7 and 8, 51 Călărași and 52 Giurgiu),
  ``NNN`` a serial number and ``C`` the check digit: the first twelve digits weighted
  ``2 7 9 1 4 6 3 5 8 2 7 9``, the sum modulo 11, a remainder of 10 counting as 1.
- **CIF / CUI** (company tax and registration code): 2-10 digits, the last a check digit. The
  others, right-aligned under the weights ``7 5 3 2 1 7 5 3 2``, are weighted and summed; the
  sum times 10 modulo 11 is the check digit, 10 counting as 0. A person registered as a sole
  trader uses the CNP instead.

Every function takes the value without separators and never raises on bad input.
"""

from __future__ import annotations

import calendar

__all__ = [
    "cif_check_digit",
    "cnp_birth_date",
    "cnp_check_digit",
    "is_valid_cif",
    "is_valid_cnp",
]

_CNP_WEIGHTS = (2, 7, 9, 1, 4, 6, 3, 5, 8, 2, 7, 9)
_CIF_WEIGHTS = (7, 5, 3, 2, 1, 7, 5, 3, 2)
# Sex/century digit -> the centuries the date of birth may be in.
_CNP_CENTURIES = {
    "1": (1900,),
    "2": (1900,),
    "3": (1800,),
    "4": (1800,),
    "5": (2000,),
    "6": (2000,),
    "7": (1900, 2000),
    "8": (1900, 2000),
    "9": (1900, 2000),
}


def _digits(value: str, n: int) -> bool:
    return len(value) == n and value.isascii() and value.isdigit()


def cnp_check_digit(payload12: str) -> int:
    """The check digit for the first twelve digits of a CNP."""
    if not _digits(payload12, 12):
        raise ValueError("expected 12 digits")
    check = sum(int(d) * w for d, w in zip(payload12, _CNP_WEIGHTS, strict=True)) % 11
    return 1 if check == 10 else check


def cnp_birth_date(digits: str) -> tuple[int, int, int] | None:
    """``(year, month, day)`` encoded in a CNP's first seven digits, ``None`` if impossible.

    For the century-less digits 7-9 the first century in which the date exists is returned.
    """
    if len(digits) < 7 or not _digits(digits[:7], 7):
        return None
    centuries = _CNP_CENTURIES.get(digits[0])
    if centuries is None:
        return None
    yy, month, day = int(digits[1:3]), int(digits[3:5]), int(digits[5:7])
    if not 1 <= month <= 12:
        return None
    for century in centuries:
        if 1 <= day <= calendar.monthrange(century + yy, month)[1]:
            return century + yy, month, day
    return None


def is_valid_cnp(digits: str) -> bool:
    """True for a 13-digit CNP with a possible date of birth, county code and check digit."""
    if not _digits(digits, 13) or cnp_birth_date(digits) is None:
        return False
    if not 1 <= int(digits[7:9]) <= 52:
        return False
    return cnp_check_digit(digits[:12]) == int(digits[12])


def cif_check_digit(payload: str) -> int:
    """The CIF/CUI check digit for its 1-9 leading digits."""
    if not 1 <= len(payload) <= 9 or not _digits(payload, len(payload)):
        raise ValueError("expected 1 to 9 digits")
    weights = _CIF_WEIGHTS[-len(payload) :]
    check = sum(int(d) * w for d, w in zip(payload, weights, strict=True)) * 10 % 11
    return 0 if check == 10 else check


def is_valid_cif(digits: str) -> bool:
    """True for a 2-10 digit CIF/CUI (no ``RO`` prefix, no leading zero) with a valid check."""
    if not 2 <= len(digits) <= 10 or not _digits(digits, len(digits)) or digits[0] == "0":
        return False
    return cif_check_digit(digits[:-1]) == int(digits[-1])
