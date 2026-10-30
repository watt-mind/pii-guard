"""A synthetic CEE dev split: short noisy documents with reference and tracking numbers (LAB-1344).

```
python -m pii_guard.eval.datasets fetch cee-dev     # writes eval/synthetic/dev/<lang>-cee-dev.jsonl
python -m pii_guard.eval.datasets check cee-dev     # rebuild, compare, write nothing
```

``cee-pii`` (CEE-PII-Bench) is a test split, so the over-masking left on it after LAB-1293 must
not be tuned on. This split is the tuning ground instead: the same *kinds* of document (bank
statement lines, chats, support tickets, e-mails, form fields, OCR-ish fragments, shipping
notices, SMS), written from scratch here, in Hungarian and English (the cee-pii languages).

Every document holds real identifiers (names, e-mail addresses, phones, IBANs and giro
accounts, cards, TAJ and tax numbers, UK national insurance and passport numbers) next to
**hard negatives** that are never labelled, each drawn from :data:`NEGATIVES`:

- timestamp-style references: 13-digit epoch milliseconds, 14-digit ``yyyymmddhhmmss`` stamps
  (also with a short letter prefix);
- tracking numbers: UPS ``1Z…`` and UPU S10 (``RB123456785HU``, ``LX…GB``) with valid check
  digits, GLS-style 11-digit and DPD-style 14-digit parcel numbers;
- CEE order, invoice and booking formats (``SZLA-2026-004812``, ``2026/004812``,
  ``HU-260412-8812``, ``E-PTRK-2026-118``).

Half the negatives come after a label no detector treats as a negative cue (``ref``,
``hivatkozás``, ``azonosító``, ``közlemény``) or after none at all, as in the bench's register.
The OCR register strips Hungarian accents and swaps ``0``/``O`` in some negatives (never in a
gold value). Gold comes from construction (:mod:`pii_guard.eval.datasets.synthetic` values):
**no model labels anything**, and the same seed gives the same bytes.
"""

# Seeded synthetic data: the standard PRNG is the point.
# ruff: noqa: S311

from __future__ import annotations

import datetime as dt
import random
import unicodedata
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pii_guard.eval.datasets.spec import Dataset
from pii_guard.eval.datasets.synthetic import (
    Built,
    Gold,
    Piece,
    Values,
    amount,
    some_date,
)
from pii_guard.eval.fixtures import Document, parse_document
from pii_guard.types import EntityType

__all__ = ["DATASET", "GENERATOR", "LANGUAGES", "NEGATIVES", "REGISTERS", "build", "document"]

GENERATOR = "pii-guard synthetic cee-dev v1 (LAB-1344)"
LANGUAGES = ("hu", "en")
SEED = 71344
SIZE = 120
OUT_DIR = Path("eval/synthetic/dev")

E = EntityType


# --- Hard negatives -------------------------------------------------------------------------


def _digits(rng: random.Random, n: int) -> str:
    return "".join(str(rng.randrange(10)) for _ in range(n))


def epoch_ms(rng: random.Random) -> str:
    """Epoch milliseconds in 2024-2027: 13 digits starting with 17 or 18."""
    return str(rng.randint(1_704_067_200_000, 1_830_297_600_000))


def stamp14(rng: random.Random) -> str:
    """A ``yyyymmddhhmmss`` stamp in 2024-2026."""
    t = dt.datetime(2024, 1, 1, tzinfo=dt.UTC) + dt.timedelta(
        seconds=rng.randint(0, 3 * 365 * 86400)
    )
    return t.strftime("%Y%m%d%H%M%S")


def stamp_ref(rng: random.Random) -> str:
    """A letter-prefixed stamp reference (``TR20261029141749``, ``K-20260412093015``)."""
    return rng.choice(["TR", "K-", "B", "PAY", "R"]) + stamp14(rng)


def _ups_check(body: str) -> str:
    total = 0
    for i, ch in enumerate(body):
        value = int(ch) if ch.isdigit() else (ord(ch) - 63) % 10
        total += value * (2 if i % 2 else 1)
    return str((10 - total % 10) % 10)


