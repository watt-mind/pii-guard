"""Span overlap handling is a sorted sweep, not a scan per span (LAB-1206).

Each sweep is checked against the quadratic scan it replaced on random span sets, and the
pipeline is timed on 100 kB adversarial inputs that took seconds to minutes before. All text
is fictional (ADR 0005).
"""

from __future__ import annotations

import random
import time

import pytest

from pii_guard.detect import pipeline, rules
from pii_guard.detect.pipeline import DetectionPipeline, resolve_spans
from pii_guard.detect.rules import RuleDetector
from pii_guard.types import EntityType, Span

E = EntityType
TYPES = (E.PERSON, E.EMAIL, E.PHONE, E.ORGANIZATION, E.BANK_ACCOUNT, E.ADDRESS)
DETECTORS = ("rules", "ner", "llm", "known", "other")
ALPHABET = "ab1 2-.,@(xé"


def _rng(seed: object) -> random.Random:
    """A seeded generator for reproducible span sets (not for anything secret)."""
    return random.Random(str(seed))  # noqa: S311


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


# The scans the sweeps replaced, kept verbatim as the reference.


def _drop_contained_scan(hits: list[rules._Hit]) -> list[rules._Hit]:
    ordered = sorted(dict.fromkeys(hits), key=lambda h: (h.start, -(h.end - h.start), -h.score))
    kept: list[rules._Hit] = []
    for hit in ordered:
        if any(k.start <= hit.start and hit.end <= k.end for k in kept):
            continue
        kept.append(hit)
    return kept


class _ScanIntervals:
    def __init__(self, cands: list[pipeline._Cand]) -> None:
        self.cands = list(cands)

    def any_overlap(self, start: int, end: int) -> bool:
        return any(_overlaps(c.start, c.end, start, end) for c in self.cands)

    def overlapping(self, start: int, end: int) -> list[pipeline._Cand]:
        return [c for c in self.cands if _overlaps(c.start, c.end, start, end)]


class _ScanTaken:
    def __init__(self) -> None:
        self.taken: list[tuple[int, int]] = []

    def add(self, start: int, end: int) -> None:
        self.taken.append((start, end))

    def subtract(self, start: int, end: int) -> list[tuple[int, int]]:
        return pipeline._subtract(start, end, self.taken)


def _random_hits(rng: random.Random, length: int, count: int) -> list[rules._Hit]:
    hits = []
    for _ in range(count):
        start = rng.randrange(length)
        end = rng.randint(start + 1, min(length, start + rng.randint(1, 25)))
        hits.append(rules._Hit(start, end, rng.choice(TYPES), rng.choice((0.5, 0.8, 0.99))))
    return hits


def _random_case(rng: random.Random) -> tuple[str, list[Span]]:
    text = "".join(rng.choice(ALPHABET) for _ in range(rng.randint(1, 60)))
    spans = [
        Span(h.start, h.end, h.entity_type, text[h.start : h.end], h.score, rng.choice(DETECTORS))
        for h in _random_hits(rng, len(text), rng.randint(0, 14))
    ]
    return text, spans


def test_drop_contained_matches_the_scan() -> None:
    rng = _rng(1206)
    for _ in range(3000):
        hits = _random_hits(rng, rng.randint(1, 60), rng.randint(0, 20))
        assert rules._drop_contained(hits) == _drop_contained_scan(hits)


def test_cued_values_outside_hits_matches_the_scan() -> None:
    rng = _rng(1207)
    for _ in range(3000):
        length = rng.randint(1, 60)
        hits = _random_hits(rng, length, rng.randint(0, 12))
        others = _random_hits(rng, length, rng.randint(0, 12))
        expected = [
            o for o in others if not any(_overlaps(h.start, h.end, o.start, o.end) for h in hits)
        ]
        assert rules._outside_hits(hits, others) == expected


def test_interval_index_matches_the_scan() -> None:
    rng = _rng(1208)
    for _ in range(2000):
        length = rng.randint(1, 60)
        cands = [
            pipeline._Cand(h.start, h.end, h.entity_type, h.score, "rules", True, 0)
            for h in _random_hits(rng, length, rng.randint(0, 15))
        ]
        index, scan = pipeline._Intervals(cands), _ScanIntervals(cands)
        for _ in range(10):
            start = rng.randrange(length)
            end = rng.randint(start + 1, length)
            assert index.any_overlap(start, end) == scan.any_overlap(start, end)
            # Same candidates (by identity), in input order.
            assert [id(c) for c in index.overlapping(start, end)] == [
                id(c) for c in scan.overlapping(start, end)
            ]


