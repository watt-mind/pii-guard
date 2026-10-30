"""Hungarian full-address recogniser: span, postcode<->settlement validation, look-alikes."""

# Seeded, reproducible sampling: the standard PRNG is the point.
# ruff: noqa: S311

from __future__ import annotations

import random

import pytest

from pii_guard.detect.rules import RuleDetector
from pii_guard.eval.identities import identity_generator
from pii_guard.lang import postcode_index
from pii_guard.languages.hu import rules as hu
from pii_guard.types import EntityType as E


@pytest.fixture(scope="module")
def detector() -> RuleDetector:
    return RuleDetector()


def addresses(detector: RuleDetector, text: str, language: str = "hu") -> list[tuple[str, float]]:
    return [
        (s.text, s.score)
        for s in detector.detect(text, language=language)
        if s.entity_type is E.ADDRESS
    ]


# (context with {} for the address, the address)
CONSISTENT = [
    ("lakcím: {} ), Vevő", "1051 Budapest, Minta utca 12. 3/5."),
    ("címe: {}. A havi", "9021 Győr, Gyöngyvirág utca 7. fszt. 2."),
    ("Lakcíme: {} adóazonosító", "6000 Kecskemét, Arany János utca 77. 6. em. 10."),
    ("a {} szám alatti", "3300 Eger, Mátyás király utca 11. fszt. 3."),
    ("Székhely: {} Adószám", "8000 Székesfehérvár, Vasút utca 98/B."),
    ("a cím {}", "1096 Budapest, Kitalált u. 2/b"),
    ("Új lakcímem: {} Régi", "2400 Dunaújváros,\nMinta Pál utca 9. 2. em. 8."),
    ("H-{}. Kérjük", "4026 Debrecen, Mintás tér 6."),
    ("{}", "1134 Budapest XIII. kerület, Váci út 41."),
    ("{} szám", "9022 Győr, Dózsa György út 23. 8/26."),
    ("{}.", "7621 Pécs, Szent István tér 18. 2. emelet 4. ajtó"),
    ("{}", "1056 Budapest, Belgrád rkp. 3."),
]


@pytest.mark.parametrize(("context", "address"), CONSISTENT)
def test_full_address_with_a_consistent_postcode(
    detector: RuleDetector, context: str, address: str
) -> None:
    assert addresses(detector, context.format(address)) == [(address, hu.SCORE_CONSISTENT)]


def test_consistent_postcode_case_from_lab_1298(detector: RuleDetector) -> None:
    """LAB-1298: this exact invocation failed once in a full local xdist run and passes
    alone. Pinned verbatim so a recurrence reproduces without the full suite."""
    assert addresses(detector, "lakcím: 1051 Budapest, Minta utca 12. 3/5. ), Vevő") == [
        ("1051 Budapest, Minta utca 12. 3/5.", hu.SCORE_CONSISTENT)
    ]


def test_the_span_has_the_right_offsets(detector: RuleDetector) -> None:
    text = "Lakcím: 6720 Szeged, Képzelt tér 4. Telefon: 06 30 123 4567"
    [span] = [s for s in detector.detect(text) if s.entity_type is E.ADDRESS]
    assert text[span.start : span.end] == "6720 Szeged, Képzelt tér 4." == span.text


def test_a_postcode_of_another_settlement_is_not_boosted(detector: RuleDetector) -> None:
    # 6750 is Algyő's postcode: the address shape is kept, but it scores like a bare postcode.
    assert addresses(detector, "6750 Szeged, Képzelt tér 4.") == [
        ("6750 Szeged, Képzelt tér 4.", hu.SCORE_MISMATCH)
    ]
    assert addresses(detector, "3300 Szeged, Kossuth Lajos utca 1.")[0][1] == hu.SCORE_MISMATCH
    assert hu.SCORE_MISMATCH < hu.SCORE_UNVALIDATED < hu.SCORE_CONSISTENT


