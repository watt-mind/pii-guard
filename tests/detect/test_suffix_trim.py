"""Detector name spans end at their stem before the vault stores them (LAB-1174).

All names are fictional (ADR 0005).
"""

from __future__ import annotations

import json

import httpx
import pytest

from pii_guard.config import Settings
from pii_guard.detect.llm import LlmDetector
from pii_guard.detect.pipeline import DetectionPipeline
from pii_guard.detect.rules import RuleDetector
from pii_guard.detect.suffix_trim import trim_name_suffixes
from pii_guard.types import EntityType, Span
from pii_guard.vault import PLACEHOLDER_RE, Vault

E = EntityType
KEY = b"k" * 32


def span(text: str, value: str, entity_type: EntityType = E.PERSON, detector: str = "ner") -> Span:
    start = text.index(value)
    return Span(start, start + len(value), entity_type, value, 0.9, detector)


class Fixed:
    """A detector that returns preset spans (stands in for NER)."""

    name = "ner"

    def __init__(self, *values: str) -> None:
        self.values = values

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        return [span(text, v) for v in self.values]


def masked(text: str, spans: list[Span]) -> tuple[str, list[str]]:
    """The masked text and what each placeholder restores to on its own (bare)."""
    session = Vault(KEY).session()
    out = session.mask(text, spans, language="hu")
    return out, [session.unmask(m.group(0)) for m in PLACEHOLDER_RE.finditer(out)]


@pytest.mark.parametrize(
    ("text", "value", "lemma", "suffix"),
    [
        ("Beutaló. Háziorvos: Kerekes Ottótól kaptuk a beutalót.", "Kerekes Ottótól",
         "Kerekes Ottó", "tól"),
        ("A választ Gyakorló Tihamérnak küldtük.", "Gyakorló Tihamérnak", "Gyakorló Tihamér",
         "nak"),
        ("Minta Hajnának írtunk, holnap jön.", "Minta Hajnának", "Minta Hajna", "nak"),
        ("A számlát Teszt Eleknek adtuk át.", "Teszt Eleknek", "Teszt Elek", "nek"),
        ("Próba Szabolccsal egyeztettünk.", "Próba Szabolccsal", "Próba Szabolcs", "al"),
        ("Holnap Minta Bélát hívjuk.", "Minta Bélát", "Minta Béla", "t"),
    ],
)  # fmt: skip
def test_pipeline_keeps_the_suffix_outside_the_placeholder(
    text: str, value: str, lemma: str, suffix: str
) -> None:
    spans = DetectionPipeline([Fixed(value)]).detect(text, "hu")
    out, bare = masked(text, spans)
    assert bare == [lemma]  # an English answer drops the case ending: the lemma comes back
    placeholder = PLACEHOLDER_RE.search(out)
    assert placeholder is not None
    assert out[placeholder.end() : placeholder.end() + len(suffix)] == suffix
    session = Vault(KEY).session()
    assert session.unmask(session.mask(text, spans, language="hu")) == text  # round trip


@pytest.mark.parametrize(
    "value", ["Próba Márton", "Próba Kornél", "Teszt Simon", "Minta Kelemen", "Teszt Zoltán"]
)
def test_names_that_look_inflected_are_not_trimmed(value: str) -> None:
    text = f"A levelet {value} írta alá."
    spans = DetectionPipeline([Fixed(value)]).detect(text, "hu")
    assert [s.text for s in spans] == [value]
    assert masked(text, spans)[1] == [value]


def test_llm_span_with_the_ablative_is_trimmed() -> None:
    """The demo sample's case (LAB-1174): the LLM returns the inflected name whole."""
    text = "Beutaló. Beutaló orvos: Kerekes Ottótól. Tünet: fejfájás."
    content = json.dumps({"entities": [{"type": "PERSON", "text": "Kerekes Ottótól"}]})
    body = {"choices": [{"index": 0, "message": {"role": "assistant", "content": content}}]}
    llm = LlmDetector(
        base_url="https://llm.test/v1",
        api_key="test-key",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
        settings=Settings(),
    )
    spans = DetectionPipeline([RuleDetector(), llm]).detect(text, "hu")
    people = [s for s in spans if s.entity_type is E.PERSON]
    assert [s.text for s in people] == ["Kerekes Ottó"]
    out, bare = masked(text, spans)
    assert "tól." in out and bare == ["Kerekes Ottó"]


def test_only_whole_word_person_spans_are_trimmed() -> None:
    text = "Kerekes Ottótól jött, a kerekes.ottotol@example.com címről. Tihamér|nak"
    spans = [
        span(text, "Kerekes Ottó"),  # already ends inside a word: the detector chose the stem
        span(text, "kerekes.ottotol@example.com", E.EMAIL, "rules"),
    ]
    assert trim_name_suffixes(text, spans, "hu") == spans


def test_languages_without_a_confident_split_are_unchanged() -> None:
    text = "We wrote to Jane Placeholdernak today."
    spans = [span(text, "Jane Placeholdernak")]
    assert trim_name_suffixes(text, spans, "en") == spans


def test_a_trimmed_span_keeps_its_detector_and_score() -> None:
    text = "Kerekes Ottótól kaptuk."
    original = span(text, "Kerekes Ottótól")
    (trimmed,) = trim_name_suffixes(text, [original], "hu")
    assert (trimmed.start, trimmed.end, trimmed.text) == (0, 12, "Kerekes Ottó")
    assert (trimmed.detector, trimmed.score, trimmed.entity_type) == ("ner", 0.9, E.PERSON)
