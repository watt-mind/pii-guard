"""NER v4.1 data (LAB-1539): court-style name forms, plans, gold, mining guards, HF mapping."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from pii_guard.eval.datasets._common import Row
from pii_guard.eval.generate import Completion
from pii_guard.types import EntityType

from .conftest import ROOT, load_script

sys.path.insert(0, str(ROOT / "training" / "ner"))


@pytest.fixture(scope="module")
def names() -> types.ModuleType:
    return load_script("training/ner/court_eu_names.py", "court_eu_names")


@pytest.fixture(scope="module")
def court() -> types.ModuleType:
    return load_script("training/ner/court_eu.py", "court_eu")


@pytest.fixture(scope="module")
def mine() -> types.ModuleType:
    return load_script("training/ner/mine_v41.py", "mine_v41")


@pytest.fixture(scope="module")
def hf() -> types.ModuleType:
    return load_script("training/ner/hf_v41.py", "hf_v41")


def test_packs_cover_24_languages(names: types.ModuleType) -> None:
    assert len(names.LANGUAGES) == 24
    assert set(names.PACKS) == set(names.LANGUAGES)
    for pack in names.PACKS.values():
        assert len(pack.given_m) >= 10 and len(pack.given_f) >= 10
        assert len(pack.surnames) >= 10 and pack.towns and pack.streets


@pytest.mark.parametrize(
    ("code", "given", "family", "gender", "text", "found"),
    [
        ("pl", "Jan", "Kowalski", "m", "powód Jan Kowalski; Kowalskiego; Kowalskiemu",
         ["Jan Kowalski", "Kowalskiego", "Kowalskiemu"]),
        ("fi", "Mikko", "Virtanen", "m", "Mikko Virtanen; Virtasen; Virtaselle",
         ["Mikko Virtanen", "Virtasen", "Virtaselle"]),
        ("hu", "László", "Kovács", "m", "Kovács László; Kovácsnak; Kovácscsal",
         ["Kovács László", "Kovácsnak", "Kovácscsal"]),
        ("cs", "Jana", "Nováková", "f", "Jana Nováková; Novákové; s Novákovou",
         ["Jana Nováková", "Novákové", "Novákovou"]),
        ("ga", "Seán", "Ó Briain", "m", "Seán Ó Briain; Uí Bhriain",
         ["Seán Ó Briain", "Uí Bhriain"]),
        ("en", "Sarah", "Walker", "f", "Mrs Sarah Walker; Walker's; Ms Walker",
         ["Sarah Walker", "Walker", "Walker"]),
        ("lv", "Jānis", "Bērziņš", "m", "Jānis Bērziņš; Bērziņa", ["Jānis Bērziņš", "Bērziņa"]),
    ],
)  # fmt: skip
def test_person_regex_finds_declined_forms(
    names: types.ModuleType,
    code: str,
    given: str,
    family: str,
    gender: str,
    text: str,
    found: list[str],
) -> None:
    pattern = names.person_regex(code, given, family, gender)
    assert [m.group() for m in pattern.finditer(text)] == found


def test_person_regex_leaves_honorifics_and_other_words(names: types.ModuleType) -> None:
    pattern = names.person_regex("en", "Sarah", "Walker", "f")
    assert [m.group() for m in pattern.finditer("Mrs Walkerton and Ms Walker")] == ["Walker"]


def test_plans_are_seeded_and_fictional(court: types.ModuleType) -> None:
    a = court.plan_document("court", "de", 1539, 3)
    b = court.plan_document("court", "de", 1539, 3)
    assert a.messages == b.messages and a.doc_id == "de-court-s1539-00003"
    assert a.kind.id.startswith("court-")
    assert any(v.entity_type is EntityType.PERSON for v in a.values)
    v = court.plan_document("variants", "pl", 1539, 0)
    assert v.kind.pattern or v.kind.id.startswith("negative-")
    assert all("mapa" not in k.brief.lower() for k in (*court.COURT_KINDS, *court.VARIANTS))


def test_locate_labels_standalone_surnames_without_honorifics(court: types.ModuleType) -> None:
    plan = court.plan_document("court", "en", 1539, 0)
    person = next(v for v in plan.values if v.entity_type is EntityType.PERSON)
    others = [v for v in plan.values if v is not person and v.required]
    text = (
        f"1. The claimant, Mr {person.text}, appeared. Mr {person.family} said that "
        f"{person.family}'s loan was repaid. " + " ".join(v.text for v in others)
    )
    spans, missing = court.locate(text, plan)
    assert not missing
    found = [s.text for s in spans if s.entity_type is EntityType.PERSON]
    assert found[:3] == [person.text, person.family, person.family]
    assert all(not s.text.startswith("Mr") for s in spans)


def test_generate_discards_a_missing_party(court: types.ModuleType, tmp_path: Path) -> None:
    plan = court.plan_document("court", "fr", 1539, 1)

    class Client:
        model = "fake"

        def payload(self, messages: object) -> dict[str, object]:
            return {"m": str(messages)}

        def complete(self, messages: object) -> Completion:
            return Completion("Le tribunal statue.", "stop", {}, 0.0, "fake")

    cache = court.ResponseCache(tmp_path)
    out = court.generate(plan, Client(), cache, court.Budget(1.0), "train", 1539)
    assert out.document is None and out.reason == "missing_value"


@pytest.mark.parametrize(
    "name",
    ["en-openpii-test.jsonl", "lv-smoke.jsonl", "lv-inflection-dev.jsonl", "mapa-dev.jsonl",
     "en-agent-traffic.jsonl"],
)  # fmt: skip
def test_mining_refuses_test_gate_and_real_text(mine: types.ModuleType, name: str) -> None:
    with pytest.raises(SystemExit):
        mine.check_inputs([Path("/x") / name])


def test_mining_accepts_dev_splits(mine: types.ModuleType) -> None:
    mine.check_inputs(
        [Path("/d/en-agent-traffic-dev.jsonl"), Path("/d/pl-openpii-dev.jsonl"),
         Path("/d/lv-distill-dev.jsonl"), Path("/d/en-court-dev.jsonl")]
    )  # fmt: skip
    assert mine.pool_of(Path("x/en-agent-traffic-dev.jsonl")) == "agent-traffic-dev"


def test_hf_mapping_merges_names_and_drops_special_categories(hf: types.ModuleType) -> None:
    text = "Herr Max Weber wohnt in Hauptstraße 5, 10115 Berlin. Termin am 12.05.2023."

    def at(value: str, label: str) -> tuple[int, int, str]:
        start = text.index(value)
        return start, start + len(value), label

    row = Row(
        "7", "de", text,
        (at("Max", "GIVEN_NAME"), at("Weber", "SURNAME"), at("Hauptstraße 5", "STREET_ADDRESS"),
         at("10115", "ZIP_CODE"), at("Berlin", "CITY"), at("12.05.2023", "DATE")),
    )  # fmt: skip
    doc = hf.to_document(row, "nym", hf.NYM)
    assert [(s.entity_type, s.text) for s in doc.spans] == [
        (EntityType.PERSON, "Max Weber"),
        (EntityType.ADDRESS, "Hauptstraße 5, 10115 Berlin"),
    ]
    assert doc.meta["synthetic"] is True and doc.meta["loss_ignore"] == []
    sick = Row("8", "de", "Der Patient Max Weber kam.", ((12, 15, "GIVEN_NAME"),))
    with pytest.raises(hf.ConversionError):
        hf.to_document(sick, "nym", hf.NYM)


def test_e3_types_map_by_keyword(hf: types.ModuleType) -> None:
    assert hf.e3_type(["osebno ime"]) is EntityType.PERSON
    assert hf.e3_type(["username"]) is None
    assert hf.e3_type(["credit card expiration date"]) is None
    assert hf.e3_type(["iban"]) is EntityType.BANK_ACCOUNT
    assert hf.e3_type(["date of birth"]) is EntityType.DATE_OF_BIRTH
