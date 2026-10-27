"""The pipeline normalises obfuscated text once, for every detector (LAB-1146).

All values are fictional (ADR 0005).
"""

from __future__ import annotations

import pytest

from pii_guard.detect.pipeline import DetectionPipeline
from pii_guard.types import DetectionError, EntityType, Span
from pii_guard.vault import Vault

E = EntityType
ZWSP, ZWJ, RLO = "\u200b", "\u200d", "\u202e"
KEY = bytes.fromhex("0f" * 32)


class Recording:
    """A detector that records the text it was given and finds preset values in it."""

    def __init__(self, name: str, values: dict[str, EntityType] | None = None) -> None:
        self.name = name
        self.values = values or {}
        self.seen: list[str] = []

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        self.seen.append(text)
        spans = []
        for value, entity_type in self.values.items():
            start = text.find(value)
            if start >= 0:
                spans.append(Span(start, start + len(value), entity_type, value, 0.9, self.name))
        return spans


class Misfit:
    """A detector whose span does not fit the text it was given."""

    name = "misfit"

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        return [Span(0, 3, E.PERSON, "xyz", 0.9, self.name)]


def triples(spans: list[Span]) -> list[tuple[int, int, EntityType]]:
    return [(s.start, s.end, s.entity_type) for s in spans]


def assert_fits(text: str, spans: list[Span]) -> None:
    for s in spans:
        assert s.text == text[s.start : s.end]


def test_zero_width_phone_is_one_span_over_the_original() -> None:
    text = f"+36{ZWSP}30 555{ZWSP}0168"
    spans = DetectionPipeline(["rules"]).detect(text, "hu")
    assert triples(spans) == [(0, len(text), E.PHONE)]
    assert_fits(text, spans)


def test_zero_width_email_is_one_whole_span() -> None:
    text = f"agatha.sam{ZWJ}plewood@example.com"
    spans = DetectionPipeline(["rules"]).detect(text, "en")
    assert triples(spans) == [(0, len(text), E.EMAIL)]
    assert_fits(text, spans)


def test_zero_width_email_in_a_sentence() -> None:
    value = f"agatha.sam{ZWJ}plewood@example.com"
    text = f"Please write to {value} today."
    spans = DetectionPipeline(["rules"]).detect(text, "en")
    start = text.index(value)
    assert triples(spans) == [(start, start + len(value), E.EMAIL)]
    assert_fits(text, spans)


def test_rule_and_llm_spans_agree_on_the_whole_address() -> None:
    # Before LAB-1146 the rule span started after the joiner and, being authoritative, kept its
    # boundaries over the LLM's whole-address span: the local part leaked.
    value = f"agatha.sam{ZWJ}plewood@example.com"
    text = f"Contact: {value}"
    llm = Recording("llm", {"agatha.samplewood@example.com": E.EMAIL})
    spans = DetectionPipeline(["rules", llm]).detect(text, "en")
    start = text.index(value)
    assert triples(spans) == [(start, len(text), E.EMAIL)]
    assert_fits(text, spans)


def test_cyrillic_lookalike_in_an_email_is_one_full_span() -> None:
    text = "Írj a t\u0435szt.elek@example.com címre."
    spans = DetectionPipeline(["rules"]).detect(text, "hu")
    value = "t\u0435szt.elek@example.com"
    start = text.index(value)
    assert triples(spans) == [(start, start + len(value), E.EMAIL)]
    assert_fits(text, spans)


def test_bidi_override_before_a_value_does_not_shift_or_split_it() -> None:
    value = "teszt.elek@example.com"
    text = f"E-mail: {RLO}{value}, telefon: {RLO}+36 30 555 0168"
    spans = DetectionPipeline(["rules"]).detect(text, "hu")
    email = text.index(value)
    phone = text.index("+36")
    assert triples(spans) == [
        (email, email + len(value), E.EMAIL),
        (phone, len(text), E.PHONE),
    ]
    assert_fits(text, spans)


def test_detectors_see_normalised_text_and_spans_map_back() -> None:
    text = f"Kedves Te{ZWSP}szt Elek!"
    stub = Recording("stub", {"Teszt Elek": E.PERSON})
    spans = DetectionPipeline([stub]).detect(text, "hu")
    assert stub.seen == ["Kedves Teszt Elek!"]
    start = text.index("Te")
    assert triples(spans) == [(start, start + len(f"Te{ZWSP}szt Elek"), E.PERSON)]
    assert spans[0].text == f"Te{ZWSP}szt Elek"
    assert spans[0].detector == "stub"


def test_clean_text_is_passed_through_identically() -> None:
    text = "Kedves Teszt Elek!"
    stub = Recording("stub", {"Teszt Elek": E.PERSON})
    spans = DetectionPipeline([stub]).detect(text, "hu")
    assert len(stub.seen) == 1
    assert stub.seen[0] is text
    assert triples(spans) == [(7, 17, E.PERSON)]


def test_every_detector_gets_the_same_normalised_text() -> None:
    text = f"Te{ZWSP}szt Elek, +36 30 555{ZWSP}0168"
    first, second = Recording("first"), Recording("second")
    DetectionPipeline([first, second]).detect(text, "hu")
    assert first.seen == second.seen == ["Teszt Elek, +36 30 5550168"]


def test_a_span_that_does_not_fit_the_normalised_text_fails_closed() -> None:
    with pytest.raises(DetectionError, match="misfit"):
        DetectionPipeline([Misfit()]).detect(f"ab{ZWSP}c", "hu")


def test_vault_round_trip_keeps_the_invisible_characters() -> None:
    text = f"Hívj: +36{ZWSP}30 555{ZWSP}0168, írj: agatha.sam{ZWJ}plewood@example.com"
    spans = DetectionPipeline(["rules"]).detect(text, "hu")
    assert {s.entity_type for s in spans} == {E.PHONE, E.EMAIL}
    session = Vault(KEY).session()
    masked = session.mask(text, spans, language="hu")
    assert ZWSP not in masked
    assert ZWJ not in masked
    assert "plewood" not in masked
    assert session.unmask(masked) == text
