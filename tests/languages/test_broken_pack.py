"""A deliberately broken pack fails the conformance checks, each with a clear message."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from importlib.resources import files
from pathlib import Path

import pytest

from pii_guard.detect.rules._base import _Hit
from pii_guard.languages import LanguagePack, SurfaceForms, get_pack
from pii_guard.languages.conformance import (
    ConformanceError,
    assert_conformant,
    check_pack,
    check_structure,
)
from pii_guard.types import EntityType

GOOD_PROMPT = files("pii_guard.languages.de").joinpath("prompt.md")
MISSING_PROMPT = files("pii_guard.languages.de").joinpath("no-such-prompt.md")


def _raises(text: str) -> Iterator[_Hit]:
    raise RuntimeError("boom")
    yield  # pragma: no cover


def _out_of_range(text: str) -> Iterator[_Hit]:
    yield _Hit(0, len(text) + 5, EntityType.PERSON, 0.9)


class _CapturingMatcher:
    def suffix_pattern(self, value: str, entity_type: EntityType) -> str:
        return "(s)"  # a capturing group breaks the vault's pattern


def _messages(pack: LanguagePack, **kwargs: object) -> list[str]:
    report = check_pack(pack, **kwargs)  # type: ignore[arg-type]
    return [f"{f.check}: {f.message}" for f in report.errors]


def test_a_broken_pack_reports_every_broken_part() -> None:
    broken = LanguagePack(
        code="XX1",
        name="",
        prompt=MISSING_PROMPT,
        everywhere=(_raises,),
        rules=(_out_of_range,),
        inflection=_CapturingMatcher(),  # type: ignore[arg-type]
        surface_forms=SurfaceForms(stopwords=frozenset({""})),
        smoke_fixtures=("wrong-name.jsonl",),
    )
    messages = "\n".join(_messages(broken))
    assert "structure.code: code 'XX1' must be a lowercase ISO 639-1" in messages
    assert "structure.name: name must be the language's English name" in messages
    assert "structure.prompt: prompt notes cannot be read" in messages
    assert "structure.everywhere: rule _raises: raises RuntimeError" in messages
    assert "structure.rules: rule _out_of_range: yields a hit with offsets outside" in messages
    assert "structure.inflection: suffix_pattern must not have capturing groups" in messages
    assert "structure.surface_forms: stopwords must be non-empty str" in messages
    assert "must be named 'XX1-<name>.jsonl'" in messages


def test_missing_required_parts_say_what_to_add() -> None:
    messages = "\n".join(_messages(LanguagePack(code="zz", name="Zedish")))
    assert "no prompt notes: add prompt.md" in messages
    assert "no smoke fixtures declared: add smoke_fixtures=('zz-smoke.jsonl',)" in messages


def test_optional_parts_report_their_fallback() -> None:
    pack = LanguagePack(
        code="zz", name="Zedish", prompt=GOOD_PROMPT, smoke_fixtures=("zz-a.jsonl",)
    )
    infos = {f.check: f.message for f in check_structure(pack) if f.severity == "info"}
    assert infos["structure.inflection"] == "no inflection matcher: exact matching"
    assert "language-independent rules" in infos["structure.rules"]
    warnings = [f.check for f in check_structure(pack) if f.severity == "warning"]
    assert "structure.registered" in warnings


def _write(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def _doc(doc_id: str, language: str, text: str, value: str, entity_type: str) -> dict:
    start = text.index(value)
    span = {"start": start, "end": start + len(value), "entity_type": entity_type}
    return {"id": doc_id, "language": language, "text": text, "spans": [span], "meta": {}}


def test_fixture_problems_are_reported(tmp_path: Path) -> None:
    pack = LanguagePack(
        code="zz",
        name="Zedish",
        prompt=GOOD_PROMPT,
        smoke_fixtures=("zz-smoke.jsonl", "zz-missing.jsonl"),
    )
    _write(
        tmp_path / "zz-smoke.jsonl",
        [_doc("zz-1", "en", "Mail sample.person@example.com now.", "sample.person@example.com",
              "EMAIL")],
    )  # fmt: skip
    messages = "\n".join(_messages(pack, fixtures_dir=tmp_path))
    assert "fixtures.files: " in messages and "zz-missing.jsonl not found" in messages
    assert "fixtures.language: 1 document(s) not in 'zz': zz-1" in messages


def test_an_imprecise_rule_fails_the_smoke_floor(tmp_path: Path) -> None:
    def every_word(text: str) -> Iterator[_Hit]:
        start = 0
        for word in text.split():
            start = text.index(word, start)
            yield _Hit(start, start + len(word), EntityType.PERSON, 0.5)
            start += len(word)

    pack = LanguagePack(
        code="zz",
        name="Zedish",
        prompt=GOOD_PROMPT,
        smoke_fixtures=("zz-smoke.jsonl",),
        rules=(every_word,),
    )
    text = "Mail sample.person@example.com now please."
    _write(
        tmp_path / "zz-smoke.jsonl",
        [_doc(f"zz-{i}", "zz", text, "sample.person@example.com", "EMAIL") for i in range(10)],
    )
    with pytest.raises(ConformanceError) as excinfo:
        assert_conformant(pack, fixtures_dir=tmp_path)
    report = str(excinfo.value)
    assert "language pack 'zz': FAILS" in report
    assert "smoke.precision: rules overlap precision 0.250 < 0.9" in report
    assert get_pack("zz") is None  # the temporary registration is undone


def test_the_leak_property_catches_an_unmasked_inflected_form(
    leak_check: Callable[[str, str, str, str], None],
) -> None:
    """Without a genitive matcher, ``Annas`` keeps the name: the property check fails."""
    with pytest.raises(AssertionError, match="left unmasked"):
        leak_check("fi", "Anna", "Annas", "Anna: Annas .")  # fi: no pack, exact matching
    leak_check("de", "Anna", "Annas", "Anna: Annas .")  # the de pack's genitive matcher
