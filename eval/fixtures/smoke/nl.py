"""Dutch smoke fixtures: ``nl-smoke.jsonl`` (the Dutch pack's, LAB-1777). Built by
``eval/fixtures/build_smoke.py``; fictional values only (ADR 0005). Ids start at
0101: the EU-wave gates ``eu/nl-smoke.jsonl`` and ``eu/nl-inflection.jsonl`` (also smoke
fixtures of the pack) use 0001-0005.

The Netherlands reserves no phone range for fiction (ADR 0005 has no row for it), so the
numbers follow the Polish and Hungarian rule: a real mobile prefix or area code with an
ascending digit run (``06-12345678``) or a subscriber number in the block ``555 01xx``
(``020 555 0123``). BSNs are computed from made-up payloads with the elfproef; IBANs carry
the made-up bank codes ``XXXX`` and ``ZZZZ``."""

from __future__ import annotations

from collections.abc import Callable

from build_smoke import BANK, DOB, IDD, ORG, PH, A, E, P, iban

from pii_guard.eval import Document, from_markup
from pii_guard.languages.nl.checksums import bsn_check_digit, is_valid_bsn


def bsn(payload8: str, layout: str = "compact") -> str:
    """A valid BSN from a made-up payload, ``compact``, ``dotted`` (4-2-3) or ``spaced`` (3-3-3)."""
    check = bsn_check_digit(payload8)
    if check is None:
        raise ValueError("payload has no BSN check digit; pick another")
    value = payload8 + str(check)
    if not is_valid_bsn(value):
        raise ValueError("payload is no possible BSN; pick another")
    if layout == "dotted":
        return f"{value[:4]}.{value[4:6]}.{value[6:]}"
    if layout == "spaced":
        return f"{value[:3]} {value[3:6]} {value[6:]}"
    return value


def bad_bsn(payload8: str) -> str:
    """Looks like a BSN, fails the elfproef."""
    good = bsn(payload8)
    return good[:8] + str((int(good[8]) + 1) % 10)


