"""Hard negatives for NER v2: numbers that are *not* personal data, in hu / en / de (LAB-1150).

The Ai4Privacy OpenPII rows teach the identifier labels, but nearly every number in them is
personal data, so a student trained on them masks order, invoice, tracking and case numbers,
article numbers and amounts too (measured on the smoke sets: 6-11 % over-masking). This
script writes short, seeded, template-based documents full of such numbers, with **no** gold
spans, to be mixed into training. Nothing here is personal data; the cue words are generic
(the kinds of reference numbers any business text carries), and the numbers are random.

::

    uv run --no-sync python training/ner/negatives.py --n 2000 --seed 1150 \\
        --out eval/generated/negatives
"""

# Seeded synthetic data: the standard PRNG is the point.
# ruff: noqa: S311

from __future__ import annotations

import argparse
import random
import string
import sys
from collections.abc import Sequence
from pathlib import Path

from pii_guard.eval.fixtures import Document, write_fixtures

#: Cue phrases for reference numbers that identify a thing or a transaction, not a person.
CUES: dict[str, tuple[str, ...]] = {
    "hu": (
        "Rendelésszám",
        "Megrendelés száma",
        "Számla sorszáma",
        "Bizonylatszám",
        "Cikkszám",
        "Termékkód",
        "Gyári szám",
        "Csomagkövetési szám",
        "Ügyiratszám",
        "Iktatószám",
        "Hivatkozási szám",
        "Szerződésszám",
        "Jegyszám",
        "Foglalási kód",
        "Hibajegy",
        "Tételszám",
        "Sorozatszám",
        "Raktári kód",
        "Járatszám",
        "Verzió",
    ),
    "en": (
        "Order number",
        "Order no.",
        "Invoice no.",
        "Invoice number",
        "SKU",
        "Item code",
        "Serial number",
        "Tracking number",
        "Case reference",
        "Ticket",
        "Booking reference",
        "Contract no.",
        "Batch",
        "Part number",
        "Model",
        "Flight",
        "Build",
        "Release",
        "Reference",
        "PO number",
    ),
    "de": (
        "Bestellnummer",
        "Auftragsnummer",
        "Rechnungsnummer",
        "Artikelnummer",
        "Seriennummer",
        "Sendungsnummer",
        "Aktenzeichen",
        "Vorgang",
        "Ticketnummer",
        "Buchungsnummer",
        "Vertragsnummer",
        "Chargennummer",
        "Teilenummer",
        "Modell",
        "Flugnummer",
        "Version",
        "Belegnummer",
        "Kundenauftrag",
        "Lieferschein",
        "Referenz",
    ),
}
TEMPLATES: dict[str, tuple[str, ...]] = {
    "hu": (
        "{cue}: {num}. Kérjük, hivatkozzon rá a további levelezésben.",
        "A {cue2} {num}, a szállítás várhatóan {days} munkanap.",
        "{cue}: {num}, összesen {amount} Ft, fizetési határidő {days} nap.",
        "Köszönjük a rendelést! {cue}: {num}. {cue_b}: {num_b}.",
        "A tétel ára {amount} Ft, a készleten {qty} darab van ({cue}: {num}).",
        "Az éves keret {amount} Ft, ebből eddig {amount_b} Ft fogyott el.",
    ),
    "en": (
        "{cue}: {num}. Please quote it in any further correspondence.",
        "Your {cue2} is {num}; delivery takes about {days} working days.",
        "{cue} {num}, total {amount} EUR, due in {days} days.",
        "Thanks for your order! {cue}: {num}. {cue_b}: {num_b}.",
        "The unit price is {amount} USD and we have {qty} in stock ({cue} {num}).",
        "The annual budget is {amount} GBP, of which {amount_b} GBP is spent.",
    ),
    "de": (
        "{cue}: {num}. Bitte geben Sie diese bei Rückfragen an.",
        "Ihre {cue2} lautet {num}; die Lieferung dauert etwa {days} Werktage.",
        "{cue} {num}, Gesamtbetrag {amount} EUR, zahlbar in {days} Tagen.",
        "Vielen Dank für Ihre Bestellung! {cue}: {num}. {cue_b}: {num_b}.",
        "Der Stückpreis beträgt {amount} EUR, auf Lager sind {qty} Stück ({cue} {num}).",
        "Das Jahresbudget beträgt {amount} EUR, davon sind {amount_b} EUR verbraucht.",
    ),
}


def number(rng: random.Random) -> str:
    """A random reference-number shape: digits, groups, a year prefix, letters + digits."""
    digits = string.digits
    kind = rng.randrange(7)
    if kind == 0:
        return "".join(rng.choice(digits) for _ in range(rng.randint(6, 12)))
    if kind == 1:
        return f"{rng.randint(2019, 2027)}-{rng.randint(1, 999999):06d}"
    if kind == 2:
        groups = [rng.randint(3, 4) for _ in range(rng.randint(2, 4))]
        sep = rng.choice([" ", "-", "/", "."])
        return sep.join("".join(rng.choice(digits) for _ in range(g)) for g in groups)
    if kind == 3:
        prefix = "".join(rng.choice(string.ascii_uppercase) for _ in range(rng.randint(1, 3)))
        return prefix + "".join(rng.choice(digits) for _ in range(rng.randint(5, 14)))
    if kind == 4:
        year = rng.randint(2019, 2026)
        return f"{rng.randint(1, 99)}.{rng.choice('PGK')}.{rng.randint(100, 99999)}/{year}"
    if kind == 5:
        alphabet = string.ascii_uppercase + digits
        return "".join(rng.choice(alphabet) for _ in range(rng.randint(8, 18)))
    return f"{rng.randint(1, 9)}.{rng.randint(0, 20)}.{rng.randint(0, 99)}"


def amount(rng: random.Random) -> str:
    n = rng.randint(100, 9_999_999_999)
    sep = rng.choice([" ", ".", ","])
    return f"{n:,}".replace(",", sep)


def document(language: str, seed: int, index: int) -> Document:
    rng = random.Random(f"pii-guard-negatives/{seed}/{language}/{index}")
    sentences = []
    for _ in range(rng.randint(1, 3)):
        cue, cue_b = rng.sample(CUES[language], 2)
        sentences.append(
            rng.choice(TEMPLATES[language]).format(
                cue=cue,
                cue2=cue[0].lower() + cue[1:] if language != "de" else cue,
                cue_b=cue_b,
                num=number(rng),
                num_b=number(rng),
                amount=amount(rng),
                amount_b=amount(rng),
                days=rng.randint(1, 60),
                qty=rng.randint(1, 5000),
            )
        )
    meta = {"kind": "negative-numbers", "split": "train", "source": "synthetic", "seed": seed}
    doc_id = f"{language}-negatives-s{seed}-{index:05d}"
    return Document(doc_id, language, " ".join(sentences), (), meta)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--n", type=int, default=2000, help="documents per language")
    parser.add_argument("--seed", type=int, default=1150)
    parser.add_argument("--out", type=Path, default=Path("eval/generated/negatives"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for language in CUES:
        docs = [document(language, args.seed, i) for i in range(args.n)]
        path = args.out / f"{language}-negatives-train.jsonl"
        write_fixtures(path, docs)
        print(f"negatives: {len(docs)} {language} documents -> {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
