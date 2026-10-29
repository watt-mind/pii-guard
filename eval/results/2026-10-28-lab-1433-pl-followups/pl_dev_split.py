"""Synthetic Polish dev split for LAB-1433: 80 documents, seed 1433. Every value is made up.

Each document is one labelled value (a PESEL, a PESEL with a bad check digit, a phone number,
a driving-licence number in two layouts) and a name, followed by a hard negative: a number
after an order, invoice, shipment, booking or amount label. ``meta.lane`` is the template.

    uv run --no-sync python eval/results/2026-10-28-lab-1433-pl-followups/pl_dev_split.py OUT
"""

from __future__ import annotations

import json
import random
import sys

from pii_guard.languages.pl.checksums import pesel_check_digit

rng = random.Random(1433)  # noqa: S311 - reproducible fixtures, not secrets
FIRST = ["Anna", "Piotr", "Marta", "Jan", "Ewa", "Tomasz", "Zofia", "Adam"]
LAST = ["Przykładowa", "Testowy", "Zmyślona", "Fikcyjny", "Wymyślona", "Próbny"]
NEGATIVES = [
    "Numer zamówienia: {n9}.",
    "Zamówienie nr {n9} zostało wysłane.",
    "Faktura nr {n10} do zapłaty.",
    "Numer przesyłki {n12}, śledź paczkę online.",
    "Paragon {n9} z dnia 3 marca.",
    "numer zlecenia {n9}",
    "Nr rezerwacji: {n9}",
    "Zgłoszenie {n9} zostało zamknięte.",
    "numer faktury {n9}",
    "Przesyłka {n9} jest w drodze.",
    "nr transakcji {n12}",
    "Paczka nr {n9} czeka w punkcie odbioru.",
    "Kwota: {n9} zł.",
]
POSITIVES = [
    ("Pan {name}, PESEL {v}, prosi o kontakt.", "pesel", "ID_DOCUMENT"),
    ("Proszę dzwonić: {v}. {name}", "phone", "PHONE"),
    ("Kontakt z {name} pod numerem {v}.", "phone", "PHONE"),
    ("{name}, prawo jazdy nr {v}.", "lic", "ID_DOCUMENT"),
    ("Numer prawa jazdy: {v}. Kierowca: {name}.", "lic2", "ID_DOCUMENT"),
    ("{name}, PESEL: {v} (błąd w numerze?)", "badpesel", "ID_DOCUMENT"),
]


def digits(n: int) -> str:
    return "".join(str(rng.randrange(10)) for _ in range(n))


def pesel() -> str:
    born = f"{rng.randrange(50, 99):02d}{rng.randrange(1, 13):02d}{rng.randrange(1, 28):02d}"
    payload = born + digits(4)
    return payload + str(pesel_check_digit(payload))


def bad_check_digit(value: str) -> str:
    return value[:-1] + str((int(value[-1]) + 1) % 10)


def value_for(kind: str) -> str:
    if kind == "pesel":
        return pesel()
    if kind == "badpesel":
        return bad_check_digit(pesel())
    if kind == "phone":
        return f"{rng.choice('5678')}{digits(2)} {digits(3)} {digits(3)}"
    if kind == "lic":
        return f"{digits(5)}/{digits(2)}/{digits(4)}"
    return f"{digits(4)}/{digits(2)}/{digits(2)}"  # "5936/42/00"


def main(out: str) -> None:
    docs = []
    for i in range(80):
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        template, kind, entity_type = rng.choice(POSITIVES)
        value = value_for(kind)
        negative = rng.choice(NEGATIVES).format(n9=digits(9), n10=digits(10), n12=digits(12))
        text = template.format(name=name, v=value) + " " + negative
        spans = []
        for val, typ in ((name, "PERSON"), (value, entity_type)):
            start = text.index(val)
            spans.append({"start": start, "end": start + len(val), "entity_type": typ, "text": val})
        docs.append(
            {
                "id": f"pl-dev-{i:04d}",
                "language": "pl",
                "text": text,
                "spans": spans,
                "meta": {"lane": kind},
            }
        )
    with open(out, "w", encoding="utf-8") as f:
        for doc in docs:
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
