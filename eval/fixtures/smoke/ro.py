"""Romanian smoke fixtures: ``ro-smoke.jsonl`` (the Romanian pack's, LAB-1778). Built by
``eval/fixtures/build_smoke.py``; fictional values only (ADR 0005). Ids start at 0101: the
EU-wave gates ``eu/ro-smoke.jsonl`` and ``eu/ro-inflection.jsonl`` (also smoke fixtures of the
pack) use 0001-0005.

Romania reserves no phone range for fiction, so the numbers follow the Polish rule of ADR 0005:
a real mobile prefix or area code with an ascending digit run (``0745 123 456``) or a
subscriber number in the block ``555 01xx`` (``021 555 0123``, ``0264 555 012``). CNPs are
computed from made-up dates and serial numbers (real county codes), CIFs from made-up company
numbers; the IBANs use the fictional bank code ``ZZZZ``.

Stem-changed forms of names (``Mariei``, ``Ioanei``) are labelled as whole words; an ending that
leaves the name intact stays outside the label (``{{PERSON|Popescu}}lui``)."""

from __future__ import annotations

from collections.abc import Callable

from build_smoke import BANK, DOB, IDD, ORG, PH, A, E, P, iban

from pii_guard.eval import Document, from_markup, label
from pii_guard.languages.ro.checksums import (
    cif_check_digit,
    cnp_check_digit,
    is_valid_cif,
    is_valid_cnp,
)


def cnp(payload12: str) -> str:
    """A valid CNP from a made-up ``SYYMMDDJJNNN``."""
    value = payload12 + str(cnp_check_digit(payload12))
    if not is_valid_cnp(value):
        raise ValueError("payload has no possible date or county; pick another")
    return value


def bad_cnp(payload12: str) -> str:
    """Looks like a CNP, fails the check digit."""
    good = cnp(payload12)
    return good[:12] + str((int(good[12]) + 1) % 10)


def cif(payload: str) -> str:
    """A valid CIF/CUI: a made-up company number and its check digit."""
    value = payload + str(cif_check_digit(payload))
    if not is_valid_cif(value):
        raise ValueError("not a possible CIF; pick another")
    return value


