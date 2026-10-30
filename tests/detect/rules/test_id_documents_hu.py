"""Hungarian ID documents: personal ID number, document numbers by label, MRZ, look-alikes.

Every value is fictional: payloads are made up and check digits computed from them; the MRZ
specimens are ICAO Doc 9303's fictional state of Utopia, or built here for a made-up holder.
"""

from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pii_guard.detect.checksums import hu_personal_id_check_digit, mrz_check_digit
from pii_guard.detect.rules import RuleDetector
from pii_guard.types import EntityType as E


@pytest.fixture(scope="module")
def detector() -> RuleDetector:
    # The validated rules on their own: a cue word before a checksum-failing number masks it
    # anyway (cued numbers, tests/languages/test_cues.py), which the look-alikes here exclude.
    return RuleDetector(cued_numbers=False)


def ids(detector: RuleDetector, text: str, language: str = "hu") -> list[tuple[str, float]]:
    return [
        (s.text, s.score)
        for s in detector.detect(text, language=language)
        if s.entity_type is E.ID_DOCUMENT
    ]


def personal_id(payload10: str) -> str:
    check = hu_personal_id_check_digit(payload10)
    assert check is not None
    return payload10 + str(check)


PID = personal_id("1710304123")  # born 1971-03-04
PID_NEW = personal_id("5050607012")  # born 2005-06-07: reversed weights


# --- Personal identification number -----------------------------------------


@pytest.mark.parametrize(
    "written",
    [PID, f"{PID[0]}-{PID[1:7]}-{PID[7:]}", f"{PID[0]} {PID[1:7]} {PID[7:]}", PID_NEW],
)
def test_personal_id_in_context(detector: RuleDetector, written: str) -> None:
    text = f"Személyi azonosító: {written}, lakcím: ismeretlen"
    assert ids(detector, text) == [(written, 0.99)]


def test_personal_id_without_context_scores_lower_and_runs_everywhere(
    detector: RuleDetector,
) -> None:
    assert ids(detector, f"Applicant {PID} attached.", language="en") == [(PID, 0.85)]


@pytest.mark.parametrize(
    "text",
    [
        f"{PID[:10]}{(int(PID[10]) + 1) % 10}",  # wrong check digit
        f"9{PID[1:]}",  # not a sex/century digit
        f"{PID}5",  # part of a longer number
        f"1 {PID}",  # part of a space-grouped number
        f"{PID} Ft",  # an amount
    ],
)
def test_personal_id_look_alikes(detector: RuleDetector, text: str) -> None:
    assert ids(detector, f"személyi szám: {text}") == []


def _valid_first_digits(born: date) -> str:
    """Sex/century digits an ID issued for ``born`` can carry (LAB-1298).

    The generator used to draw the first digit independently of the date, producing
    never-issued combos (an 1800s digit with a 1900s birth, a 2000s digit with a date
    before 2000). The checksum helper accepts those, but no authority issues them, so
    every generated value is now one that could have been issued."""
    return "1278" if born.year < 2000 else "56"


@given(
    parts=st.dates(min_value=date(1900, 1, 1), max_value=date(2099, 12, 31)).flatmap(
        lambda born: st.tuples(
            st.just(born),
            st.sampled_from(_valid_first_digits(born)),
            st.integers(0, 999),
        )
    ),
)
def test_any_valid_personal_id_is_found(parts: tuple[date, str, int]) -> None:
    born, first, serial = parts
    payload = f"{first}{born:%y%m%d}{serial:03d}"
    check = hu_personal_id_check_digit(payload)
    if check is None:
        return
    value = payload + str(check)
    found = RuleDetector().detect(f"személyi azonosító jele: {value}.")
    assert [(s.text, s.entity_type) for s in found] == [(value, E.ID_DOCUMENT)]


def test_personal_id_generator_boundaries() -> None:
    """LAB-1298: pinned edges of the generator space (leap day, serial ends, the
    1997-01-01 weight switch, every issuable century digit). A recurrence of the
    once-seen xdist failure reproduces here without the full suite."""
    cases = [
        ("5", date(2000, 2, 29), 0),  # leap day with a 2000s digit
        ("6", date(2099, 12, 31), 999),  # serial top
        ("1", date(1900, 1, 1), 0),  # serial bottom
        ("8", date(1996, 12, 31), 500),  # pre-1997 weights, foreign-resident digit
        ("2", date(1997, 1, 1), 1),  # reversed weights from 1997-01-01
        ("7", date(1950, 6, 15), 123),
    ]
    for first, born, serial in cases:
        payload = f"{first}{born:%y%m%d}{serial:03d}"
        check = hu_personal_id_check_digit(payload)
        assert check is not None, payload
        value = payload + str(check)
        found = RuleDetector().detect(f"személyi azonosító jele: {value}.")
        assert [(s.text, s.entity_type) for s in found] == [(value, E.ID_DOCUMENT)]


