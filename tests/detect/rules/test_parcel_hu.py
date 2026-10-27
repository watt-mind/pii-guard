"""Hungarian land registry parcel numbers (helyrajzi szám): label required, look-alikes.

The parcel numbers and places are made up; a parcel number identifies a property, not a
person, but with the land registry it leads straight to its owner, so it is masked.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pii_guard.detect.rules import RuleDetector
from pii_guard.types import EntityType as E


@pytest.fixture(scope="module")
def detector() -> RuleDetector:
    return RuleDetector()


def parcels(detector: RuleDetector, text: str, language: str = "hu") -> list[tuple[str, float]]:
    return [
        (s.text, s.score)
        for s in detector.detect(text, language=language)
        if s.entity_type is E.PARCEL_NUMBER_HU
    ]


@pytest.mark.parametrize(
    ("text", "value"),
    [
        # label after the number
        ("hogy a {} hrsz. alatti ingatlan ügyében", "1452/7"),
        ("a {} helyrajzi számú ingatlant érinti", "0455"),
        ("a {} helyrajzi szám alatt nyilvántartott", "22291/16"),
        ("a {} hrsz.-ú telek", "318/2"),
        ("a {} (korábban 318/1) hrsz. alatti", "318/2"),
        # label before the number
        ("amelynek helyrajzi száma: {}. A meghatalmazott", "5108/6"),
        ("Helyrajzi szám:\n{}\nCím:", "6924/18"),
        ("hrsz.: {}, 3. emelet", "0123/4/A/12"),
        ("hrsz {} alatt", "77"),
        ("a Hrsz-on {} szerepel", "1200/3"),
    ],
)
def test_parcel_next_to_its_label(detector: RuleDetector, text: str, value: str) -> None:
    assert parcels(detector, text.format(value)) == [(value, 0.9)]


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Az ingatlan: Budapest belterület, {} helyrajzi számú lakás.", "28145/3"),
        ("Település: Kecskemét, helyrajzi szám: {}\nTulajdonos", "0412/18"),
        ("A munkaterület: Szentendre, {} hrsz. A díj", "2231/14"),
        ("a külterületi {} hrsz. szántó", "0567/2"),
    ],
)
def test_a_settlement_or_area_nearby_raises_the_score(
    detector: RuleDetector, text: str, value: str
) -> None:
    assert parcels(detector, text.format(value)) == [(value, 0.95)]


def test_a_list_after_the_label(detector: RuleDetector) -> None:
    text = "hrsz.: 0123/4/A/12, 0123/4/A/13 és 0123/5 ingatlanok"
    assert [v for v, _ in parcels(detector, text)] == ["0123/4/A/12", "0123/4/A/13", "0123/5"]


def test_parcels_run_in_any_language(detector: RuleDetector) -> None:
    text = "The flat (hrsz. 28145/3) is sold."
    assert parcels(detector, text, language="en") == [("28145/3", 0.9)]


@pytest.mark.parametrize(
    "text",
    [
        "1/2 arányú tulajdoni hányad",  # fraction
        "a felperes hányada 3/4, az alperesé 1/4",
        "a 2026/10. havi állapot",  # year/month
        "a kérelem 3/5. oldalán",  # page number
        "Ügyszám: 12.P.21.345/2025/7.",  # court case number
        "a 3/2025. (X. 27.) számú rendelkezés",
        "számla száma 2026/0042",
        "2025.10.27. napján",
        "Az ingatlan helyrajzi számának megállapítása folyamatban van.",  # label, no number
        "hrsz. 2026.10.27. óta",  # a date after the label
        "hrsz.: 1234/5/6/7/8",  # not a parcel shape
    ],
)
def test_parcel_look_alikes(detector: RuleDetector, text: str) -> None:
    assert parcels(detector, text) == []


def test_only_the_parcel_after_the_label_not_a_fraction_after_it(detector: RuleDetector) -> None:
    text = "hrsz. 1234/5 1/2 arányban"
    assert parcels(detector, text) == [("1234/5", 0.9)]


@given(a=st.integers(1, 99_999), b=st.integers(1, 9_999))
def test_bare_fractions_are_never_parcels(a: int, b: int) -> None:
    found = RuleDetector().detect(f"A hányad {a}/{b}, a többi rész a társé.")
    assert [s for s in found if s.entity_type is E.PARCEL_NUMBER_HU] == []


@given(a=st.integers(1, 99_999), b=st.integers(1, 9_999))
def test_any_labelled_parcel_is_found(a: int, b: int) -> None:
    value = f"{a}/{b}"
    found = RuleDetector().detect(f"az ingatlan helyrajzi száma: {value}, a jelzálog")
    assert [(s.text, s.entity_type) for s in found] == [(value, E.PARCEL_NUMBER_HU)]
