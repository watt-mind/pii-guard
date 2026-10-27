"""The language-pack registry: discovery, entry points, overrides, compatibility paths."""

from __future__ import annotations

from collections.abc import Iterator
from importlib import metadata

import pytest

import pii_guard.languages as languages
from pii_guard.languages import (
    LanguagePack,
    LanguagePackError,
    available_languages,
    get_pack,
    packs,
    primary_language,
    register_pack,
    unregister_pack,
)
from pii_guard.types import EntityType


@pytest.fixture
def fresh_registry() -> Iterator[None]:
    languages.clear_registry()
    yield
    languages.clear_registry()


def test_lookup_is_by_primary_language() -> None:
    assert primary_language("en-GB") == primary_language("EN_us") == "en"
    assert primary_language("") == "und"
    assert get_pack("hu-HU") is get_pack("hu")
    assert get_pack("fi") is None
    assert available_languages() == ("de", "en", "hu")


def test_register_and_unregister_override_a_built_in_pack() -> None:
    built_in = get_pack("en")
    custom = register_pack(lambda: LanguagePack(code="en", name="English (custom)"))
    try:
        assert get_pack("en-GB") is custom
        assert packs()["en"] is custom
    finally:
        unregister_pack("en")
    assert get_pack("en") is built_in


def test_register_pack_rejects_what_is_not_a_pack() -> None:
    with pytest.raises(LanguagePackError, match="is a str, not a LanguagePack"):
        register_pack(lambda: "de")  # type: ignore[arg-type,return-value]
    with pytest.raises(LanguagePackError, match="failed to load: ZeroDivisionError"):
        register_pack(lambda: 1 / 0)  # type: ignore[arg-type,return-value]


class _EntryPoint:
    def __init__(self, name: str, value: str, load: object) -> None:
        self.name, self.value, self._load = name, value, load

    def load(self) -> object:
        if isinstance(self._load, Exception):
            raise self._load
        return self._load


def _entry_points(*eps: _EntryPoint):
    def fake(*, group: str) -> tuple[_EntryPoint, ...]:
        assert group == languages.ENTRY_POINT_GROUP
        return eps

    return fake


def test_entry_points_add_a_language(monkeypatch: pytest.MonkeyPatch, fresh_registry: None) -> None:
    pack = LanguagePack(code="pl", name="Polish")
    monkeypatch.setattr(
        metadata, "entry_points", _entry_points(_EntryPoint("pl", "third_party.pl:pack", pack))
    )
    assert get_pack("pl-PL") is pack
    assert set(available_languages()) == {"de", "en", "hu", "pl"}


def test_an_entry_point_may_replace_a_built_in_pack(
    monkeypatch: pytest.MonkeyPatch, fresh_registry: None
) -> None:
    better = LanguagePack(code="hu", name="Hungarian (improved)")
    monkeypatch.setattr(
        metadata,
        "entry_points",
        _entry_points(_EntryPoint("hu", "better_hu:pack", lambda: better)),
    )
    assert get_pack("hu") is better


def test_this_packages_own_entry_points_are_the_built_ins(
    monkeypatch: pytest.MonkeyPatch, fresh_registry: None
) -> None:
    monkeypatch.setattr(
        metadata,
        "entry_points",
        _entry_points(_EntryPoint("de", "pii_guard.languages.de:pack", RuntimeError("unused"))),
    )
    assert get_pack("de") is not None and get_pack("de").name == "German"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("ep", "message"),
    [
        (_EntryPoint("pl", "broken.pl:pack", ImportError("x")), "failed to import: ImportError"),
        (_EntryPoint("pl", "broken.pl:pack", 42), "is a int, not a LanguagePack"),
        (
            _EntryPoint("pl", "broken.pl:pack", LanguagePack(code="cs", name="Czech")),
            "declares code 'cs', expected 'pl'",
        ),
    ],
)
def test_a_broken_entry_point_fails_closed(
    monkeypatch: pytest.MonkeyPatch, fresh_registry: None, ep: _EntryPoint, message: str
) -> None:
    monkeypatch.setattr(metadata, "entry_points", _entry_points(ep))
    with pytest.raises(LanguagePackError, match=message):
        get_pack("hu")


# --- The components read the registry ------------------------------------------------------


def test_components_use_a_registered_pack() -> None:
    from pii_guard.detect.llm import language_profile
    from pii_guard.detect.rules import RuleDetector
    from pii_guard.detect.rules._base import _Hit
    from pii_guard.eval.forms import language_forms
    from pii_guard.languages import SurfaceForms
    from pii_guard.vault.inflection import inflection_for

    def find_ok(text: str) -> Iterator[_Hit]:
        start = text.find("OK-1234")
        if start >= 0:
            yield _Hit(start, start + 7, EntityType.ID_DOCUMENT, 0.9)

    class Matcher:
        def suffix_pattern(self, value: str, entity_type: EntityType) -> str:
            return "(?:ko)"

    matcher = Matcher()
    register_pack(
        LanguagePack(
            code="zz",
            name="Zedish",
            rules=(find_ok,),
            inflection=matcher,  # type: ignore[arg-type]
            surface_forms=SurfaceForms(stopwords=frozenset({"street"})),
            country_entity_types=(EntityType.PARCEL_NUMBER_HU,),
            allow_suffix=False,
        )
    )
    try:
        assert [s.text for s in RuleDetector().detect("id OK-1234", "zz")] == ["OK-1234"]
        assert RuleDetector().detect("id OK-1234", "en") == []
        assert inflection_for("zz-ZZ") is matcher
        assert language_forms("zz").stopwords == {"street"}
        profile = language_profile("zz")
        assert (profile.name, profile.allow_suffix, profile.notes) == (
            "Zedish",
            False,
            "default.md",
        )
        assert EntityType.PARCEL_NUMBER_HU in profile.entity_types
        assert EntityType.NATIONAL_ID_HU_TAX not in profile.entity_types
    finally:
        unregister_pack("zz")
    assert RuleDetector().detect("id OK-1234", "zz") == []


def test_the_hungarian_profile_asks_for_every_type_as_before() -> None:
    from pii_guard.detect.llm import ENTITY_DESCRIPTIONS, LANGUAGES, language_profile

    assert language_profile("hu").entity_types == tuple(ENTITY_DESCRIPTIONS)
    assert set(LANGUAGES) == {"de", "en", "hu"}
    assert LANGUAGES["en"].allow_suffix is False
    with pytest.raises(KeyError):
        LANGUAGES["en-GB"]


def test_old_import_paths_still_work() -> None:
    from pii_guard.detect.rules import en, hu
    from pii_guard.eval import HungarianForms
    from pii_guard.languages.en import rules as en_rules
    from pii_guard.languages.hu import rules as hu_rules
    from pii_guard.languages.hu.inflection import HungarianSuffixMatcher
    from pii_guard.vault import HungarianSuffixMatcher as FromVault
    from pii_guard.vault.inflection import EnglishPossessiveMatcher

    assert hu is hu_rules and en is en_rules
    assert FromVault is HungarianSuffixMatcher
    assert EnglishPossessiveMatcher().suffix_pattern("Smith", EntityType.PERSON)
    assert HungarianForms().stem_variants("Anna", EntityType.PERSON)
    with pytest.raises(AttributeError):
        import pii_guard.vault.inflection as inflection

        _ = inflection.NoSuchMatcher  # type: ignore[attr-defined]
