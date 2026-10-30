"""Seeded fictional identities (ADR 0005): deterministic, checksum-valid, never real."""

# Seeded, reproducible synthetic data: the standard PRNG is the point, not a weakness.
# ruff: noqa: S311

from __future__ import annotations

import random
import re

import pytest

from pii_guard.detect.checksums import (
    is_valid_giro,
    is_valid_hu_tax_id,
    is_valid_hu_tax_number,
    is_valid_iban,
    is_valid_taj,
)
from pii_guard.detect.rules import RuleDetector
from pii_guard.eval.identities import (
    FIELD_TYPES,
    Company,
    EnglishIdentities,
    HungarianIdentities,
    Person,
    Value,
    ascii_fold,
    email_address,
    hu_giro,
    hu_iban,
    identity_generator,
    taj_number,
)
from pii_guard.types import EntityType as E

SEEDS = range(60)


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _compact(text: str) -> str:
    return text.replace(" ", "")


def hu(seed: int | str) -> HungarianIdentities:
    return HungarianIdentities(random.Random(seed))


def en(seed: int | str) -> EnglishIdentities:
    return EnglishIdentities(random.Random(seed))


def test_same_seed_same_identities() -> None:
    for make in (hu, en):
        a, b = make("s/1"), make("s/1")
        assert [a.person() for _ in range(3)] == [b.person() for _ in range(3)]
        assert a.company() == b.company()
        assert a.property() == b.property()
        assert a.institution("court") == b.institution("court")


def test_different_seeds_differ() -> None:
    people = {hu(seed).person().name for seed in SEEDS}
    assert len(people) > 40


def test_identity_generator_by_language() -> None:
    rng = random.Random(1)
    assert isinstance(identity_generator("hu", rng), HungarianIdentities)
    assert isinstance(identity_generator("en-GB", rng), EnglishIdentities)
    with pytest.raises(ValueError, match="no identity generator"):
        identity_generator("xx", rng)
    with pytest.raises(ValueError, match="unknown identity kind"):
        identity_generator("hu", rng).make("spaceship")


@pytest.mark.parametrize("seed", SEEDS)
def test_hungarian_identifiers_are_checksum_valid(seed: int) -> None:
    gen = hu(seed)
    p = gen.person()
    assert p.tax_id is not None and is_valid_hu_tax_id(p.tax_id)
    # Digits 2-6 of the tax ID encode the date of birth (days since 1867-01-01).
    assert int(p.tax_id[1:6]) == (p.birth_date - __import__("datetime").date(1867, 1, 1)).days
    assert p.taj is not None and is_valid_taj(_digits(p.taj))
    account = _compact(p.bank_account)
    if account.startswith("HU"):
        assert is_valid_iban(account)
    else:
        assert is_valid_giro(_digits(account))
    assert re.fullmatch(r"\d{6}[A-Z]{2}", p.id_document)
    assert re.fullmatch(r"[A-Z]{3}-\d{3}|A[A-Z] [A-Z]{2}-\d{3}", p.plate)
    assert p.email.rsplit("@", 1)[1] in {"example.com", "example.org", "example.net"}
    c = gen.company()
    assert c.tax_number is not None
    base, vat, area = c.tax_number.split("-")
    assert is_valid_hu_tax_number(base, vat, area)
    assert c.reg_number is not None and re.fullmatch(r"\d{2}-(06|09|10)-\d{6}", c.reg_number)
    assert c.email.endswith(".example")
    assert c.org_name.startswith(c.short_name)
    parcel = gen.property().parcel
    assert parcel is not None and re.fullmatch(r"\d{3,6}(/\d{1,2})?", parcel)


@pytest.mark.parametrize("seed", SEEDS)
def test_english_identities_use_reserved_ranges(seed: int) -> None:
    gen = en(seed)
    p = gen.person()
    assert p.tax_id is None and p.taj is None and p.mother_name is None
    assert p.name == f"{p.given} {p.family}"
    assert is_valid_iban(_compact(p.bank_account)) and p.bank_account.startswith("GB")
    phone = _digits(p.phone)
    assert any(r in phone for r in ("7700900", "2079460", "1134960")), "Ofcom drama ranges only"
    assert re.fullmatch(r"\d{9}", p.id_document)
    assert re.search(r", [A-Za-z]+ [A-Z]{2}\d{1,2} \d[A-Z]{2}$", p.address)
    assert p.email.rsplit("@", 1)[1].startswith("example.")
    assert gen.company().email.endswith(".example")
    assert gen.property().parcel is None