def ro_documents() -> list[Document]:
    iban_1 = iban("RO", "ZZZZ0000000012345678")
    iban_2 = iban("RO", "ZZZZ0000000087654321", grouped=False)
    cnp_1 = cnp("285031012345")  # Maria Popescu, 10 March 1985, Bucharest sector 1 (county 40)
    cnp_2 = cnp("179011212001")  # Andrei Exemplu, 12 January 1979, Cluj (12)
    cnp_3 = cnp("288070535006")  # Elena Exemplu, 5 July 1988, Timiș (35)
    cnp_4 = cnp("192102235003")  # Mihai Testescu, 22 October 1992, Timiș (35)
    cnp_6 = cnp("295121512007")  # Ioana Probă, 15 December 1995, Cluj (12)
    cnp_5 = bad_cnp("290070722004")  # a mistyped one: still a person's, masked after its cue
    cif_1, cif_2 = cif("1234567"), cif("9900012")
    docs: list[tuple[str, str, dict[str, object]]] = [
        (
            "ro-email-0101",
            f"Subiect: Garanția chiriei\n\nStimată doamnă {P('Maria Popescu')},\n\ngaranția "
            f"vă va fi restituită în contul {BANK(iban_1)}. Pentru întrebări ne puteți suna la "
            f"{PH('0745 123 456')} sau scrie la {E('andrei.exemplu@example.com')}.\n\n"
            f"Cu stimă,\n{P('Andrei Exemplu')}",
            {"kind": "email"},
        ),
        (
            "ro-contract-0102",
            "CONTRACT DE ÎNCHIRIERE\n\n"
            f"Locator: {P('Andrei Exemplu')}, născut la {DOB('12.01.1979')}, CNP {IDD(cnp_2)}, "
            f"domiciliat în {A('Strada Teilor nr. 15, ap. 7, 400123 Cluj-Napoca')}.\n"
            f"Chiriaș: {P('Maria Popescu')}, CI seria {IDD('RX nr. 123456')}, CNP "
            f"{IDD(cnp_1)}.\nChiria de 2.100,00 lei se plătește lunar în contul "
            f"{BANK(iban_2)}. Cheile au fost predate {P('Mariei Popescu')} la semnare.",
            {"kind": "contract", "tags": ["dat"]},
        ),
        (
            "ro-invoice-0103",
            "FACTURA nr. EXM-2026-0815 din 28.10.2026\n"
            f"Furnizor: {ORG('Exemplu Software SRL')}, CUI {IDD('RO' + cif_1)}, "
            f"{A('Bd. Unirii nr. 40, bl. A3, sc. 2, ap. 12, sector 3, 030167 București')}\n"
            f"Client: {P('Ioana Probă')}, CNP {IDD(cnp_6)}\n"
            "Total de plată: 1.250,50 RON, din care TVA 19% 199,66 RON.",
            {"kind": "invoice"},
        ),
        (
            "ro-letter-0104",
            f"{P('Popescu Maria')}\n{A('Calea Victoriei nr. 120, et. 3, ap. 9\n010093 București')}"
            f"\n\nStimată doamnă,\n\nvă informăm că pașaportul nr. {IDD('051234567')} poate fi "
            f"ridicat. Pentru programare sunați la {PH('021 555 0123')}. Documentul se "
            f"eliberează doar doamnei {P('Popescu Mariei')}, personal.\n\n"
            f"Cu stimă,\n{ORG('Serviciul Pașapoarte București')}",
            {"kind": "letter", "tags": ["dat", "surname-first"]},
        ),
        (
            "ro-chat-0105",
            f"salut, sunt {P('Ioana')}! noul meu nr. de mobil e {PH('0756123456')}, "
            f"sau scrie-mi pe {E('ioana.proba@example.net')}. i-ai dat cheia {P('Ioanei')}?",
            {"kind": "chat", "tags": ["informal", "dat"]},
        ),
        (
            "ro-form-0106",
            "Formular de înscriere\n"
            f"Nume și prenume: {P('Testescu Mihai')}\nData nașterii: {DOB('22.10.1992')}\n"
            f"CNP: {IDD(cnp_4)}\nDomiciliu: "
            f"{A('Str. Mihai Eminescu nr. 7, 300011 Timișoara, jud. Timiș')}\n"
            f"Permis de conducere nr. {IDD('TM123456AB')}\nTelefon: {PH('0256 555 014')}",
            {"kind": "form"},
        ),
        (
            "ro-bank-0107",
            f"Extras de cont\nTitular: {P('Elena Exemplu')}, CNP {IDD(cnp_3)}\n"
            f"Card de debit nr. {label('PAYMENT_CARD', '4111 1111 1111 1111')}, "
            f"IBAN {BANK(iban_1)}.\n"
            "Sold final: 3.456,78 RON la 31.10.2026.",
            {"kind": "statement"},
        ),
        (
            "ro-booking-0108",
            f"Rezervarea nr. 2026-004512 a fost confirmată pentru {P('Mihai Testescu')} "
            f"(CNP {IDD(cnp_4)}). Consultația are loc pe 14.11.2026 la ora 09:30, la "
            f"{A('Șoseaua Kiseleff nr. 5, sector 1, 011341 București')}. Pentru anulare: "
            f"{PH('(021) 555 0112')}.",
            {"kind": "booking"},
        ),
        (
            "ro-hr-0109",
            f"Angajarea doamnei {P('Cristina Probă')}, născută la {DOB('7 iulie 1990')}, CNP "
            f"{IDD(cnp_5)} (de verificat), domiciliată în {A('Aleea Teilor nr. 2')}. Angajator: "
            f"{ORG('Exemplu Consult SRL')}, CIF {IDD(cif_2)}. Contract semnat de "
            f"{P('Cristinei Probă')} pe 30.10.2026. Contact: {E('cristina.proba@example.org')}, "
            f"{PH('+40 722 345 678')}.",
            {"kind": "hr", "tags": ["dat"]},
        ),
        (
            "ro-court-0110",
            f"Avocatul lui {P('Andrei Exemplu')} a depus cererea. Semnătura "
            f"{P('Exemplu')}lui lipsește, iar actul de identitate al {P('Mariei')} a fost "
            f"prezentat în copie (seria {IDD('CJ 234567')}).",
            {"kind": "court", "tags": ["gen", "standalone-surname"]},
        ),
        (
            "ro-negative-0111",
            "Proces-verbal al ședinței din 05.11.2026, orele 08:30-12:30\n"
            "La târg au participat 200000 de persoane. Comanda nr. 4500123456 și dosarul "
            "nr. 2026/0815; cod produs ZZ12345AB, EAN 5940000123459, lot 99012345678. "
            f"Numărul comenzii {bad_cnp('285031012345')[:12]}. Bugetul de 1.250.000,00 lei "
            "acoperă perioada 2026-2030; cod poștal 400123.",
            {"kind": "minutes", "tags": ["hard-negative"]},
        ),
        (
            "ro-negative-0112",
            "Locatorul și chiriașul convin o chirie de 850 lei pe lună. Apartamentul are 3 "
            "camere și este la etajul 4; ne-am auzit pe Calea Zoom 3 ori. Din 01.01.2027 "
            "chiria crește cu 2,5 la sută, iar AWB 1029384756 a sosit.",
            {"kind": "contract", "tags": ["hard-negative"]},
        ),
    ]
    return [from_markup(doc_id, text, language="ro", meta=meta) for doc_id, text, meta in docs]


OUTPUTS: dict[str, Callable[[], list[Document]]] = {
    "ro-smoke.jsonl": ro_documents,
}
