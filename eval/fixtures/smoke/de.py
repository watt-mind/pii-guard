"""German smoke fixtures: ``de-smoke.jsonl`` (the German language pack's smoke set, see
``docs/languages.md``). Built by ``eval/fixtures/build_smoke.py``; fictional values only
(ADR 0005)."""

from __future__ import annotations

from collections.abc import Callable

from build_smoke import BANK, DOB, IDD, ORG, PH, A, E, P, iban

from pii_guard.eval import Document, from_markup
from pii_guard.languages.de.checksums import (
    is_valid_steuer_id,
    steuer_id_check_digit,
    sv_number_check_digit,
)


def steuer_id(payload10: str, grouped: bool = True) -> str:
    """A valid Steuer-ID: ten digits with exactly one repeated digit, plus the check digit."""
    digits = payload10 + str(steuer_id_check_digit(payload10))
    if not is_valid_steuer_id(digits):
        raise ValueError("payload has no valid Steuer-ID structure; pick another")
    return f"{digits[:2]} {digits[2:5]} {digits[5:8]} {digits[8:]}" if grouped else digits


def bad_steuer_id(payload10: str) -> str:
    """Looks like a Steuer-ID, fails the check digit."""
    good = steuer_id(payload10, grouped=False)
    return good[:10] + str((int(good[10]) + 1) % 10)


def sv_number(payload11: str, grouped: bool = True) -> str:
    """A valid Sozialversicherungsnummer ``AA DDMMYY L SS C`` from ``AADDMMYYLSS``."""
    value = payload11 + str(sv_number_check_digit(payload11))
    if not grouped:
        return value
    return f"{value[:2]} {value[2:8]} {value[8]} {value[9:11]} {value[11]}"


def de_documents() -> list[Document]:
    iban_de_1 = iban("DE", "100000000123456789")
    iban_de_2 = iban("DE", "370000000987654321", grouped=False)
    st_1, st_2 = steuer_id("4710382946"), steuer_id("5921730481", grouped=False)
    st_3 = steuer_id("3608142973")
    sv_1, sv_2 = sv_number("12150885M01"), sv_number("53270139J48", grouped=False)
    sv_3 = sv_number("28010472B07")
    docs: list[tuple[str, str, dict[str, object]]] = [
        (
            "de-email-0001",
            f"Betreff: Kaution\n\nHallo {P('Erika Beispiel')},\n\ndie Kaution überweisen "
            f"wir auf {BANK(iban_de_1)}. Rückfragen gern unter {PH('+49 30 23125042')} oder an "
            f"{E('erika.beispiel@example.com')}.\n\nViele Grüße\n{P('Jonas Muster')}",
            {"kind": "email"},
        ),
        (
            "de-contract-0002",
            "ARBEITSVERTRAG\n\n"
            f"Zwischen der {ORG('Beispielwerk GmbH')} und {P('Max Platzhalter')}, geboren am "
            f"{DOB('14.03.1988')}, wohnhaft {A('Musterstraße 12, 10115 Berlin')}.\n"
            f"Steuer-ID: {IDD(st_1)}, Sozialversicherungsnummer: {IDD(sv_1)}.\n"
            f"Das Gehalt wird auf das Konto {BANK(iban_de_2)} gezahlt.",
            {"kind": "contract"},
        ),
        (
            "de-letter-0003",
            f"{P('Lena Testmann')}\n{A('Am Beispielweg 3a\n50667 Köln')}\n\n"
            f"Sehr geehrte Frau {P('Testmann')},\n\nbitte rufen Sie uns unter "
            f"{PH('(0221) 4710123')} an. Ihre Rentenversicherungsnummer {IDD(sv_2)} liegt "
            f"uns vor.\n\nMit freundlichen Grüßen\n{ORG('Musterkasse Rheinland')}",
            {"kind": "letter"},
        ),
        (
            "de-chat-0004",
            f"hi, hier ist {P('Tim Fiktiv')}! meine neue nummer ist {PH('0171 3920042')}, "
            f"mail an {E('tim.fiktiv@example.net')} geht auch",
            {"kind": "chat", "tags": ["informal"]},
        ),
        (
            "de-genitive-0005",
            f"{P('Anna Probst')} zieht um. {P('Anna')}s neue Adresse ist "
            f"{A('Lindenallee 7, 04109 Leipzig')}. {P('Hans')}' Fahrrad steht noch im Hof, "
            f"und {P('Probst')}s Briefkasten wird erst im Mai geleert.",
            {"kind": "note", "tags": ["genitive"]},
        ),
        (
            "de-form-0006",
            "Antrag auf Erstattung\n"
            f"Name: {P('Paula Beispielfrau')}\nGeburtsdatum: {DOB('02.07.1979')}\n"
            f"Anschrift: {A('Hauptstraße 101, 80331 München')}\n"
            f"Identifikationsnummer: {IDD(st_2)}\nTelefon: {PH('089 99998123')}",
            {"kind": "form"},
        ),
        (
            "de-invoice-0007",
            f"RECHNUNG Nr. 2026-0815\n{ORG('Kitalit Software AG')}\n"
            f"Kunde: {P('Ole Exemplar')}, {A('Gartenweg 5, 20095 Hamburg')}\n"
            "Betrag: 12500 Euro, fällig am 01.12.2026.\n"
            f"Bitte geben Sie bei der Zahlung Ihre Steuernummer {IDD(st_3)} an.",
            {"kind": "invoice"},
        ),
        (
            "de-insurance-0008",
            f"Versicherte Person: {P('Greta Fiktiva')}, geb. {DOB('28.01.1972')}\n"
            f"Versicherungsnummer {IDD(sv_3)}\n"
            f"Rückruf erbeten an {E('g.fiktiva@example.org')} oder {PH('+49 40 66969123')}.",
            {"kind": "form"},
        ),
        (
            "de-negative-0009",
            "Protokoll der Sitzung vom 01.02.2026\n"
            "Die Studie mit 20000 Teilnehmern lief über 18 Monate. Bestellnummer 4711-0815, "
            f"Vorgang {bad_steuer_id('4710382946')}, Aktenzeichen 12 150885 M 01 0. "
            "Nach Paragraph 3 Absatz 2 wurden 12500 Euro überwiesen.",
            {"kind": "minutes", "tags": ["hard-negative"]},
        ),
        (
            "de-negative-0010",
            "Der Mieter und die Vermieterin vereinbaren eine Staffelmiete. Die Miete steigt "
            "zum 01.01.2027 um 2,5 Prozent. Die Wohnung hat 3 Zimmer auf 78 Quadratmetern.",
            {"kind": "contract", "tags": ["hard-negative"]},
        ),
    ]
    return [from_markup(doc_id, text, language="de", meta=meta) for doc_id, text, meta in docs]


OUTPUTS: dict[str, Callable[[], list[Document]]] = {
    "de-smoke.jsonl": de_documents,
}
