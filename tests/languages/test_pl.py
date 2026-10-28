"""The Polish pack (LAB-1400): checksums, rules, cues, case endings. All values are fictional."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pii_guard.detect.checksums import taj_check_digit
from pii_guard.detect.ner import NerDetector, RawEntity
from pii_guard.detect.ner_numbers import number_verdict
from pii_guard.detect.rules import RuleDetector
from pii_guard.detect.rules._base import reference_or_amount_before
from pii_guard.languages.pl.checksums import (
    id_card_check_digit,
    is_valid_id_card,
    is_valid_nip,
    is_valid_passport,
    is_valid_pesel,
    is_valid_regon,
    nip_check_digit,
    passport_check_digit,
    pesel_birth_date,
    pesel_check_digit,
    regon_check_digit,
)
from pii_guard.languages.pl.inflection import PolishCaseMatcher
from pii_guard.types import EntityType as E
from pii_guard.types import Span
from pii_guard.vault import Vault

# Made-up payloads with computed check digits (issued to nobody).
PESEL = "8503140123" + str(pesel_check_digit("8503140123"))
PESEL_2000 = "0227080362" + str(pesel_check_digit("0227080362"))  # born 2002: month + 20
NIP = "777000124" + str(nip_check_digit("777000124"))
REGON_9 = "99000123" + str(regon_check_digit("99000123"))
REGON_14 = REGON_9 + "0001" + str(regon_check_digit(REGON_9 + "0001"))
ID_CARD = "ZZB" + str(id_card_check_digit("ZZB", "00123")) + "00123"
PASSPORT = "ZS" + str(passport_check_digit("ZS", "000321")) + "000321"
TAJ = "55501234" + str(taj_check_digit("55501234"))  # nine digits, valid as a Hungarian TAJ


def _bump(value: str, index: int = -1) -> str:
    """The value with one digit changed: every check digit here catches that."""
    i = index % len(value)
    return value[:i] + str((int(value[i]) + 1) % 10) + value[i + 1 :]


@pytest.fixture(scope="module")
def detector() -> RuleDetector:
    return RuleDetector()


def _found(detector: RuleDetector, text: str, language: str = "pl") -> list[tuple[str, str]]:
    return [(s.entity_type.value, s.text) for s in detector.detect(text, language)]


# --- Checksums ---------------------------------------------------------------------------


def test_published_algorithm_examples() -> None:
    # The worked examples printed in the public descriptions of the algorithms.
    assert is_valid_pesel("44051401359")
    assert is_valid_nip("1234563218")
    assert is_valid_regon("123456785")
    assert is_valid_id_card("ABA300000")


def test_valid_values() -> None:
    for valid, value in (
        (is_valid_pesel, PESEL),
        (is_valid_pesel, PESEL_2000),
        (is_valid_nip, NIP),
        (is_valid_regon, REGON_9),
        (is_valid_regon, REGON_14),
        (is_valid_id_card, ID_CARD),
        (is_valid_passport, PASSPORT),
    ):
        assert valid(value), value


@pytest.mark.parametrize(
    ("value", "year"),
    [("85031401234", 1985), ("02270803628", 2002), ("00810100000", 1800), ("00410100000", 2100)],
)
def test_pesel_century_offsets(value: str, year: int) -> None:
    date = pesel_birth_date(value)
    assert date is not None and date[0] == year


@pytest.mark.parametrize(
    "value",
    [
        _bump(PESEL),  # check digit
        _bump(PESEL, 4),  # another digit
        PESEL[:2] + "13" + PESEL[4:],  # month 13
        PESEL[:2] + "00" + PESEL[4:],  # month 0
        PESEL[:4] + "32" + PESEL[6:],  # day 32
        "01" + "02" + "29" + PESEL[6:],  # 29 February 1901: not a leap year
        PESEL[:10],
        PESEL + "0",
        "8503140123x",
        "".join(chr(0xFF10 + int(d)) for d in PESEL),  # fullwidth digits
    ],
)
def test_invalid_pesels(value: str) -> None:
    assert not is_valid_pesel(value)


def test_pesel_leap_day() -> None:
    payload = "0022290000"  # 29 February 2000 (month 02 + 20)
    assert is_valid_pesel(payload + str(pesel_check_digit(payload)))


@pytest.mark.parametrize(
    "value", [_bump(NIP), _bump(NIP, 2), "000" + NIP[3:], NIP[:9], NIP + "1", "123456321x"]
)
def test_invalid_nips(value: str) -> None:
    assert not is_valid_nip(value)


def test_nip_remainder_ten_is_never_issued() -> None:
    assert nip_check_digit("777000123") is None
    assert not any(is_valid_nip("777000123" + d) for d in "0123456789")


@pytest.mark.parametrize(
    "value",
    [
        _bump(REGON_9),
        _bump(REGON_14),
        _bump(REGON_14, 3),  # the parent's nine digits fail
        REGON_9[:8],
        REGON_9 + "0",
        "12345678901",
    ],
)
def test_invalid_regons(value: str) -> None:
    assert not is_valid_regon(value)


@pytest.mark.parametrize(
    "value",
    [
        _bump(ID_CARD),
        _bump(ID_CARD, 3),  # the check digit itself
        "ZZC" + ID_CARD[3:],
        ID_CARD.lower(),
        "ZZ1" + ID_CARD[3:],
        ID_CARD[:8],
        ID_CARD + "0",
    ],
)
def test_invalid_id_cards(value: str) -> None:
    assert not is_valid_id_card(value)


@pytest.mark.parametrize(
    "value",
    [_bump(PASSPORT), _bump(PASSPORT, 2), "ZT" + PASSPORT[2:], PASSPORT.lower(), PASSPORT[:8]],
)
def test_invalid_passports(value: str) -> None:
    assert not is_valid_passport(value)


@given(st.text("0123456789", min_size=10, max_size=10))
def test_a_wrong_pesel_check_digit_is_rejected(payload: str) -> None:
    good = pesel_check_digit(payload)
    assert not is_valid_pesel(payload + str((good + 1) % 10))


@given(st.text("0123456789", min_size=9, max_size=9))
def test_a_wrong_nip_check_digit_is_rejected(payload: str) -> None:
    good = nip_check_digit(payload)
    if good is None:
        assert not any(is_valid_nip(payload + d) for d in "0123456789")
    else:
        assert not is_valid_nip(payload + str((good + 1) % 10))


@given(
    st.text("ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=3, max_size=3),
    st.text("0123456789", min_size=5, max_size=5),
)
def test_id_card_check_digit_round_trip(letters: str, digits: str) -> None:
    check = id_card_check_digit(letters, digits)
    assert is_valid_id_card(f"{letters}{check}{digits}")
    assert not is_valid_id_card(f"{letters}{(check + 1) % 10}{digits}")


def test_check_digit_arguments_are_validated() -> None:
    for call in (
        lambda: pesel_check_digit("12345"),
        lambda: nip_check_digit("12345678x"),
        lambda: regon_check_digit("1234567"),
        lambda: id_card_check_digit("AB1", "12345"),
        lambda: passport_check_digit("ab", "123456"),
    ):
        with pytest.raises(ValueError):
            call()


# --- Rules -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        NIP,
        f"{NIP[:3]}-{NIP[3:6]}-{NIP[6:8]}-{NIP[8:]}",
        f"{NIP[:3]}-{NIP[3:5]}-{NIP[5:7]}-{NIP[7:]}",
    ],
)
def test_nip_layouts(detector: RuleDetector, value: str) -> None:
    assert _found(detector, f"NIP: {value}") == [("ID_DOCUMENT", value)]
    assert _found(detector, f"Sprzedawca {value}, Kraków") == [("ID_DOCUMENT", value)]


def test_identifiers(detector: RuleDetector) -> None:
    spaced_card, spaced_passport = f"{ID_CARD[:3]} {ID_CARD[3:]}", f"{PASSPORT[:2]} {PASSPORT[2:]}"
    assert _found(detector, f"PESEL {PESEL}") == [("ID_DOCUMENT", PESEL)]
    assert _found(detector, f"REGON: {REGON_9}") == [("ID_DOCUMENT", REGON_9)]
    assert _found(detector, f"REGON {REGON_14}") == [("ID_DOCUMENT", REGON_14)]
    assert _found(detector, f"seria i numer {spaced_card}") == [("ID_DOCUMENT", spaced_card)]
    assert _found(detector, f"paszport nr {spaced_passport}") == [("ID_DOCUMENT", spaced_passport)]
    assert _found(detector, f"NIP UE: PL{NIP}") == [("ID_DOCUMENT", f"PL{NIP}")]


def test_scopes(detector: RuleDetector) -> None:
    # Labelled identifiers and a PL VAT number are found in any language ...
    assert _found(detector, f"PESEL {PESEL}", "en") == [("ID_DOCUMENT", PESEL)]
    assert _found(detector, f"ID card (dowód) {ID_CARD}", "en") == [("ID_DOCUMENT", ID_CARD)]
    assert _found(detector, f"VAT PL{NIP}", "de") == [("ID_DOCUMENT", f"PL{NIP}")]
    # ... a bare PESEL, ID card or Polish address only in Polish text.
    for text in (f"numer {PESEL}", f"karta {ID_CARD}", "ul. Kwiatowa 12/5, 00-950 Warszawa"):
        assert _found(detector, text, "en") == []
        assert _found(detector, text, "pl") != []


def test_bad_check_digits_are_masked_after_a_cue(detector: RuleDetector) -> None:
    # Unvalidated, at the cue score: a mistyped identifier is still personal data.
    for text, value in (
        ("PESEL", _bump(PESEL)),
        ("NIP", _bump(NIP)),
        ("nr dowodu osobistego", _bump(ID_CARD)),
        ("numer paszportu", _bump(PASSPORT)),
        ("prawo jazdy nr", "00123/16/1234"),
    ):
        spans = detector.detect(f"{text} {value}.", "pl")
        assert [(s.entity_type, s.text) for s in spans] == [(E.ID_DOCUMENT, value)], text


@pytest.mark.parametrize(
    "text", ["+48 555 010 203", "555 123 456", "555-123-456", "(22) 555 12 34", "58 555 01 23"]
)
def test_phone_numbers(detector: RuleDetector, text: str) -> None:
    assert _found(detector, f"Kontakt: {text}.") == [("PHONE", text)]


@pytest.mark.parametrize(
    "text",
    [
        "ul. Wymyślona 12/5, 00-950 Warszawa",
        "al. Testowa 100",
        "os. Kwiatowe 3 m. 14",
        "ul. 3 Maja 7, 40-001 Katowice",
        "ul. Jana Pawła II 15, 80-001 Gdańsk",
        "pl. Zmyślony 1a 31-008 Kraków",
        "ulica Marii Skłodowskiej-Curie 4/2",
    ],
)
def test_addresses(detector: RuleDetector, text: str) -> None:
    assert _found(detector, f"mieszka przy {text}.") == [("ADDRESS", text)]


def test_postcode_before_a_town(detector: RuleDetector) -> None:
    assert _found(detector, "Katarzyna Wzorcowa\n61-001 Poznań") == [("ADDRESS", "61-001 Poznań")]


@pytest.mark.parametrize(
    "text",
    [
        "W badaniu wzięło udział 20000 osób przez 18 miesięcy.",
        f"Numer zamówienia {_bump(PESEL)}, sygn. akt I C 123/26.",
        f"Kod produktu {_bump(ID_CARD)}, partia {_bump(REGON_9)}.",
        "Uchwałą nr 12/2026 przyznano 500 000 000 zł na lata 2026-2030.",
        "Czynsz od 01.01.2027 wzrośnie o 2,5 procent, do 2 400 zł.",
        f"Faktura nr {NIP} z dnia 12.10.2026.",  # a valid NIP shape after an invoice label
        "Rabat 10-150 osób, wersja 1.2.3, kod 00-950.",
    ],
)
def test_hard_negatives(detector: RuleDetector, text: str) -> None:
    assert _found(detector, text) == []


# --- Case endings ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "allowed", "refused"),
    [
        ("Nowak", ["a", "owi", "iem", "u", "owie", "ów"], ["ego", "y"]),
        ("Kowalski", ["ego", "emu", "m", "ch"], ["a", "owi"]),
        ("Anna", [], ["a", "y", "ie"]),
        ("ABC123456", [], ["a"]),
    ],
)
def test_case_endings(value: str, allowed: list[str], refused: list[str]) -> None:
    import re

    pattern = PolishCaseMatcher().suffix_pattern(value, E.PERSON)
    for ending in allowed:
        assert re.fullmatch(pattern, ending), ending
    for ending in refused:
        assert not pattern or not re.fullmatch(pattern, ending), ending


def test_case_forms_are_masked_and_restored() -> None:
    session = Vault(b"pl-pack-test-key-01").session()
    text = "Marek Nowak dzwonił. Klucze dla Nowaka, rozmowa z Nowakiem, list do Kowalskiego."
    spans = [
        Span(0, 11, E.PERSON, "Marek Nowak", 1.0, "t"),
        Span(text.index("Nowak", 12), text.index("Nowak", 12) + 5, E.PERSON, "Nowak", 1.0, "t"),
        Span(text.index("Kowalski"), text.index("Kowalski") + 8, E.PERSON, "Kowalski", 1.0, "t"),
    ]
    masked = session.mask(text, spans, language="pl")
    assert "Nowak" not in masked and "Kowalsk" not in masked
    assert "]]a," in masked and "]]iem," in masked and "]]ego." in masked
    assert session.unmask(masked) == text


def test_llm_profile_and_prompt() -> None:
    from pii_guard.detect.llm import build_messages, language_profile

    profile = language_profile("pl-PL")
    assert (profile.code, profile.name, profile.allow_suffix) == ("pl", "Polish", True)
    system = build_messages("Tekst", "pl")[0]["content"]
    assert "PESEL" in system and "dowód" in system


# --- LAB-1433 follow-ups -----------------------------------------------------------------


def test_a_licence_number_that_looks_like_a_date_tail_is_masked(detector: RuleDetector) -> None:
    # "2345/42/00" sits inside the value and "5936/42/00" has no month 42: neither is a date.
    for value in ("12345/42/00", "05936/42/00", "5936/42/00"):
        spans = detector.detect(f"Prawo jazdy nr {value}.", "pl")
        assert [(s.entity_type, s.text) for s in spans] == [(E.ID_DOCUMENT, value)], value


def test_a_real_date_after_a_cue_is_still_not_masked(detector: RuleDetector) -> None:
    for text in ("prawo jazdy wydane 2026/10/26", "telefon 2026-10-27", "PESEL od 26.10.2026"):
        assert _found(detector, text) == [], text


def test_an_unlabelled_taj_is_hungarian_only(detector: RuleDetector) -> None:
    grouped = f"{TAJ[:3]} {TAJ[3:6]} {TAJ[6:]}"
    assert _found(detector, f"Kontakt: {grouped}.", "hu") == [("NATIONAL_ID_HU_TAJ", grouped)]
    assert _found(detector, f"Kontakt: {grouped}.", "pl") == [("PHONE", grouped)]
    assert _found(detector, f"Contact: {TAJ}.", "en") == []
    # After its label a TAJ is still found in every language.
    for language in ("pl", "en", "de"):
        assert _found(detector, f"TAJ: {grouped}", language) == [("NATIONAL_ID_HU_TAJ", grouped)]


@pytest.mark.parametrize(
    "label",
    [
        "Faktura nr",
        "numer zamówienia:",
        "Zamówienie nr",
        "nr przesyłki",
        "Paragon",
        "numer zlecenia",
        "Nr rezerwacji:",
        "Kwota",
        "PLN",
    ],
)
def test_polish_reference_labels_are_shared(label: str) -> None:
    text = f"{label} 123456789"
    assert reference_or_amount_before(text, len(text) - 9)


@pytest.mark.parametrize(
    "label",
    [
        "Numer zamówienia:",
        "Faktura nr",
        "numer przesyłki",
        "Paczka nr",
        "Nr rezerwacji:",
        "Zgłoszenie",
        "nr transakcji",
        "Przesyłka",
    ],
)
def test_ner_numbers_after_a_polish_reference_label_are_dropped(label: str) -> None:
    text = f"{label} 5550123456 jest gotowe."
    start = text.index("5550123456")
    assert not number_verdict(text, start, start + 10)


def test_numer_alone_is_no_positive_cue() -> None:
    # "numer" is in many cues ("numer konta", "numer dowodu") but names nothing by itself.
    text = "Faktura numer 5550123456"
    start = text.index("5550123456")
    assert not number_verdict(text, start, start + 10)
    text = "numer 5550123456"
    assert number_verdict(text, 6, 16)  # no cue at all: the shape decides, and keeps it


class _TagBackend:
    def __init__(self, value: str) -> None:
        self.value = value

    def predict(self, text: str) -> list[RawEntity]:
        start = text.find(self.value)
        return [RawEntity("ID_DOCUMENT", start, start + len(self.value), 0.9)]


def test_ner_keeps_an_identifier_after_its_polish_label() -> None:
    for text, value in (
        (f"PESEL {_bump(PESEL)}", _bump(PESEL)),
        ("nr konta 5550123456", "5550123456"),
    ):
        detector = NerDetector(backend=_TagBackend(value))
        assert [s.text for s in detector.detect(text, "pl")] == [value], text
    detector = NerDetector(backend=_TagBackend("5550123456"))
    assert detector.detect("Numer zamówienia 5550123456", "pl") == []
