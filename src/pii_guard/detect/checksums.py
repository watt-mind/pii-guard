"""Check-digit algorithms for the structured identifiers the rule detector validates.

Each identifier has a ``*_check_digit(s)`` function that computes the check digit(s) from the
payload, and an ``is_valid_*`` predicate on the normalized value (digits only, or for IBANs
uppercase without spaces). The check-digit functions are public so synthetic data generators
can build valid fictional values; nothing here knows about real people.
"""

from __future__ import annotations

from datetime import date

__all__ = [
    "IBAN_LENGTHS",
    "giro_check_digit",
    "hu_personal_id_check_digit",
    "hu_tax_id_check_digit",
    "hu_tax_number_check_digit",
    "iban_check_digits",
    "is_valid_giro",
    "is_valid_hu_personal_id",
    "is_valid_hu_tax_id",
    "is_valid_hu_tax_number",
    "is_valid_iban",
    "is_valid_mrz_td1",
    "is_valid_mrz_td3",
    "is_valid_taj",
    "mrz_check_digit",
    "taj_check_digit",
]

# IBAN length per country (SWIFT IBAN registry).
IBAN_LENGTHS: dict[str, int] = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16, "BG": 22,
    "BH": 22, "BR": 29, "BY": 28, "CH": 21, "CR": 22, "CY": 28, "CZ": 24, "DE": 22,
    "DK": 18, "DO": 28, "EE": 20, "EG": 29, "ES": 24, "FI": 18, "FO": 18, "FR": 27,
    "GB": 22, "GE": 22, "GI": 23, "GL": 18, "GR": 27, "GT": 28, "HR": 21, "HU": 28,
    "IE": 22, "IL": 23, "IQ": 23, "IS": 26, "IT": 27, "JO": 30, "KW": 30, "KZ": 20,
    "LB": 28, "LC": 32, "LI": 21, "LT": 20, "LU": 20, "LV": 21, "LY": 25, "MC": 27,
    "MD": 24, "ME": 22, "MK": 19, "MR": 27, "MT": 31, "MU": 30, "NL": 18, "NO": 15,
    "PK": 24, "PL": 28, "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22, "SA": 24,
    "SC": 31, "SE": 24, "SI": 19, "SK": 24, "SM": 27, "ST": 25, "SV": 28, "TL": 23,
    "TN": 24, "TR": 26, "UA": 29, "VA": 22, "VG": 24, "XK": 20,
}  # fmt: skip

_GIRO_WEIGHTS = (9, 7, 3, 1)


def _is_digits(value: str, length: int) -> bool:
    return len(value) == length and value.isascii() and value.isdigit()


# --- Hungarian personal tax ID (adóazonosító jel) ---------------------------


def hu_tax_id_check_digit(first9: str) -> int | None:
    """Check digit for the first 9 digits of a tax ID, or ``None`` if no digit is valid.

    The weighted sum ``d1*1 + d2*2 + ... + d9*9`` modulo 11 is the 10th digit; a remainder
    of 10 means the payload is never issued.
    """
    if not _is_digits(first9, 9):
        raise ValueError("expected 9 digits")
    remainder = sum(int(d) * i for i, d in enumerate(first9, start=1)) % 11
    return None if remainder == 10 else remainder


def is_valid_hu_tax_id(value: str) -> bool:
    """10 digits, first digit 8, valid mod-11 check digit."""
    if not _is_digits(value, 10) or value[0] != "8":
        return False
    return hu_tax_id_check_digit(value[:9]) == int(value[9])


# --- Hungarian personal identification number (személyi azonosító) ---------
#
# 11 digits: ``S YYMMDD NNN C``. ``S`` encodes sex and century, ``YYMMDD`` is the date of
# birth, ``NNN`` a serial for people born that day, ``C`` the check digit: the weighted sum
# of the first 10 digits modulo 11, with weights 1..10 for people born before 1997-01-01 and
# 10..1 from then on. A remainder of 10 means the serial is never issued.