def nl_documents() -> list[Document]:
    iban_1 = iban("NL", "XXXX0000123456")
    iban_2 = iban("NL", "ZZZZ0987654321", grouped=False)
    bsn_1 = bsn("12345678")  # 123456782
    bsn_2 = bsn("23456789", "dotted")
    bsn_3 = bsn("34567891", "spaced")
    bsn_4 = bsn("45678912")
    bsn_5 = bad_bsn("56789123")  # a mistyped one: still a person's, masked after its cue
    docs: list[tuple[str, str, dict[str, object]]] = [
        (
            "nl-email-0101",
            f"Onderwerp: Borg terugbetaling\n\nBeste mevrouw {P('Lotte de Voorbeeld')},\n\n"
            f"de borg wordt teruggestort op rekening {BANK(iban_1)}. Bij vragen kunt u mij "
            f"bellen op {PH('06-12345678')} of mailen naar {E('daan.fictief@example.nl')}.\n\n"
            f"Met vriendelijke groet,\n{P('Daan Fictief')}",
            {"kind": "email"},
        ),
        (
            "nl-contract-0102",
            "HUUROVEREENKOMST WOONRUIMTE\n\n"
            f"Verhuurder: {ORG('Woonstichting Voorbeeld B.V.')}, KvK 12345678, gevestigd "
            f"{A('Stationsplein 1, 3511 ED Utrecht')}.\n"
            f"Huurder: {P('Pieter van Proef')}, geboren op {DOB('11-10-1985')}, BSN {IDD(bsn_1)}, "
            f"thans wonende {A('Van Goghstraat 7-II, 1071 AB Amsterdam')}.\n"
            f"De huur van 1.250,00 EUR per maand wordt voldaan op {BANK(iban_2)}.",
            {"kind": "contract"},
        ),
        (
            "nl-invoice-0103",
            "FACTUUR\nFactuurnummer: 2026-00815, factuurdatum 28-10-2026\n"
            f"Leverancier: {ORG('Fictief Installatietechniek B.V.')}, KvK 87654321, "
            "btw-nummer NL001234567B01\n"
            f"Klant: {P('Anna Verzonnen')}, {A('Dorpsstraat 12a, 9711 AB Groningen')}\n"
            "Klantnummer 100234, totaal 1.450,00 EUR incl. 21% btw.",
            {"kind": "invoice"},
        ),
        (
            "nl-letter-0104",
            f"{P('Joris Testkamp')}\n{A('Burgemeester de Withstraat 3\n5211 AB Den Bosch')}\n\n"
            f"Geachte heer {P('Testkamp')},\n\nuw paspoort met documentnummer "
            f"{IDD('NX12345K7')} ligt klaar. Maak een afspraak via {PH('073 555 0134')}.\n\n"
            f"Met vriendelijke groet,\n{ORG('Gemeente Voorbeeldstad')}",
            {"kind": "letter"},
        ),
        (
            "nl-chat-0105",
            f"hoi! met {P('Fleur')} hier, mijn nieuwe nummer is {PH('0634567890')}, "
            f"of app me op {E('fleur.proef@example.org')}",
            {"kind": "chat", "tags": ["informal"]},
        ),
        (
            "nl-form-0106",
            "Aanmeldformulier\n"
            f"Naam: {P('Sanne Voorbeeld')}\nGeboortedatum: {DOB('03-03-1990')}\n"
            f"BSN: {IDD(bsn_2)}\nAdres: {A('Kerkweg 5, 2611 AB Delft')}\n"
            f"Rijbewijsnummer: {IDD('5123456789')}\nTelefoon: {PH('(010) 555 0147')}",
            {"kind": "form"},
        ),
        (
            "nl-bank-0107",
            f"Rekeningoverzicht\nRekeninghouder: {P('Anna Verzonnen')}\n"
            f"Creditcard {BANK('4111 1111 1111 1111')}, rekening {BANK(iban_1)}.\n"
            "Eindsaldo 3.456,78 EUR per 31-10-2026.",
            {"kind": "statement"},
        ),
        (
            "nl-medical-0108",
            f"Verwijzing voor {P('Pieter')}s knie: patiënt {P('Pieter van Proef')} "
            f"({IDD(bsn_4)}), {A('Lindelaan 42, 3521 AB Utrecht')}. "
            f"Afspraak op 14-11-2026 om 09.30 uur; afzeggen via {PH('030-5550112')}.",
            {"kind": "medical", "tags": ["genitive-s", "unlabelled-bsn"]},
        ),
        (
            "nl-hr-0109",
            f"Indiensttreding van {P('Femke Fictief')}, geboren {DOB('1 augustus 1992')}, "
            f"sofinummer {IDD(bsn_3)}, burgerservicenummer volgens loonstrook {IDD(bsn_5)} "
            f"(nog controleren). Woonadres: {A('Prins Hendrikkade 21-H, 1012 TM Amsterdam')}. "
            f"Contact: {E('femke.fictief@example.com')}, {PH('+31 6 23456789')}.",
            {"kind": "hr"},
        ),
        (
            "nl-email-0110",
            f"Goedemiddag, {P('Anna')}'s aanvraag is binnen. Zij woont op "
            f"{A('Oude Gracht 3, 3511 AP Utrecht')} en is bereikbaar op {PH('020 555 0123')}. "
            f"Haar identiteitskaart {IDD('IX98765K4')} is nog geldig.",
            {"kind": "email", "tags": ["genitive-s"]},
        ),
        (
            "nl-negative-0111",
            "Notulen van de vergadering van 05-11-2026, 08.30-12.30 uur\n"
            f"Op de beurs kwamen 20000 bezoekers. Bestelnummer {bsn('87654321')} en "
            f"factuurnummer 2026/0815; betalingskenmerk 7000123456789012, KvK 12345678. "
            "De begroting van 1.250.000,00 EUR loopt van 2026-2030; het bestand is 1000 KB groot "
            "en de 2026 EU-richtlijn geldt.",
            {"kind": "minutes", "tags": ["hard-negative"]},
        ),
        (
            "nl-negative-0112",
            "De verhuurder en de huurder spreken een huur van 850 euro per maand af. "
            "De woning heeft 3 kamers op de 4e verdieping; we liepen de weg 3 keer op en neer. "
            "Vanaf 01-01-2027 stijgt de huur met 2,5 procent.",
            {"kind": "contract", "tags": ["hard-negative"]},
        ),
    ]
    return [from_markup(doc_id, text, language="nl", meta=meta) for doc_id, text, meta in docs]


OUTPUTS: dict[str, Callable[[], list[Document]]] = {
    "nl-smoke.jsonl": nl_documents,
}
