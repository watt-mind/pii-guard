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
        api_key="test-key",
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
    # Base form and inflected form of the same name merge into one span per occurrence; an
    # inflected one ends at its stem, so the case ending stays outside the placeholder (LAB-1174).
    assert ("Teszt Eleknek", E.PERSON) not in by_text
    assert ("Teszt Elek", E.PERSON) in by_text
    assert ("Példa Ágnes", E.PERSON) in by_text
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


# A same-type span from another detector that runs past the validated span keeps its rest,
# as a span of another type does (LAB-1205): the rules cut the value short, not the LLM.
@pytest.mark.parametrize(
    ("text", "rule", "other", "entity_type", "rest"),
    [
        ("Write to user@example.xn--p1ai now", "user@example.xn", "user@example.xn--p1ai",
         E.EMAIL, "p1ai"),
        ("Write to x@ex.xn--qxam now", "x@ex.xn", "x@ex.xn--qxam", E.EMAIL, "qxam"),
        ("Hívjon: +36 1 234 5678 / 123 mellék", "+36 1 234 5678", "+36 1 234 5678 / 123",
         E.PHONE, "123"),
        ("Hívjon: 06 1 234 5678", "1 234 5678", "06 1 234 5678", E.PHONE, "06"),
    ],
)  # fmt: skip
@pytest.mark.parametrize("other_detector", ["llm", "ner"])
def test_same_type_overlap_keeps_the_rest_of_the_longer_span(
    text: str, rule: str, other: str, entity_type: EntityType, rest: str, other_detector: str
) -> None:
    spans = resolve_spans(
        text,
        [
            span(text, rule, entity_type, "rules", 0.9),
            span(text, other, entity_type, other_detector),
        ],
        detector_order=["rules", other_detector],
    )
    assert [(s.entity_type, s.text, s.detector) for s in spans] == sorted(
        [(entity_type, rule, "rules"), (entity_type, rest, other_detector)],
        key=lambda t: text.index(t[1]),
    )
    # The validated span keeps its boundaries and takes the higher score; nothing is lost.
    assert next(s for s in spans if s.detector == "rules").score == 0.9
    covered = {i for s in spans for i in range(s.start, s.end)}
    assert all(i in covered for i in range(text.index(other), text.index(other) + len(other))
               if text[i].isalnum())  # fmt: skip


@pytest.mark.parametrize(
    ("text", "rule", "other"),
    [
        ("Hívj: +36 30 123 4567 (mobil)", "+36 30 123 4567", "+36 30 123 4567 (mobil)"),
        ("E-mail: teszt@example.com", "teszt@example.com", "E-mail: teszt@example.com"),
        ("Írjon a teszt@example.com-ra", "teszt@example.com", "teszt@example.com-ra"),
    ],
)
def test_same_type_overlap_drops_label_words_and_suffixes(text: str, rule: str, other: str) -> None:
    entity_type = E.EMAIL if "@" in rule else E.PHONE
    spans = resolve_spans(
        text, [span(text, rule, entity_type, "rules", 0.9), span(text, other, entity_type, "llm")]
    )
    assert [(s.text, s.detector) for s in spans] == [(rule, "rules")]


def test_same_type_rest_merges_with_other_detectors_rest() -> None:
    text = "Hívjon: +36 1 234 5678 / 123 mellék"
    spans = resolve_spans(
        text,
        [
            span(text, "+36 1 234 5678", E.PHONE, "rules", 0.9),
            span(text, "+36 1 234 5678 / 12", E.PHONE, "ner", 0.7),
            span(text, "+36 1 234 5678 / 123", E.PHONE, "llm", 0.85),
        ],
        detector_order=["rules", "ner", "llm"],
    )
    assert [(s.text, s.detector) for s in spans] == [("+36 1 234 5678", "rules"), ("123", "llm")]


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


def test_validated_rule_id_document_beats_higher_score_ner_span_on_exact_range() -> None:
    # LAB-1380: after token-snapping, the NER PHONE/BANK_ACCOUNT span covers the same range
    # as a checksum-validated rule ID_DOCUMENT span but scores higher; masking is complete
    # either way, only the type label (and per-type recall) is wrong.
    text = "Steuer-ID: 86095742719"
    rule = Span(11, 22, E.ID_DOCUMENT, "86095742719", 0.85, "rules", subtype="validated")
    ner = span(text, "86095742719", E.PHONE, "ner", 0.95)
    spans = resolve_spans(text, [rule, ner], detector_order=["rules", "ner"])
    assert [(s.entity_type, s.text, s.detector) for s in spans] == [
        (E.ID_DOCUMENT, "86095742719", "rules")
    ]
    # Without the validated subtype the higher-score NER span still wins.
    bare = Span(11, 22, E.ID_DOCUMENT, "86095742719", 0.85, "rules")
    spans = resolve_spans(text, [bare, ner], detector_order=["rules", "ner"])
    assert [(s.entity_type, s.detector) for s in spans] == [(E.PHONE, "ner")]


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
        api_key="test-key",
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
        settings=Settings(),
    )
    with pytest.raises(DetectionError):
        DetectionPipeline([RuleDetector(), llm]).detect("E-mail: teszt.elek@example.com")


# --- detect_many: detectors that batch get every text at once (LAB-1279) ---------------------


