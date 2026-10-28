"""Brand names the NER calls a person become ORGANIZATION (LAB-1336).

No model is loaded: the backend is a fake that tags the given values. Every person name is
fictional (ADR 0005); the brands are public company and product names.
"""

from __future__ import annotations

from importlib.resources import files

import pytest

from pii_guard.detect import ner_orgs
from pii_guard.detect.ner import NerDetector, RawEntity
from pii_guard.detect.ner_orgs import brand_names, load_brands, parse_brands, relabel_brands
from pii_guard.languages import LanguagePack, get_pack, packs, register_pack, unregister_pack
from pii_guard.policy import Policy, PolicySet
from pii_guard.types import EntityType, Span

E = EntityType


class TagBackend:
    """Tags every occurrence of each ``(value, label)`` pair."""

    def __init__(self, tags: list[tuple[str, str]]) -> None:
        self.tags = tags

    def predict(self, text: str) -> list[RawEntity]:
        out = []
        for value, label in self.tags:
            start = text.find(value)
            while start >= 0:
                out.append(RawEntity(label, start, start + len(value), 0.97))
                start = text.find(value, start + 1)
        return out


def detect(text: str, *tags: tuple[str, str], language: str = "en") -> list[tuple[E, str]]:
    det = NerDetector(backend=TagBackend(list(tags)))
    return [(s.entity_type, s.text) for s in det.detect(text, language)]


# --- The reported case ------------------------------------------------------------------------


def test_the_haiku_prompt_keeps_meta() -> None:
    text = "Write a haiku about Meta that greets me by name."
    assert detect(text, ("Meta", "PER")) == [(E.ORGANIZATION, "Meta")]


def test_relabelled_span_is_kept_by_the_default_policy() -> None:
    text = "Write a haiku about Meta that greets me by name."
    (span,) = NerDetector(backend=TagBackend([("Meta", "PER")])).detect(text, "en")
    assert PolicySet().of(span.entity_type) is Policy.KEEP
    assert (span.start, span.end, span.score, span.detector) == (20, 24, 0.97, "ner")


@pytest.mark.parametrize(
    ("text", "value", "language"),
    [
        ("Compare Llama with Muse.", "Llama", "en"),
        ("Compare Llama with Muse.", "Muse", "en"),
        ("Ask OpenAI and Anthropic.", "OpenAI", "en"),
        ("Is Meta's model better?", "Meta's", "en"),
        ("Is META better?", "META", "en"),
        ("Ask Hugging Face for the weights.", "Hugging Face", "en"),
        ("Szabó a Google-nél dolgozik.", "Google-nél", "hu"),
        ("Írj egy haikut a Metáról.", "Metáról", "hu"),
        ("Foglald össze az OTP Bank jelentését.", "OTP Bank", "hu"),
        ("Ist Metas Modell besser?", "Metas", "de"),
        ("Fasse die Mitteilung der Deutsche Bahn zusammen.", "Deutsche Bahn", "de"),
    ],
)
def test_brands_become_organisations(text: str, value: str, language: str) -> None:
    assert detect(text, (value, "PER"), language=language) == [(E.ORGANIZATION, value)]


# --- Persons stay persons ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "tags"),
    [
        # A longer span: the brand is a word of a person's name.
        ("Meta Kovács will call you.", [("Meta Kovács", "PER")]),
        ("Ask Anna Apple about it.", [("Anna Apple", "PER")]),
        # An honorific before or after.
        ("Dear Ms. Apple, thank you.", [("Apple", "PER")]),
        ("Herr Meta hat angerufen.", [("Meta", "PER")]),
        ("Meta úr holnap jön.", [("Meta", "PER")]),
        # Two person spans that touch: one longer name.
        ("Anna Meta called.", [("Anna", "PER"), ("Meta", "PER")]),
        # A neighbouring word that a name lexicon knows.
        ("Kovács Meta holnap jön.", [("Meta", "PER")]),
        # Not a listed name, and a name with a suffix no language allows.
        ("Ask Hannah about it.", [("Hannah", "PER")]),
        ("Ask Metamorph about it.", [("Metamorph", "PER")]),
    ],
)
def test_persons_stay_persons(text: str, tags: list[tuple[str, str]]) -> None:
    found = detect(text, *tags, language="hu" if "úr" in text or "Kovács" in text else "en")
    assert all(t is E.PERSON for t, _ in found), found


