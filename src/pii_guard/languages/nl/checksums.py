"""Check digits of Dutch identifiers (pure functions, no I/O).

- **Burgerservicenummer** (BSN, the personal number since 2007; the older sofinummer has the
  same number and format): 9 digits that pass the *elfproef* (eleven test) of the Wet algemene
  bepalingen burgerservicenummer: the first eight digits weighted ``9 8 7 6 5 4 3 2`` and the
  ninth ``-1``, the total a multiple of 11. An all-zero number passes the arithmetic and is
  not a BSN. Published examples: ``111222333`` (RvIG's test number) and ``123456782``.

The elfproef catches one wrong digit in eleven, which is weak on its own: about one 9-digit
number in eleven passes it. That is why an unlabelled BSN is matched only in Dutch text
(:mod:`.rules`).

Every function takes the value without separators and never raises on bad input, except the
check-digit helper, which rejects a malformed payload with :class:`ValueError`.
"""

from __future__ import annotations

__all__ = ["bsn_check_digit", "is_valid_bsn"]

_WEIGHTS = (9, 8, 7, 6, 5, 4, 3, 2)


def _digits(value: str, n: int) -> bool:
    return len(value) == n and value.isascii() and value.isdigit()


def bsn_check_digit(payload8: str) -> int | None:
    """The ninth digit that makes ``payload8`` a BSN, ``None`` if no digit does.

    The check digit is the weighted sum modulo 11; a remainder of 10 has no digit, so a
    payload with that remainder never becomes a BSN.
    """
    if not _digits(payload8, 8):
        raise ValueError("expected 8 digits")
    check = sum(w * int(ch) for w, ch in zip(_WEIGHTS, payload8, strict=True)) % 11
    return None if check == 10 else check


def is_valid_bsn(digits: str) -> bool:
    """True for a 9-digit BSN (or sofinummer) that passes the elfproef and is not all zeros."""
    if not _digits(digits, 9) or int(digits) == 0:
        return False
    return bsn_check_digit(digits[:8]) == int(digits[8])
