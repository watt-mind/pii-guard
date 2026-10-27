"""The ``known`` detector, its storage on the vault session and its place in the resolver.

All values are fictional (ADR 0005).
"""

from __future__ import annotations

import logging

import pytest

from pii_guard.detect.known import KNOWN_DETECTOR, KnownValuesDetector, merge_known
from pii_guard.detect.pipeline import DetectionPipeline, resolve_spans
from pii_guard.types import EntityType, Span
from pii_guard.vault import PLACEHOLDER_RE, Vault
from pii_guard.vault.known import (
    MIN_KNOWN_VALUE_LENGTH,
    KnownValue,
    KnownValueError,
    KnownValues,
    known_values_from,
)

KEY = bytes(range(32))
RSQUO = "\N{RIGHT SINGLE QUOTATION MARK}"  # the typographic apostrophe
NAME_HU = "Próba Zsuzsanna"
NAME_EN = "Quillon Ashgrove"


def known(*pairs: tuple[str, str]) -> list[KnownValue]:
    return known_values_from([{"value": v, "entity_type": t} for v, t in pairs])


def texts(spans: list[Span]) -> list[str]:
    return [s.text for s in spans]


class FixedDetector:
    """Returns given spans of ``text`` (by value), as a statistical detector would."""

    def __init__(self, name: str, *found: tuple[str, EntityType]) -> None:
        self.name = name
        self.found = found

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        out = []
        for value, entity_type in self.found:
            start = text.find(value)
            while start >= 0:
                out.append(Span(start, start + len(value), entity_type, value, 0.8, self.name))
                start = text.find(value, start + 1)
        return out


# --- AC1: inflected forms (hu) and possessives (en), no other detector ---------------------


def test_hungarian_inflected_forms_share_one_placeholder() -> None:
    text = (
        f"Próba Zsuzsannának küldtük. {NAME_HU} válaszol, Próba Zsuzsannát hívjuk, "
        "próba  zsuzsannával egyeztetünk, Próba Zsuzsannánál marad."
    )
    detector = KnownValuesDetector(known((NAME_HU, "PERSON")))
    spans = detector.detect(text, "hu")
    assert len(spans) == 5
    assert all(s.detector == KNOWN_DETECTOR and s.score == 1.0 for s in spans)

    session = Vault(KEY).session()
    masked = session.mask(text, spans, language="hu")
    assert "Zsuzsann" not in masked and "zsuzsann" not in masked
    assert len(set(PLACEHOLDER_RE.findall(masked))) == 1
    assert "]]nak küldtük" in masked and "]]t hívjuk" in masked and "]]val egyeztetünk" in masked


def test_digraph_and_consonant_doubling() -> None:
    text = "Kovács Szabolccsal tárgyaltunk, Kovács Szabolcsnak írunk. Teszt Elekkel is."
    detector = KnownValuesDetector(known(("Kovács Szabolcs", "PERSON"), ("Teszt Elek", "PERSON")))
    session = Vault(KEY).session()
    masked = session.mask(text, detector.detect(text, "hu"), language="hu")
    assert "Kovács" not in masked and "Elek" not in masked
    assert len(set(PLACEHOLDER_RE.findall(masked))) == 2
    assert session.unmask(masked) == text


def test_english_possessive_and_case() -> None:
    text = f"{NAME_EN}'s file. {NAME_EN}{RSQUO}s manager. quillon ashgrove called."
    detector = KnownValuesDetector(known((NAME_EN, "PERSON")))
    spans = detector.detect(text, "en")
    assert texts(spans) == [NAME_EN, NAME_EN, "quillon ashgrove"]
    masked = Vault(KEY).session().mask(text, spans, language="en")
    assert "]]'s file" in masked and f"]]{RSQUO}s manager" in masked
    assert "uillon" not in masked


def test_no_match_inside_other_words() -> None:
    detector = KnownValuesDetector(known(("Anna", "PERSON")))
    assert detector.detect("Annabella and Hannah, but Anna's coat.", "en") == [
        Span(26, 30, EntityType.PERSON, "Anna", 1.0, KNOWN_DETECTOR)
    ]