def test_hungarian_names_family_first_and_distinct_in_one_document() -> None:
    gen = hu("one-document")
    people = [gen.person() for _ in range(6)]
    assert all(p.name.startswith(p.family + " " + p.given) for p in people)
    assert len({p.family for p in people}) == 6
    assert all(p.mother_name and p.family not in p.mother_name.split()[0] for p in people)


def test_given_names_are_unique_in_one_document() -> None:
    """Two people in one document never share a given name, mothers included (LAB-1105)."""
    for seed in SEEDS:
        for make in (hu, en):
            gen = make(f"given/{seed}")
            gen.distinct_given_names = True
            people = [gen.person() for _ in range(3)]
            given = [p.given for p in people]
            assert len(set(given)) == len(given), seed
            mothers = [p.mother_name.split()[-1] for p in people if p.mother_name]
            assert not set(mothers) & set(given), seed
            assert len(set(mothers)) == len(mothers), seed


def test_local_town_ties_property_and_institution() -> None:
    """With ``local_town`` set, the property and the office share a town (LAB-1105)."""
    for seed in SEEDS:
        gen = hu(f"town/{seed}")
        gen.local_town = gen.rng.randrange(gen.town_count)
        prop, office = gen.property(), gen.institution("office")
        town = office.address.split(",")[0].split(" ", 1)[1]
        assert prop.address.split(",")[0].split(" ", 1)[1] == town
        english = en(f"town/{seed}")
        english.local_town = english.rng.randrange(english.town_count)
        court = english.institution("court")
        assert court.org_name.split(" County")[0] in english.property().address


def test_rule_detector_recognises_generated_identifiers() -> None:
    """The generated values look like the real thing to the rule detector."""
    det = RuleDetector()
    for seed in range(20):
        p = hu(seed).person()
        for value, expected in [
            (p.tax_id, E.NATIONAL_ID_HU_TAX),
            (p.taj, E.NATIONAL_ID_HU_TAJ),
            (p.bank_account, E.BANK_ACCOUNT),
            (p.email, E.EMAIL),
            (p.phone, E.PHONE),
        ]:
            assert value is not None
            text = f"Adatok: {value} ."
            found = {(s.entity_type, s.text) for s in det.detect(text, "hu")}
            assert (expected, value) in found, expected


def test_values_maps_fields_to_types_and_adds_name_parts() -> None:
    p = hu(3).person()
    values = p.values(["name", "tax_id"])
    assert [(v.field, v.entity_type, v.required) for v in values] == [
        ("name", E.PERSON, True),
        ("tax_id", E.NATIONAL_ID_HU_TAX, True),
        ("given", E.PERSON, False),
        ("family", E.PERSON, False),
    ]
    assert all(v.capitalized for v in values if not v.required)
    # No name requested: no optional name parts.
    assert [v.field for v in p.values(["phone"])] == ["phone"]
    company = hu(3).company()
    assert [v.field for v in company.values(["org_name"])] == ["org_name", "short_name"]


def test_values_rejects_missing_fields() -> None:
    with pytest.raises(KeyError, match="taj"):
        en(1).person().values(["name", "taj"])
    with pytest.raises(KeyError):
        hu(1).property().values(["email"])


def test_every_field_has_a_text_entity_type() -> None:
    assert all(not t.is_visual for t in FIELD_TYPES.values())


def test_reprs_hide_values() -> None:
    p = hu(5).person()
    for obj in (p, hu(5).company(), *p.values(["name", "tax_id"])):
        assert p.family not in repr(obj) and p.family not in str(obj)
        assert str(p.tax_id) not in repr(obj)
    assert repr(Value("name", E.PERSON, "Teszt Elek")).endswith("text=<redacted>)")
    assert isinstance(p, Person) and isinstance(hu(5).company(), Company)


def test_shared_helpers() -> None:
    assert ascii_fold("Kovács Ödön Szűcs") == "Kovacs Odon Szucs"
    rng = random.Random(9)
    assert email_address(rng, "Ödön", "Szűcs").isascii()
    assert is_valid_giro(_digits(hu_giro(random.Random(1), long=False)))
    assert len(_digits(hu_giro(random.Random(1), long=True))) == 24
    assert " " not in hu_iban(random.Random(2), grouped=False)
    assert re.fullmatch(r"\d{9}", taj_number(random.Random(3), sep=""))
