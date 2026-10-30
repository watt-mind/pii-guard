"""The German pack's corpus generator (LAB-1143): seeded, fictional, recognisable as German."""

# Seeded, reproducible synthetic data: the standard PRNG is the point, not a weakness.
# ruff: noqa: S311

from __future__ import annotations

import random
import re

import pytest

from pii_guard.detect.checksums import is_valid_iban
from pii_guard.detect.rules import RuleDetector
from pii_guard.eval.generate import load_language, plan_document
from pii_guard.eval.identities import LANGUAGES, identity_generator
from pii_guard.languages.de.checksums import is_valid_steuer_id
from pii_guard.languages.de.identities import GermanIdentities, steuer_id
from pii_guard.types import EntityType as E

SEEDS = range(40)
_RESERVED_PHONE = re.compile(r"(30|40|69|89)\s?\D*(23125|66969|90009|99998)|221\D*4710")


def de(seed: int | str) -> GermanIdentities:
    return GermanIdentities(random.Random(seed))


def test_the_generator_comes_from_the_pack() -> None:
    assert isinstance(identity_generator("de", random.Random(1)), GermanIdentities)
    assert isinstance(identity_generator("de-AT", random.Random(1)), GermanIdentities)
    assert "de" in LANGUAGES
    assert isinstance(LANGUAGES["de"](random.Random(1)), GermanIdentities)
    with pytest.raises(KeyError):
        LANGUAGES["pl"]  # a pack without a corpus


def test_same_seed_same_identities() -> None:
    a, b = de("s/1"), de("s/1")
    assert [a.person() for _ in range(3)] == [b.person() for _ in range(3)]
    assert a.company() == b.company()
    assert a.institution("court") == b.institution("court")


@pytest.mark.parametrize("seed", SEEDS)
def test_identifiers_are_valid_and_reserved(seed: int) -> None:
    p = de(seed).person()
    assert p.steuer_id is not None
    assert is_valid_steuer_id(p.steuer_id.replace(" ", ""))
    assert p.bank_account.startswith("DE")
    assert is_valid_iban(p.bank_account.replace(" ", ""))
    assert _RESERVED_PHONE.search(p.phone), "phone numbers come from the reserved ranges"
    assert p.email.split("@")[1] in {"example.com", "example.org", "example.net"}
    assert re.fullmatch(r"[CFGHJKLMNPRTVWXYZ][CFGHJKLMNPRTVWXYZ0-9]{8}", p.id_document)
    assert p.tax_id is None and p.taj is None and p.mother_name is None
    assert p.name == f"{p.given} {p.family}"


def test_steuer_id_grouping() -> None:
    grouped = steuer_id(random.Random(3), grouped=True)
    assert re.fullmatch(r"\d{2} \d{3} \d{3} \d{3}", grouped)
    assert is_valid_steuer_id(grouped.replace(" ", ""))


def test_the_german_rules_recognise_the_generated_values() -> None:
    """Whole addresses, phones, labelled Steuer-IDs and IBANs are found by the rule layer."""
    det = RuleDetector()
    for seed in range(30):
        ids = de(seed)
        p = ids.person()
        for text, value, expected in [
            (f"Anschrift: {p.address}\n", p.address, E.ADDRESS),
            (f"Telefon: {p.phone} .", p.phone, E.PHONE),
            (f"Steuer-ID: {p.steuer_id} .", p.steuer_id, E.ID_DOCUMENT),
            (f"IBAN: {p.bank_account} .", p.bank_account, E.BANK_ACCOUNT),
            (f"E-Mail: {p.email} .", p.email, E.EMAIL),
        ]:
            assert value is not None
            found = {(s.entity_type, s.text) for s in det.detect(text, "de")}
            assert (expected, value) in found, (seed, expected)


def test_companies_and_institutions() -> None:
    ids = de(5)
    c = ids.company()
    assert c.org_name.startswith(c.short_name + " ")
    assert c.email.endswith(".example")
    court = ids.institution("court")
    office = ids.institution("office")
    assert court.org_name.startswith("Amtsgericht ")
    assert office.org_name.startswith("Bürgeramt ")
    assert court.address.endswith(court.org_name.removeprefix("Amtsgericht "))


def test_every_template_plans_with_the_german_generator() -> None:
    templates = load_language("de")
    assert templates.language == "de"
    for index, template in enumerate(templates.kinds):
        plan = plan_document("de", 7, index, kind=template.id)
        assert plan.doc_id == f"de-synth-s7-{index:05d}"
        assert plan.required, template.id
    employment = plan_document("de", 7, 0, kind="employment")
    assert any(v.field == "steuer_id" and v.entity_type is E.ID_DOCUMENT for v in employment.values)
