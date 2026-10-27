"""A kept type never hides a value another detector says to mask (LAB-1228, ADR 0006).

All text is fictional (ADR 0005).
"""

from __future__ import annotations

import pytest

from pii_guard.detect.pipeline import DetectionPipeline, resolve_spans
from pii_guard.detect.rules import RuleDetector
from pii_guard.policy import Policy, PolicySet
from pii_guard.types import EntityType, Span

E = EntityType
TAX = "12345676-2-41"  # adószám shape with a valid check digit: the rules say COMPANY_ID_HU


def span(text: str, value: str, entity_type: EntityType, detector: str, score: float = 0.8) -> Span:
    start = text.index(value)
    return Span(start, start + len(value), entity_type, value, score, detector)


class Fixed:
    def __init__(self, name: str, spans: list[Span]) -> None:
        self.name = name
        self.spans = spans

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        return list(self.spans)


def found(spans: list[Span]) -> list[tuple[EntityType, str, str, str | None]]:
    return [(s.entity_type, s.text, s.detector, s.forced_by) for s in spans]


def test_probe_keep_vs_tax_is_masked() -> None:
    # The reviewers' probe: rules COMPANY_ID_HU (kept) vs the LLM's personal tax ID.
    text = f"Adószám: {TAX}"
    spans = resolve_spans(
        text,
        [
            span(text, TAX, E.COMPANY_ID_HU, "rules", 0.95),
            span(text, TAX, E.NATIONAL_ID_HU_TAX, "llm", 0.85),
        ],
        detector_order=["rules", "llm"],
    )
    assert found(spans) == [(E.NATIONAL_ID_HU_TAX, TAX, "rules", "llm")]
    assert spans[0].score == 0.95
    assert PolicySet().apply(spans).kept == []


def test_sole_trader_tax_number_is_masked_end_to_end() -> None:
    text = f"Számla kiállítója: Horváth Emese e.v., adószám: {TAX}."
    llm = Fixed(
        "llm",
        [
            span(text, "Horváth Emese", E.PERSON, "llm"),
            span(text, TAX, E.NATIONAL_ID_HU_TAX, "llm"),
        ],
    )
    policies = PolicySet()
    spans = DetectionPipeline([RuleDetector(), llm], keep_types=policies.keep_types).detect(text)
    decision = policies.apply(spans)
    assert {(s.entity_type, s.text) for s in decision.masked} == {
        (E.PERSON, "Horváth Emese"),
        (E.NATIONAL_ID_HU_TAX, TAX),
    }
    assert decision.kept == []


def test_rule_keeps_its_boundaries_and_the_rest_stays_masked() -> None:
    # The other detector's span is longer and starts inside the label: the validated span keeps
    # its exact boundaries, the other span's own characters stay masked as before.
    text = f"Egyéni vállalkozó adószáma {TAX} (Teszt Elek)"
    spans = resolve_spans(
        text,
        [
            span(text, TAX, E.COMPANY_ID_HU, "rules", 0.95),
            span(text, f"adószáma {TAX}", E.NATIONAL_ID_HU_TAX, "llm", 0.85),
        ],
        detector_order=["rules", "llm"],
    )
    assert (E.NATIONAL_ID_HU_TAX, TAX, "rules", "llm") in found(spans)
    assert all(s.entity_type is not E.COMPANY_ID_HU for s in spans)


def test_shorter_mask_span_masks_the_whole_validated_value() -> None:
    text = f"Adószám: {TAX}"
    spans = resolve_spans(
        text,
        [
            span(text, TAX, E.COMPANY_ID_HU, "rules", 0.95),
            span(text, "12345676", E.ID_DOCUMENT, "ner", 0.6),
        ],
        detector_order=["rules", "ner"],
    )
    assert found(spans) == [(E.ID_DOCUMENT, TAX, "rules", "ner")]