def test_longer_value_wins_over_a_contained_one() -> None:
    detector = KnownValuesDetector(known(("Kocsárd", "PERSON"), ("Tesztes Kocsárd", "PERSON")))
    text = "Tesztes Kocsárd aláírt, Kocsárd elfogadta."
    assert texts(detector.detect(text, "hu")) == ["Tesztes Kocsárd", "Kocsárd"]


def test_internal_id_format() -> None:
    detector = KnownValuesDetector(known(("KX-77-3021", "ID_DOCUMENT")))
    text = "Azonosító: KX-77-3021, a KX-77-3021-nek megfelelően; KX-77-30210 nem az."
    spans = detector.detect(text, "hu")
    assert texts(spans) == ["KX-77-3021", "KX-77-3021"]
    assert {s.entity_type for s in spans} == {EntityType.ID_DOCUMENT}


def test_empty_detector_finds_nothing() -> None:
    assert KnownValuesDetector().detect("Próba Zsuzsanna", "hu") == []


# --- AC3: pre-loaded and detected -> one placeholder -----------------------------------------


def test_known_wins_and_keeps_the_suffix_outside() -> None:
    text = f"Próba Zsuzsannának küldtük, {NAME_HU} válaszolt."
    llm = FixedDetector(
        "llm", ("Próba Zsuzsannának", EntityType.PERSON), (NAME_HU, EntityType.PERSON)
    )
    spans = merge_known(text, llm.detect(text), store_of((NAME_HU, "PERSON")), "hu")
    assert [(s.text, s.detector) for s in spans] == [
        ("Próba Zsuzsanná", KNOWN_DETECTOR),
        (NAME_HU, KNOWN_DETECTOR),
    ]
    masked = Vault(KEY).session().mask(text, spans, language="hu")
    assert len(set(PLACEHOLDER_RE.findall(masked))) == 1
    assert masked.count("]]nak küldtük") == 1


def test_known_wins_a_type_conflict() -> None:
    text = "Szerződő fél: Minta Rozália."
    llm = FixedDetector("llm", ("Minta Rozália", EntityType.ORGANIZATION))
    spans = merge_known(text, llm.detect(text), store_of(("Minta Rozália", "PERSON")), "hu")
    assert [(s.entity_type, s.detector) for s in spans] == [(EntityType.PERSON, KNOWN_DETECTOR)]


def test_losing_span_keeps_its_other_characters() -> None:
    text = "Kedves dr. Minta Rozália!"
    llm = FixedDetector("llm", ("dr. Minta Rozália", EntityType.PERSON))
    spans = merge_known(text, llm.detect(text), store_of(("Minta Rozália", "PERSON")), "hu")
    assert [(s.text, s.detector) for s in spans] == [("dr", "llm"), ("Minta Rozália", "known")]


def test_detected_first_then_preloaded_gives_the_same_placeholder() -> None:
    session = Vault(KEY).session()
    first = session.mask(f"{NAME_HU} írt.", [Span(0, 15, EntityType.PERSON, NAME_HU, 0.9, "llm")])
    session.known_values.add(known((NAME_HU, "PERSON")))
    text = "Válasz Próba Zsuzsannának."
    second = session.mask(text, merge_known(text, [], session.known_values, "hu"))
    assert PLACEHOLDER_RE.findall(first) == PLACEHOLDER_RE.findall(second)


def test_pipeline_runs_known_first_and_it_wins() -> None:
    text = "Minta Rozália, Kovács Szabolcs."
    pipeline = DetectionPipeline(
        [
            FixedDetector("llm", ("Minta Rozália, Kovács", EntityType.ORGANIZATION)),
            KnownValuesDetector(known(("Minta Rozália", "PERSON"))),
        ]
    )
    spans = pipeline.detect(text, "hu")
    assert [(s.text, s.entity_type.value, s.detector) for s in spans] == [
        ("Minta Rozália", "PERSON", "known"),
        ("Kovács", "ORGANIZATION", "llm"),
    ]


def test_resolver_without_known_spans_is_unchanged() -> None:
    text = "Teszt Elek írt."
    spans = [Span(0, 10, EntityType.PERSON, "Teszt Elek", 0.9, "llm")]
    assert resolve_spans(text, spans) == resolve_spans(text, spans, overriding=())


# --- validation and limits -----------------------------------------------------------------