def ups(rng: random.Random) -> str:
    alnum = "0123456789ABCDEFGHJKLMNPRSTVWXYZ"
    body = "".join(rng.choice(alnum) for _ in range(6)) + _digits(rng, 9)
    return "1Z" + body + _ups_check(body)


def s10(rng: random.Random) -> str:
    """A UPU S10 item id with a valid check digit (``RB123456785HU``)."""
    serial = _digits(rng, 8)
    total = sum(int(d) * w for d, w in zip(serial, (8, 6, 4, 2, 3, 5, 9, 7), strict=True))
    check = 11 - total % 11
    check = {10: 0, 11: 5}.get(check, check)
    prefix = rng.choice(["RB", "RR", "LX", "CP", "EE", "UA", "LY"])
    country = rng.choice(["HU", "GB", "HU", "SK", "AT", "GB", "DE"])
    return f"{prefix}{serial}{check}{country}"


def parcel(rng: random.Random) -> str:
    """A GLS-style 11-digit or DPD-style 14-digit parcel number."""
    return _digits(rng, 11) if rng.random() < 0.5 else "0" + _digits(rng, 13)


def cee_order(rng: random.Random) -> str:
    """CEE invoice, order and booking formats."""
    year = rng.randint(2024, 2026)
    return rng.choice(
        [
            f"SZLA-{year}-{rng.randint(1, 99999):06d}",
            f"{year}/{rng.randint(1, 99999):06d}",
            f"HU-{year % 100}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}"
            f"-{rng.randint(1000, 9999)}",
            f"E-{rng.choice(['PTRK', 'KAP', 'BSZ', 'NAV'])}-{year}-{rng.randint(1, 999)}",
            f"{rng.choice(['INV', 'FV', 'VSZ'])} {year}/{rng.randint(1, 9999):05d}",
            f"{rng.randint(100, 999)}-{rng.randint(1000000, 9999999)}"
            f"-{rng.randint(1000000, 9999999)}",
        ]
    )


#: Hard-negative kinds: never labelled; a masked span on one is over-masking.
NEGATIVES: dict[str, Callable[[random.Random], str]] = {
    "epoch-ms": epoch_ms,
    "stamp14": stamp14,
    "stamp-ref": stamp_ref,
    "ups": ups,
    "s10": s10,
    "parcel": parcel,
    "cee-order": cee_order,
}

#: Labels before a negative. None: the value stands alone. Not negative cues on purpose.
_NEUTRAL = {
    "hu": ("ref", "hivatkozás:", "azonosító:", "közlemény:", "ref.", None, None),
    "en": ("ref", "reference:", "ID:", "ref no.", None, None),
}
#: Labels that name the negative (a cue the detector may use).
_NAMED = {
    "hu": {
        "epoch-ms": "tranzakció",
        "stamp14": "tranzakció",
        "stamp-ref": "tranzakció",
        "ups": "követési szám:",
        "s10": "küldeményazonosító:",
        "parcel": "csomagszám:",
        "cee-order": "rendelésszám:",
    },
    "en": {
        "epoch-ms": "transaction",
        "stamp14": "transaction",
        "stamp-ref": "transaction",
        "ups": "tracking:",
        "s10": "tracking no.",
        "parcel": "parcel",
        "cee-order": "invoice",
    },
}


class Negatives:
    """The negatives of one document, with their kinds and offsets recorded in ``meta``."""

    def __init__(self, language: str, rng: random.Random, *, ocr: bool = False) -> None:
        self.language, self.rng, self.ocr = language, rng, ocr
        self.made: list[tuple[str, str]] = []

    def __call__(self, kind: str | None = None, *, label: bool | None = None) -> str:
        rng = self.rng
        kind = kind or rng.choice(list(NEGATIVES))
        value = NEGATIVES[kind](rng)
        if self.ocr and rng.random() < 0.3 and "0" in value:
            i = rng.choice([i for i, ch in enumerate(value) if ch == "0"])
            value = value[:i] + "O" + value[i + 1 :]
        self.made.append((kind, value))
        if label is None:
            label = rng.random() < 0.5
        cue = _NAMED[self.language][kind] if label else rng.choice(_NEUTRAL[self.language])
        return f"{cue} {value}" if cue else value


# --- Registers ------------------------------------------------------------------------------

