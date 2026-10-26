"""Scorer math on tiny synthetic cases. All values are fictional."""

from __future__ import annotations

import pytest

from pii_guard.eval import (
    DEFAULT_POLICY,
    DetectorAnalyzer,
    GoldSpan,
    TypeCounts,
    from_markup,
    label,
    leak_report,
    match_counts,
    over_masked,
    prf,
    run_documents,
    summarize,
)
from pii_guard.eval.scorer import _percentile
from pii_guard.types import DetectionError, EntityType, Span

P, E, A = EntityType.PERSON, EntityType.EMAIL, EntityType.ADDRESS


def g(start: int, end: int, t: EntityType = P) -> GoldSpan:
    return GoldSpan(start, end, t, "x" * (end - start))


def s(start: int, end: int, t: EntityType = P, score: float = 0.9) -> Span:
    return Span(start, end, t, "x" * (end - start), score, "fake")


# --- match_counts / prf -------------------------------------------------------------------


def test_exact_match_counts() -> None:
    counts = match_counts([g(0, 5), g(10, 15)], [s(0, 5), s(10, 14), s(20, 25)], "exact")
    c = counts[P]
    assert (c.gold, c.pred, c.tp_gold, c.tp_pred) == (2, 3, 1, 1)
    assert c.precision == pytest.approx(1 / 3)
    assert c.recall == pytest.approx(1 / 2)
    assert c.f1 == pytest.approx(2 * (1 / 3) * (1 / 2) / (1 / 3 + 1 / 2))


def test_overlap_match_is_not_one_to_one() -> None:
    # One long prediction covering two gold spans: both gold spans recalled, 1 TP prediction.
    counts = match_counts([g(0, 5), g(6, 10)], [s(0, 10)], "overlap")
    c = counts[P]
    assert (c.tp_gold, c.tp_pred) == (2, 1)
    assert c.recall == 1.0
    assert c.precision == 1.0


def test_type_must_agree() -> None:
    counts = match_counts([g(0, 5, P)], [s(0, 5, E)], "overlap")
    assert counts[P].recall == 0.0
    assert counts[E].precision == 0.0
    assert counts[P].precision is None
    assert counts[E].recall is None
    assert counts[P].f1 == 0.0
    assert counts[E].f1 == 0.0


def test_empty_counts_are_undefined() -> None:
    assert TypeCounts().f1 is None
    assert prf({})["macro"] == {"precision": None, "recall": None, "f1": None}


def test_micro_and_macro() -> None:
    counts = {
        P: TypeCounts(gold=4, pred=2, tp_pred=2, tp_gold=2),  # P 1.0, R 0.5
        E: TypeCounts(gold=1, pred=0),  # P undefined -> 0 in macro, R 0
    }
    out = prf(counts)
    assert out["micro"]["precision"] == 1.0
    assert out["micro"]["recall"] == pytest.approx(2 / 5)
    assert out["macro"]["precision"] == pytest.approx(0.5)
    assert out["macro"]["recall"] == pytest.approx(0.25)
    assert out["macro"]["f1"] == pytest.approx((2 / 3 + 0) / 2)
    assert list(out["per_type"]) == ["PERSON", "EMAIL"]
    assert out["per_type"]["EMAIL"]["precision"] is None


# --- leak_report ----------------------------------------------------------------------------


def _doc(marked: str, language: str = "hu"):
    return from_markup("d", marked, language=language)


def test_leak_full_partial_and_masked() -> None:
    doc = _doc(
        f"{label('PERSON', 'Teszt Elek')} ír {label('ADDRESS', '1051 Budapest, Minta utca 12.')} "
        f"{label('EMAIL', 'kapcsolat@example.com')}"
    )
    masked = "Teszt Elek ír [[ADDRESS_aaaa]] Budapest, Minta utca 12. [[EMAIL_bbbb]]"
    report = {r.entity_type: r for r in leak_report(doc, masked)}
    assert report[P].leaked and not report[P].partial
    assert not report[A].leaked and report[A].partial  # "Minta", "Budapest" survive
    assert not report[E].leaked and not report[E].partial


def test_leak_finds_inflected_and_reformatted_forms() -> None:
    doc = _doc(
        f"{label('PERSON', 'Minta Anna')} és {label('PHONE', '+36 30 123 4567')}. "
        "Később Minta Annának írtam, a 06-30-123-4567 számra."
    )
    masked = (
        "[[PERSON_aaaa]] és [[PHONE_bbbb]]. Később Minta Annának írtam, a 06-30-123-4567 számra."
    )
    assert all(r.leaked for r in leak_report(doc, masked))


def test_leak_ignores_placeholder_ids_and_keep_policy() -> None:
    taj, org = label("NATIONAL_ID_HU_TAJ", "123456788"), label("ORGANIZATION", "Minta Kft.")
    doc = _doc(f"{taj} a {org}")
    masked = "[[NATIONAL_ID_HU_TAJ_123456788]] a Minta Kft."
    report = leak_report(doc, masked)
    assert [r.entity_type for r in report] == [EntityType.NATIONAL_ID_HU_TAJ]
    assert not report[0].leaked
    # With a mask policy for organisations, the surviving name is a leak.
    policy = {**DEFAULT_POLICY, EntityType.ORGANIZATION: "mask"}
    assert any(r.leaked for r in leak_report(doc, masked, policy=policy))


