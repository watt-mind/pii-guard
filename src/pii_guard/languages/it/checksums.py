"""Check characters of Italian identifiers (pure functions, no I/O).

- **Codice fiscale** (personal tax code, DM 23/12/1976): 16 characters ``SSSNNNYYMDDCCCCK``:
  three letters from the surname and three from the given name, the year of birth (two
  digits), the month as a letter (``A B C D E H L M P R S T`` for January to December), the
  day of birth (plus 40 for women, so 01-31 or 41-71), the municipality or foreign country
  code (a letter and three digits, ``Z`` for a country) and a check letter. The check letter
  is the sum of the first fifteen characters, each converted with the *odd* table at odd
  positions (1st, 3rd ... 15th) and the *even* table at even ones, modulo 26, as a letter
  (``0`` = ``A``).
- **Omocodia**: when two people would get the same code, the Agenzia delle Entrate replaces
  digits with letters, from the right (``0`` = ``L``, ``1`` = ``M``, ``2`` = ``N``, ``3`` =
  ``P``, ``4`` = ``Q``, ``5`` = ``R``, ``6`` = ``S``, ``7`` = ``T``, ``8`` = ``U``, ``9`` =
  ``V``). Any of the seven digit positions (year, day, the three digits of the place) may hold
  such a letter; the check letter is computed over the substituted characters.
- **Partita IVA** (VAT number, DPR 633/1972): 11 digits, the company number (seven), the
  office code of the province (three: ``001``-``100``, or ``120``, ``121``, ``888``, ``999``)
  and a check digit computed as Luhn's: the digits at even positions doubled (9 subtracted
  above 9), the total plus the check digit a multiple of 10.

Every function takes the value without separators and never raises on bad input, except the
check-character helpers, which reject a malformed payload with :class:`ValueError`.
"""

from __future__ import annotations

__all__ = [
    "MONTHS",
    "OMOCODIA",
    "codice_fiscale_birth",
    "codice_fiscale_check_char",
    "is_valid_codice_fiscale",
    "is_valid_partita_iva",
    "partita_iva_check_digit",
]

#: Month letters, January to December.
MONTHS = "ABCDEHLMPRST"
#: The letters that replace the digits 0-9 in an omocodic code.
OMOCODIA = "LMNPQRSTUV"
# The value of each character at an odd position (1st, 3rd ...): digits share their letter's.
_ODD = dict(
    zip(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        (1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 2, 4, 18, 20, 11, 3, 6, 8, 12, 14, 16, 10, 22, 25,
         24, 23),
        strict=True,
    )
)  # fmt: skip
_ODD.update({str(d): _ODD[chr(65 + d)] for d in range(10)})
# At an even position a digit counts as itself and a letter as its place in the alphabet.
_EVEN = {**{chr(65 + i): i for i in range(26)}, **{str(d): d for d in range(10)}}
# The positions (0-based) that hold digits, or their omocodia letters.
_DIGIT_POSITIONS = (6, 7, 9, 10, 12, 13, 14)
_LETTER_POSITIONS = (0, 1, 2, 3, 4, 5, 8, 11, 15)
_OFFICES = frozenset({*range(1, 101), 120, 121, 888, 999})


def _upper_alnum(value: str) -> bool:
    return value.isascii() and value.isalnum() and value == value.upper()


def _digits(value: str, n: int) -> bool:
    return len(value) == n and value.isascii() and value.isdigit()


def codice_fiscale_check_char(payload15: str) -> str:
    """The check letter for the first fifteen characters of a codice fiscale."""
    if len(payload15) != 15 or not _upper_alnum(payload15):
        raise ValueError("expected 15 capital letters and digits")
    total = sum(
        (_ODD if i % 2 == 0 else _EVEN)[ch] for i, ch in enumerate(payload15)
    )  # i is 0-based: index 0 is the 1st, odd, position
    return chr(65 + total % 26)


def _de_omocodia(value: str) -> str | None:
    """``value`` with every omocodia letter turned back into its digit, ``None`` if malformed."""
    chars = list(value)
    for i in _DIGIT_POSITIONS:
        ch = chars[i]
        if ch.isdigit():
            continue
        if ch not in OMOCODIA:
            return None
        chars[i] = str(OMOCODIA.index(ch))
    return "".join(chars)


def codice_fiscale_birth(value: str) -> tuple[int, int, int, bool] | None:
    """``(yy, month, day, female)`` encoded in a codice fiscale, ``None`` if impossible.

    The year has two digits (the century is not encoded). Omocodia letters are read as their
    digits.
    """
    if len(value) != 16 or not _upper_alnum(value):
        return None
    plain = _de_omocodia(value)
    if plain is None or value[8] not in MONTHS:
        return None
    yy, day = int(plain[6:8]), int(plain[9:11])
    female = day > 40
    day -= 40 if female else 0
    if not 1 <= day <= 31:
        return None
    return yy, MONTHS.index(value[8]) + 1, day, female


def is_valid_codice_fiscale(value: str) -> bool:
    """True for a 16-character codice fiscale (omocodic or not) with a valid check letter.

    Checks the letter and digit positions, the month letter, the day (01-31, 41-71 for women)
    and the check letter. The municipality code is not looked up: it changes with every
    merger of municipalities, and a code that only fails the lookup is still a person's.
    """
    if len(value) != 16 or not _upper_alnum(value):
        return False
    if not all(value[i].isalpha() for i in _LETTER_POSITIONS):
        return False
    if codice_fiscale_birth(value) is None:
        return False
    return codice_fiscale_check_char(value[:15]) == value[15]


def partita_iva_check_digit(payload10: str) -> int:
    """The Luhn check digit for the first ten digits of a partita IVA."""
    if not _digits(payload10, 10):
        raise ValueError("expected 10 digits")
    total = 0
    for i, ch in enumerate(payload10):
        d = int(ch)
        if i % 2 == 1:  # the 2nd, 4th ... digit is doubled
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return (10 - total % 10) % 10


def is_valid_partita_iva(digits: str) -> bool:
    """True for an 11-digit partita IVA with a known office code and a valid check digit."""
    if not _digits(digits, 11) or digits[:7] == "0000000":
        return False
    if int(digits[7:10]) not in _OFFICES:
        return False
    return partita_iva_check_digit(digits[:10]) == int(digits[10])