Register = Callable[[Values, Negatives, random.Random], list[Piece]]

_TEXT: dict[str, dict[str, Any]] = {  # str or tuple[str, ...] per key
    "hu": {
        "statement": ("ÁTUTALÁS", "KÁRTYÁS VÁSÁRLÁS", "BESZEDÉS", "JÓVÁÍRÁS"),
        "chat_hi": "Szia",
        "chat_sent": "a futár hívni fog, itt a csomag:",
        "chat_num": "a számom",
        "ticket": "Hibajegy: a rendelés nem érkezett meg.",
        "customer": "Ügyfél:",
        "email_hi": "Tisztelt",
        "email_body": "Csatoltuk a számlát, a fizetést erre a számlára várjuk:",
        "regards": "Üdvözlettel,",
        "form": ("Név", "E-mail", "Telefon", "TAJ szám", "Adóazonosító jel", "Bankszámla"),
        "ship": "Csomagja úton van.",
        "sms": "Fizetés sikeres, összeg",
        "card": "kártya",
    },
    "en": {
        "statement": ("TRANSFER", "CARD PAYMENT", "DIRECT DEBIT", "CREDIT"),
        "chat_hi": "Hi",
        "chat_sent": "the courier will call, here is the parcel:",
        "chat_num": "my number is",
        "ticket": "Ticket: the order has not arrived.",
        "customer": "Customer:",
        "email_hi": "Dear",
        "email_body": "Please find the invoice attached; payment is due to this account:",
        "regards": "Kind regards,",
        "form": ("Name", "Email", "Phone", "NI number", "Passport no.", "Account"),
        "ship": "Your parcel is on its way.",
        "sms": "Payment successful, amount",
        "card": "card",
    },
}


def _id(v: Values) -> Gold:
    return v.taj() if v.language == "hu" else v.national_id()


def bank_statement(v: Values, neg: Negatives, rng: random.Random) -> list[Piece]:
    t = _TEXT[v.language]
    lines: list[Piece] = []
    for i in range(rng.randint(2, 3)):
        lines += [rng.choice(t["statement"]), " ", some_date(rng, v.language), " "]
        if i == 0:
            lines += [v.name(), " ", v.iban(), " "]
        lines += [neg(), " ", amount(rng, v.language), "\n"]
    return lines


def chat(v: Values, neg: Negatives, rng: random.Random) -> list[Piece]:
    t = _TEXT[v.language]
    return [
        f"{t['chat_hi']} ", v.name(v.other), ", ", t["chat_sent"], " ", neg(), ", ",
        t["chat_num"], " ", v.phone(), "\n", neg(rng.choice(["ups", "s10", "parcel"])),
    ]  # fmt: skip


def support_ticket(v: Values, neg: Negatives, rng: random.Random) -> list[Piece]:
    t = _TEXT[v.language]
    return [
        t["ticket"], " ", neg("cee-order"), "\n", t["customer"], " ", v.name(), ", ", v.email(),
        "\n", neg(), "; ", neg(), "\n",
    ]  # fmt: skip


def email(v: Values, neg: Negatives, rng: random.Random) -> list[Piece]:
    t = _TEXT[v.language]
    return [
        f"{t['email_hi']} ", v.name(), "!\n\n", t["email_body"], " ", v.iban(), "\n",
        neg("cee-order"), ", ", neg(), "\n\n", t["regards"], "\n", v.name(v.other), "\n",
        v.phone(),
    ]  # fmt: skip


def form_fields(v: Values, neg: Negatives, rng: random.Random) -> list[Piece]:
    t = _TEXT[v.language]
    labels = t["form"]
    second = v.national_id() if v.language == "hu" else Gold(E.ID_DOCUMENT, v.person.id_document)
    values: list[Piece] = [v.name(), v.email(), v.phone(), _id(v), second, v.iban()]
    out: list[Piece] = []
    for label, value in zip(labels, values, strict=True):
        out += [f"{label}: ", value, "\n"]
    return [*out, neg(), "\n", neg(), "\n"]