@pytest.mark.parametrize("detector", ["ner", "llm", "custom"])
def test_any_detector_forces_the_mask(detector: str) -> None:
    text = f"Adószám: {TAX}"
    spans = resolve_spans(
        text,
        [
            span(text, TAX, E.COMPANY_ID_HU, "rules", 0.95),
            span(text, TAX, E.NATIONAL_ID_HU_TAX, detector),
        ],
        detector_order=["rules", detector],
    )
    assert found(spans) == [(E.NATIONAL_ID_HU_TAX, TAX, "rules", detector)]


def test_adjudicator_type_wins_when_detectors_disagree() -> None:
    text = f"Adószám: {TAX}"
    spans = resolve_spans(
        text,
        [
            span(text, TAX, E.COMPANY_ID_HU, "rules", 0.95),
            span(text, TAX, E.ID_DOCUMENT, "ner", 0.9),
            span(text, TAX, E.NATIONAL_ID_HU_TAX, "llm", 0.7),
        ],
        detector_order=["rules", "ner", "llm"],
    )
    assert found(spans) == [(E.NATIONAL_ID_HU_TAX, TAX, "rules", "llm")]


def test_company_tax_number_alone_stays_kept() -> None:
    text = f"Teszt Kft., adószám: {TAX}"
    spans = resolve_spans(
        text,
        [
            span(text, TAX, E.COMPANY_ID_HU, "rules", 0.95),
            span(text, "Teszt Kft.", E.ORGANIZATION, "llm"),
            span(text, TAX, E.COMPANY_ID_HU, "llm"),  # agreement on a kept type
        ],
        detector_order=["rules", "llm"],
    )
    assert (E.COMPANY_ID_HU, TAX, "rules", None) in found(spans)
    assert PolicySet().apply(spans).masked == []


def test_a_policy_override_to_keep_is_respected() -> None:
    # The operator keeps NATIONAL_ID_HU_TAX too: no detector asks for a mask, nothing changes.
    policies = PolicySet({E.NATIONAL_ID_HU_TAX: Policy.KEEP})
    text = f"Adószám: {TAX}"
    spans = resolve_spans(
        text,
        [
            span(text, TAX, E.COMPANY_ID_HU, "rules", 0.95),
            span(text, TAX, E.NATIONAL_ID_HU_TAX, "llm"),
        ],
        detector_order=["rules", "llm"],
        keep_types=policies.keep_types,
    )
    assert found(spans) == [(E.COMPANY_ID_HU, TAX, "rules", None)]


def test_known_value_still_wins_over_the_forced_span() -> None:
    text = f"Adószám: {TAX}"
    spans = resolve_spans(
        text,
        [
            span(text, TAX, E.COMPANY_ID_HU, "rules", 0.95),
            span(text, TAX, E.NATIONAL_ID_HU_TAX, "llm"),
            span(text, TAX, E.NATIONAL_ID_HU_TAX, "known", 1.0),
        ],
        detector_order=["known", "rules", "llm"],
    )
    assert found(spans) == [(E.NATIONAL_ID_HU_TAX, TAX, "known", None)]


def test_person_in_sole_trader_name_is_unchanged() -> None:
    # A non-authoritative kept span already lost to a masked type; it is not retyped.
    text = "Próba Zsuzsanna e.v. számlája"
    spans = resolve_spans(
        text,
        [
            span(text, "Próba Zsuzsanna e.v.", E.ORGANIZATION, "llm"),
            span(text, "Próba Zsuzsanna", E.PERSON, "llm"),
        ],
        detector_order=["rules", "llm"],
    )
    assert found(spans) == [
        (E.PERSON, "Próba Zsuzsanna", "llm", None),
        (E.ORGANIZATION, "e.v", "llm", None),
    ]


def test_forced_by_is_debug_metadata_only() -> None:
    a = Span(0, 3, E.NATIONAL_ID_HU_TAX, "123", 0.9, "rules", forced_by="llm")
    b = Span(0, 3, E.NATIONAL_ID_HU_TAX, "123", 0.9, "rules")
    assert a == b and hash(a) == hash(b)
    assert "forced_by" not in a.to_public_dict()
    assert "123" not in repr(a) and "forced_by='llm'" in repr(a)
