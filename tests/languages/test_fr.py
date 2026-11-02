"""The French pack (LAB-1774): checksums, rules, cues, elision. All values are fictional."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pii_guard.detect.rules import RuleDetector
from pii_guard.detect.rules._base import reference_or_amount_before
from pii_guard.languages.fr.checksums import (
    is_valid_nir,
    is_valid_spi,
    nir_key,
    nir_month_is_calendar,
    spi_check,
)
from pii_guard.types import EntityType as E
from pii_guard.types import Span
from pii_guard.vault import Vault

# Made-up payloads with computed keys (issued to nobody).
NIR = "1850578006084" + f"{nir_key('1850578006084'):02d}"
NIR_GROUPED = " ".join((NIR[0], NIR[1:3], NIR[3:5], NIR[5:7], NIR[7:10], NIR[10:13], NIR[13:]))
NIR_2A = "153072A073004" + f"{nir_key('153072A073004'):02d}"  # Corse-du-Sud
NIR_2B = "253072B073004" + f"{nir_key('253072B073004'):02d}"  # Haute-Corse
NIR_PSEUDO_MONTH = "1853578006084" + f"{nir_key('1853578006084'):02d}"  # month 35: incomplete act
SPI = "2701234567" + spi_check("2701234567")
SPI_GROUPED = f"{SPI[:2]} {SPI[2:4]} {SPI[4:7]} {SPI[7:10]} {SPI[10:]}"


def _bump(value: str, index: int = -1) -> str:
    """The value with one digit changed."""
    i = index % len(value)
    return value[:i] + str((int(value[i]) + 1) % 10) + value[i + 1 :]


@pytest.fixture(scope="module")
def detector() -> RuleDetector:
    return RuleDetector()


def _found(detector: RuleDetector, text: str, language: str = "fr") -> list[tuple[str, str]]:
    return [(s.entity_type.value, s.text) for s in detector.detect(text, language)]


# --- Checksums ---------------------------------------------------------------------------


def test_published_algorithm_examples() -> None:
    # The DGFiP's worked example of the SPI algorithm (first ten digits 3023217600, check 053)
    # and the examples in the public descriptions of the NIR and SPI checks.
    assert spi_check("3023217600") == "053"
    assert is_valid_spi("3023217600053")
    assert is_valid_spi("0701987765493")
    assert is_valid_nir("295109912611193")
    assert nir_key("2951099126111") == 93


def test_valid_values() -> None:
    for value in (NIR, NIR_2A, NIR_2B, NIR_PSEUDO_MONTH):
        assert is_valid_nir(value), value
    assert is_valid_spi(SPI)


def test_corsica_counts_as_19_and_18() -> None:
    assert nir_key("153072A073004") == 97 - int("1530719073004") % 97
    assert nir_key("253072B073004") == 97 - int("2530718073004") % 97
    # The letters are not interchangeable, and no other letter is a department.
    assert not is_valid_nir(NIR_2A.replace("2A", "2B"))
    assert not is_valid_nir(NIR_2A.replace("2A", "2C"))
    assert not is_valid_nir(NIR_2A.lower())


@pytest.mark.parametrize(
    "value",
    [
        _bump(NIR),  # key
        _bump(NIR, 6),  # another digit
        "5" + NIR[1:],  # sex 5
        NIR[:3] + "14" + NIR[5:],  # month 14
        NIR[:3] + "00" + NIR[5:],  # month 0
        NIR[:5] + "00" + NIR[7:],  # department 00
        NIR[:13] + "00",  # key 00 is never issued
        NIR[:14],
        NIR + "0",
        "18505780060x436",
        "".join(chr(0xFF10 + int(d)) for d in NIR),  # fullwidth digits
    ],
)
def test_invalid_nirs(value: str) -> None:
    assert not is_valid_nir(value)


def test_calendar_month_and_sex() -> None:
    assert nir_month_is_calendar(NIR) and nir_month_is_calendar(NIR_2A)
    assert not nir_month_is_calendar(NIR_PSEUDO_MONTH)
    assert not nir_month_is_calendar("7" + NIR[1:])


@pytest.mark.parametrize(
    "value", [_bump(SPI), _bump(SPI, 3), "4" + SPI[1:], SPI[:12], SPI + "1", "27012345x7000"]
)
def test_invalid_spis(value: str) -> None:
    assert not is_valid_spi(value)


@given(st.text("0123456789", min_size=13, max_size=13))
def test_a_wrong_nir_key_is_rejected(payload: str) -> None:
    key = nir_key(payload)
    assert not is_valid_nir(f"{payload}{key % 97 + 1:02d}")


@given(st.text("0123", min_size=1, max_size=1), st.text("0123456789", min_size=9, max_size=9))
def test_spi_check_round_trip(first: str, rest: str) -> None:
    payload = first + rest
    assert is_valid_spi(payload + spi_check(payload))
    assert not is_valid_spi(payload + f"{(int(spi_check(payload)) + 1) % 1000:03d}")


def test_check_arguments_are_validated() -> None:
    for call in (
        lambda: nir_key("12345"),
        lambda: nir_key("185057800608x"),
        lambda: spi_check("123456789"),
    ):
        with pytest.raises(ValueError):
            call()


# --- Rules -------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [NIR, NIR_GROUPED, f"{NIR[:13]} {NIR[13:]}"])
def test_nir_layouts(detector: RuleDetector, value: str) -> None:
    assert _found(detector, f"N° de sécurité sociale : {value}") == [("ID_DOCUMENT", value)]
    assert _found(detector, f"Assuré {value}, Lyon") == [("ID_DOCUMENT", value)]


def test_nir_scopes(detector: RuleDetector) -> None:
    # A NIR with a calendar month is found in every language, labelled or not ...
    for language in ("en", "de", "hu", "pl"):
        assert _found(detector, f"Insured: {NIR_GROUPED}.", language) == [
            ("ID_DOCUMENT", NIR_GROUPED)
        ]
    # ... a rarer field code (a pseudo-month, Corsica's letters are fine) only after a label.
    assert _found(detector, f"Insured {NIR_PSEUDO_MONTH}.", "en") == []
    assert _found(detector, f"NIR {NIR_PSEUDO_MONTH}.", "en") == [("ID_DOCUMENT", NIR_PSEUDO_MONTH)]
    assert _found(detector, f"Patient {NIR_2A}", "en") == [("ID_DOCUMENT", NIR_2A)]


def test_nir_label_is_a_whole_word(detector: RuleDetector) -> None:
    # "nir" inside "fournir" is no label: a pseudo-month NIR after it stays unmasked.
    assert _found(detector, f"Merci de fournir {NIR_PSEUDO_MONTH}.") == []


def test_spi_needs_its_label(detector: RuleDetector) -> None:
    for value in (SPI, SPI_GROUPED):
        assert _found(detector, f"Numéro fiscal : {value}") == [("ID_DOCUMENT", value)]
        assert _found(detector, f"tax number (numéro fiscal) {value}", "en") == [
            ("ID_DOCUMENT", value)
        ]
    assert _found(detector, f"Code produit {SPI}.") == []
    assert _found(detector, f"Article {SPI_GROUPED}.") == []


def test_bad_keys_are_masked_after_a_cue(detector: RuleDetector) -> None:
    # Unvalidated, at the cue score: a mistyped identifier is still personal data.
    for label, value in (
        ("numéro de sécurité sociale", _bump(NIR)),
        ("numéro fiscal", _bump(SPI)),
        ("carte Vitale", _bump(NIR)),
    ):
        spans = detector.detect(f"{label} {value}.", "fr")
        assert [(s.entity_type, s.text) for s in spans] == [(E.ID_DOCUMENT, value)], label
        assert all(s.score == pytest.approx(0.6) for s in spans)


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("passeport n° 19ZZ00123, valable", "19ZZ00123"),
        ("Passeport : 19ZZ00123", "19ZZ00123"),
        ("carte d'identité n° : X4RTZZ123.", "X4RTZZ123"),
        ("CNI n° 123456789012.", "123456789012"),
        ("permis de conduire n° 13AB00123", "13AB00123"),
        ("titre de séjour no 1234567890", "1234567890"),
    ],
)
def test_documents_after_their_label(detector: RuleDetector, text: str, value: str) -> None:
    assert _found(detector, text) == [("ID_DOCUMENT", value)]


@pytest.mark.parametrize(
    "text",
    ["06 39 98 12 34", "01 99 00 12 34", "01.99.00.45.67", "06-39-98-00-12", "0639980123"],
)
def test_phone_numbers(detector: RuleDetector, text: str) -> None:
    assert _found(detector, f"Appelez le {text}.") == [("PHONE", text)]
    assert _found(detector, f"Client : {text}.") == [("PHONE", text)]  # a chat speaker label


@pytest.mark.parametrize(
    "text",
    [
        "12 rue des Lilas, 69003 Lyon",
        "8 avenue Jean Jaurès, 31000 Toulouse",
        "3 place de la République\n75011 Paris",
        "13 bis avenue du Général de Gaulle, 13100 Aix-en-Provence Cedex 1",
        "5 impasse d'Alsace",
        "7 rue du 8 Mai 1945",
        "2 boulevard Saint-Michel 75006 Paris",
    ],
)
def test_addresses(detector: RuleDetector, text: str) -> None:
    assert _found(detector, f"demeurant {text}.") == [("ADDRESS", text)]


def test_postcode_where_an_address_line_starts(detector: RuleDetector) -> None:
    assert _found(detector, "Claire Exemple\n75008 Paris") == [("ADDRESS", "75008 Paris")]
    assert _found(detector, "Mme Exemple, 69003 Lyon") == [("ADDRESS", "69003 Lyon")]
    assert _found(detector, "le bureau de 75008 Paris") == []


def test_french_formats_are_french_only(detector: RuleDetector) -> None:
    for text in ("Appelez le 06 39 98 12 34.", "12 rue des Lilas, 69003 Lyon", "\n75008 Paris"):
        assert _found(detector, text, "en") == [], text
        assert _found(detector, text, "fr") != [], text


@pytest.mark.parametrize(
    "text",
    [
        "Le salon a accueilli 20000 visiteurs en 18 mois.",
        "20000 Participants ont répondu.",
        "Il y a 12 rues et 3 places dans le quartier.",
        f"Numéro de commande {_bump(NIR)}, dossier RG 26/01234.",
        f"Facture n° {NIR} du 01.02.2026.",  # a valid NIR shape after an invoice label
        f"Commande n° {NIR_GROUPED}.",
        f"Facture n° {SPI}, montant 1 240,00 €.",
        "La délibération n° 12/2026 attribue 500 000 000 € pour 2026-2030.",
        "Le loyer de 2 400 € augmentera de 2,5 % au 01.01.2027.",
        "SIRET 123 456 789 00012, SIREN 123456789.",
        "75008 Paris SAS, siège social.",
        "Passeport n° du titulaire : à compléter.",
        "Le permis n° 2026 est accordé.",
    ],
)
def test_hard_negatives(detector: RuleDetector, text: str) -> None:
    assert _found(detector, text) == []


@pytest.mark.parametrize(
    "label", ["Facture", "Numéro de commande :", "Bon de commande", "Devis", "Réservation"]
)
def test_french_reference_labels_are_shared(label: str) -> None:
    text = f"{label} 123456789"
    assert reference_or_amount_before(text, len(text) - 9)


# --- Cues --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "entity_type", "value"),
    [
        ("Téléphone : 0044 20 7946 0123", "PHONE", "0044 20 7946 0123"),
        ("RIB 12345 00001 00012345678 90", "BANK_ACCOUNT", "12345 00001 00012345678 90"),
        ("numéro de passeport : 19ZZ00123", "ID_DOCUMENT", "19ZZ00123"),
        ("permis de conduire 13AB00123", "ID_DOCUMENT", "13AB00123"),
    ],
)
def test_cues(detector: RuleDetector, text: str, entity_type: str, value: str) -> None:
    assert _found(detector, text) == [(entity_type, value)]


@pytest.mark.parametrize(
    "text",
    [
        "Numéro de commande 100045123987",
        "Téléphone et numéro de commande 4500123456",  # "et" hands the window on
        "Référence 4400123456",
        "SIRET 12345678900012",
    ],
)
def test_negative_cues_end_the_window(detector: RuleDetector, text: str) -> None:
    assert _found(detector, text) == []


# --- Elision -----------------------------------------------------------------------------


def test_elided_names_are_masked_and_restored() -> None:
    session = Vault(b"fr-pack-test-key-01").session()
    text = "L'avis d'Hélène Garnier est clair ; selon Garnier, l'Ardent a signé."
    spans = [
        Span(text.index("Hélène"), text.index("Hélène") + 14, E.PERSON, "Hélène Garnier", 1, "t"),
        Span(text.index("Garnier,"), text.index("Garnier,") + 7, E.PERSON, "Garnier", 1, "t"),
        Span(text.index("Ardent"), text.index("Ardent") + 6, E.PERSON, "Ardent", 1, "t"),
    ]
    masked = session.mask(text, spans, language="fr")
    assert "Garnier" not in masked and "Ardent" not in masked
    assert "d'[[PERSON_" in masked and "l'[[PERSON_" in masked
    assert session.unmask(masked) == text


def test_llm_profile_and_prompt() -> None:
    from pii_guard.detect.llm import build_messages, language_profile

    profile = language_profile("fr-FR")
    assert (profile.code, profile.name, profile.allow_suffix) == ("fr", "French", False)
    system = build_messages("Texte", "fr")[0]["content"]
    assert "NIR" in system and "d'Hélène Garnier" in system
