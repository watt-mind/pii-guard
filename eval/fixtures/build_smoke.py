"""Build the hand-written smoke fixtures, one module per language under ``smoke/``:
``hu-smoke.jsonl`` and ``hu-inflection.jsonl`` (Hungarian stem-changing forms of names,
``smoke/hu.py``), ``en-smoke.jsonl`` (``smoke/en.py``), ``de-smoke.jsonl`` (the German language
pack's smoke set, ``smoke/de.py``, see ``docs/languages.md``) and ``pl-smoke.jsonl`` (the Polish
pack's, ``smoke/pl.py``, LAB-1400).

Each ``smoke/<code>.py`` exports ``OUTPUTS``, a mapping of fixture file name to builder; this
script finds them by file name, so adding a language adds a module and edits nothing here
(LAB-1773). The shared helpers below (the fictional identifiers and the label shorthands) are
imported by the language modules with ``from build_smoke import ...``.

Every person, address, number and organisation is **fictional** (ADR 0005). Names use
placeholder-style Hungarian and English surnames; e-mail domains are the reserved
``example.com`` / ``example.org`` / ``example.net``; English and German phone numbers come from
ranges set aside for drama and fiction (German: the Bundesnetzagentur drama numbers), and
Hungarian and Polish ones use a real area code with an ascending-run or ``555 01xx``
subscriber number (ADR 0005). Checksummed identifiers are computed from made-up payloads with
:mod:`pii_guard.detect.checksums`, so they are valid in form but issued to nobody.

Labels are written inline as ``{{TYPE|value}}`` (see :func:`pii_guard.eval.from_markup`), so
offsets are never typed by hand. Hungarian suffixes that leave the value intact stay outside
the label (``{{PERSON|Teszt Elek}}nek``); a stem-changing form is labelled as a whole word.

Regenerate after editing (a test fails if the committed files are stale)::

    uv run python eval/fixtures/build_smoke.py
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path

from pii_guard.detect.checksums import (
    giro_check_digit,
    hu_personal_id_check_digit,
    hu_tax_id_check_digit,
    hu_tax_number_check_digit,
    iban_check_digits,
    mrz_check_digit,
    taj_check_digit,
)
from pii_guard.eval import Document, label, write_fixtures

HERE = Path(__file__).resolve().parent
SMOKE = HERE / "smoke"


# --- Fictional identifiers -------------------------------------------------------------


def tax_id(payload9: str) -> str:
    """A checksum-valid adóazonosító jel (10 digits, starts with 8)."""
    check = hu_tax_id_check_digit(payload9)
    if check is None:
        raise ValueError("payload has no valid check digit; pick another")
    return payload9 + str(check)


def bad_tax_id(payload9: str) -> str:
    """Looks like a tax ID, fails the checksum."""
    good = tax_id(payload9)
    return good[:9] + str((int(good[9]) + 1) % 10)


def taj(payload8: str, sep: str = " ") -> str:
    digits = payload8 + str(taj_check_digit(payload8))
    return sep.join((digits[:3], digits[3:6], digits[6:]))


def bad_taj(payload8: str, sep: str = " ") -> str:
    digits = payload8 + str((taj_check_digit(payload8) + 1) % 10)
    return sep.join((digits[:3], digits[3:6], digits[6:]))


def _giro_block(payload: str) -> str:
    return payload + str(giro_check_digit(payload))


def giro(bank7: str, account: str, sep: str = "-") -> str:
    """A checksum-valid giro account: 8 + 8 digits (7-digit account) or 8 + 16 (15-digit)."""
    first = _giro_block(bank7)
    second = _giro_block(account)
    if len(second) == 8:
        return f"{first}{sep}{second}"
    return f"{first}{sep}{second[:8]}{sep}{second[8:]}"


def hu_iban(bank7: str, account15: str, grouped: bool = True) -> str:
    bban = giro(bank7, account15, sep="")
    compact = "HU" + iban_check_digits("HU", bban) + bban
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4)) if grouped else compact


def iban(country: str, bban: str, grouped: bool = True) -> str:
    compact = country + iban_check_digits(country, bban) + bban
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4)) if grouped else compact


def company_tax_number(base7: str, vat: str = "2", area: str = "42") -> str:
    return f"{base7}{hu_tax_number_check_digit(base7)}-{vat}-{area}"


def bad_company_tax_number(base7: str) -> str:
    return f"{base7}{(hu_tax_number_check_digit(base7) + 1) % 10}-2-42"


def personal_id(payload10: str) -> str:
    """A checksum-valid személyi azonosító, written ``S-YYMMDD-NNNC``."""
    check = hu_personal_id_check_digit(payload10)
    if check is None:
        raise ValueError("payload has no valid check digit; pick another")
    return f"{payload10[0]}-{payload10[1:7]}-{payload10[7:]}{check}"


def mrz_td1(doc: str, born: str, sex: str, expires: str, surname: str, given: str) -> str:
    """A TD1 (ID card) machine-readable zone with valid check digits, issued by ``HUN``."""
    number = doc.ljust(9, "<")
    line1 = f"I<HUN{number}{mrz_check_digit(number)}".ljust(30, "<")
    head = f"{born}{mrz_check_digit(born)}{sex}{expires}{mrz_check_digit(expires)}HUN"
    head = head.ljust(29, "<")
    composite = line1[5:30] + head[0:7] + head[8:15] + head[18:29]
    line2 = head + str(mrz_check_digit(composite))
    line3 = f"{surname}<<{given}".ljust(30, "<")
    return "\n".join((line1, line2, line3))


# Shorthands for inline labels.
def P(v: str) -> str:
    return label("PERSON", v)


def A(v: str) -> str:
    return label("ADDRESS", v)


def E(v: str) -> str:
    return label("EMAIL", v)


def PH(v: str) -> str:
    return label("PHONE", v)


def DOB(v: str) -> str:
    return label("DATE_OF_BIRTH", v)


def TAX(v: str) -> str:
    return label("NATIONAL_ID_HU_TAX", v)


def TAJ(v: str) -> str:
    return label("NATIONAL_ID_HU_TAJ", v)


def IDD(v: str) -> str:
    return label("ID_DOCUMENT", v)


def BANK(v: str) -> str:
    return label("BANK_ACCOUNT", v)


def CO(v: str) -> str:
    return label("COMPANY_ID_HU", v)


def ORG(v: str) -> str:
    return label("ORGANIZATION", v)


def HRSZ(v: str) -> str:
    return label("PARCEL_NUMBER_HU", v)


def PLATE(v: str) -> str:
    return label("VEHICLE_PLATE", v)


# --- Discovery ---------------------------------------------------------------------------


def _load_language_modules() -> dict[str, Callable[[], list[Document]]]:
    """Merge the ``OUTPUTS`` of every ``smoke/<code>.py``, in file-name order.

    The modules are loaded by file path, so this works when the script runs directly and when
    a test loads it with :func:`importlib.util.spec_from_file_location`. They import the helpers
    above from ``build_smoke``, which is this module whichever way it was loaded.
    """
    this = sys.modules.get(__name__)
    if this is None:
        raise RuntimeError("register build_smoke in sys.modules before executing it")
    sys.modules["build_smoke"] = this
    outputs: dict[str, Callable[[], list[Document]]] = {}
    for path in sorted(SMOKE.glob("*.py")):
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f"build_smoke_{path.stem}", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name, build in module.OUTPUTS.items():
            if name in outputs:
                raise RuntimeError(f"{name} is built by more than one module in {SMOKE}")
            outputs[name] = build
    return outputs


OUTPUTS = _load_language_modules()


def main() -> None:
    for name, build in OUTPUTS.items():
        write_fixtures(HERE / name, build())
        print(f"wrote {HERE / name}")


if __name__ == "__main__":
    main()