# --- Document numbers next to their label ---------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("személyi igazolvány száma: {}, TAJ", "123456AB"),
        ("Személyi ig. szám: {})", "987654EF"),
        ("személyazonosító igazolvány: {}", "234567GH"),
        ("a szigszamat is lefotoztam: {}. a cime", "654321CD"),
        ("szig.: {}", "345678IJ"),
        ("Okmányazonosító: {}", "456789KL"),
        ("Az útlevél ({}) megérkezett.", "BA1234567"),
        ("útlevélszám: {}", "BC765432"),
        ("Vezetői engedély száma: {}.", "CB765432"),
        ("jogositvany: {}", "CA123456"),
        ("a {} számú személyi igazolvánnyal rendelkező", "123456AB"),
        ("a {} sz. útlevéllel", "AB2345678"),
        ("Hungarian ID card {} expired", "123456AB"),
        ("passport no. {}", "BA1234567"),
    ],
)
def test_known_formats_next_to_their_label(detector: RuleDetector, text: str, value: str) -> None:
    assert ids(detector, text.format(value)) == [(value, 0.95)]


def test_labelled_documents_run_in_any_language(detector: RuleDetector) -> None:
    text = "Her személyi igazolvány száma: 123456AB."
    assert ids(detector, text, language="en") == [("123456AB", 0.95)]


def test_other_formats_after_their_label_score_lower(detector: RuleDetector) -> None:
    text = "tartózkodási engedély száma: HU12345X9, kiállítva"
    assert ids(detector, text) == [("HU12345X9", 0.85)]


def test_a_bare_id_card_number_only_in_hungarian_and_lower(detector: RuleDetector) -> None:
    assert ids(detector, "Átvettem: 123456AB, köszönöm") == [("123456AB", 0.7)]
    assert ids(detector, "Received: 123456AB, thanks", language="en") == []


@pytest.mark.parametrize(
    "text",
    [
        "szigorúan bizalmas: AB1234567",  # "szig" inside another word is no label
        "rendelésszám: AB1234567",  # letters-first numbers need a document label
        "a termék kódja CB765432",
        "személyi igazolványát és lakcímkártyáját hozza magával",
        "személyi igazolvány száma: 2026.10.27.",  # a date, not a number
        "személyi igazolvány száma: 123456",  # digits only: no Hungarian document format
        "személyi igazolvány: 123456AB-12",  # part of a longer code
        "útlevél: ABCDEFGH",
    ],
)
def test_id_document_look_alikes(detector: RuleDetector, text: str) -> None:
    assert ids(detector, text) == []


@given(
    digits=st.integers(0, 999_999),
    letters=st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=2, max_size=2),
)
def test_any_id_card_number_after_its_label_is_found(digits: int, letters: str) -> None:
    value = f"{digits:06d}{letters}"
    found = RuleDetector().detect(f"Személyi igazolvány száma: {value}, kiállítva.")
    assert [(s.text, s.entity_type, s.score) for s in found] == [(value, E.ID_DOCUMENT, 0.95)]


# --- Machine-readable zones -----------------------------------------------------

TD3 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\nL898902C36UTO7408122F1204159ZE184226B<<<<<10"
TD1 = (
    "I<UTOD231458907<<<<<<<<<<<<<<<\n7408122F1204159UTO<<<<<<<<<<<6\nERIKSSON<<ANNA<MARIA<<<<<<<<<<"
)


def hungarian_td1() -> str:
    """A fictional holder's ID card zone, built with valid check digits."""
    number = "765432KL<"
    line1 = f"I<HUN{number}{mrz_check_digit(number)}".ljust(30, "<")
    head = f"950817{mrz_check_digit('950817')}F310817{mrz_check_digit('310817')}HUN".ljust(29, "<")
    line2 = head + str(mrz_check_digit(line1[5:30] + head[0:7] + head[8:15] + head[18:29]))
    return "\n".join((line1, line2, "PROBA<<PIROSKA".ljust(30, "<")))


@pytest.mark.parametrize("zone", [TD3, TD1, hungarian_td1()])
def test_a_valid_mrz_is_one_span(detector: RuleDetector, zone: str) -> None:
    text = f"Beolvasott okmány:\n{zone}\nVége."
    assert ids(detector, text, language="en") == [(zone, 0.99)]


def test_mrz_tolerates_ocr_indentation_and_crlf(detector: RuleDetector) -> None:
    line1, line2 = TD3.split("\n")
    text = f"  {line1}  \r\n {line2}\n"
    [(value, score)] = ids(detector, text)
    assert score == 0.99
    assert value.startswith("P<UTO") and value.endswith("<<<<<10")


def test_an_mrz_with_a_wrong_check_digit_scores_lower(detector: RuleDetector) -> None:
    broken = TD3[:-1] + "1"  # composite check digit off by one, as an OCR error would be
    assert ids(detector, broken) == [(broken, 0.8)]


@pytest.mark.parametrize(
    "text",
    [
        "P" + "A" * 43 + "\n" + "B" * 44,  # right shape, no "<<" name separator
        TD3.replace("\n", " "),  # not on two lines
        TD3.split("\n")[1],  # a single line
        TD1.rsplit("\n", 1)[0] + "\n" + "ERIKSSONANNAMARIA" + "X" * 13,  # TD1, no name separator
    ],
)
def test_mrz_look_alikes(detector: RuleDetector, text: str) -> None:
    assert ids(detector, text) == []
