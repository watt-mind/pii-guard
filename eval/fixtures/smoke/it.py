"""Italian smoke fixtures: ``it-smoke.jsonl`` (the Italian pack's, LAB-1776). Built by
``eval/fixtures/build_smoke.py``; fictional values only (ADR 0005). Ids start at
0101: the EU-wave gates ``eu/it-smoke.jsonl`` (also smoke fixtures of the pack) use 0001-0005.

Italy reserves no phone range for fiction, so the numbers follow the Polish rule of ADR 0005:
a real mobile prefix or area code with an ascending digit run (``347 123 4567``) or a
subscriber number in the block ``555 01xx`` (``02 555 0123``). Codici fiscali are computed
from made-up surnames, names and dates; the municipality codes are public place codes."""

from __future__ import annotations

from collections.abc import Callable

from build_smoke import BANK, DOB, IDD, ORG, PH, A, E, P, iban

from pii_guard.eval import Document, from_markup
from pii_guard.languages.it.checksums import (
    OMOCODIA,
    codice_fiscale_check_char,
    is_valid_codice_fiscale,
    is_valid_partita_iva,
    partita_iva_check_digit,
)


def cf(payload15: str, omocodia: int = 0) -> str:
    """A valid codice fiscale, made up; ``omocodia``: digits replaced, from the right."""
    chars = list(payload15)
    for i in (14, 13, 12, 10, 9, 7, 6)[:omocodia]:
        chars[i] = OMOCODIA[int(chars[i])]
    payload = "".join(chars)
    value = payload + codice_fiscale_check_char(payload)
    if not is_valid_codice_fiscale(value):
        raise ValueError("payload is not a possible codice fiscale; pick another")
    return value


def bad_cf(payload15: str) -> str:
    """Looks like a codice fiscale, fails the check letter."""
    good = cf(payload15)
    return good[:15] + chr(65 + (ord(good[15]) - 64) % 26)


def partita_iva(payload10: str) -> str:
    """A valid partita IVA: a made-up company number, an office code and the Luhn digit."""
    value = payload10 + str(partita_iva_check_digit(payload10))
    if not is_valid_partita_iva(value):
        raise ValueError("payload has no valid office code; pick another")
    return value