def test_repeated_values_count_once_per_document() -> None:
    doc = _doc(f"{label('PERSON', 'Teszt Elek')} és {label('PERSON', 'teszt elek')}")
    (report,) = leak_report(doc, "[[PERSON_aaaa]] és [[PERSON_aaaa]]")
    assert report.occurrences == 2
    assert not report.leaked


def test_partial_ignores_tokens_found_outside_gold_spans() -> None:
    doc = _doc(f"Budapest, 2026. {label('ADDRESS', '1051 Budapest, Teszt utca 1.')}")
    (report,) = leak_report(doc, "Budapest, 2026. [[ADDRESS_aaaa]] Budapest, [[X_bbbb]] utca 1.")
    assert not report.leaked
    assert not report.partial  # "Budapest" also occurs outside the label; "utca" is generic


def test_leak_report_repr_has_no_value() -> None:
    doc = _doc(f"{label('PERSON', 'Teszt Elek')}")
    assert "Teszt" not in repr(leak_report(doc, doc.text))


# --- over_masked / run_documents / summarize ----------------------------------------------


def test_over_masked_counts_spans_off_any_gold_span() -> None:
    doc = _doc(f"{label('PERSON', 'Teszt Elek')} 12345")
    masked = [s(0, 10, E), s(11, 16, EntityType.PHONE)]
    assert over_masked(doc, masked) == [masked[1]]  # wrong type still covers personal data


class FakeAnalyzer:
    """Finds a fixed value as PERSON, plus an extra ORGANIZATION hit (keep policy)."""

    def __init__(self, value: str) -> None:
        self.value = value

    def analyze(self, text: str, language: str) -> list[Span]:
        spans = []
        start = text.find(self.value)
        if start >= 0:
            spans.append(Span(start, start + len(self.value), P, self.value, 0.9, "fake"))
        org = text.find("Minta Kft.")
        if org >= 0:
            spans.append(Span(org, org + 10, EntityType.ORGANIZATION, "Minta Kft.", 0.9, "fake"))
        return spans


def test_run_documents_masks_and_summarizes() -> None:
    docs = [
        _doc(f"{label('PERSON', 'Teszt Elek')} írt a Minta Kft.-nek, Teszt Eleknek is."),
        _doc(f"Hi {label('PERSON', 'Jane Example')}!", language="en"),
    ]
    results = run_documents(docs, FakeAnalyzer("Teszt Elek"))
    first, second = results
    assert "Teszt Elek" not in first.masked_text  # the second occurrence masked by the vault
    assert "Minta Kft." in first.masked_text  # keep policy: not masked
    assert [sp.entity_type for sp in first.masked_spans] == [P]
    assert first.roundtrip and second.roundtrip
    assert "Teszt" not in repr(first)

    block = summarize(results)
    assert block["documents"] == 2
    assert block["gold_spans"] == 2
    assert block["predicted_spans"] == 2
    exact = block["detection"]["exact"]
    assert exact["per_type"]["PERSON"]["recall"] == 0.5
    assert exact["per_type"]["ORGANIZATION"]["precision"] == 0.0
    assert block["leak"]["values"] == 2
    assert block["leak"]["leaked"] == 1
    assert block["leak"]["rate"] == 0.5
    assert block["leak"]["per_type"]["PERSON"]["rate"] == 0.5
    assert block["over_masking"] == {
        "masked": 1,
        "over_masked": 0,
        "rate": 0.0,
        "per_type": {"PERSON": {"masked": 1, "over_masked": 0, "rate": 0.0}},
    }
    assert block["roundtrip"]["rate"] == 1.0
    assert block["latency_ms"]["detect"]["p50"] is not None


def test_summarize_empty() -> None:
    block = summarize([])
    assert block["leak"]["rate"] is None
    assert block["latency_ms"]["mask"]["p95"] is None


def test_percentile_nearest_rank() -> None:
    assert _percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.0
    assert _percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0
    assert _percentile([], 0.5) is None


def test_detector_analyzer_skips_unknown_and_merges_overlaps() -> None:
    analyzer = DetectorAnalyzer(["rules", "definitely_not_a_detector"])
    assert analyzer.loaded == ["rules"]
    assert [name for name, _ in analyzer.skipped] == ["definitely_not_a_detector"]
    spans = analyzer.analyze("írj: teszt@example.com", "hu")
    assert [sp.entity_type for sp in spans] == [E]


def test_detector_analyzer_skips_detectors_that_cannot_be_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(name: str) -> object:
        raise RuntimeError("needs a model")

    monkeypatch.setattr("pii_guard.eval.scorer.create_detector", boom)
    analyzer = DetectorAnalyzer(["llm"])
    assert analyzer.detectors == []
    assert analyzer.skipped == [("llm", "could not be created (RuntimeError)")]


def test_run_fails_closed_on_detector_error() -> None:
    class Failing:
        def analyze(self, text: str, language: str) -> list[Span]:
            raise DetectionError("detector 'x' failed")

    with pytest.raises(DetectionError):
        run_documents([_doc("szöveg")], Failing())
