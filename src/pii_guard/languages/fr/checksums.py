"""Check digits of French identifiers (pure functions, no I/O).

- **NIR** (numéro d'inscription au répertoire, the numéro de sécurité sociale): 15 characters
  ``SAAMMDDCCCOOOKK``. ``S`` is the sex (1 men, 2 women; 3, 4, 7 and 8 for people being
  registered, 7 and 8 temporary), ``AA`` the last two digits of the birth year, ``MM`` the
  birth month (01-12; 13 and 20-42 or 50-99 when the record gives no month or an incomplete
  one), ``DD`` the department of birth (01-95, ``2A``/``2B`` for Corsica, 96, 97x/98x
  overseas with a two-digit commune, 99 born abroad), ``CCC`` the commune (or country) and
  ``OOO`` the order number. The key ``KK`` (01-97) is 97 minus the first 13 digits modulo 97;
  for Corsica ``2A`` counts as ``19`` and ``2B`` as ``18`` (INSEE).
- **Numéro fiscal** (SPI, the DGFiP tax number): 13 digits starting with 0-3. The last three
  digits are the first ten modulo 511, zero-padded (DGFiP, "algorithme SPI").

Every function takes the value without separators and never raises on bad input.
"""

from __future__ import annotations

__all__ = [
    "is_valid_nir",
    "is_valid_spi",
    "nir_key",
    "nir_month_is_calendar",
    "spi_check",
]

# Corsica's departments in the 13 digits the key is computed from (INSEE).
_CORSICA = {"2A": "19", "2B": "18"}


def _digits(value: str, n: int) -> bool:
    return len(value) == n and value.isascii() and value.isdigit()


def _nir_numeric(payload13: str) -> str | None:
    """The 13 digits the key is computed from (``2A``/``2B`` replaced), ``None`` if malformed."""
    if len(payload13) != 13:
        return None
    department = payload13[5:7]
    numeric = payload13[:5] + _CORSICA.get(department, department) + payload13[7:]
    return numeric if _digits(numeric, 13) else None


def nir_key(payload13: str) -> int:
    """The two-digit key (1-97) for the first 13 characters of a NIR (``2A``/``2B`` allowed)."""
    numeric = _nir_numeric(payload13)
    if numeric is None:
        raise ValueError("expected 13 digits (2A or 2B for a Corsican department)")
    return 97 - int(numeric) % 97


def _nir_fields_valid(value: str) -> bool:
    sex, month, department = value[0], int(value[3:5]), value[5:7]
    if sex not in "123478":
        return False
    if not (1 <= month <= 13 or 20 <= month <= 42 or month >= 50):
        return False
    if department in _CORSICA:
        return True
    if not department.isdigit() or department == "00":
        return False
    return department != "96" or value[7:10] != "000"


def is_valid_nir(value: str) -> bool:
    """True for a 15-character NIR with possible fields and a valid key."""
    if len(value) != 15 or not value.isascii() or not _digits(value[13:], 2):
        return False
    numeric = _nir_numeric(value[:13])
    if numeric is None or not _nir_fields_valid(value):
        return False
    return nir_key(value[:13]) == int(value[13:])


def nir_month_is_calendar(value: str) -> bool:
    """True when a NIR's month is a real one (01-12) and its sex digit is 1 or 2.

    The unlabelled rule accepts only these: the other codes are rare, and every one accepted
    makes a random 15-digit run more likely to pass.
    """
    return value[:1] in ("1", "2") and value[3:5].isdigit() and 1 <= int(value[3:5]) <= 12


def spi_check(payload10: str) -> str:
    """The three check digits for the first ten digits of a numéro fiscal."""
    if not _digits(payload10, 10):
        raise ValueError("expected 10 digits")
    return f"{int(payload10) % 511:03d}"


def is_valid_spi(value: str) -> bool:
    """True for a 13-digit numéro fiscal (first digit 0-3) with valid check digits."""
    if not _digits(value, 13) or value[0] not in "0123":
        return False
    return spi_check(value[:10]) == value[10:]