def it_documents() -> list[Document]:
    iban_it_1 = iban("IT", "X0000099999000000123456")
    iban_it_2 = iban("IT", "Z0000088888000000654321", grouped=False)
    cf_1 = cf("PRVGLI85T50F205")  # Giulia Prova, 10 December 1985, Milano
    cf_2 = cf("SMPMRC79A12H501")  # Marco Esempio, 12 January 1979, Roma
    cf_3 = cf("FTTLRA92E63A944", omocodia=2)  # Laura Fittizi, 23 May 1992, Bologna
    cf_4 = cf("NVNPLA68R07L219")  # Paolo Inventato, 7 October 1968, Torino
    cf_5 = bad_cf("TSTNNA90M41D612")  # a mistyped one: still a person's, masked after its cue
    piva_1, piva_2 = partita_iva("9990001037"), partita_iva("9990002015")
    docs: list[tuple[str, str, dict[str, object]]] = [
        (
            "it-email-0101",
            f"Oggetto: Deposito cauzionale\n\nGentile sig.ra {P('Giulia Prova')},\n\nla "
            f"cauzione verrà restituita sul conto {BANK(iban_it_1)}. Per domande può chiamare "
            f"il {PH('347 123 4567')} o scrivere a {E('marco.esempio@example.com')}.\n\n"
            f"Cordiali saluti,\n{P('Marco Esempio')}",
            {"kind": "email"},
        ),
        (
            "it-contract-0102",
            "CONTRATTO DI LOCAZIONE AD USO ABITATIVO\n\n"
            f"Il Locatore {P('Marco Esempio')}, nato a Roma il {DOB('12/01/1979')}, codice "
            f"fiscale {IDD(cf_2)}, residente in {A('Via dei Mille 27, 40121 Bologna (BO)')}, "
            f"e il Conduttore {P('Paolo Inventato')}, carta d'identità {IDD('CA00123ZZ')}, "
            f"C.F. {IDD(cf_4)}, convengono quanto segue. Il canone di 850,00 euro mensili "
            f"sarà versato sul conto {BANK(iban_it_2)}.",
            {"kind": "contract"},
        ),
        (
            "it-invoice-0103",
            "FATTURA n. FT/2026/0815 del 28/10/2026\n"
            f"Cedente: {ORG('Officine Fittizie S.r.l.')}, P.IVA {IDD(piva_1)}, "
            f"{A('Corso Esempio 8, 20121 Milano')}\n"
            f"Cessionario: {P('Laura Fittizi')}, C.F. {IDD(cf_3)}, "
            f"{A('Piazza San Prova 3, 40126 Bologna')}\n"
            "Imponibile 1.025,00 EUR, IVA 22% 225,50 EUR, totale 1.250,50 EUR.",
            {"kind": "invoice", "tags": ["omocodia"]},
        ),
        (
            "it-letter-0104",
            f"{P('Giulia Prova')}\n{A('Viale Immaginario 14/B\n00184 Roma')}\n\n"
            f"Gentile signora,\n\nla informiamo che il passaporto n. {IDD('YA1234567')} è pronto "
            f"per il ritiro. Per un appuntamento chiami lo {PH('06 555 0134')}.\n\n"
            f"Distinti saluti\n{ORG('Questura di Roma')}",
            {"kind": "letter"},
        ),
        (
            "it-chat-0105",
            f"ciao, sono {P('Chiara')}! il mio nuovo cell. è {PH('3332345678')}, "
            f"oppure scrivimi su {E('chiara.prova@example.net')}",
            {"kind": "chat", "tags": ["informal"]},
        ),
        (
            "it-form-0106",
            "Modulo di iscrizione\n"
            f"Cognome e nome: {P('Inventato Paolo')}\nData di nascita: {DOB('07/10/1968')}\n"
            f"Codice fiscale: {IDD(cf_4)}\nIndirizzo: {A('Via Roma, 12 - 10121 Torino (TO)')}\n"
            f"Patente n. {IDD('U13457826Z')}\nTelefono: {PH('(011) 555 0147')}",
            {"kind": "form"},
        ),
        (
            "it-bank-0107",
            f"Estratto conto\nIntestatario: {P('Laura Fittizi')}, codice fiscale {IDD(cf_3)}\n"
            f"Carta di credito n. {BANK('4111 1111 1111 1111')}, IBAN {BANK(iban_it_1)}.\n"
            "Saldo finale: 3.456,78 EUR al 31/10/2026.",
            {"kind": "statement"},
        ),
        (
            "it-booking-0108",
            f"Prenotazione n. 2026-004512 confermata per {P('Marco Esempio')} "
            f"(C.F. {IDD(cf_2)}). Visita il 14/11/2026 alle 09.30 presso l'ambulatorio di "
            f"{A('Via XX Settembre 5, 16121 Genova')}. Per disdire: {PH('010 555 0112')}.",
            {"kind": "booking"},
        ),
        (
            "it-hr-0109",
            f"Assunzione di {P('Anna Testa')}, nata il {DOB('1 agosto 1990')}, codice fiscale "
            f"{IDD(cf_5)} (da verificare), domiciliata in {A('Largo dei Gelsomini 2')}. "
            f"Datore di lavoro: {ORG('Studio Esempio')}, partita IVA {IDD(piva_2)}. "
            f"Contatti: {E('anna.testa@example.org')}, {PH('+39 320 345 6789')}.",
            {"kind": "hr"},
        ),
        (
            "it-email-0110",
            f"Buongiorno, il fornitore {ORG('Fittizia Forniture S.p.A.')} (n. IVA comunitario "
            f"{IDD('IT' + piva_1)}) ha inviato il contratto firmato da {P('Giulia Prova')}, "
            f"codice fiscale {IDD(cf_1)}. Lo trovate in allegato.",
            {"kind": "email"},
        ),
        (
            "it-negative-0111",
            "Verbale della riunione del 05.11.2026, dalle 08.30 alle 12.30\n"
            "Alla fiera hanno partecipato 20000 persone. Ordine n. 4500123456 e protocollo "
            "n. 2026/0815; codice articolo ZZ12345AB, lotto 99012345678. "
            f"Rif. pratica {bad_cf('PRVGLI85T50F205')[:15]}. Il preventivo di 1.250.000,00 "
            "EUR copre il periodo 2026-2030; CAP 20121.",
            {"kind": "minutes", "tags": ["hard-negative"]},
        ),
        (
            "it-negative-0112",
            "Il Locatore e il Conduttore concordano un canone di 850 euro al mese. "
            "L'appartamento ha 3 camere ed è al 4 piano; ci siamo sentiti via Zoom 3 volte. "
            "Dal 01/01/2027 il canone aumenta del 2,5 per cento.",
            {"kind": "contract", "tags": ["hard-negative"]},
        ),
    ]
    return [from_markup(doc_id, text, language="it", meta=meta) for doc_id, text, meta in docs]


OUTPUTS: dict[str, Callable[[], list[Document]]] = {
    "it-smoke.jsonl": it_documents,
}
