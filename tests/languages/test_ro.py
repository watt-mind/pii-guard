"""The Romanian pack (LAB-1778): checksums, rules, cues, case endings. All values are fictional."""

from __future__ import annotations

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pii_guard.detect.rules import RuleDetector
from pii_guard.languages.ro.checksums import (
    cif_check_digit,
    cnp_birth_date,
    cnp_check_digit,
    is_valid_cif,
    is_valid_cnp,
)
from pii_guard.languages.ro.forms import SURFACE_FORMS
from pii_guard.languages.ro.inflection import RomanianCaseMatcher
from pii_guard.types import EntityType as E
from pii_guard.types import Span
from pii_guard.vault import Vault

# Made-up payloads with computed check digits (issued to nobody).
CNP = "285031040123" + str(cnp_check_digit("285031040123"))  # 10 March 1985, Bucharest S1
CNP_2000 = "500022912001" + str(cnp_check_digit("500022912001"))  # 29 February 2000
CNP_FOREIGN = "700022912002" + str(cnp_check_digit("700022912002"))  # 29 Feb 1900 or 2000
CIF = "1234567" + str(cif_check_digit("1234567"))
CIF_SHORT = "99" + str(cif_check_digit("99"))
MATCHER = RomanianCaseMatcher()
_WEIGHTS = (2, 7, 9, 1, 4, 6, 3, 5, 8, 2, 7, 9)  # the CNP's, from the published structure


def _bump(value: str, index: int = -1) -> str:
    """The value with one digit changed: every check digit here catches that."""
    i = index % len(value)
    return value[:i] + str((int(value[i]) + 1) % 10) + value[i + 1 :]


@pytest.fixture(scope="module")
def detector() -> RuleDetector:
    return RuleDetector()


def _found(detector: RuleDetector, text: str, language: str = "ro") -> list[tuple[str, str]]:
    return [(s.entity_type.value, s.text) for s in detector.detect(text, language)]


# --- Checksums ---------------------------------------------------------------------------


def test_worked_cnp_example() -> None:
    # 1 8 0 0 8 1 7 1 2 3 4 5 weighted 2 7 9 1 4 6 3 5 8 2 7 9 sums to 217; 217 mod 11 = 8.
    assert cnp_check_digit("180081712345") == 8
    assert is_valid_cnp("1800817123458")  # the EU-wave gate's value (eu/ro-smoke.jsonl)


def test_cnp_remainder_ten_counts_as_one() -> None:
    payload = next(
        p
        for p in (f"18501011{n:04d}" for n in range(10000))
        if sum(int(d) * w for d, w in zip(p, _WEIGHTS, strict=True)) % 11 == 10
    )
    assert cnp_check_digit(payload) == 1
    assert is_valid_cnp(payload + "1") and not is_valid_cnp(payload + "0")


def test_valid_cnps() -> None:
    for value in (CNP, CNP_2000, CNP_FOREIGN):
        assert is_valid_cnp(value), value


@pytest.mark.parametrize(
    ("value", "year"),
    [("1850310", 1985), ("2850310", 1985), ("3850310", 1885), ("5020229", None), ("6000229", 2000)],
)
def test_cnp_centuries(value: str, year: int | None) -> None:
    date = cnp_birth_date(value)
    assert (date[0] if date else None) == year  # 29 February 2002 does not exist


def test_century_less_cnps_take_either_century() -> None:
    # 29 February 1900 does not exist, 29 February 2000 does: a foreign resident's CNP is fine.
    assert cnp_birth_date("7000229") == (2000, 2, 29)
    assert cnp_birth_date("1000229") is None


@pytest.mark.parametrize(
    "value",
    [
        _bump(CNP),  # check digit
        _bump(CNP, 8),  # a county digit
        "0" + CNP[1:],  # sex/century 0
        CNP[:3] + "13" + CNP[5:],  # month 13
        CNP[:3] + "00" + CNP[5:],  # month 0
        CNP[:5] + "32" + CNP[7:],  # day 32
        CNP[:7] + "00" + CNP[9:],  # county 00
        CNP[:7] + "53" + CNP[9:],  # county 53
        CNP[:12],
        CNP + "0",
        CNP[:12] + "x",
        "".join(chr(0xFF10 + int(d)) for d in CNP),  # fullwidth digits
    ],
)
def test_invalid_cnps(value: str) -> None:
    assert not is_valid_cnp(value)


@given(st.text("0123456789", min_size=12, max_size=12))
def test_a_wrong_cnp_check_digit_is_rejected(payload: str) -> None:
    good = cnp_check_digit(payload)
    assert not is_valid_cnp(payload + str((good + 1) % 10))


