"""The Italian pack (LAB-1776): checksums, omocodia, rules, hard negatives, cues. All values are
fictional or the published examples of the algorithms."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pii_guard.detect.ner_numbers import number_verdict
from pii_guard.detect.rules import RuleDetector
from pii_guard.detect.rules._base import reference_or_amount_before
from pii_guard.languages.it.checksums import (
    MONTHS,
    OMOCODIA,
    codice_fiscale_birth,
    codice_fiscale_check_char,
    is_valid_codice_fiscale,
    is_valid_partita_iva,
    partita_iva_check_digit,
)
from pii_guard.types import EntityType as E
from pii_guard.types import Span
from pii_guard.vault import Vault


def _cf(payload15: str) -> str:
    return payload15 + codice_fiscale_check_char(payload15)


def _omocodic(value: str, n: int) -> str:
    """``value`` with its last ``n`` digit positions replaced by omocodia letters."""
    chars = list(value[:15])
    for i in (14, 13, 12, 10, 9, 7, 6)[:n]:
        chars[i] = OMOCODIA[int(chars[i])]
    return _cf("".join(chars))


# Made-up payloads with computed check characters (issued to nobody).
CF = _cf("PRVGLI85T50F205")  # a woman born 10 December 1985
CF_MAN = _cf("SMPMRC79A12H501")
CF_OMO = _omocodic(CF, 2)
PIVA = "9990001037" + str(partita_iva_check_digit("9990001037"))
CIE = "CA00123ZZ"


def _bump_char(value: str) -> str:
    """The value with its check letter changed."""
    return value[:15] + chr(65 + (ord(value[15]) - 64) % 26)


def _bump(value: str, index: int = -1) -> str:
    i = index % len(value)
    return value[:i] + str((int(value[i]) + 1) % 10) + value[i + 1 :]


@pytest.fixture(scope="module")
def detector() -> RuleDetector:
    return RuleDetector()


def _found(detector: RuleDetector, text: str, language: str = "it") -> list[tuple[str, str]]:
    return [(s.entity_type.value, s.text) for s in detector.detect(text, language)]


# --- Checksums ---------------------------------------------------------------------------


def test_published_algorithm_examples() -> None:
    # The worked examples printed in the public descriptions of the codice fiscale ...
    for value in ("RSSMRA85T10A562S", "MRTMTT25D09F205Z", "RCCMNL83S18D969H"):
        assert is_valid_codice_fiscale(value), value
    # ... and Luhn's: 7992739871 takes the check digit 3.
    assert partita_iva_check_digit("7992739871") == 3


def test_valid_values() -> None:
    for value in (CF, CF_MAN, CF_OMO):
        assert is_valid_codice_fiscale(value), value
    assert is_valid_partita_iva(PIVA)


def test_birth_data() -> None:
    assert codice_fiscale_birth(CF) == (85, 12, 10, True)
    assert codice_fiscale_birth(CF_MAN) == (79, 1, 12, False)
    assert codice_fiscale_birth(CF_OMO) == codice_fiscale_birth(CF)
    assert MONTHS.index("T") == 11


@pytest.mark.parametrize("n", range(1, 8))
def test_omocodia(n: int) -> None:
    # Every number of substituted positions, each with its own check letter.
    value = _omocodic(CF, n)
    assert sum(ch.isdigit() for ch in value) == 7 - n
    assert is_valid_codice_fiscale(value)
    assert not is_valid_codice_fiscale(_bump_char(value))


@pytest.mark.parametrize(
    "value",
    [
        _bump_char(CF),  # check letter
        CF[:8] + "F" + CF[9:],  # F is no month letter
        CF[:9] + "32" + CF[11:],  # day 32
        CF[:9] + "00" + CF[11:],  # day 0
        CF[:9] + "72" + CF[11:],  # day 32 for a woman
        CF[:6] + "8A" + CF[8:],  # A is no omocodia letter
        "1" + CF[1:],  # a digit at a letter position
        CF.lower(),
        CF[:15],
        CF + "A",
    ],
)
def test_invalid_codici_fiscali(value: str) -> None:
    assert not is_valid_codice_fiscale(value)


@pytest.mark.parametrize(
    "value",
    [
        _bump(PIVA),
        "0000000" + PIVA[7:],  # no company number
        PIVA[:7] + "101" + PIVA[10:],  # no such office
        PIVA[:10],
        PIVA + "0",
        PIVA[:10] + "x",
    ],
)
def test_invalid_partite_iva(value: str) -> None:
    assert not is_valid_partita_iva(value)


@given(st.text("0123456789", min_size=10, max_size=10))
def test_a_wrong_luhn_digit_is_rejected(payload: str) -> None:
    good = partita_iva_check_digit(payload)
    assert not is_valid_partita_iva(payload + str((good + 1) % 10))


def test_check_arguments_are_validated() -> None:
    for call in (
        lambda: codice_fiscale_check_char("PRVGLI85"),
        lambda: codice_fiscale_check_char(CF[:15].lower()),
        lambda: partita_iva_check_digit("12345"),
    ):
        with pytest.raises(ValueError):
            call()


# --- Rules -------------------------------------------------------------------------------


def test_identifiers(detector: RuleDetector) -> None:
    assert _found(detector, f"Codice fiscale: {CF}.") == [("ID_DOCUMENT", CF)]
    assert _found(detector, f"il CF {CF_OMO} risulta omocodico") == [("ID_DOCUMENT", CF_OMO)]
    assert _found(detector, f"P.IVA {PIVA}") == [("ID_DOCUMENT", PIVA)]
    assert _found(detector, f"partita IVA: {PIVA}") == [("ID_DOCUMENT", PIVA)]
    assert _found(detector, f"n. IVA comunitario IT{PIVA}") == [("ID_DOCUMENT", f"IT{PIVA}")]
    assert _found(detector, f"carta d'identità {CIE}") == [("ID_DOCUMENT", CIE)]
    assert _found(detector, f"titolare del documento {CIE}") == [("ID_DOCUMENT", CIE)]
    assert _found(detector, f"il Sig. Esempio, {CIE}, residente") == [("ID_DOCUMENT", CIE)]


def test_scopes(detector: RuleDetector) -> None:
    # A codice fiscale, an IT VAT number and a labelled CIE are found in any language ...
    for language in ("en", "de", "hu", "pl"):
        assert _found(detector, f"tax code {CF}", language) == [("ID_DOCUMENT", CF)]
        assert _found(detector, f"VAT IT{PIVA}", language) == [("ID_DOCUMENT", f"IT{PIVA}")]
        assert _found(detector, f"ID card {CIE}", language) == [("ID_DOCUMENT", CIE)]
    # ... a labelled partita IVA everywhere only through its cue (0.6), the validated rule and
    # an unlabelled CIE, phone or address only in Italian text.
    spans = RuleDetector().detect(f"P.IVA {PIVA}", "en")
    assert [(s.text, s.score) for s in spans] == [(PIVA, 0.6)]
    for text in (
        f"Rilasciata a Roma: {CIE}",
        "Chiamare il 347 123 4567",
        "Via dei Mille 27, 40121 Bologna",
    ):
        assert _found(detector, text, "en") == []
        assert _found(detector, text, "it") != []


def test_an_unlabelled_partita_iva_is_never_masked(detector: RuleDetector) -> None:
    # Eleven digits with a Luhn digit are as often a Hungarian personal ID or a Steuer-ID.
    for language in ("it", "en", "hu", "de"):
        assert _found(detector, f"Il numero {PIVA} è stato registrato.", language) == []


def test_bad_check_characters_are_masked_after_a_cue(detector: RuleDetector) -> None:
    # Unvalidated, at the cue score: a mistyped identifier is still personal data.
    for label, value in (
        ("codice fiscale", _bump_char(CF)),
        ("C.F.", _bump_char(CF)),
        ("P.IVA", _bump(PIVA)),
        ("passaporto n.", "YA1234567"),
        ("patente n.", "U13457826Z"),
        ("tessera sanitaria", "80380000001234567890"),
    ):
        spans = detector.detect(f"{label} {value}.", "it")
        assert [(s.entity_type, s.text, s.score) for s in spans] == [(E.ID_DOCUMENT, value, 0.6)], (
            label
        )


@pytest.mark.parametrize(
    "text",
    [
        "347 123 4567",
        "347 1234567",
        "347-123-4567",
        "347.123.4567",
        "333 234 567",
        "02 555 0123",
        "02 5550 1234",
        "(011) 555 0147",
        "0471 555012",
        "06/5550123",
        "+39 320 345 6789",
    ],
)
def test_phone_numbers(detector: RuleDetector, text: str) -> None:
    assert _found(detector, f"Recapiti: {text}.") == [("PHONE", text)]


def test_a_compact_mobile_needs_a_cue(detector: RuleDetector) -> None:
    assert _found(detector, "Il codice 3332345678 è scaduto.") == []
    assert _found(detector, "il mio cell. è 3332345678") == [("PHONE", "3332345678")]
    assert _found(detector, "telefono o cellulare 3332345678") == [("PHONE", "3332345678")]


@pytest.mark.parametrize(
    "text",
    [
        "Via dei Mille 27, 40121 Bologna",
        "Via dei Mille 27, 40121 Bologna (BO)",
        "via XX Settembre 15/A, 00187 Roma (RM)",
        "Corso Venezia 8",
        "Viale Immaginario 14/B",
        "Piazza San Marco 1",
        "Via Roma, 12 - 10121 Torino (TO)",
        "Largo dei Gelsomini 2",
        "Via 4 Novembre 3",
        "Via dell'Indipendenza 10, 40121 Bologna",
        "C.so Esempio 8",
    ],
)
def test_addresses(detector: RuleDetector, text: str) -> None:
    assert _found(detector, f"residente in {text}.") == [("ADDRESS", text)]


def test_an_address_over_two_lines(detector: RuleDetector) -> None:
    text = "Giulia Prova\nViale Immaginario 14/B\n00184 Roma"
    assert _found(detector, text) == [("ADDRESS", "Viale Immaginario 14/B\n00184 Roma")]


def test_cap_at_the_start_of_an_address_line(detector: RuleDetector) -> None:
    assert _found(detector, "Giulia Prova\n00184 Roma") == [("ADDRESS", "00184 Roma")]
    assert _found(detector, "Studio Esempio, 20121 Milano") == [("ADDRESS", "20121 Milano")]


@pytest.mark.parametrize(
    "text",
    [
        "Alla fiera hanno partecipato\n20000 Persone da tutta Italia.",
        "Riunione del 05.11.2026 dalle 08.30-12.30, rinviata al 05/11/2026.",
        "Fattura n. 2026/00731, importo 1.120,00 EUR, da pagare entro 30 giorni.",
        f"Fattura n. {PIVA} del 12/10/2026.",  # a valid partita IVA without its label
        "Numero d'ordine 50039127, codice articolo IT-7741-B.",
        f"Ordine n. 4500123456, codice articolo {_bump_char(CF)[:9]}.",
        f"Rif. pratica {CF[:15]}, lotto 99012345678.",
        "Codice articolo ZZ12345AB, CAP 20121.",
        "Il preventivo di 1.250.000,00 EUR copre il periodo 2026-2030.",
        "La popolazione è di 345.123.456 abitanti.",
        "Ci siamo sentiti via Zoom 3 volte.",
        f"Il codice {CF.lower()} non è in maiuscolo.",
        "Spedizione 20121 Milano S.r.l., magazzino 3.",
        f"Prenotazione n. {CIE}, {_bump_char(CF)} senza etichetta.",
    ],
)
def test_hard_negatives(detector: RuleDetector, text: str) -> None:
    assert _found(detector, text) == []


# --- Cues and reference words ------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "Fattura n.",
        "fattura numero",
        "Ordine n.",
        "numero d'ordine:",
        "Ricevuta n.",
        "Scontrino",
        "Protocollo n.",
        "prot.",
        "Pratica n.",
        "Spedizione",
        "Prenotazione",
    ],
)
def test_italian_reference_labels_are_shared(label: str) -> None:
    text = f"{label} 123456789"
    assert reference_or_amount_before(text, len(text) - 9)


@pytest.mark.parametrize(
    "text",
    [
        "Numero d'ordine 3471234567",
        "Fattura n. 3471234567",
        "Codice cliente 3471234567",
        "Riferimento 3471234567",
        "Protocollo 3471234567",
        "Telefono o numero d'ordine 3471234567",
    ],
)
def test_negative_cues_keep_business_numbers(detector: RuleDetector, text: str) -> None:
    assert _found(detector, text) == []


def test_italian_reference_words_stay_out_of_the_ner_check() -> None:
    # Scoped to the rules check until the NER negatives may grow beyond the built-in list
    # (LAB-1788): an Italian label alone does not drop an NER number yet.
    from pii_guard.detect.ner_numbers import _pack_negatives

    assert not {"fattur*", "ordin*", "spedizion*", "prenotazion*"} & set(_pack_negatives() or [])


def test_ner_keeps_an_identifier_after_its_italian_label() -> None:
    for label in ("codice fiscale", "partita IVA", "passaporto", "carta d'identità"):
        text = f"{label} 5550123456"
        assert number_verdict(text, len(label) + 1, len(text)), label


# --- Names, prompt -----------------------------------------------------------------------


def test_names_are_masked_exactly_and_restored() -> None:
    session = Vault(b"it-pack-test-key-01").session()
    text = "La relazione dell'ing. Pietro Gatti conferma che Gatti aveva ragione; Gattini no."
    first = text.index("Pietro Gatti")
    spans = [Span(first, first + 12, E.PERSON, "Pietro Gatti", 1.0, "t")]
    masked = session.mask(text, spans, language="it")
    assert "Pietro" not in masked and "dell'ing. [[" in masked
    assert "Gattini" in masked  # no suffix runs on: a longer word is another word
    assert session.unmask(masked) == text


def test_llm_profile_and_prompt() -> None:
    from pii_guard.detect.llm import build_messages, language_profile

    profile = language_profile("it-IT")
    assert (profile.code, profile.name, profile.allow_suffix) == ("it", "Italian", False)
    system = build_messages("Testo", "it")[0]["content"]
    assert "codice fiscale" in system and "partita IVA" in system
