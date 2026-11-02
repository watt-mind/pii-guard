"""Check characters of Spanish identifiers (pure functions, no I/O).

- **DNI / NIF** (Documento Nacional de Identidad; the same number is a person's tax ID):
  eight digits and a check letter, ``12345678Z``. The letter is the number modulo 23 looked
  up in ``TRWAGMYFPDXBNJZSQVHLCKE`` (Real Decreto 1553/2005 and the Ministry of the
  Interior's published table; ``I``, ``Ñ``, ``O`` and ``U`` are never used).
- **NIE** (Número de Identidad de Extranjero): ``X``, ``Y`` or ``Z``, seven digits and a check
  letter, ``X1234567L``. The leading letter stands for the digit 0, 1 or 2; the check letter
  is then computed as for a DNI over the eight digits.
- **CIF** (a company's tax ID, today its NIF): an organisation-type letter, seven digits and a
  control character, ``J99216582``. Over the seven digits, the digits in even positions are
  added and those in odd positions doubled with their digits summed; the control digit is
  ``(10 - total % 10) % 10``, and the control letter is ``JABCDEFGHI`` at that index. Types
  ``P Q R S N W`` (and a number starting ``00``) take the letter, ``A B E H`` the digit,
  the others either (Orden EHA/451/2008).

Every function takes the value without separators and never raises on bad input.
"""

from __future__ import annotations

__all__ = [
    "cif_control",
    "dni_letter",
    "is_valid_cif",
    "is_valid_dni",
    "is_valid_nie",
]

_DNI_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
_NIE_PREFIX = {"X": "0", "Y": "1", "Z": "2"}
_CIF_TYPES = "ABCDEFGHJNPQRSUVW"
_CIF_LETTERS = "JABCDEFGHI"
_CIF_LETTER_ONLY = "PQRSNW"
_CIF_DIGIT_ONLY = "ABEH"


def _digits(value: str, n: int) -> bool:
    return len(value) == n and value.isascii() and value.isdigit()


def dni_letter(digits8: str) -> str:
    """The check letter for the eight digits of a DNI (or of a NIE with its prefix mapped)."""
    if not _digits(digits8, 8):
        raise ValueError("expected 8 digits")
    return _DNI_LETTERS[int(digits8) % 23]


def is_valid_dni(value: str) -> bool:
    """True for a DNI ``DDDDDDDDL`` (separators removed) with the right check letter."""
    if len(value) != 9 or not _digits(value[:8], 8):
        return False
    return dni_letter(value[:8]) == value[8]


def is_valid_nie(value: str) -> bool:
    """True for a NIE ``XDDDDDDDL`` (``X``, ``Y`` or ``Z``; separators removed)."""
    if len(value) != 9 or value[0] not in _NIE_PREFIX or not _digits(value[1:8], 7):
        return False
    return dni_letter(_NIE_PREFIX[value[0]] + value[1:8]) == value[8]


def cif_control(digits7: str) -> int:
    """The CIF control digit for its seven digits (the letter is ``JABCDEFGHI`` at it)."""
    if not _digits(digits7, 7):
        raise ValueError("expected 7 digits")
    even = sum(int(d) for d in digits7[1::2])
    odd = sum(sum(divmod(int(d) * 2, 10)) for d in digits7[0::2])
    return (10 - (even + odd) % 10) % 10


def is_valid_cif(value: str) -> bool:
    """True for a CIF ``TDDDDDDDC`` (separators removed) with a valid control character."""
    if len(value) != 9 or value[0] not in _CIF_TYPES or not _digits(value[1:8], 7):
        return False
    control = cif_control(value[1:8])
    as_digit, as_letter = str(control), _CIF_LETTERS[control]
    if value[0] in _CIF_LETTER_ONLY or value[1:3] == "00":
        return value[8] == as_letter
    if value[0] in _CIF_DIGIT_ONLY:
        return value[8] == as_digit
    return value[8] in (as_digit, as_letter)
