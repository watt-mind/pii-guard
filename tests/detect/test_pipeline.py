"""Detection pipeline and span resolver. All text is fictional (ADR 0005)."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import httpx
import pytest

from pii_guard.config import Settings
from pii_guard.detect.llm import LlmDetector
from pii_guard.detect.pipeline import DetectionPipeline, resolve_spans
from pii_guard.detect.rules import RuleDetector
from pii_guard.types import DetectionError, Detector, EntityType, Span

E = EntityType
FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "muse_spark_recorded.json").read_text("utf-8")
)


def span(text: str, value: str, entity_type: EntityType, detector: str, score: float = 0.8,
         nth: int = 0) -> Span:  # fmt: skip
    start = -1
    for _ in range(nth + 1):
        start = text.index(value, start + 1)
    return Span(start, start + len(value), entity_type, value, score, detector)


class Fixed:
    """A detector that returns preset spans."""

    def __init__(self, name: str, spans: list[Span]) -> None:
        self.name = name
        self.spans = spans

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        return list(self.spans)


class Broken:
    name = "broken"

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        raise self.exc


def recorded_llm(name: str) -> LlmDetector:
    body = FIXTURES[name]["response"]
    return LlmDetector(
        base_url="https://llm.test/v1",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
        settings=Settings(),
    )


def assert_valid(text: str, spans: list[Span]) -> None:
    for a, b in itertools.pairwise(spans):
        assert a.end <= b.start, "resolved spans must not overlap"
    for s in spans:
        assert text[s.start : s.end] == s.text


# --- End to end with the rules and the recorded LLM ----------------------------


def test_rules_and_llm_on_recorded_contract() -> None:
    text = FIXTURES["contract_hu"]["text"]
    pipeline = DetectionPipeline([RuleDetector(), recorded_llm("contract_hu")])
    spans = pipeline.detect(text)
    assert_valid(text, spans)
    by_text = {(s.text, s.entity_type): s.detector for s in spans}

    # Checksum-validated rule spans keep their boundaries and provenance.
    assert by_text[("HU42 1177 3016 1111 1018 0000 0000", E.BANK_ACCOUNT)] == "rules"
    assert by_text[("pelda.agnes@example.com", E.EMAIL)] == "rules"
    assert by_text[("+36 30 123 4567", E.PHONE)] == "rules"
    # The rules' bare postcode is absorbed into the LLM's full address.
    assert by_text[("6720 Szeged, Kárász utca 7. szám", E.ADDRESS)] == "llm"
    # Base form and inflected form of the same name merge into one span per occurrence.
    assert ("Teszt Eleknek", E.PERSON) in by_text
    assert ("Példa Ágnesnek", E.PERSON) in by_text
    assert sum(s.entity_type is E.PERSON for s in spans) == 6
    assert ("1985. április 12.", E.DATE_OF_BIRTH) in by_text


def test_person_beats_organization_in_sole_trader_name() -> None:
    text = FIXTURES["prose_hu"]["text"]
    spans = DetectionPipeline([RuleDetector(), recorded_llm("prose_hu")]).detect(text)
    assert_valid(text, spans)
    found = [(s.entity_type, s.text) for s in spans]
    # "Próba Zsuzsanna e.v." (ORGANIZATION, kept by policy) must not hide the PERSON inside.
    assert (E.PERSON, "Próba Zsuzsanna") in found
    assert (E.ORGANIZATION, "e.v") in found
    assert (E.PERSON, "Kovácsné Próba Zsuzsanna") in found
    assert (E.VEHICLE_PLATE, "ABC-123") in found


def test_rules_and_llm_on_recorded_english_letter() -> None:
    text = FIXTURES["letter_en"]["text"]
    spans = DetectionPipeline([RuleDetector(), recorded_llm("letter_en")]).detect(text, "en")
    assert_valid(text, spans)
    found = {(s.entity_type, s.text): s.detector for s in spans}
    assert found[(E.PHONE, "+44 7700 900123")] == "rules"
    assert found[(E.EMAIL, "j.fakename@example.org")] == "rules"
    assert found[(E.PERSON, "Jonathan Fakename")] == "llm"
    assert (E.ADDRESS, "Flat 3, 27 Example Road, Testington TE5 7XY") in found
    assert (E.ID_DOCUMENT, "123456789") in found
    assert (E.ORGANIZATION, "Placeholder Widgets Ltd") in found


# --- Resolver rules ----------------------------------------------------------------


def test_same_type_overlaps_are_unioned() -> None:
    text = "Lakcím: 6720 Szeged, Kárász utca 7."
    spans = resolve_spans(
        text,
        [
            span(text, "6720 Szeged", E.ADDRESS, "ner", 0.7),
            span(text, "Szeged, Kárász utca 7.", E.ADDRESS, "llm", 0.85),
        ],
    )
    assert [(s.text, s.score, s.detector) for s in spans] == [
        ("6720 Szeged, Kárász utca 7.", 0.85, "llm")
    ]


def test_identical_spans_keep_highest_score() -> None:
    text = "Szia Ede!"
    spans = resolve_spans(
        text,
        [span(text, "Ede", E.PERSON, "ner", 0.6), span(text, "Ede", E.PERSON, "llm", 0.9)],
        detector_order=["ner", "llm"],
    )
    assert [(s.text, s.score) for s in spans] == [("Ede", 0.9)]


def test_authoritative_structured_span_keeps_boundaries() -> None:
    text = "Hívj: +36 30 123 4567 (mobil)"
    spans = resolve_spans(
        text,
        [
            span(text, "+36 30 123 4567", E.PHONE, "rules", 0.9),
            span(text, "+36 30 123 4567 (mobil)", E.PHONE, "llm", 0.85),
        ],
    )
    assert [(s.text, s.detector) for s in spans] == [("+36 30 123 4567", "rules")]


def test_authoritative_span_beats_longer_llm_span_of_another_type() -> None:
    text = "Írj: teszt.elek@example.com most."
    spans = resolve_spans(
        text,
        [
            span(text, "teszt.elek@example.com", E.EMAIL, "rules", 0.99),
            span(text, "Írj: teszt.elek@example.com", E.PERSON, "llm", 0.85),
        ],
    )
    # The rule span wins; the uncovered remainder of the LLM span stays masked.
    assert [(s.entity_type, s.text) for s in spans] == [
        (E.PERSON, "Írj"),
        (E.EMAIL, "teszt.elek@example.com"),
    ]


def test_non_structured_rule_spans_are_not_authoritative() -> None:
    text = "Cím: 6720 Szeged"
    spans = resolve_spans(
        text,
        [
            span(text, "6720", E.ADDRESS, "rules", 0.75),
            span(text, "6720 Szeged", E.ADDRESS, "llm", 0.85),
        ],
    )
    assert [(s.text, s.detector) for s in spans] == [("6720 Szeged", "llm")]


def test_adjudicator_wins_type_disagreement() -> None:
    text = "Átvette: Bárány Kft képviseletében Bárány."
    ner = span(text, "Bárány", E.ADDRESS, "ner", 0.9, nth=1)
    llm = span(text, "Bárány", E.PERSON, "llm", 0.6, nth=1)
    spans = resolve_spans(text, [ner, llm], detector_order=["ner", "llm"])
    assert [(s.entity_type, s.detector) for s in spans] == [(E.PERSON, "llm")]
    # Without an adjudicator, the higher score wins.
    spans = resolve_spans(text, [ner, llm], adjudicator=None)
    assert [(s.entity_type, s.detector) for s in spans] == [(E.ADDRESS, "ner")]


def test_partial_cross_type_overlap_keeps_remainder() -> None:
    text = "Teszt Elek Szeged lakos"
    spans = resolve_spans(
        text,
        [
            span(text, "Teszt Elek Szeged", E.PERSON, "ner", 0.6),
            span(text, "Szeged lakos", E.ADDRESS, "llm", 0.6),
        ],
        adjudicator=None,
    )
    assert_valid(text, spans)
    assert [(s.entity_type, s.text) for s in spans] == [
        (E.PERSON, "Teszt Elek Szeged"),
        (E.ADDRESS, "lakos"),
    ]


def test_remainder_of_only_punctuation_is_dropped() -> None:
    text = "(Minta Mária)"
    spans = resolve_spans(
        text,
        [
            span(text, "(Minta Mária)", E.ORGANIZATION, "llm", 0.9),
            span(text, "Minta Mária", E.PERSON, "ner", 0.6),
        ],
    )
    assert [(s.entity_type, s.text) for s in spans] == [(E.PERSON, "Minta Mária")]


def test_span_that_does_not_fit_the_text_fails_closed() -> None:
    bad = Span(0, 4, E.PERSON, "Ödön", 0.9, "ner")
    with pytest.raises(DetectionError):
        resolve_spans("Ede ír", [bad])
    with pytest.raises(DetectionError):
        resolve_spans("Ed", [bad])


# --- Pipeline ------------------------------------------------------------------


def test_pipeline_is_a_detector_and_resolves_names() -> None:
    pipeline = DetectionPipeline(["rules"])
    assert isinstance(pipeline, Detector)
    text = "E-mail: teszt.elek@example.com"
    assert [s.entity_type for s in pipeline.detect(text)] == [E.EMAIL]


def test_pipeline_needs_detectors() -> None:
    with pytest.raises(ValueError):
        DetectionPipeline([])


def test_min_score_filters_before_resolving() -> None:
    text = "Szia Ede és Ödön!"
    pipeline = DetectionPipeline(
        [
            Fixed(
                "ner",
                [span(text, "Ede", E.PERSON, "ner", 0.3), span(text, "Ödön", E.PERSON, "ner", 0.9)],
            )
        ],
        min_score=0.5,
    )
    assert [s.text for s in pipeline.detect(text)] == ["Ödön"]


def test_detection_error_propagates() -> None:
    pipeline = DetectionPipeline([RuleDetector(), Broken(DetectionError("llm timed out"))])
    with pytest.raises(DetectionError, match="llm timed out"):
        pipeline.detect("Teszt Elek")


def test_unexpected_error_becomes_detection_error_without_raw_text() -> None:
    pipeline = DetectionPipeline([Broken(RuntimeError("could not parse Teszt Elek"))])
    with pytest.raises(DetectionError) as excinfo:
        pipeline.detect("Teszt Elek")
    assert "Teszt" not in excinfo.value.message
    assert "broken" in excinfo.value.message


def test_llm_failure_blocks_the_pipeline() -> None:
    llm = LlmDetector(
        base_url="https://llm.test/v1",
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
        settings=Settings(),
    )
    with pytest.raises(DetectionError):
        DetectionPipeline([RuleDetector(), llm]).detect("E-mail: teszt.elek@example.com")
