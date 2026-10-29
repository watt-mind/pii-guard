"""Check digits of German identifiers (pure functions, no I/O).

- **Steuerliche Identifikationsnummer** (Steuer-ID, IdNr): 11 digits, the last a check digit
  over the first ten (ISO/IEC 7064 MOD 11,10). The first digit is never 0, and in the first
  ten digits exactly one digit occurs twice or three times (never three times in a row).
- **Versicherungsnummer** of the statutory pension insurance (Sozialversicherungsnummer,
  RVNR): 12 characters, ``AA DDMMYY L SS C``: area number, date of birth, the initial of the
  birth name, a serial number and a check digit. For the check digit the letter is replaced by
  its two-digit position in the alphabet, the 12 digits are weighted ``2 1 2 5 7 1 2 1 2 1 2 1``,
  and the digit sums of the products are added modulo 10.
"""

from __future__ import annotations

from collections import Counter

__all__ = [
    "is_valid_steuer_id",
    "is_valid_sv_number",
    "steuer_id_check_digit",
    "sv_number_check_digit",
]

_SV_WEIGHTS = (2, 1, 2, 5, 7, 1, 2, 1, 2, 1, 2, 1)


def steuer_id_check_digit(payload10: str) -> int:
    """The check digit for the first ten digits of a Steuer-ID."""
    if len(payload10) != 10 or not (payload10.isascii() and payload10.isdigit()):
        raise ValueError("expected 10 digits")
    product = 10
    for ch in payload10:
        total = (int(ch) + product) % 10 or 10
        product = (total * 2) % 11
    check = 11 - product
    return 0 if check == 10 else check


def is_valid_steuer_id(digits: str) -> bool:
    """True for an 11-digit Steuer-ID with a valid structure and check digit."""
    if len(digits) != 11 or not (digits.isascii() and digits.isdigit()) or digits[0] == "0":
        return False
    head = digits[:10]
    counts = Counter(head)
    repeated = [d for d, n in counts.items() if n > 1]
    if len(repeated) != 1 or counts[repeated[0]] not in (2, 3):
        return False
    if any(head[i] == head[i + 1] == head[i + 2] for i in range(len(head) - 2)):
        return False
    return steuer_id_check_digit(head) == int(digits[10])


def sv_number_check_digit(payload: str) -> int:
    """The check digit for ``AADDMMYYLSS`` (11 characters, ``L`` an ASCII capital letter)."""
    if len(payload) != 11 or not payload[8].isascii() or not payload[8].isupper():
        raise ValueError("expected AADDMMYYLSS")
    digits = payload[:8] + f"{ord(payload[8]) - 64:02d}" + payload[9:]
    if not (digits.isascii() and digits.isdigit()):
        raise ValueError("expected AADDMMYYLSS")
    total = sum(sum(divmod(int(d) * w, 10)) for d, w in zip(digits, _SV_WEIGHTS, strict=True))
    return total % 10


def is_valid_sv_number(value: str) -> bool:
    """True for a 12-character Versicherungsnummer (spaces removed) with a valid check digit.

    The date part must be a plausible ``DDMMYY`` (day 01-31, month 01-12); the area number
    must be 02-89.
    """
    value = value.replace(" ", "")
    # ``isdigit()`` alone accepts any script's digits (and superscripts), which the arithmetic
    # below rejects: only ASCII digits are a Versicherungsnummer, and this never raises.
    if len(value) != 12 or not value.isascii():
        return False
    if not value[:8].isdigit() or not value[9:].isdigit():
        return False
    if not ("A" <= value[8] <= "Z"):
        return False
    area, day, month = int(value[:2]), int(value[2:4]), int(value[4:6])
    if not (2 <= area <= 89 and 1 <= day <= 31 and 1 <= month <= 12):
        return False
    return sv_number_check_digit(value[:11]) == int(value[11])
