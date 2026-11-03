"""Polish smoke fixtures: ``pl-smoke.jsonl`` (the Polish pack's, LAB-1400). Built by
``eval/fixtures/build_smoke.py``; fictional values only (ADR 0005)."""

from __future__ import annotations

from collections.abc import Callable

from build_smoke import BANK, DOB, IDD, ORG, PH, A, E, P, iban

from pii_guard.eval import Document, from_markup
from pii_guard.languages.pl.checksums import (
    id_card_check_digit,
    is_valid_pesel,
    nip_check_digit,
    passport_check_digit,
    pesel_check_digit,
    regon_check_digit,
)


def pesel(payload10: str) -> str:
    """A valid PESEL from a made-up ``YYMMDDZZZX`` (the month carries the century)."""
    value = payload10 + str(pesel_check_digit(payload10))
    if not is_valid_pesel(value):
        raise ValueError("payload has no possible date of birth; pick another")
    return value


def bad_pesel(payload10: str) -> str:
    """Looks like a PESEL, fails the check digit."""
    good = pesel(payload10)
    return good[:10] + str((int(good[10]) + 1) % 10)


def nip(payload9: str, layout: str = "3-3-2-2") -> str:
    """A valid NIP, grouped ``3-3-2-2`` (people), ``3-2-2-3`` (companies) or compact."""
    check = nip_check_digit(payload9)
    if check is None:
        raise ValueError("payload has no NIP check digit; pick another")
    digits = payload9 + str(check)
    if layout == "3-3-2-2":
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:8]}-{digits[8:]}"
    if layout == "3-2-2-3":
        return f"{digits[:3]}-{digits[3:5]}-{digits[5:7]}-{digits[7:]}"
    return digits


def regon(payload8: str) -> str:
    """A valid 9-digit REGON."""
    return payload8 + str(regon_check_digit(payload8))


def id_card(letters: str, digits5: str, sep: str = "") -> str:
    """A valid dowód osobisty number ``AAA`` + check digit + five digits."""
    return f"{letters}{sep}{id_card_check_digit(letters, digits5)}{digits5}"


def passport_pl(letters: str, digits6: str, sep: str = "") -> str:
    """A valid Polish passport number ``AA`` + check digit + six digits."""
    return f"{letters}{sep}{passport_check_digit(letters, digits6)}{digits6}"