def ocr_fragment(v: Values, neg: Negatives, rng: random.Random) -> list[Piece]:
    t = _TEXT[v.language]
    head = _strip(rng.choice(t["statement"])) if v.language == "hu" else t["statement"][0]
    return [
        head, " ", neg(), " ", v.card(), "\n", neg(), "\n", _strip(t["customer"]), " ",
        v.name(), "\n",
    ]  # fmt: skip


def shipping_notice(v: Values, neg: Negatives, rng: random.Random) -> list[Piece]:
    t = _TEXT[v.language]
    return [
        t["ship"], " ", neg(rng.choice(["ups", "s10", "parcel"])), "\n", v.name(), ", ",
        v.address(), "\n", neg(rng.choice(["epoch-ms", "stamp14", "stamp-ref"])), "\n",
    ]  # fmt: skip


def sms(v: Values, neg: Negatives, rng: random.Random) -> list[Piece]:
    t = _TEXT[v.language]
    return [
        t["sms"], " ", amount(rng, v.language), ", ", t["card"], " ", v.card(), ", ", neg(), ".",
    ]  # fmt: skip


REGISTERS: dict[str, Register] = {
    "bank-statement": bank_statement,
    "chat": chat,
    "support-ticket": support_ticket,
    "email": email,
    "form-fields": form_fields,
    "ocr-fragment": ocr_fragment,
    "shipping-notice": shipping_notice,
    "sms": sms,
}


def _strip(text: str) -> str:
    """Hungarian accents stripped, as OCR and ASCII-only systems do."""
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


# --- Documents ------------------------------------------------------------------------------


def document(language: str, index: int, *, seed: int = SEED) -> Document:
    """One document; same arguments, same document."""
    rng = random.Random(f"pii-guard-cee-dev/{seed}/{language}/{index}")
    register = list(REGISTERS)[index % len(REGISTERS)]
    v = Values(language, rng)
    neg = Negatives(language, rng, ocr=register == "ocr-fragment")
    built = Built().extend(REGISTERS[register](v, neg, rng))
    doc_id = f"{language}-cee-dev-{index:04d}"
    record = {
        "id": doc_id,
        "language": language,
        "text": built.text,
        "spans": [
            {"start": s, "end": e, "entity_type": g.entity_type.value} for s, e, g in built.spans
        ],
        "meta": {
            "kind": "synthetic-cee-dev",
            "source": "synthetic",
            "generator": GENERATOR,
            "seed": seed,
            "split": "dev",
            "shape": register,
            "negatives": [kind for kind, _ in neg.made],
            "checksum": [
                {"start": s, "end": e, "valid": g.valid}
                for s, e, g in built.spans
                if g.valid is not None
            ],
            "perturbed": [
                {"start": s, "end": e, "kind": g.perturbed}
                for s, e, g in built.spans
                if g.perturbed
            ],
            "ignore": [],
        },
    }
    return parse_document(record, where=doc_id)


def build(sizes: Mapping[str, int] | None = None) -> dict[str, list[Document]]:
    return {
        lang: [document(lang, i) for i in range((sizes or {}).get(lang, SIZE))]
        for lang in LANGUAGES
    }


def paths() -> list[Path]:
    return [OUT_DIR / f"{lang}-cee-dev.jsonl" for lang in LANGUAGES]


DATASET = Dataset(
    name="cee-dev",
    title="pii-guard synthetic CEE references (dev)",
    homepage="https://github.com/watt-mind/pii-guard/blob/develop/docs/datasets.md",
    revision=GENERATOR,
    license="Apache-2.0",
    license_url="https://www.apache.org/licenses/LICENSE-2.0",
    attribution="pii-guard contributors",
    languages=LANGUAGES,
    source_split="dev",
    split="dev",
    synthetic=True,
    commit_rows=True,
    description="bank lines, chats, tickets, forms, OCR: timestamps, tracking and CEE references",
    sample=dict.fromkeys(LANGUAGES, SIZE),
    seed=SEED,
    external=tuple(str(p) for p in paths()),
    builder=build,
    notes=(
        "Gold from construction: values are inserted into templates, never labelled by a model.",
        "Hard negatives (meta.negatives): epoch-ms and yyyymmddhhmmss references, UPS and UPU "
        "S10 tracking, parcel numbers, CEE order and invoice formats. Tune on this split, never "
        "on cee-pii.",
    ),
)
