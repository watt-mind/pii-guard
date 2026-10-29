"""The synthetic agent-traffic generator (LAB-1226): seeded, gold from construction, fictional."""

# ruff: noqa: S311

from __future__ import annotations

import json
import random
import re
from collections import Counter
from pathlib import Path

import pytest

from pii_guard.detect.checksums import is_valid_hu_tax_id, is_valid_iban, is_valid_taj
from pii_guard.eval.datasets import synthetic as syn
from pii_guard.eval.fixtures import load_fixtures
from pii_guard.languages.de.checksums import is_valid_steuer_id
from pii_guard.types import EntityType

ROOT = Path(__file__).resolve().parents[2]
TEST = [ROOT / p for p in syn.split_paths("test")]


@pytest.fixture(scope="module")
def docs() -> list:
    return load_fixtures(TEST)


def test_committed_split_is_the_generator_output() -> None:
    for path, lang in zip(TEST, syn.LANGUAGES, strict=True):
        first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        doc = syn.document(lang, 0, seed=syn.DEFAULT_SEED, split="test")
        assert first == json.loads(json.dumps(doc.to_dict(), ensure_ascii=False))


def test_size_shapes_and_languages(docs: list) -> None:
    per_lang = Counter(d.language for d in docs)
    assert all(per_lang[lang] >= 300 for lang in syn.LANGUAGES)
    shapes = Counter(d.meta["shape"] for d in docs)
    assert set(shapes) >= set(syn.SHAPES) - {"inflected-names"} | {"inflected-names", "prose-note"}
    assert all(d.meta["source"] == "synthetic" and d.meta["generator"] for d in docs)


def _validator(t: EntityType, lang: str):
    if t is EntityType.NATIONAL_ID_HU_TAX:
        return is_valid_hu_tax_id
    if t is EntityType.NATIONAL_ID_HU_TAJ:
        return lambda v: is_valid_taj(re.sub(r"\D", "", v))
    if t is EntityType.ID_DOCUMENT and lang == "de":
        return is_valid_steuer_id
    if t is EntityType.BANK_ACCOUNT:
        return lambda v: (
            is_valid_iban(v.replace(" ", ""))
            if v[:2].isalpha()
            else syn._luhn_digit(re.sub(r"\D", "", v)[:-1]) == int(re.sub(r"\D", "", v)[-1])
        )
    raise AssertionError(t)


def test_checksum_flags_match_the_validators(docs: list) -> None:
    seen: Counter[bool] = Counter()
    for d in docs:
        perturbed = {(p["start"], p["end"]) for p in d.meta["perturbed"]}
        for mark in d.meta["checksum"]:
            if (mark["start"], mark["end"]) in perturbed:
                continue  # spacing/dots/zero-width change the surface, not the digits
            span = next(s for s in d.spans if (s.start, s.end) == (mark["start"], mark["end"]))
            assert _validator(span.entity_type, d.language)(span.text) is mark["valid"], d.id
            seen[mark["valid"]] += 1
    share = seen[False] / (seen[True] + seen[False])
    assert 0.08 < share < 0.25, share


def test_perturbations_and_negatives(docs: list) -> None:
    kinds = Counter(p["kind"] for d in docs for p in d.meta["perturbed"])
    assert set(kinds) >= {"spaced-digits", "dotted-digits", "homoglyph", "zero-width",
                          "line-break", "leetspeak-email"}  # fmt: skip
    text = "\n".join(d.text for d in docs)
    for company in ("OTP Bank", "Siemens", "Microsoft"):
        assert company in text
    for d in docs:  # public companies and secrets are never gold
        assert not any(s.text in {"OTP Bank", "Siemens", "Microsoft"} for s in d.spans)
        for region in d.meta["ignore"]:
            assert d.text[region["start"] : region["end"]].startswith("sk-test-")


def test_values_are_fictional(docs: list) -> None:
    for d in docs:
        for s in d.spans:
            if s.entity_type is EntityType.EMAIL and "[at]" not in s.text:
                latin = str.maketrans(
                    {c: lat for lat, c in syn._HOMOGLYPHS.items()} | {"\u200b": ""}
                )
                domain = s.text.rsplit("@", 1)[1].translate(latin)
                assert re.search(r"example\.(com|org|net)$|\.example$", domain), d.id


def test_json_shapes_parse(docs: list) -> None:
    for d in docs:
        if d.meta["shape"] in ("tool-call-json", "nested-json") or d.text.startswith(
            '{\n  "messages"'
        ):
            body = json.loads(d.text)
            if d.meta["shape"] == "tool-call-json":
                args = body["messages"][1]["tool_calls"][0]["function"]["arguments"]
                assert json.loads(args)["customer"]["name"]


def test_dev_split_differs_and_is_seeded() -> None:
    a = syn.build_split("dev", {"hu": 3, "en": 3, "de": 3})
    b = syn.build_split("dev", {"hu": 3, "en": 3, "de": 3})
    assert [d.to_dict() for d in a["hu"]] == [d.to_dict() for d in b["hu"]]
    t = syn.document("hu", 0, seed=syn.DEFAULT_SEED, split="test")
    assert a["hu"][0].text != t.text and a["hu"][0].id.startswith("hu-agent-traffic-dev-")


def test_perturb_and_checksum_helpers() -> None:
    rng = random.Random(1)
    assert syn.break_checksum(rng, "123") != "123"
    assert is_valid_steuer_id(syn.steuer_id(rng))
    for kind_needed in ("spaced-digits", "dotted-digits"):
        for _ in range(50):
            out, kind = syn.perturb(rng, EntityType.PHONE, "+36 20 123 4567")
            if kind == kind_needed:
                assert sum(c.isdigit() for c in out) == 11
                break
        else:  # pragma: no cover
            raise AssertionError(kind_needed)
    out, kind = syn.perturb(random.Random(3), EntityType.PERSON, "Abc", multiline=True)
    assert kind in ("homoglyph", "zero-width")
    built = syn.escape_built(syn.to_json({"a": syn.Gold(EntityType.EMAIL, "x@example.com")}))
    assert built.text[built.spans[0][0] : built.spans[0][1]] == "x@example.com"
