"""Escalate mode's detector (LAB-1766): selector, windows, masked view, add-only merge,
verbatim alignment, fail closed, cache, local-only refusal. All values are fictional (ADR 0005).
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Sequence

import httpx
import pytest

from pii_guard.config import Settings
from pii_guard.detect.escalate import (
    Candidate,
    EscalatingDetector,
    RawRecorder,
    build_windows,
    escalation_request,
    masked_view,
    select_candidates,
)
from pii_guard.detect.llm import LlmDetector
from pii_guard.detect.pipeline import DetectionPipeline
from pii_guard.detect.rules import RuleDetector
from pii_guard.detection_profile import DetectionProfileError
from pii_guard.types import DetectionError, EntityType, Span

EMAIL = "jane.placeholder@example.net"


class FixedDetector:
    """A detector that reports fixed values with a type and score (stands in for NER)."""

    def __init__(self, name: str, found: Sequence[tuple[str, EntityType, float]]) -> None:
        self.name = name
        self.found = list(found)

    def detect(self, text: str, language: str = "en") -> list[Span]:
        out = []
        for value, entity_type, score in self.found:
            for m in re.finditer(re.escape(value), text):
                out.append(Span(m.start(), m.end(), entity_type, value, score, self.name))
        return out


class FakeLlm:
    """Answers with fixed ``(type, value)`` pairs found in what it is sent; records it."""

    name = "llm"
    model = "fake-llm"

    def __init__(
        self,
        answer: Sequence[tuple[EntityType, str]] = (),
        *,
        fail: bool = False,
        delay: float = 0.0,
    ) -> None:
        self.answer = list(answer)
        self.fail = fail
        self.delay = delay
        self.sent: list[str] = []
        self._lock = threading.Lock()

    def detect(self, text: str, language: str = "en") -> list[Span]:
        with self._lock:
            self.sent.append(text)
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise DetectionError("fake llm failed")
        out = []
        for entity_type, value in self.answer:
            start = text.find(value)
            if start != -1:
                out.append(Span(start, start + len(value), entity_type, value, 0.9, self.name))
        return out


def pipeline(*extra: object) -> DetectionPipeline:
    return DetectionPipeline([RawRecorder(d) for d in (RuleDetector(), *extra)])  # type: ignore[arg-type]


def escalating(llm: object, *extra: object, **kwargs: object) -> EscalatingDetector:
    return EscalatingDetector(pipeline(*extra), llm, **kwargs)  # type: ignore[arg-type]


def kinds(cands: Sequence[Candidate], text: str) -> list[tuple[str, str]]:
    return [(c.kind, text[c.start : c.end]) for c in cands]


# --- selector ---


def test_nothing_uncertain_means_no_call_and_the_fast_result_unchanged() -> None:
    llm = FakeLlm()
    text = f"Please send the report to {EMAIL} by Friday."
    fast = pipeline().detect(text, "en")
    assert escalating(llm).detect(text, "en") == fast
    assert llm.sent == []


def test_selects_a_name_after_a_form_of_address() -> None:
    text = "Dear Ms. Quillfeather, thanks for the call."
    assert kinds(select_candidates(text, []), text) == [("name", "Quillfeather")]


def test_selects_a_capitalised_word_next_to_a_person_span() -> None:
    text = "Ask Jane Brightwater about it."
    person = Span(4, 8, EntityType.PERSON, "Jane", 0.9, "ner")
    assert kinds(select_candidates(text, [person]), text) == [("name", "Brightwater")]


def test_selects_a_name_before_a_hungarian_postposed_address() -> None:
    text = "Holnap Ropogós úr is jön."
    assert ("name", "Ropogós") in kinds(select_candidates(text, []), text)


def test_a_sentence_opening_word_before_a_name_is_not_selected() -> None:
    text = "Ask Jane about it. Yesterday Jane called."
    persons = [
        Span(m.start(), m.end(), EntityType.PERSON, "Jane", 0.9, "ner")
        for m in re.finditer("Jane", text)
    ]
    assert select_candidates(text, persons) == []


def test_does_not_select_ordinary_capitalised_words() -> None:
    text = "The Board met on Monday in Building C. Revenue grew."
    assert select_candidates(text, []) == []


def test_selects_uncovered_long_numbers_but_not_dates_or_amounts() -> None:
    text = "Ref 4471 2289 33 on 2026-10-01, total 1 200 000 Ft, also € 3 500 000, room 12."
    assert kinds(select_candidates(text, []), text) == [("number", "4471 2289 33")]


def test_does_not_select_inside_an_earlier_turns_placeholder() -> None:
    text = "Mr. [[PERSON_123456]] wrote [[ID_DOCUMENT_998877]]."
    assert select_candidates(text, []) == []


def test_selects_low_confidence_ner_spans_only() -> None:
    text = "Jane met Kim."
    spans = [
        Span(0, 4, EntityType.PERSON, "Jane", 0.6, "ner"),
        Span(9, 12, EntityType.PERSON, "Kim", 0.95, "ner"),
    ]
    assert kinds(select_candidates(text, spans, low_score=0.75), text) == [("low_score", "Jane")]


def test_selects_rules_vs_ner_type_conflicts() -> None:
    text = "Born 1990-01-02 here."
    raw = [
        Span(5, 15, EntityType.DATE_OF_BIRTH, "1990-01-02", 0.9, "rules"),
        Span(5, 15, EntityType.ID_DOCUMENT, "1990-01-02", 0.9, "ner"),
    ]
    resolved = [raw[0]]
    assert kinds(select_candidates(text, resolved, raw), text) == [("conflict", "1990-01-02")]


def test_a_validated_rules_span_is_not_a_conflict() -> None:
    text = "Code 12345678 here."
    raw = [
        Span(5, 13, EntityType.PHONE, "12345678", 1.0, "rules"),
        Span(5, 13, EntityType.ID_DOCUMENT, "12345678", 0.9, "ner"),
    ]
    assert select_candidates(text, [raw[0]], raw) == []


# --- windows and the masked view ---


def test_windows_stay_near_the_candidate_and_never_cut_a_found_span() -> None:
    text = ("x " * 300) + f"Mr. Quill {EMAIL} " + ("y " * 300)
    spans = RuleDetector().detect(text, "en")
    cands = select_candidates(text, spans)
    windows, covered = build_windows(text, cands, spans, radius=20)
    assert covered == cands
    [(start, end)] = windows
    assert end - start < 80
    assert all(not (s.start < start < s.end or s.start < end < s.end) for s in spans)


def test_windows_are_capped_per_text() -> None:
    text = " filler ".join(f"Mr. Name{c}" for c in "ABCDEFGH") + " " + "z " * 400
    cands = select_candidates(text, [])
    windows, covered = build_windows(text, cands, [], radius=2, max_windows=3)
    assert len(windows) <= 3
    assert len(covered) < len(cands)


def test_no_found_span_leaves_in_the_masked_view() -> None:
    text = f"Mr. Quill (mail {EMAIL}, IBAN HU42 1177 3016 1111 1018 0000 0000) asked Ms. Brook."
    spans = RuleDetector().detect(text, "en")
    assert spans
    cands = select_candidates(text, spans)
    windows, _ = build_windows(text, cands, spans, radius=200)
    view = masked_view(text, windows, spans)
    for s in spans:
        assert s.text not in view.text
    assert "[[EMAIL_1]]" in view.text and "Quill" in view.text


def test_view_offsets_map_back_and_refuse_separators_and_half_placeholders() -> None:
    text = "AAA Mr. Quill BBB " + "z " * 200 + "CCC Mr. Brook DDD " + f"{EMAIL} end"
    spans = RuleDetector().detect(text, "en")
    cands = select_candidates(text, spans)
    windows, _ = build_windows(text, cands, spans, radius=60)
    assert len(windows) == 2
    view = masked_view(text, windows, spans)
    q = view.text.index("Quill")
    assert view.to_original(q, q + 5) == (text.index("Quill"), text.index("Quill") + 5)
    sep = view.text.index("…")
    assert view.to_original(sep - 2, sep + 3) is None
    ph = view.text.index("[[EMAIL_1]]")
    assert view.to_original(ph + 2, ph + 7) is None
    full = view.to_original(ph, ph + len("[[EMAIL_1]]"))
    assert full is not None and text[full[0] : full[1]] == EMAIL


def test_conflicting_spans_get_a_neutral_placeholder() -> None:
    text = "Code 12345678 for Mr. Quill."
    spans = [Span(5, 13, EntityType.PHONE, "12345678", 1.0, "rules")]
    neutral = [Candidate(5, 13, "conflict")]
    view = masked_view(text, [(0, len(text))], spans, neutral)
    assert "[[ENTITY_1]]" in view.text and "PHONE" not in view.text


# --- merge ---


def test_the_llm_can_add_a_span() -> None:
    llm = FakeLlm([(EntityType.PERSON, "Quill")])
    text = f"Please write to Mr. Quill at {EMAIL} today."
    out = escalating(llm).detect(text, "en")
    assert [(s.entity_type, s.text, s.detector) for s in out] == [
        (EntityType.PERSON, "Quill", "llm"),
        (EntityType.EMAIL, EMAIL, "rules"),
    ]
    assert EMAIL not in llm.sent[0]


def test_the_llm_can_widen_a_span_through_its_placeholder() -> None:
    ner = FixedDetector("ner", [("Brightwater", EntityType.PERSON, 0.9)])
    llm = FakeLlm([(EntityType.PERSON, "Jane [[PERSON_1]]")])
    text = "Ask Jane Brightwater about it."
    out = escalating(llm, ner).detect(text, "en")
    assert [(s.text, s.entity_type) for s in out] == [("Jane Brightwater", EntityType.PERSON)]
    assert "Brightwater" not in llm.sent[0]


def test_the_llm_settles_a_type_but_never_unmasks() -> None:
    ner = FixedDetector("ner", [("Brightwater", EntityType.ORGANIZATION, 0.6)])
    llm = FakeLlm([(EntityType.PERSON, "[[ORGANIZATION_1]]")])
    text = "Ask Brightwater about it."
    out = escalating(llm, ner).detect(text, "en")
    assert [(s.text, s.entity_type) for s in out] == [("Brightwater", EntityType.PERSON)]


def test_fast_spans_survive_whatever_the_llm_says() -> None:
    llm = FakeLlm([(EntityType.ORGANIZATION, "[[EMAIL_1]]"), (EntityType.PERSON, "Quill")])
    text = f"Mr. Quill: {EMAIL}"
    out = escalating(llm).detect(text, "en")
    email = text.index(EMAIL)
    assert any(s.start <= email and email + len(EMAIL) <= s.end for s in out)
    assert {s.entity_type for s in out} >= {EntityType.EMAIL, EntityType.PERSON}


def test_only_verbatim_values_are_kept() -> None:
    from pii_guard.detect.escalate import align

    text = "Mr. Quill wrote."
    view = masked_view(text, [(0, len(text))], [])
    assert align(text, view, [(EntityType.PERSON, "quill")], "en") == []
    assert align(text, view, [(EntityType.PERSON, "Quilt")], "en") == []
    [span] = align(text, view, [(EntityType.PERSON, "Quill")], "en")
    assert span.text == "Quill"


# --- fail closed ---


def test_a_failed_call_masks_the_uncertain_candidates() -> None:
    llm = FakeLlm(fail=True)
    text = f"Mr. Quill, ref 4471 2289 33, {EMAIL}."
    with escalation_request("s1") as request:
        out = escalating(llm).detect(text, "en")
    assert {(s.text, s.entity_type) for s in out} == {
        ("Quill", EntityType.PERSON),
        ("4471 2289 33", EntityType.ID_DOCUMENT),
        (EMAIL, EntityType.EMAIL),
    }
    assert request.failures == 1


def test_a_failed_call_keeps_rules_and_ner_when_configured() -> None:
    llm = FakeLlm(fail=True)
    text = f"Mr. Quill, {EMAIL}."
    out = escalating(llm, on_failure="keep").detect(text, "en")
    assert out == pipeline().detect(text, "en")


def test_a_slow_call_times_out_and_fails_closed() -> None:
    llm = FakeLlm([(EntityType.PERSON, "Quill")], delay=2.0)
    text = "Mr. Quill wrote."
    started = time.perf_counter()
    out = escalating(llm, timeout=0.2).detect(text, "en")
    assert time.perf_counter() - started < 1.5
    assert [(s.text, s.detector) for s in out] == [("Quill", "escalate")]


# --- cache and per-request cap ---


def test_decisions_are_cached_per_session_scope() -> None:
    llm = FakeLlm([(EntityType.PERSON, "Quill")])
    detector = escalating(llm)
    text = "Mr. Quill wrote."
    with escalation_request("session-a") as first:
        a = detector.detect(text, "en")
    with escalation_request("session-a") as second:
        b = detector.detect(text, "en")
    with escalation_request("session-b"):
        detector.detect(text, "en")
    assert a == b
    assert len(llm.sent) == 2
    assert (first.escalations, second.escalations, second.cache_hits) == (1, 0, 1)


def test_escalations_per_request_are_capped() -> None:
    llm = FakeLlm([(EntityType.PERSON, "Quill")])
    texts = ["Mr. Quill wrote.", "Ms. Brook replied."]
    with escalation_request("s", max_texts=1) as request:
        out = escalating(llm).detect_many(texts, "en")
    assert len(llm.sent) == 1 and request.capped == 1
    assert out[1] == []


# --- the real LLM detector, on a mock transport ---


def test_the_llm_detector_gets_only_the_masked_windows() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        content = json.dumps({"entities": [{"type": "PERSON", "text": "Quill"}]})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 5},
            },
        )

    llm = LlmDetector(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
        challenge_empty=False,
        settings=Settings(_env_file=None),
    )
    filler = "Lorem ipsum dolor sit amet. " * 40
    text = f"{filler}Please ask Mr. Quill at {EMAIL}. {filler}"
    out = EscalatingDetector(pipeline(), llm, radius=60).detect(text, "en")
    assert [(s.text, s.entity_type) for s in out] == [
        ("Quill", EntityType.PERSON),
        (EMAIL, EntityType.EMAIL),
    ]
    [body] = bodies
    sent = json.dumps(body, ensure_ascii=False)
    assert EMAIL not in sent and "[[EMAIL_1]]" in sent
    assert sent.count("Lorem ipsum") < 10
    assert llm.usage["requests"] == 1


def test_a_keyless_llm_makes_escalate_unavailable() -> None:
    llm = LlmDetector(api_key="", settings=Settings(_env_file=None))
    detector = EscalatingDetector(pipeline(), llm)
    assert detector.unavailable_reason is not None
    assert detector.unavailable_reason.startswith("escalate mode needs")


def test_local_only_refuses_escalation() -> None:
    settings = Settings(_env_file=None, detection_profile="local-only")
    with pytest.raises(DetectionProfileError):
        EscalatingDetector(pipeline(), FakeLlm(), settings=settings)  # type: ignore[arg-type]