def test_cif() -> None:
    # 1 2 3 4 5 6 7 right-aligned under 7 5 3 2 1 7 5 3 2, i.e. 3 2 1 7 5 3 2:
    # 3+4+3+28+25+18+14 = 95; 950 mod 11 = 4.
    assert cif_check_digit("1234567") == 4
    assert is_valid_cif(CIF) and is_valid_cif(CIF_SHORT)
    for value in (_bump(CIF), "0" + CIF, "1", CIF + "1" * 3, "12345678x"):
        assert not is_valid_cif(value), value


@given(st.text("0123456789", min_size=1, max_size=9).filter(lambda p: p[0] != "0"))
def test_cif_check_digit_round_trip(payload: str) -> None:
    check = cif_check_digit(payload)
    assert is_valid_cif(payload + str(check))
    assert not is_valid_cif(payload + str((check + 1) % 10))


def test_check_digit_arguments_are_validated() -> None:
    for call in (
        lambda: cnp_check_digit("12345"),
        lambda: cnp_check_digit("12345678901x"),
        lambda: cif_check_digit(""),
        lambda: cif_check_digit("1234567890"),
    ):
        with pytest.raises(ValueError):
            call()


# --- Rules -------------------------------------------------------------------------------


def test_identifiers(detector: RuleDetector) -> None:
    assert _found(detector, f"CNP {CNP}") == [("ID_DOCUMENT", CNP)]
    assert _found(detector, f"Subsemnatul, născut în 1985, {CNP}.") == [("ID_DOCUMENT", CNP)]
    assert _found(detector, f"CUI: RO{CIF}") == [("ID_DOCUMENT", f"RO{CIF}")]
    assert _found(detector, f"cod fiscal {CIF_SHORT}") == [("ID_DOCUMENT", CIF_SHORT)]
    assert _found(detector, "CI seria RX nr. 123456") == [("ID_DOCUMENT", "RX nr. 123456")]
    assert _found(detector, "buletinul KX 234567") == [("ID_DOCUMENT", "KX 234567")]


def test_scopes(detector: RuleDetector) -> None:
    # A CNP validates fully: found in any language ...
    for language in ("en", "de", "hu", "pl"):
        assert _found(detector, f"Applicant {CNP} confirmed.", language) == [("ID_DOCUMENT", CNP)]
    # ... a labelled CIF, an ID card number or an address only in Romanian text (a grouped
    # "0721 234 567" is a phone number to the English and German rules already).
    for text in (f"CUI {CIF}", "seria RX 123456", "Strada Teilor nr. 15"):
        assert _found(detector, text, "en") == [], text
        assert _found(detector, text, "ro") != [], text


def test_a_cif_needs_its_label(detector: RuleDetector) -> None:
    assert _found(detector, f"Am plătit {CIF} pentru {CIF_SHORT} bucăți.") == []


def test_bad_check_digits_are_masked_after_a_cue(detector: RuleDetector) -> None:
    # Unvalidated, at the cue score: a mistyped identifier is still personal data.
    for text, value in (
        ("CNP", _bump(CNP)),
        ("codul numeric personal", _bump(CNP)),
        ("pașaport nr.", "051234567"),
        ("paşaportul", "051234567"),  # cedilla
        ("permis de conducere nr.", "12345678AB"),
    ):
        spans = detector.detect(f"{text} {value}.", "ro")
        assert [(s.entity_type, s.text) for s in spans] == [(E.ID_DOCUMENT, value)], text


@pytest.mark.parametrize(
    "text",
    [
        "0721 234 567",
        "0721-234-567",
        "0721.234.567",
        "0721234567",
        "021 555 0123",
        "021 312 34 56",
        "(021) 555 0123",
        "0264 555 012",
        "0264/555012",
        "+40 744 120 556",
    ],
)
def test_phone_numbers(detector: RuleDetector, text: str) -> None:
    assert _found(detector, f"Contact: {text}.") == [("PHONE", text)]


def test_a_speaker_label_is_no_reference(detector: RuleDetector) -> None:
    assert _found(detector, "Client: 0744 120 556.") == [("PHONE", "0744 120 556")]