def test_taken_subtract_matches_the_scan() -> None:
    rng = _rng(1209)
    for _ in range(2000):
        length = rng.randint(2, 80)
        taken, scan = pipeline._Taken(), _ScanTaken()
        for _ in range(rng.randint(0, 20)):
            start = rng.randrange(length)
            end = rng.randint(start + 1, length)
            expected = scan.subtract(start, end)
            assert taken.subtract(start, end) == expected
            # Accept a random part of what is free, as the resolver does (disjoint ranges).
            for ps, pe in expected:
                if rng.random() < 0.7:
                    ps2 = rng.randint(ps, pe - 1)
                    pe2 = rng.randint(ps2 + 1, pe)
                    taken.add(ps2, pe2)
                    scan.add(ps2, pe2)


@pytest.mark.parametrize("adjudicator", ["llm", "ner", None])
def test_resolve_spans_matches_the_scans(
    monkeypatch: pytest.MonkeyPatch, adjudicator: str | None
) -> None:
    rng = _rng(f"1210-{adjudicator}")
    cases = []
    for _ in range(1500):
        text, spans = _random_case(rng)
        order = rng.sample(DETECTORS, rng.randint(0, len(DETECTORS)))
        cases.append((text, spans, order, resolve_spans(
            text, spans, detector_order=order, adjudicator=adjudicator
        )))  # fmt: skip
    monkeypatch.setattr(pipeline, "_Intervals", _ScanIntervals)
    monkeypatch.setattr(pipeline, "_Taken", _ScanTaken)
    for text, spans, order, swept in cases:
        assert resolve_spans(text, spans, detector_order=order, adjudicator=adjudicator) == swept


class _EveryWord:
    """A stand-in model detector that tags every word (and its neighbours) as one type."""

    def __init__(self, name: str, entity_type: EntityType, reach: int) -> None:
        self.name, self.entity_type, self.reach = name, entity_type, reach

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        spans, start = [], 0
        for word in text.split(" "):
            end = start + len(word)
            if word:
                s, e = max(0, start - self.reach), min(len(text), end + self.reach)
                spans.append(Span(s, e, self.entity_type, text[s:e], 0.7, self.name))
            start = end + 1
        return spans


# (language, repeated unit, prefix, repeats for about 100 kB)
ADVERSARIAL = {
    "emails": ("en", "", "a@b.co ", 14_000),
    "parcel list": ("hu", "hrsz.: 1", ", 1", 33_000),
    "phones": ("hu", "", "+36 1 234 5678, ", 6_000),
}


def _adversarial(name: str, fraction: float = 1.0) -> tuple[str, str]:
    language, prefix, unit, repeats = ADVERSARIAL[name]
    return language, prefix + unit * int(repeats * fraction)


def _scaling(run: object, name: str) -> tuple[float, float]:
    """Best-of-2 time on the full input and on a quarter of it.

    A runner's speed cancels out of the ratio: linear work grows about 4x from the quarter
    to the full input, the quadratic scans this guards against about 16x. Absolute budgets
    flaked on loaded CI runners (LAB-1748).
    """
    times = []
    for fraction in (0.25, 1.0):
        language, text = _adversarial(name, fraction)
        best = float("inf")
        for _ in range(2):
            t0 = time.perf_counter()
            run(text, language)  # type: ignore[operator]
            best = min(best, time.perf_counter() - t0)
        times.append(best)
    return times[1], times[1] / max(times[0], 1e-3)


def _resolve(text: str, language: str) -> None:
    rule_spans = RuleDetector().detect(text, language)
    model_spans = _EveryWord("ner", E.EMAIL, 1).detect(text) + _EveryWord(
        "llm", E.PERSON, 0
    ).detect(text)
    resolve_spans(text, rule_spans + model_spans, detector_order=("rules", "ner", "llm"))


@pytest.mark.parametrize("name", ADVERSARIAL)
@pytest.mark.slow
def test_adversarial_100kb_resolves_in_linear_time(name: str) -> None:
    language, text = _adversarial(name)
    assert len(text) >= 95_000
    assert len(RuleDetector().detect(text, language)) > 5_000
    # About 100k candidate spans: the scans took minutes here, the sweeps about a second.
    elapsed, ratio = _scaling(_resolve, name)
    assert ratio < 8.0, f"{name}: resolver grew {ratio:.1f}x for 4x input ({elapsed:.2f}s)"
    assert elapsed < 60.0, f"{name}: resolver took {elapsed:.2f}s"


@pytest.mark.parametrize("name", ADVERSARIAL)
@pytest.mark.slow
def test_adversarial_100kb_rules_pipeline_is_fast(name: str) -> None:
    detector = DetectionPipeline([RuleDetector()])
    language, text = _adversarial(name)
    assert detector.detect(text, language)
    # The scans took 8-60 s per input here.
    elapsed, ratio = _scaling(detector.detect, name)
    assert ratio < 8.0, f"{name}: pipeline grew {ratio:.1f}x for 4x input ({elapsed:.2f}s)"
    assert elapsed < 60.0, f"{name}: pipeline took {elapsed:.2f}s"
