"""The conformance suite: every registered language pack, the same checks (docs/languages.md).

Parametrised over :func:`pii_guard.languages.packs`, so a new pack in
``src/pii_guard/languages/<code>/`` (or installed through the ``pii_guard.languages`` entry
point) is covered without touching this file. The smoke scores are printed (``-s``) and
attached to the test report as properties; only round trip and rules precision are gated.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pii_guard.languages import LanguagePack, packs
from pii_guard.languages.conformance import (
    check_fixtures,
    check_roundtrip,
    check_structure,
    load_smoke_documents,
    smoke_scores,
)
from pii_guard.types import EntityType
from pii_guard.vault.inflection import splits, variant_stems

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "eval" / "fixtures"
PACKS = packs()
CODES = sorted(PACKS)
WITH_MATCHER = [code for code in CODES if PACKS[code].inflection is not None]


def _errors(findings: list) -> list[str]:
    return [str(f) for f in findings if f.severity == "error"]


def test_the_built_in_packs_are_registered() -> None:
    assert {"de", "en", "hu"} <= set(CODES)


@pytest.mark.parametrize("code", CODES)
def test_required_parts_present_and_well_formed(code: str) -> None:
    assert _errors(check_structure(PACKS[code])) == []


@pytest.mark.parametrize("code", CODES)
def test_smoke_fixtures_validate(code: str) -> None:
    findings, documents = check_fixtures(PACKS[code], FIXTURES)
    assert _errors(findings) == []
    assert documents


@pytest.mark.parametrize("code", CODES)
def test_mask_unmask_is_the_identity_on_the_fixtures(code: str) -> None:
    pack = PACKS[code]
    assert _errors(check_roundtrip(pack, load_smoke_documents(pack, FIXTURES))) == []


@pytest.mark.parametrize("code", CODES)
def test_smoke_eval_floor(code: str, record_property: pytest.RecordProperty) -> None:
    """Round trip 100 % and rules precision >= the floor; recall is reported, not gated."""
    pack = PACKS[code]
    findings, scores = smoke_scores(pack, load_smoke_documents(pack, FIXTURES))
    for key, value in scores.items():
        record_property(f"{code}.{key}", value)
    print(f"\n{code} smoke (rules): {scores}")
    assert _errors(findings) == []


# --- Inflection: a masked occurrence never leaks ---------------------------------------------


def _person_values(pack: LanguagePack) -> list[str]:
    """The pack's labelled names that are dictionary forms (the vault confirms lemmas).

    Labelled surface forms that are themselves unambiguously inflected (``Teszt Hajnának``
    in ``hu-inflection.jsonl``) are left out: suffixing them again makes forms like
    ``Hajnánaknak`` that the language does not have.
    """
    documents = load_smoke_documents(pack, FIXTURES)
    values = {
        span.text
        for doc in documents
        for span in doc.spans
        if span.entity_type is EntityType.PERSON and span.text[-1:].isalpha()
    }
    matcher = pack.inflection
    return sorted(
        v
        for v in values
        if matcher is None or not any(s.strong for s in splits(matcher, v, EntityType.PERSON))
    )


@st.composite
def _value_and_suffix(draw: st.DrawFn, code: str) -> tuple[str, str]:
    pack = PACKS[code]
    value = draw(st.sampled_from(_person_values(pack)))
    pattern = pack.inflection.suffix_pattern(value, EntityType.PERSON)  # type: ignore[union-attr]
    suffix = draw(st.from_regex(re.compile(pattern), fullmatch=True)) if pattern else ""
    return value, suffix


@pytest.mark.parametrize("code", WITH_MATCHER)
def test_allowed_suffixes_never_leak_the_value(
    code: str, leak_check: Callable[[str, str, str, str], None]
) -> None:
    """Every suffix the matcher allows is masked with the value and restored on unmask."""

    @settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(_value_and_suffix(code))
    def check(pair: tuple[str, str]) -> None:
        value, suffix = pair
        form = value + suffix
        leak_check(code, value, form, f"{value}: {form} .")

    check()


@st.composite
def _value_and_variant(draw: st.DrawFn, code: str) -> tuple[str, str, str]:
    pack = PACKS[code]
    candidates = [
        (value, stem, pattern)
        for value in _person_values(pack)
        for stem, pattern in variant_stems(pack.inflection, value, EntityType.PERSON)  # type: ignore[arg-type]
    ]
    value, stem, pattern = draw(st.sampled_from(candidates))
    return value, stem, draw(st.from_regex(re.compile(pattern), fullmatch=True))


_WITH_VARIANTS = [
    code
    for code in WITH_MATCHER
    if any(
        variant_stems(PACKS[code].inflection, v, EntityType.PERSON)  # type: ignore[arg-type]
        for v in _person_values(PACKS[code])
    )
]


@pytest.mark.parametrize("code", _WITH_VARIANTS)
def test_changed_stems_never_leak_the_value(
    code: str, leak_check: Callable[[str, str, str, str], None]
) -> None:
    """A stem-changed form (``Zsuzsannának``) is masked under the lemma and restored."""

    @settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(_value_and_variant(code))
    def check(triple: tuple[str, str, str]) -> None:
        value, stem, suffix = triple
        form = stem + suffix
        leak_check(code, value, form, f"{value}: {form} .")

    check()