def test_other_types_pass_untouched() -> None:
    spans = [Span(0, 4, E.ADDRESS, "Meta", 0.9, "ner")]
    assert relabel_brands("Meta street", spans, "en") == spans


def test_a_brand_that_is_a_known_given_name_is_not_relabelled(monkeypatch) -> None:
    monkeypatch.setattr(ner_orgs, "_person_names", lambda: frozenset({"muse"}))
    spans = [Span(8, 12, E.PERSON, "Muse", 0.9, "ner")]
    assert relabel_brands("Compare Muse.", spans, "en") == spans


def test_switch_off(monkeypatch) -> None:
    monkeypatch.setenv("PII_GUARD_NER_BRANDS", "false")
    assert detect("Write a haiku about Meta.", ("Meta", "PER")) == [(E.PERSON, "Meta")]


# --- The data ---------------------------------------------------------------------------------


def test_parse_brands() -> None:
    assert parse_brands("# c\nMeta\n\n  Hugging   Face  # trailing\n") == ("Meta", "Hugging Face")
    with pytest.raises(ValueError, match="no tab"):
        parse_brands("Meta\tORG\n")
    with pytest.raises(ValueError, match="letter"):
        parse_brands("1234\n")


def test_shipped_lists_parse_and_cover_the_demo_names() -> None:
    shared = load_brands(files("pii_guard.languages").joinpath("brands.tsv"))
    assert {"Meta", "Llama", "Muse", "WhatsApp", "Instagram", "Facebook", "OpenAI"} <= set(shared)
    for code in ("hu", "en", "de"):
        pack = get_pack(code)
        assert pack is not None and pack.brands is not None
        assert load_brands(pack.brands)


def test_no_shipped_brand_is_a_known_person_name() -> None:
    """A listed name that a name lexicon also lists would never fire: keep the lists apart."""
    assert not brand_names() & ner_orgs._person_names()


@pytest.mark.parametrize(
    "name", ["Ford", "Dell", "Tesla", "Siemens", "Porsche", "Disney", "Claude", "Alexa", "Otto"]
)
def test_names_that_are_also_personal_names_are_not_listed(name: str) -> None:
    assert name.casefold() not in brand_names()


def test_a_registered_pack_adds_its_brands(tmp_path) -> None:
    (tmp_path / "brands.tsv").write_text("# test\nZorblax\n", encoding="utf-8")
    register_pack(LanguagePack(code="xx", name="Test", brands=tmp_path / "brands.tsv"))
    try:
        assert "xx" in packs()
        assert "zorblax" in brand_names()
        assert detect("Ask Zorblax.", ("Zorblax", "PER")) == [(E.ORGANIZATION, "Zorblax")]
    finally:
        unregister_pack("xx")
    assert "zorblax" not in brand_names()


def test_conformance_checks_the_brands_file(tmp_path) -> None:
    from pii_guard.languages.conformance import check_structure

    def brand_findings(pack: LanguagePack) -> list[str]:
        return [
            f"{f.severity}:{f.message}"
            for f in check_structure(pack)
            if f.check == "structure.brands"
        ]

    base = get_pack("de")
    assert base is not None
    assert brand_findings(base) == []
    bad = tmp_path / "brands.tsv"
    bad.write_text("Lufthansa\tORG\n", encoding="utf-8")
    import dataclasses

    (finding,) = brand_findings(dataclasses.replace(base, brands=bad))
    assert finding.startswith("error:") and "no tab" in finding
    (finding,) = brand_findings(dataclasses.replace(base, brands=None))
    assert finding.startswith("info:")