@pytest.mark.parametrize(
    "text",
    [
        "Strada Teilor nr. 15, ap. 7, 400123 Cluj-Napoca",
        "Str. Mihai Eminescu nr. 7, 300011 Timișoara, jud. Timiș",
        "Bd. Unirii nr. 40, bl. A3, sc. 2, et. 4, ap. 7, sector 3, 030167 București",
        "Calea lui Traian 12, 550001 Sibiu",
        "Şoseaua Kiseleff nr. 5, sector 1",  # cedilla
        "Bulevardul 1 Decembrie 1918 nr. 3",
        "Aleea Teilor nr. 2",
    ],
)
def test_addresses(detector: RuleDetector, text: str) -> None:
    assert _found(detector, f"locuiește în {text}.") == [("ADDRESS", text)]


def test_postcode_at_the_start_of_a_line(detector: RuleDetector) -> None:
    assert _found(detector, "Ioana Probă\n400123 Cluj-Napoca") == [
        ("ADDRESS", "400123 Cluj-Napoca")
    ]


@pytest.mark.parametrize(
    "text",
    [
        "La târg au participat 200000 de persoane timp de 18 luni.",
        f"Factura nr. {CNP} din 12.10.2026.",  # a valid CNP shape after an invoice label
        f"Numărul comenzii {_bump(CNP)}, AWB 1029384756.",
        "Comanda nr. 0712345678 a fost expediată.",
        "Bugetul de 1.250.000,00 lei acoperă perioada 2026-2030, din 02.11.2026.",
        "Chiria crește din 01.01.2027 cu 2,5 la sută, la 2.400 lei.",
        f"Am plătit {CIF} lei.",
        "Ne-am auzit pe Calea Zoom 3 ori, apoi 400123 Lei.",
        "Codul clientului 4500123456; referința 2026-77812-AB.",
    ],
)
def test_hard_negatives(detector: RuleDetector, text: str) -> None:
    assert _found(detector, text) == []


def test_si_ends_a_cue_window(detector: RuleDetector) -> None:
    # "telefonul și numărul comenzii": the order number is not a phone number, with either "ș".
    for conjunction in ("și", "şi", "si"):
        text = f"Telefonul {conjunction} numărul comenzii 4500123456"
        assert _found(detector, text) == [], conjunction


# --- Case endings ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "allowed", "refused"),
    [
        ("Popescu", ["lui", "l", "le"], ["ului", "ei", "a"]),
        ("Marin", ["ului", "ul", "ule"], ["lui", "ei"]),
        ("Maria", [], ["ei", "lui", "a"]),  # the stem changes: variant_stems
        ("Andrei", [], ["ului", "lui"]),
        ("SRL", ["-ului", "-ul"], ["ului", "ul"]),
        ("1800817123458", [], ["ul"]),
    ],
)
def test_case_endings(value: str, allowed: list[str], refused: list[str]) -> None:
    pattern = MATCHER.suffix_pattern(value, E.PERSON)
    for ending in allowed:
        assert re.fullmatch(pattern, ending), ending
    for ending in refused:
        assert not pattern or not re.fullmatch(pattern, ending), ending


@pytest.mark.parametrize(
    ("value", "stem", "endings"),
    [
        ("Maria", "Mari", ["ei"]),
        ("Ioana", "Ioan", ["ei", "o"]),
        ("Andreea", "Andree", ["i"]),
        ("Monica", "Monic", ["ăi", "o"]),
        ("Popescu Maria", "Popescu Mari", ["ei"]),
    ],
)
def test_stem_changes(value: str, stem: str, endings: list[str]) -> None:
    [(found, pattern)] = MATCHER.variant_stems(value, E.PERSON)
    assert found == stem
    for ending in endings:
        assert re.fullmatch(pattern, ending), ending
    assert not re.fullmatch(pattern, "a")


def test_no_stem_change_for_codes_or_other_types() -> None:
    assert MATCHER.variant_stems("Maria", E.EMAIL) == []
    assert MATCHER.variant_stems("ABCA", E.PERSON) == []
    assert MATCHER.variant_stems("Popescu", E.PERSON) == []


def test_splits() -> None:
    def readings(surface: str) -> list[tuple[str, str, bool]]:
        return [(s.lemma, s.suffix, s.strong) for s in MATCHER.splits(surface, E.PERSON)]

    assert readings("Mariei") == [("Maria", "ei", True)]
    assert readings("Monicăi") == [("Monica", "ăi", True)]
    assert readings("Andreei") == [("Andreea", "i", True)]
    assert readings("Ioanei") == [("Ioana", "ei", False)]  # weak: Andrei, Matei are names
    assert readings("Popescului") == [("Popescu", "lui", True)]
    assert ("Radu", "le", False) in readings("Radule")
    assert readings("Ana") == []  # too short to read an ending off