def test_a_budapest_district_must_match_the_postcode(detector: RuleDetector) -> None:
    assert addresses(detector, "1134 Budapest XIII. kerület, Váci út 41.")[0][1] == (
        hu.SCORE_CONSISTENT
    )
    assert addresses(detector, "1134 Budapest IV. ker., Váci út 41.")[0][1] == hu.SCORE_MISMATCH
    assert [hu._roman(r) for r in ("I", "IV", "IX", "XIV", "XIX", "XXIII")] == [1, 4, 9, 14, 19, 23]


def test_an_unknown_settlement_is_unvalidated(detector: RuleDetector) -> None:
    assert addresses(detector, "1234 Kitaláltfalva, Minta utca 1.") == [
        ("1234 Kitaláltfalva, Minta utca 1.", hu.SCORE_UNVALIDATED)
    ]


@pytest.mark.parametrize(
    ("text", "address"),
    [
        ("Ő Debrecen, Kitalált utca 5. alatt lakik.", "Debrecen, Kitalált utca 5."),
        ("Szegeden, Petőfi Sándor utca 3. szám alatt", "Szegeden, Petőfi Sándor utca 3."),
        ("Egerben, Fő tér 2. alatt", "Egerben, Fő tér 2."),
    ],
)
def test_without_a_postcode_the_settlement_must_be_known(
    detector: RuleDetector, text: str, address: str
) -> None:
    assert addresses(detector, text) == [(address, hu.SCORE_UNVALIDATED)]


@pytest.mark.parametrize(
    "text",
    [
        "Kedves Anna, Minta utca 1. alatt vártalak.",  # a greeting, not a town
        "Május, Kossuth Lajos utca 5.",  # a month
        "Szeged szép város, a Tisza partján.",  # a town, but no street
        "Budapest, 2026. október 27.",  # place and date line
        "Tisztelt Kovács, Fő utca nélkül",  # no house number
        "Szeged, Kossuth Lajos utca",  # no house number
        "Szegedke, Fő utca 1.",  # not a settlement, nor an inflected one
    ],
)
def test_look_alikes(detector: RuleDetector, text: str) -> None:
    assert [a for a, score in addresses(detector, text) if score >= hu.SCORE_MISMATCH] == []


def test_bare_postcode_still_found_and_consistency_boosts_it(detector: RuleDetector) -> None:
    assert addresses(detector, "3300 Eger") == [("3300", 0.85)]
    assert addresses(detector, "3300 Szeged") == [("3300", 0.75)]
    # An unknown word after the number is not a settlement, so there is no postcode (LAB-1476).
    assert addresses(detector, "3300 Kitaláltfalva") == []


@pytest.mark.parametrize(
    "text",
    [
        "-rw-r--r--  1 dev  staff  1203 Oct 28 22:40 customers.md",
        "-rw-r--r--  1 dev  staff  2048 Jan 12 10:00 notes.md",
        "drwxr-xr-x  5 dev  staff   160 Szept 3 09:11 docs",
    ],
)
def test_tool_output_sizes_are_not_postcodes(detector: RuleDetector, text: str) -> None:
    """A file size before a month abbreviation in `ls -la` output is not an ADDRESS."""
    assert addresses(detector, text) == []


def test_only_for_hungarian_text(detector: RuleDetector) -> None:
    assert addresses(detector, "6720 Szeged, Képzelt tér 4.", language="en") == []


def test_inflected_settlement_lookup() -> None:
    assert hu._settlement("Szeged") == "Szeged"
    assert hu._settlement("Szegeden") == "Szeged"
    assert hu._settlement("Debrecenből") == "Debrecen"
    assert hu._settlement("Szegedke") is None
    assert hu._settlement("Xyz") is None


def test_generated_addresses_validate() -> None:
    """Every address the corpus generator draws passes the postcode check."""
    det = RuleDetector()
    index = postcode_index("hu")
    for seed in range(40):
        address = identity_generator("hu", random.Random(seed)).address()
        code, rest = address.split(" ", 1)
        assert index.consistent(code, rest.split(",", 1)[0]), address
        assert addresses(det, f"Lakcím: {address} Telefon") == [(address, hu.SCORE_CONSISTENT)]