def pl_documents() -> list[Document]:
    iban_pl_1 = iban("PL", "123400000000001234567890")
    iban_pl_2 = iban("PL", "432100000000009876543210", grouped=False)
    pesel_1, pesel_2, pesel_3 = pesel("8503140123"), pesel("9211250456"), pesel("0227080362")
    nip_1, nip_2 = nip("777000124"), nip("526000111", layout="3-2-2-3")
    nip_3 = nip("951000345", layout="compact")
    regon_1 = regon("99000123")
    dowod_1, dowod_2 = id_card("ZZB", "00123", sep=" "), id_card("ZXA", "45678")
    paszport_1 = passport_pl("ZS", "000321")
    docs: list[tuple[str, str, dict[str, object]]] = [
        (
            "pl-email-0001",
            f"Temat: Kaucja\n\nDzień dobry Pani {P('Anna Przykładowa')},\n\nkaucję przelejemy "
            f"na rachunek {BANK(iban_pl_1)}. W razie pytań proszę dzwonić pod "
            f"{PH('+48 22 555 01 03')} albo pisać na {E('anna.przykladowa@example.com')}.\n\n"
            f"Z poważaniem\n{P('Jan Testowy')}",
            {"kind": "email"},
        ),
        (
            "pl-contract-0002",
            "UMOWA O PRACĘ\n\n"
            f"zawarta pomiędzy {ORG('Fikcyjna Spółka z o.o.')} a {P('Piotrem Zmyślonym')}, "
            f"urodzonym {DOB('14.03.1985')}, zamieszkałym przy "
            f"{A('ul. Wymyślona 12/5, 00-950 Warszawa')}, PESEL {IDD(pesel_1)}, legitymującym "
            f"się dowodem osobistym seria i numer {IDD(dowod_1)}.\n"
            f"Wynagrodzenie będzie wypłacane na konto {BANK(iban_pl_2)}.",
            {"kind": "contract"},
        ),
        (
            "pl-invoice-0003",
            "FAKTURA VAT nr FV/2026/10/0815\n"
            f"Sprzedawca: {P('Tomasz Próbny')} Usługi Remontowe, NIP: {IDD(nip_1)}, "
            f"REGON: {IDD(regon_1)}\n"
            f"Nabywca: {ORG('Wzorcowa Sp. z o.o.')}, NIP {IDD(nip_2)}, "
            f"{A('al. Testowa 100, 31-008 Kraków')}\n"
            "Do zapłaty: 12 500,00 zł, termin płatności 01.12.2026.",
            {"kind": "invoice"},
        ),
        (
            "pl-letter-0004",
            f"{P('Katarzyna Wzorcowa')}\n{A('os. Kwiatowe 3 m. 14\n61-001 Poznań')}\n\n"
            f"Szanowna Pani,\n\ninformujemy, że paszport nr {IDD(paszport_1)} jest gotowy do "
            f"odbioru. Prosimy o kontakt pod numerem {PH('(61) 555 01 34')}.\n\n"
            f"Z wyrazami szacunku\n{ORG('Urząd Fikcyjny w Poznaniu')}",
            {"kind": "letter"},
        ),
        (
            "pl-chat-0005",
            f"hej, tu {P('Ola Fikcyjna')}! mój nowy numer to {PH('512 345 678')}, "
            f"możesz też pisać na {E('ola.fikcyjna@example.net')}",
            {"kind": "chat", "tags": ["informal"]},
        ),
        (
            "pl-inflection-0006",
            f"{P('Marek Nowak')} się przeprowadza. Klucze oddaliśmy {P('Nowak')}owi, a umowę "
            f"podpisaliśmy z {P('Nowak')}iem w poniedziałek. Paczka dla "
            f"{P('Jana Kowalskiego')} czeka u {P('Kowalski')}ch na "
            f"{A('ul. 3 Maja 7, 40-001 Katowice')}.",
            {"kind": "note", "tags": ["inflected"]},
        ),
        (
            "pl-form-0007",
            "Wniosek o zwrot kosztów\n"
            f"Imię i nazwisko: {P('Ewa Zmyślona')}\nData urodzenia: {DOB('02.07.1992')}\n"
            f"PESEL: {IDD(pesel_2)}\nAdres: {A('ul. Jana Pawła II 15, 80-001 Gdańsk')}\n"
            f"Nr prawa jazdy: {IDD('00123/16/1234')}\nTelefon: {PH('58 555 01 23')}",
            {"kind": "form"},
        ),
        (
            "pl-bank-0008",
            f"Wyciąg z rachunku\nPosiadacz: {P('Adam Testowy')}, NIP {IDD(nip_3)}\n"
            f"Karta płatnicza nr {BANK('4111 1111 1111 1111')}, dowód osobisty "
            f"{IDD(dowod_2)}.\nSaldo końcowe: 3 456,78 zł.",
            {"kind": "statement"},
        ),
        (
            "pl-registry-0009",
            f"Dane dziecka: {P('Zofia Próbna')}, ur. {DOB('08.07.2002')}, numer PESEL "
            f"{IDD(pesel_3)}. Opiekun prawny: {P('Paweł Próbny')}, "
            f"e-mail {E('pawel.probny@example.org')}.",
            {"kind": "form"},
        ),
        (
            "pl-negative-0010",
            "Protokół z zebrania z dnia 01.02.2026\n"
            "W badaniu wzięło udział 20000 osób przez 18 miesięcy. Numer zamówienia "
            f"{bad_pesel('8503140123')}, sygn. akt I C 123/26, kod produktu ZZB100123. "
            "Uchwałą nr 12/2026 przyznano 500 000 000 zł na lata 2026-2030.",
            {"kind": "minutes", "tags": ["hard-negative"]},
        ),
        (
            "pl-negative-0011",
            "Najemca i Wynajmujący ustalają czynsz w wysokości 2 400 zł miesięcznie. Od "
            "01.01.2027 czynsz wzrośnie o 2,5 procent. Mieszkanie ma 3 pokoje i 54 metry "
            "kwadratowe na 4 piętrze.",
            {"kind": "contract", "tags": ["hard-negative"]},
        ),
    ]
    return [from_markup(doc_id, text, language="pl", meta=meta) for doc_id, text, meta in docs]


OUTPUTS: dict[str, Callable[[], list[Document]]] = {
    "pl-smoke.jsonl": pl_documents,
}