@pytest.mark.parametrize(
    ("lemma", "suffix", "restored"),
    [
        ("Maria", "ei", "Mariei"),
        ("Maria", "-ei", "Mariei"),
        ("Ioana", "o", "Ioano"),
        ("Monica", "ei", "Monicăi"),
        ("Andreea", "ei", "Andreei"),
        ("Popescu Maria", "ei", "Popescu Mariei"),
        ("Popescu", "ului", "Popescului"),
        ("Popescu", "lui", "Popescului"),
        ("Marin", "ului", "Marinului"),
        ("SRL", "-ului", "SRL-ului"),
    ],
)
def test_restore(lemma: str, suffix: str, restored: str) -> None:
    assert MATCHER.restore(lemma, suffix, E.PERSON) == restored


def _session_mask(text: str, values: list[str]) -> tuple[str, str]:
    session = Vault(b"ro-pack-test-key-01").session()
    spans = []
    for value in values:
        start = text.index(value)
        spans.append(Span(start, start + len(value), E.PERSON, value, 1.0, "t"))
    masked = session.mask(text, spans, language="ro")
    return masked, session.unmask(masked)


def test_a_declined_given_name_shares_the_placeholder() -> None:
    text = "Maria a semnat. Cheile au fost date Mariei, iar Popescu Maria le-a primit."
    masked, unmasked = _session_mask(text, ["Maria", "Popescu Maria"])
    placeholder = masked.split(" ", 1)[0]
    assert f"{placeholder}ei," in masked  # Mariei -> [[PERSON_x]]ei
    assert "Mari" not in masked and "Popescu" not in masked
    assert unmasked == text


def test_surname_first_declines_at_the_end() -> None:
    text = "Popescu Maria a semnat; documentul se eliberează doamnei Popescu Mariei."
    masked, unmasked = _session_mask(text, ["Popescu Maria"])
    placeholder = masked.split(" ", 1)[0]
    assert masked.count(placeholder) == 2 and f"{placeholder}ei." in masked
    assert "Popescu" not in masked and unmasked == text


def test_a_detected_dative_form_is_split_onto_its_nominative() -> None:
    text = "Maria Popescu a semnat. I-am trimis Mariei contractul, avocatul Popescului l-a citit."
    masked, unmasked = _session_mask(text, ["Maria Popescu", "Mariei", "Popescului"])
    assert "Mari" not in masked and "Popescu" not in masked
    assert unmasked == text


def test_a_declined_full_name_is_masked_and_restored() -> None:
    # The given name declines inside the value (Maria Popescu -> Mariei Popescu): the vault
    # keys the declined form on its own (see inflection.py), so it never leaks.
    text = "Maria Popescu a semnat. Cheile au fost date Mariei Popescu."
    masked, unmasked = _session_mask(text, ["Maria Popescu", "Mariei Popescu"])
    assert "Mari" not in masked and "Popescu" not in masked
    assert unmasked == text


def test_unmask_re_inflects_a_suffix_the_model_added() -> None:
    session = Vault(b"ro-pack-test-key-02").session()
    masked = session.mask(
        "Maria a sunat.", [Span(0, 5, E.PERSON, "Maria", 1.0, "t")], language="ro"
    )
    placeholder = masked.split(" ", 1)[0]
    assert session.unmask(f"I-am răspuns {placeholder}ei.") == "I-am răspuns Mariei."


def test_eval_surface_forms_see_a_declined_given_name() -> None:
    variants = SURFACE_FORMS.stem_variants("Maria Popescu", E.PERSON)
    assert any(re.fullmatch(v, "Mariei Popescu") for v in variants)
    assert any(
        re.fullmatch(v, "Popescu Mariei")
        for v in SURFACE_FORMS.stem_variants("Popescu Maria", E.PERSON)
    )
    assert SURFACE_FORMS.stem_variants("Maria", E.EMAIL) == []
    assert "strada" in SURFACE_FORMS.stopwords


def test_llm_profile_and_prompt() -> None:
    from pii_guard.detect.llm import build_messages, language_profile

    profile = language_profile("ro-RO")
    assert (profile.code, profile.name, profile.allow_suffix) == ("ro", "Romanian", True)
    system = build_messages("Text", "ro")[0]["content"]
    assert "CNP" in system and "Mariei" in system


def test_captions_have_both_spellings_of_s_and_t() -> None:
    from pii_guard.languages import get_pack

    pack = get_pack("ro")
    assert pack is not None and pack.captions is not None
    text = pack.captions.read_text(encoding="utf-8")
    for comma, cedilla in (("Cetățenie", "Cetăţenie"), ("Data nașterii", "Data naşterii")):
        assert comma in text and cedilla in text
