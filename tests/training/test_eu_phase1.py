"""Phase-1 multilingual data (LAB-1525): gate sets, name declension, template generators."""

from __future__ import annotations

import json
import sys
import types

import pytest

from pii_guard.eval.fixtures import load_fixtures
from pii_guard.types import EntityType

from .conftest import ROOT, load_script

sys.path.insert(0, str(ROOT / "training" / "ner"))


@pytest.fixture(scope="module")
def gates() -> types.ModuleType:
    return load_script("eval/fixtures/build_eu_gates.py", "build_eu_gates")


@pytest.fixture(scope="module")
def ids() -> types.ModuleType:
    return load_script("training/ner/eu_identities.py", "eu_identities")


def test_gate_files_are_fresh(gates: types.ModuleType) -> None:
    for name, build in gates.OUTPUTS.items():
        committed = load_fixtures([gates.HERE / name])
        assert [d.to_dict() for d in committed] == [d.to_dict() for d in build()], name


def test_every_gate_language_has_smoke_and_inflection(gates: types.ModuleType) -> None:
    langs = {"lv", "lt", "hr", "sl", "fr", "es", "it", "nl", "ro", "mt", "ga"}
    for lang in langs:
        smoke = load_fixtures([gates.HERE / f"{lang}-smoke.jsonl"])
        assert any(not d.spans for d in smoke), f"{lang}: no over-masking document"
        assert load_fixtures([gates.HERE / f"{lang}-inflection.jsonl"])


@pytest.mark.parametrize(
    ("lang", "token", "gender", "family", "form"),
    [
        ("lv", "Bērziņš", "m", True, "Bērziņam"),
        ("lv", "Jānis", "m", False, "Jāņa"),
        ("lv", "Eglīte", "f", True, "Eglītei"),
        ("lt", "Kazlauskas", "m", True, "Kazlausko"),
        ("lt", "Adomaitis", "m", True, "Adomaičio"),
        ("lt", "Petrauskienė", "f", True, "Petrauskienei"),
        ("hr", "Petar", "m", False, "Petra"),
        ("hr", "Horvat", "m", True, "Horvatom"),
        ("sl", "Peter", "m", False, "Petru"),
        ("sl", "Ana", "f", False, "Ani"),
    ],
)
def test_name_forms(
    ids: types.ModuleType, lang: str, token: str, gender: str, family: bool, form: str
) -> None:
    assert form in ids.name_forms(lang, token, gender, is_family=family)


def test_womans_surname_does_not_decline_in_hr_sl(ids: types.ModuleType) -> None:
    hr = ids.name_forms("hr", "Babić", "f", is_family=True)
    assert "Babića" not in hr and {"Babić", "Babićeva"} <= hr  # colloquial possessive
    sl = ids.name_forms("sl", "Novak", "f", is_family=True)
    assert "Novaka" not in sl and {"Novak", "Novakova"} <= sl
    assert "Kasteličeva" in ids.name_forms("sl", "Kastelic", "m", is_family=True)


def test_checksummed_ids(ids: types.ModuleType) -> None:
    import datetime as dt
    import random

    rng = random.Random(1)  # noqa: S311
    oib = ids.hr_oib(rng)
    assert len(oib) == 11 and oib.isdigit()
    emso = ids.si_emso(rng, dt.date(1990, 5, 17), "f")
    assert emso.startswith("1705990") and len(emso) == 13
    code = ids.lt_personal_code(rng, dt.date(1985, 1, 2), "m")
    assert code.startswith("3850102") and len(code) == 11


def test_court_surnames_spans_and_titles() -> None:
    court = load_script("training/ner/court_surnames_en.py", "court_surnames_en")
    for i in range(50):
        doc = court.document(1525, i)
        assert all(doc.text[s.start : s.end] == s.text for s in doc.spans)
        assert all(s.entity_type is EntityType.PERSON for s in doc.spans)
        assert any(" " not in s.text for s in doc.spans)  # a standalone surname
        for a, b in doc.meta["loss_ignore"]:
            assert doc.text[a:b] in {"Mr", "Mrs", "Ms", "Miss", "Dr"}
            assert not any(s.start < b and a < s.end for s in doc.spans)


def test_negatives_eu_have_no_spans() -> None:
    neg = load_script("training/ner/negatives_eu.py", "negatives_eu")
    for lang in neg.LANGS:
        doc = neg.document(lang, 1525, 0)
        assert doc.spans == () and doc.text


def test_eu_corpus_locates_declined_names() -> None:
    corpus = load_script("training/ner/eu_corpus.py", "eu_corpus")
    p = corpus.Planted("name", EntityType.PERSON, "Jonas Kazlauskas", given="Jonas",
                       family="Kazlauskas", gender="m")  # fmt: skip
    plan = corpus.Plan("lt-x", "lt", 0, "email", (p,), ())
    text = "Sutartį pasirašė Jonas Kazlauskas. Vėliau Kazlauskui paskambinome, Jono nebuvo."
    spans, missing = corpus.locate(text, plan)
    assert not missing
    assert [s.text for s in spans] == ["Jonas Kazlauskas", "Kazlauskui", "Jono"]


def test_manifests_are_marked_synthetic() -> None:
    m = json.loads((ROOT / "training/ner/eu-openpii-train-manifest.json").read_text())
    assert m["synthetic"] is True and m["rows_committed"] is False
    assert {"lv", "lt", "hr", "sl", "fr", "es", "it", "nl", "ro"} <= set(m["languages"])