# First digit -> century of birth. 1-2: citizens born 1900-1999; 3-4: born 1800-1899; 5-6:
# born 2000 or later; 7-8: foreign residents born 1900-1999 (0 and 9 are not used for new
# numbers and are rejected).
_PERSONAL_ID_CENTURY = {"1": 1900, "2": 1900, "3": 1800, "4": 1800, "5": 2000, "6": 2000,
                        "7": 1900, "8": 1900}  # fmt: skip
_PERSONAL_ID_REVERSED_FROM = date(1997, 1, 1)


def _personal_id_birth_date(first7: str) -> date | None:
    century = _PERSONAL_ID_CENTURY.get(first7[0])
    if century is None:
        return None
    try:
        return date(century + int(first7[1:3]), int(first7[3:5]), int(first7[5:7]))
    except ValueError:
        return None


def hu_personal_id_check_digit(first10: str) -> int | None:
    """Check digit for the first 10 digits of a személyi azonosító.

    ``None`` if the payload can't be issued: unknown sex/century digit, an impossible date of
    birth, or a weighted sum with remainder 10.
    """
    if not _is_digits(first10, 10):
        raise ValueError("expected 10 digits")
    born = _personal_id_birth_date(first10[:7])
    if born is None:
        return None
    weights = range(1, 11) if born < _PERSONAL_ID_REVERSED_FROM else range(10, 0, -1)
    remainder = sum(int(d) * w for d, w in zip(first10, weights, strict=True)) % 11
    return None if remainder == 10 else remainder


def is_valid_hu_personal_id(value: str) -> bool:
    """11 digits, a valid sex/century digit and date of birth, a valid check digit."""
    if not _is_digits(value, 11):
        return False
    return hu_personal_id_check_digit(value[:10]) == int(value[10])


# --- Hungarian social security number (TAJ) ---------------------------------


def taj_check_digit(first8: str) -> int:
    """Check digit for the first 8 digits of a TAJ number (weights 3, 7 alternating, mod 10)."""
    if not _is_digits(first8, 8):
        raise ValueError("expected 8 digits")
    return sum(int(d) * (3 if i % 2 == 0 else 7) for i, d in enumerate(first8)) % 10


def is_valid_taj(value: str) -> bool:
    """9 digits with a valid check digit."""
    return _is_digits(value, 9) and taj_check_digit(value[:8]) == int(value[8])


# --- Hungarian giro account and company tax number (weights 9, 7, 3, 1) -----


def giro_check_digit(payload: str) -> int:
    """The digit that makes ``payload + digit`` sum to 0 mod 10 under weights 9, 7, 3, 1, ...

    Used for each block of a Hungarian giro account number (the 7-digit bank/branch prefix and
    the 7- or 15-digit account part) and for the 8th digit of a company tax number.
    """
    if not payload or not (payload.isascii() and payload.isdigit()):
        raise ValueError("expected digits")
    total = sum(int(d) * _GIRO_WEIGHTS[i % 4] for i, d in enumerate(payload))
    return (10 - total % 10) % 10


def _giro_block_valid(block: str) -> bool:
    return giro_check_digit(block[:-1]) == int(block[-1])


def is_valid_giro(value: str) -> bool:
    """16 or 24 digits: an 8-digit bank/branch block and an 8- or 16-digit account block."""
    if not (_is_digits(value, 16) or _is_digits(value, 24)):
        return False
    return _giro_block_valid(value[:8]) and _giro_block_valid(value[8:])


def hu_tax_number_check_digit(first7: str) -> int:
    """Check digit (8th digit) of a Hungarian company tax number's base number."""
    if not _is_digits(first7, 7):
        raise ValueError("expected 7 digits")
    return giro_check_digit(first7)


# County / office codes that appear as the last two digits of a company tax number.
_TAX_NUMBER_AREA_CODES = frozenset(
    {f"{n:02d}" for n in range(2, 21)} | {"22", "41", "42", "43", "44", "51"}
)


def is_valid_hu_tax_number(base: str, vat_code: str, area: str) -> bool:
    """``12345678-2-42``: check digit on the base, VAT code 1-5, a known area code."""
    return (
        _is_digits(base, 8)
        and hu_tax_number_check_digit(base[:7]) == int(base[7])
        and vat_code in {"1", "2", "3", "4", "5"}
        and area in _TAX_NUMBER_AREA_CODES
    )