class NameFinder:
    """Finds the fictional names in any text; counts per-text and batch calls."""

    def __init__(self, name: str = "ner", *, batch: bool = True, fail: bool = False) -> None:
        self.name = name
        self.fail = fail
        self.detect_calls = 0
        self.batches: list[list[str]] = []
        if not batch:
            self.detect_batch = None  # type: ignore[assignment]

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        self.detect_calls += 1
        return self._find(text)

    def detect_batch(self, texts, language: str = "hu"):  # type: ignore[no-untyped-def]
        self.batches.append(list(texts))
        if self.fail:
            raise RuntimeError("Teszt Elek")  # a raw value: must not reach the message
        return [self._find(t) for t in texts]

    def _find(self, text: str) -> list[Span]:
        out = []
        for name in ("Teszt Elek", "Minta Mária"):
            start = text.find(name)
            if start >= 0:
                out.append(Span(start, start + len(name), E.PERSON, name, 0.9, self.name))
        return out


MANY_TEXTS = [
    "Teszt Elek e-mail címe teszt.elek@example.com.",
    "Nincs itt semmi.",
    "Minta\u200b Mária hívja Teszt Eleket: +36 30 123 4567",  # normalised: zero-width space
    "",
    "Teszt Elek",
]


def test_detect_many_equals_detect_per_text() -> None:
    ner = NameFinder()
    pipeline = DetectionPipeline(["rules", ner])
    many = pipeline.detect_many(MANY_TEXTS, "hu")
    assert len(ner.batches) == 1 and len(ner.batches[0]) == len(MANY_TEXTS)
    assert ner.detect_calls == 0
    assert many == [pipeline.detect(t, "hu") for t in MANY_TEXTS]
    assert ner.detect_calls == len(MANY_TEXTS)  # detect() itself does not batch
    # The zero-width space is inside the mapped-back name.
    assert next(s.text for s in many[2] if s.entity_type is E.PERSON) == "Minta\u200b Mária"
    assert pipeline.detect_many([], "hu") == []


def test_detect_many_loops_detectors_without_detect_batch() -> None:
    ner = NameFinder(batch=False)
    pipeline = DetectionPipeline(["rules", ner])
    assert pipeline.detect_many(MANY_TEXTS) == [pipeline.detect(t) for t in MANY_TEXTS]
    assert ner.batches == []


def test_detect_many_fails_closed() -> None:
    pipeline = DetectionPipeline(["rules", NameFinder(fail=True)])
    with pytest.raises(DetectionError, match="RuntimeError") as info:
        pipeline.detect_many(MANY_TEXTS)
    assert "Teszt" not in info.value.message


def test_detect_many_rejects_a_wrong_result_count() -> None:
    finder = NameFinder()
    finder.detect_batch = lambda texts, language="hu": [[]]  # type: ignore[method-assign]
    with pytest.raises(DetectionError, match="number of results"):
        DetectionPipeline([finder]).detect_many(["a", "b"])


def test_outside_drops_short_remainder_past_newline() -> None:
    """When wrapped-number folding joins a trailing line number (`\\n5`) onto a complete IBAN,
    subtracting the authoritative rule IBAN span must drop the short `< 4` char line remainder."""
    text = (
        "4\t3,Max Mustermann,max.mustermann@example.de,+49 30 12345678,"
        "DE89 3704 0044 0532 0130 00\n5\n"
    )
    iban_start = text.index("DE89")
    iban_end = text.index("\n5")
    rule_span = Span(iban_start, iban_end, E.BANK_ACCOUNT, text[iban_start:iban_end], 0.99, "rules")
    ner_span = Span(
        iban_start,
        iban_end + 2,
        E.BANK_ACCOUNT,
        text[iban_start : iban_end + 2],
        0.99,
        "ner",
    )
    resolved = resolve_spans(text, [rule_span, ner_span], detector_order=("rules", "ner"))
    assert [s.text for s in resolved] == ["DE89 3704 0044 0532 0130 00"]


@pytest.mark.parametrize(
    ("text", "ner_start", "value", "tail", "entity_type"),
    [
        # A newline before the value (the NER span starts on the label line) says nothing
        # about the same-line extension after it.
        ("Hívjon:\n+36 1 234 5678 / 12", 0, "+36 1 234 5678", "12", E.PHONE),
        # A CVV on the next line is still card data.
        (
            "Kártya: 4111 1111 1111 1111\n123 lejár",
            8,
            "4111 1111 1111 1111",
            "123",
            E.PAYMENT_CARD,
        ),
        # A wrapped phone tail is not dropped: phones are not a LAB-1604 number type.
        ("Tel. +49 30 1234567\n89", 5, "+49 30 1234567", "89", E.PHONE),
    ],
    ids=["hu-phone-extension", "hu-card-cvv", "de-phone-wrapped-tail"],
)
def test_outside_keeps_short_remainder_unless_number_type_past_newline(
    text: str, ner_start: int, value: str, tail: str, entity_type: E
) -> None:
    """LAB-1735: the short-remainder drop is scoped to the number types and to a newline after
    the covering rule span; every other short tail the NER span holds stays masked."""
    start = text.index(value)
    end = start + len(value)
    tail_end = text.index(tail, end) + len(tail)
    rule_span = Span(start, end, entity_type, value, 0.99, "rules")
    ner_span = Span(ner_start, tail_end, entity_type, text[ner_start:tail_end], 0.9, "ner")
    resolved = resolve_spans(text, [rule_span, ner_span], detector_order=("rules", "ner"))
    assert [s.text for s in resolved] == [value, tail]
