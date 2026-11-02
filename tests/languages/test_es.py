"""The Spanish pack (LAB-1775): checksums, rules, cues, reference words. All values fictional."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pii_guard.detect.ner_numbers import number_verdict
from pii_guard.detect.rules import RuleDetector
from pii_guard.detect.rules._base import reference_or_amount_before
from pii_guard.languages.es.checksums import (
    cif_control,
    dni_letter,
    is_valid_cif,
    is_valid_dni,
    is_valid_nie,
)
from pii_guard.types import EntityType as E

_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"

# Made-up payloads with computed check letters (issued to nobody).
DNI = "99000123" + dni_letter("99000123")
NIE = "X9000123" + dni_letter("09000123")
NIE_Y = "Y9000456" + dni_letter("19000456")
CIF = "B9900012" + str(cif_control("9900012"))


def _wrong_letter(value: str) -> str:
    """The value with its check letter replaced by the next one in the table."""
    return value[:-1] + _LETTERS[(_LETTERS.index(value[-1]) + 1) % 23]


@pytest.fixture(scope="module")
def detector() -> RuleDetector:
    return RuleDetector()


def _found(detector: RuleDetector, text: str, language: str = "es") -> list[tuple[str, str]]:
    return [(s.entity_type.value, s.text) for s in detector.detect(text, language)]


# --- Checksums ---------------------------------------------------------------------------


def test_published_algorithm_examples() -> None:
    # The worked examples printed in the public descriptions of the algorithms.
    assert is_valid_dni("12345678Z")
    assert is_valid_dni("00000000T")
    assert is_valid_nie("X1234567L")
    assert is_valid_nie("Y1234567X")
    assert is_valid_nie("Z1234567R")
    assert is_valid_cif("J99216582")


def test_valid_values() -> None:
    for valid, value in (
        (is_valid_dni, DNI),
        (is_valid_nie, NIE),
        (is_valid_nie, NIE_Y),
        (is_valid_cif, CIF),
    ):
        assert valid(value), value


@pytest.mark.parametrize(
    "value",
    [
        _wrong_letter(DNI),
        DNI[:8] + "I",  # never a check letter
        DNI.lower(),
        DNI[:8],
        "0" + DNI,
        DNI[1:],
        "9900012x" + DNI[-1],
        "".join(chr(0xFF10 + int(d)) for d in DNI[:8]) + DNI[-1],  # fullwidth digits
    ],
)
def test_invalid_dnis(value: str) -> None:
    assert not is_valid_dni(value)


@pytest.mark.parametrize(
    "value",
    [_wrong_letter(NIE), "W" + NIE[1:], "Y" + NIE[1:], NIE.lower(), NIE[:8], "X" + DNI],
)
def test_invalid_nies(value: str) -> None:
    assert not is_valid_nie(value)


def test_cif_control_letters_and_digits() -> None:
    control = cif_control("9900012")
    letter = "JABCDEFGHI"[control]
    assert is_valid_cif(f"B9900012{control}")  # B: a digit
    assert not is_valid_cif(f"B9900012{letter}")
    assert is_valid_cif(f"Q9900012{letter}")  # Q: a letter
    assert not is_valid_cif(f"Q9900012{control}")
    assert is_valid_cif(f"G9900012{control}") and is_valid_cif(f"G9900012{letter}")  # either
    assert not is_valid_cif(f"B9900012{(control + 1) % 10}")
    assert not is_valid_cif(f"I9900012{control}")  # no such organisation type


@given(st.text("0123456789", min_size=8, max_size=8))
def test_only_the_right_letter_validates(payload: str) -> None:
    letter = dni_letter(payload)
    assert is_valid_dni(payload + letter)
    assert not any(is_valid_dni(payload + other) for other in _LETTERS if other != letter)


@given(st.sampled_from("XYZ"), st.text("0123456789", min_size=7, max_size=7))
def test_nie_maps_its_prefix_to_a_digit(prefix: str, payload: str) -> None:
    letter = dni_letter(str("XYZ".index(prefix)) + payload)
    assert is_valid_nie(prefix + payload + letter)
    assert not is_valid_nie(prefix + payload + _wrong_letter(letter))


def test_check_arguments_are_validated() -> None:
    for call in (lambda: dni_letter("1234567"), lambda: cif_control("12345x7")):
        with pytest.raises(ValueError):
            call()


# --- Rules -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        DNI,
        f"{DNI[:8]}-{DNI[8]}",
        f"{DNI[:2]}.{DNI[2:5]}.{DNI[5:8]}-{DNI[8]}",
        NIE,
        f"{NIE[0]}-{NIE[1:8]}-{NIE[8]}",
    ],
)
def test_identifier_layouts(detector: RuleDetector, value: str) -> None:
    assert _found(detector, f"DNI/NIE: {value}") == [("ID_DOCUMENT", value)]
    assert _found(detector, f"Vendedor {value}, Madrid") == [("ID_DOCUMENT", value)]


def test_scopes(detector: RuleDetector) -> None:
    # A DNI or NIE is found in any language, a labelled CIF too ...
    for language in ("en", "de", "hu", "pl"):
        assert _found(detector, f"ID {DNI}, residence permit {NIE}.", language) == [
            ("ID_DOCUMENT", DNI),
            ("ID_DOCUMENT", NIE),
        ]
        assert _found(detector, f"CIF {CIF}", language) == [("ID_DOCUMENT", CIF)]
    # ... a Spanish phone number or address only in Spanish text.
    for text in ("Llame al 612 345 678.", "Calle Ficticia 14, 3.º B, 28012 Madrid"):
        assert _found(detector, text, "en") == []
        assert _found(detector, text, "es") != []


def test_an_unlabelled_cif_is_left_alone(detector: RuleDetector) -> None:
    assert _found(detector, f"código de producto {CIF}") == []


def test_a_spaced_letter_needs_a_label(detector: RuleDetector) -> None:
    spaced = f"{DNI[:8]} {DNI[8]}"
    assert _found(detector, f"DNI {spaced}") == [("ID_DOCUMENT", spaced)]
    assert _found(detector, f"unos {spaced} más") == []


def test_bad_check_letters_are_masked_after_a_cue(detector: RuleDetector) -> None:
    # Unvalidated, at the cue score: a mistyped identifier is still personal data.
    for text, value in (
        ("DNI", _wrong_letter(DNI)),
        ("NIE", _wrong_letter(NIE)),
        ("número de pasaporte", "PAA000123"),
        ("permiso de conducir", "99000123A1"),
        ("n.º de la Seguridad Social", "28 12345678 40"),
    ):
        spans = detector.detect(f"{text} {value}.", "es")
        assert [(s.entity_type, s.text) for s in spans] == [(E.ID_DOCUMENT, value)], text


@pytest.mark.parametrize(
    "text",
    [
        "612 345 678",
        "612-345-678",
        "612 34 56 78",
        "612.34.56.78",
        "91 555 01 23",
        "976 555 012",
        "623456789",
        "+34 612 345 678",
    ],
)
def test_phone_numbers(detector: RuleDetector, text: str) -> None:
    assert _found(detector, f"Contacto: {text}.") == [("PHONE", text)]


def test_a_cued_fixed_line_without_grouping(detector: RuleDetector) -> None:
    assert _found(detector, "Teléfono: 912345678.") == [("PHONE", "912345678")]
    assert _found(detector, "Contacto: 912345678.") == []


@pytest.mark.parametrize(
    "text",
    [
        "Calle Ficticia 14, 3.º B, 28012 Madrid",
        "Avenida del Puerto 51, 46021 Valencia",
        "Avda. de la Prueba 100",
        "C/ Inventada 7, 2º izda.",
        "plaza Mayor s/n, bajo, C.P. 37001 Salamanca",
        "Paseo de Alfonso XII 3",
        "calle de la Paz n.º 12, 4.º 2.ª",
    ],
)
def test_addresses(detector: RuleDetector, text: str) -> None:
    assert _found(detector, f"vive en {text}.") == [("ADDRESS", text)]


def test_postcode_where_an_address_line_starts(detector: RuleDetector) -> None:
    assert _found(detector, "Ana Prueba\n28801 Alcalá de Henares") == [
        ("ADDRESS", "28801 Alcalá de Henares")
    ]
    assert _found(detector, "Envío a Lugo, 27001 Lugo") == [("ADDRESS", "27001 Lugo")]
    assert _found(detector, "En 2026 vinieron 28012 Madrileños") == []  # not a line start


@pytest.mark.parametrize(
    "text",
    [
        "En el estudio participaron 20000 personas durante 18 meses.",
        f"Número de pedido {DNI}, expediente 2026/004412.",
        f"Pedido n.º {DNI} enviado.",
        f"Factura n.º {DNI} del 12/10/2026.",
        f"Código de producto {_wrong_letter(DNI)}, lote 990001230.",
        "Por acuerdo n.º 12/2026 se aprobaron 500.000.000 € para los años 2026-2030.",
        "Importe 612 345 678 € a liquidar; 612.345.678 habitantes.",
        "Referencia del pedido 612345678, factura 912345678.",
        "La renta de 950 € subirá un 2,5 % desde el 01/01/2027.",
        "Código postal 28012, versión 1.2.3.",
        "Total\n25000 Euros",
    ],
)
def test_hard_negatives(detector: RuleDetector, text: str) -> None:
    assert _found(detector, text) == []


def test_nie_label_is_a_whole_word(detector: RuleDetector) -> None:
    # "nieto" holds "nie": only the word NIE raises the score, as a label does.
    spans = detector.detect(f"Su nieto, {NIE}.", "es")
    assert [(s.text, s.score) for s in spans] == [(NIE, 0.9)]
    spans = detector.detect(f"NIE {NIE}.", "es")
    assert [(s.text, s.score) for s in spans] == [(NIE, 0.97)]


# --- Cues and reference words --------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    ["Factura", "Factura n.º", "Pedido nº", "número de pedido:", "Albarán", "Expediente", "Recibo"],
)
def test_spanish_reference_labels_are_shared(label: str) -> None:
    text = f"{label} 123456789"
    assert reference_or_amount_before(text, len(text) - 9)


@pytest.mark.parametrize(
    "label", ["Número de pedido:", "Factura", "Cliente", "Referencia", "número de seguimiento"]
)
def test_negative_cues_keep_business_numbers(detector: RuleDetector, label: str) -> None:
    assert _found(detector, f"{label} 5550123456.") == []


def test_ner_keeps_a_number_after_a_spanish_id_label() -> None:
    # The Spanish reference words are rules-only until LAB-1787; an ID label still counts.
    text = "DNI 5550123456 del titular."
    assert number_verdict(text, 4, 14)


def test_llm_profile_and_prompt() -> None:
    from pii_guard.detect.llm import build_messages, language_profile

    profile = language_profile("es-ES")
    assert (profile.code, profile.name, profile.allow_suffix) == ("es", "Spanish", False)
    system = build_messages("Texto", "es")[0]["content"]
    assert "DNI" in system and "NIE" in system