# --- IBAN (ISO 13616, mod 97) -----------------------------------------------


def _iban_to_int(rearranged: str) -> int:
    # Letters become 10..35; int() of the digit string is exact for any IBAN length.
    return int("".join(str(int(ch, 36)) for ch in rearranged))


def iban_check_digits(country: str, bban: str) -> str:
    """The two check digits for ``country`` + ``bban`` (uppercase, no spaces)."""
    if not (len(country) == 2 and country.isascii() and country.isalpha() and country.isupper()):
        raise ValueError("expected a 2-letter uppercase country code")
    if not (bban and bban.isascii() and bban.isalnum() and bban == bban.upper()):
        raise ValueError("expected an uppercase alphanumeric BBAN")
    return f"{98 - _iban_to_int(bban + country + '00') % 97:02d}"


def is_valid_iban(value: str) -> bool:
    """Uppercase, no spaces, known country with the right length, mod-97 remainder 1."""
    country = value[:2]
    expected = IBAN_LENGTHS.get(country)
    if expected is None or len(value) != expected:
        return False
    if not (value.isascii() and value.isalnum() and value == value.upper()):
        return False
    if not value[2:4].isdigit():
        return False
    return _iban_to_int(value[4:] + value[:4]) % 97 == 1


# --- Machine-readable zone of travel documents (ICAO Doc 9303) --------------
#
# Every check digit is the sum of the field's character values (digits as themselves, A-Z as
# 10-35, the filler ``<`` as 0) times the repeating weights 7, 3, 1, modulo 10.

_MRZ_WEIGHTS = (7, 3, 1)
_MRZ_CHARS = frozenset("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ<")


def _mrz_value(ch: str) -> int:
    if ch == "<":
        return 0
    if ch.isdigit():
        return int(ch)
    return ord(ch) - ord("A") + 10


def mrz_check_digit(field: str) -> int:
    """The ICAO 9303 check digit of an MRZ field (``0-9``, ``A-Z`` and ``<`` only)."""
    if not field or not set(field) <= _MRZ_CHARS:
        raise ValueError("expected MRZ characters (0-9, A-Z, <)")
    return sum(_mrz_value(ch) * _MRZ_WEIGHTS[i % 3] for i, ch in enumerate(field)) % 10


def _mrz_check(field: str, digit: str) -> bool:
    # A field left empty may carry '<' as its check digit (optional data in TD3).
    if digit == "<":
        return set(field) <= {"<"}
    return digit.isascii() and digit.isdigit() and mrz_check_digit(field) == int(digit)


def _is_mrz_line(line: str, length: int) -> bool:
    return len(line) == length and set(line) <= _MRZ_CHARS


def is_valid_mrz_td3(line1: str, line2: str) -> bool:
    """A passport-size (TD3, 2 x 44) MRZ whose check digits all agree.

    Line 2 carries the document number, date of birth, expiry date and optional data with
    their check digits, then a composite check digit over all of them.
    """
    if not (_is_mrz_line(line1, 44) and _is_mrz_line(line2, 44)):
        return False
    return (
        _mrz_check(line2[0:9], line2[9])
        and _mrz_check(line2[13:19], line2[19])
        and _mrz_check(line2[21:27], line2[27])
        and _mrz_check(line2[28:42], line2[42])
        and _mrz_check(line2[0:10] + line2[13:20] + line2[21:43], line2[43])
    )


def is_valid_mrz_td1(line1: str, line2: str, line3: str) -> bool:
    """An ID-card-size (TD1, 3 x 30) MRZ whose check digits all agree.

    The document number and its check digit are on line 1; the date of birth and expiry date
    with theirs on line 2, which ends with the composite check digit over both lines.
    """
    if not all(_is_mrz_line(line, 30) for line in (line1, line2, line3)):
        return False
    return (
        _mrz_check(line1[5:14], line1[14])
        and _mrz_check(line2[0:6], line2[6])
        and _mrz_check(line2[8:14], line2[14])
        and _mrz_check(line1[5:30] + line2[0:7] + line2[8:15] + line2[18:29], line2[29])
    )