@pytest.mark.parametrize("value", ["", "  ", "Al", " A b "])
def test_too_short_values_are_refused(value: str) -> None:
    with pytest.raises(KnownValueError) as info:
        known((value, "PERSON"))
    assert str(MIN_KNOWN_VALUE_LENGTH) in info.value.message
    assert "known value 0 (PERSON)" in info.value.message


def test_too_long_values_are_refused() -> None:
    with pytest.raises(KnownValueError, match="longer than 10"):
        known_values_from([{"value": "Hosszú Név Nagyon", "entity_type": "PERSON"}], max_length=10)


@pytest.mark.parametrize(
    "item",
    [
        {"value": "Teszt Elek", "entity_type": "NOT_A_TYPE"},
        {"value": "Teszt Elek", "entity_type": "FACE"},
        {"value": 42, "entity_type": "PERSON"},
        "Teszt Elek",
    ],
)
def test_invalid_items_are_refused_without_the_value(item: object) -> None:
    with pytest.raises(KnownValueError) as info:
        known_values_from([item])
    assert "Teszt Elek" not in info.value.message
    assert info.value.status_code == 422


def test_store_deduplicates_and_limits_atomically() -> None:
    store = KnownValues()
    assert store.add(known(("Teszt Elek", "PERSON"), ("teszt  elek", "PERSON"))) == 1
    assert store.add(known(("Teszt Elek", "PERSON"), ("Teszt Elek", "ORGANIZATION"))) == 1
    assert len(store) == 2
    with pytest.raises(KnownValueError) as info:
        store.add(known(("Minta Rozália", "PERSON"), ("Kovács Szabolcs", "PERSON")), max_values=3)
    assert info.value.code == "too_many_known_values"
    assert len(store) == 2  # nothing added


# --- AC2 / AC4: never in reprs or logs; expiry removes them --------------------------------


def test_values_never_in_reprs_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    values = known((NAME_HU, "PERSON"))
    session = Vault(KEY).session()
    session.known_values.add(values)
    detector = KnownValuesDetector(session.known_values)
    text = "Levél Próba Zsuzsannának."
    spans = merge_known(text, [], detector, "hu")
    session.mask(text, spans)
    shown = " ".join(
        [
            repr(values),
            str(values[0]),
            repr(session.known_values),
            repr(detector),
            repr(session),
            repr(spans),
            caplog.text,
        ]
    )
    assert "Zsuzsann" not in shown
    assert "Próba" not in shown


def test_session_expiry_removes_known_values() -> None:
    now = [0.0]
    vault = Vault(KEY, ttl_seconds=10, clock=lambda: now[0])
    session = vault.session()
    store = session.known_values
    store.add(known((NAME_HU, "PERSON")))
    assert len(store) == 1
    now[0] = 11.0
    assert vault.purge_expired() == 1
    assert len(store) == 0
    with pytest.raises(Exception, match="not found or expired"):
        _ = session.known_values


def test_closing_a_session_clears_known_values() -> None:
    vault = Vault(KEY)
    session = vault.session()
    store = session.known_values
    store.add(known((NAME_HU, "PERSON")))
    vault.drop(session.session_id)
    assert len(store) == 0


def store_of(*pairs: tuple[str, str]) -> KnownValues:
    store = KnownValues()
    store.add(known(*pairs))
    return store


# --- AC5: the eval measures the uplift of pre-loading -------------------------------------


def test_eval_known_values_uplift(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    import json
    from pathlib import Path

    from pii_guard.eval.cli import main

    fixtures = Path(__file__).parents[2] / "eval" / "fixtures" / "known-values"
    without, with_known = tmp_path / "without.json", tmp_path / "with.json"
    assert main(["--fixtures", str(fixtures), "--json", str(without)]) == 0
    assert main(["--fixtures", str(fixtures), "--known-values", "--json", str(with_known)]) == 0
    assert "Known values pre-loaded from fixture meta" in capsys.readouterr().out

    def overall(path: Path) -> dict:
        card = json.loads(path.read_text(encoding="utf-8"))
        return card["overall"], card["meta"]

    base, base_meta = overall(without)
    known_card, meta = overall(with_known)
    assert "known_values" not in base_meta and meta["known_values"] > 0
    assert json.dumps(known_card) != json.dumps(base)
    assert known_card["leak"]["rate"] == 0.0
    assert base["leak"]["rate"] > 0.5
