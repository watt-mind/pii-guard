"""Scorer math on tiny synthetic cases. All values are fictional."""

from __future__ import annotations

import pytest

from pii_guard.eval import (
    DEFAULT_POLICY,
    DetectorAnalyzer,
    GoldSpan,
    TypeCounts,
    consistency_report,
    from_markup,
    label,
    leak_report,
    match_counts,
    over_masked,
    prf,
    run_documents,
    summarize,
)
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


@pytest.mark.parametrize(
    ("gold", "pred"),
    [
        (EntityType.BANK_ACCOUNT, EntityType.PAYMENT_CARD),
        (EntityType.PAYMENT_CARD, EntityType.BANK_ACCOUNT),
    ],
)
def test_card_and_bank_account_score_alike(gold: EntityType, pred: EntityType) -> None:
    # LAB-1102: gold sets older than PAYMENT_CARD label cards BANK_ACCOUNT.
    counts = match_counts([g(0, 16, gold)], [s(0, 16, pred)], "exact")
    assert counts[gold].recall == 1.0
    assert counts[pred].precision == 1.0


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


@pytest.mark.parametrize(
    ("value", "masked", "partial"),
    [
        ("8461269321", "8461269", True),  # "[[X]]322": the edge cuts the digit run
        ("8461269321", "461269321", True),  # "8[[X]]"
        ("812.754.113.91", "812.754.113", True),  # "[[X]].91": joined by a dot
        ("812.754.113.91", "812.754.113.91", False),  # whole value
        ("06 30 123 4567", "06 30 123", False),  # a space is not a joiner, "4567" is a token
        ("Minta utca 12.", "Minta utca", False),  # house number after a space
    ],
)
def test_partial_counts_digits_left_at_the_placeholder_edge(
    value: str, masked: str, partial: bool
) -> None:
    """LAB-1367: a few digits of an identifier left next to its placeholder."""
    doc = _doc(f"Az azonosító: {label('ID_DOCUMENT', value)}.")
    (span,) = doc.spans
    start = span.start + value.index(masked)
    reps = [(start, start + len(masked), "[[ID_DOCUMENT_aaaa]]")]
    masked_text = doc.text[:start] + "[[ID_DOCUMENT_aaaa]]" + doc.text[start + len(masked) :]
    (report,) = leak_report(doc, masked_text, replacements=reps)
    assert not report.leaked
    expected = partial or value == "06 30 123 4567"  # the 4-digit token rule still applies
    assert report.partial is expected
    # Without the replacements only the token rule runs: short digit runs aren't seen.
    (old,) = leak_report(doc, masked_text)
    assert old.partial is (value == "06 30 123 4567")
    # Consistency reads the same gap as not covered.
    (entity,) = consistency_report(doc, reps)
    assert entity.consistent is (not expected)


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


def test_detector_analyzer_uses_the_pipeline_resolver() -> None:
    """Same resolver as the API and gateway: a PERSON inside an ORGANIZATION stays a PERSON."""
    from pii_guard.eval.scorer import DetectorAnalyzer

    class Org:
        name = "org"

        def detect(self, text: str, language: str = "hu") -> list[Span]:
            return [Span(0, len(text), EntityType.ORGANIZATION, text, 0.6, self.name)]

    class Person:
        name = "person"

        def detect(self, text: str, language: str = "hu") -> list[Span]:
            return [Span(0, 10, EntityType.PERSON, text[:10], 0.9, self.name)]

    analyzer = DetectorAnalyzer(["rules"])
    assert analyzer.pipeline is not None
    analyzer.pipeline.detectors = [Org(), Person()]
    spans = analyzer.analyze("Teszt Elek Bt", "hu")
    assert [s.entity_type for s in spans] == [EntityType.PERSON, EntityType.ORGANIZATION]
    assert DEFAULT_POLICY[EntityType.ORGANIZATION] == "keep"
    assert DEFAULT_POLICY[EntityType.PERSON] == "mask"


# --- placeholder consistency (LAB-1115) -----------------------------------------------------


def test_consistency_groups_surface_forms_and_needs_one_placeholder() -> None:
    doc = _doc(
        f"{label('PERSON', 'Minta Anna')} és {label('PERSON', 'Minta Annának')}, "
        f"{label('PERSON', 'Teszt Elek')} és {label('PERSON', 'TESZT ELEK')}, "
        f"{label('EMAIL', 'anna@example.com')}"
    )
    spans = sorted(doc.spans, key=lambda sp: sp.start)
    anna, anna_dat, elek, elek_caps, _email = spans
    replacements = [
        (anna.start, anna.end, "[[PERSON_aaaa]]"),
        (anna_dat.start, anna_dat.end - 3, "[[PERSON_aaaa]]"),  # suffix outside
        (elek.start, elek.end, "[[PERSON_bbbb]]"),
        (elek_caps.start, elek_caps.end, "[[PERSON_cccc]]"),  # a second placeholder
    ]
    report = consistency_report(doc, replacements)
    by_occurrences = sorted((r.entity_type.value, r.occurrences, r.consistent) for r in report)
    assert by_occurrences == [
        ("EMAIL", 1, False),  # not masked at all
        ("PERSON", 2, False),
        ("PERSON", 2, True),
    ]
    assert "Anna" not in repr(report)


def test_consistency_keeps_case_differing_secrets_apart() -> None:
    """LAB-1382: two SECRET tokens that differ only in case are two credentials (LAB-1350)."""
    doc = _doc(
        f"a={label('SECRET', 'FakeTok0000Abc')} b={label('SECRET', 'faketok0000abc')} "
        f"c={label('SECRET', 'FakeTok0000Abc')} {label('PERSON', 'Teszt Elek')} "
        f"{label('PERSON', 'TESZT ELEK')}"
    )
    upper, lower, again, elek, elek_caps = sorted(doc.spans, key=lambda sp: sp.start)
    replacements = [
        (upper.start, upper.end, "[[SECRET_aaaa]]"),
        (lower.start, lower.end, "[[SECRET_bbbb]]"),
        (again.start, again.end, "[[SECRET_aaaa]]"),
        (elek.start, elek.end, "[[PERSON_cccc]]"),
        (elek_caps.start, elek_caps.end, "[[PERSON_cccc]]"),
    ]
    report = consistency_report(doc, replacements)
    by_occurrences = sorted((r.entity_type.value, r.occurrences, r.consistent) for r in report)
    assert by_occurrences == [
        ("PERSON", 2, True),  # names stay case-insensitive
        ("SECRET", 1, True),
        ("SECRET", 2, True),  # the repeated token, one placeholder
    ]


def test_leak_counts_case_differing_secrets_as_two_values() -> None:
    """LAB-1382: dedup by exact value for SECRET, and only the exact casing is a leak."""
    doc = _doc(
        f"a={label('SECRET', 'FakeTok0000Abc')} b={label('SECRET', 'faketok0000abc')} "
        f"{label('PERSON', 'Teszt Elek')} {label('PERSON', 'TESZT ELEK')}"
    )
    masked = "a=[[SECRET_aaaa]] b=faketok0000abc [[PERSON_cccc]] [[PERSON_cccc]]"
    report = leak_report(doc, masked)
    secrets = sorted((r.value, r.leaked) for r in report if r.entity_type is EntityType.SECRET)
    assert secrets == [("FakeTok0000Abc", False), ("faketok0000abc", True)]
    assert [r.occurrences for r in report if r.entity_type is P] == [2]


def test_consistency_needs_each_occurrence_fully_covered() -> None:
    """LAB-1355: one masked character is not a masked occurrence."""
    doc = _doc(f"{label('PERSON', 'Teszt Elek')} írt, {label('PERSON', 'Teszt Elek')} válaszolt.")
    a, b = sorted(doc.spans, key=lambda sp: sp.start)

    def consistent(*reps: tuple[int, int, str]) -> bool:
        (entity,) = consistency_report(doc, reps)
        assert entity.occurrences == 2
        return entity.consistent

    p = "[[PERSON_aaaa]]"
    assert consistent((a.start, a.end, p), (b.start, b.end, p))
    assert not consistent((a.start, a.start + 1, p), (b.start, b.start + 1, p))  # first char
    assert not consistent((a.start + 1, a.end, p), (b.start + 1, b.end, p))  # leading gap
    assert not consistent((a.start, a.end - 1, p), (b.start, b.end - 1, p))  # not a suffix
    assert not consistent((a.start, a.start + 5, p), (b.start, b.end, p))  # surname only
    assert not consistent((a.start + 6, a.end, p), (b.start, b.end, p))  # given name only


@pytest.mark.parametrize(
    ("language", "value", "stem"),
    [
        ("hu", "Teszt Eleknek", "Teszt Elek"),
        ("hu", "Próba Zsuzsannának", "Próba Zsuzsanná"),
        ("en", "Smith's", "Smith"),
    ],
)
def test_consistency_accepts_a_suffix_outside_the_placeholder(
    language: str, value: str, stem: str
) -> None:
    doc = _doc(f"{label('PERSON', value)} és {label('PERSON', value)}.", language=language)
    reps = [(s.start, s.start + len(stem), "[[PERSON_aaaa]]") for s in doc.spans]
    assert [r.consistent for r in consistency_report(doc, reps)] == [True]
    # One character short of the stem is not a suffix.
    reps = [(s.start, s.start + len(stem) - 1, "[[PERSON_aaaa]]") for s in doc.spans]
    assert [r.consistent for r in consistency_report(doc, reps)] == [False]


@pytest.mark.parametrize(
    ("language", "entity_type", "value", "masked", "consistent"),
    [
        ("en", "PERSON", "Ms Testwood", "Testwood", True),  # a title identifies no one
        ("de", "PERSON", "Frau Beispiel", "Beispiel", True),
        ("en", "PERSON", "Dr. Jane Testwood, MD", "Jane Testwood", True),
        ("de", "PERSON", "Erika Beispiel", "Erika", False),  # the surname stays readable
        ("hu", "PERSON", "Próba Piroska", "Piroska", False),
        ("en", "ID_DOCUMENT", "AB1234010", "AB1234", False),  # digits left after it
        ("de", "ID_DOCUMENT", "812.754.113.91", "812.754.113", False),  # ".91" (LAB-1367)
        ("hu", "ADDRESS", "1051 Budapest, Minta utca 12.", "1051", False),
    ],
)
def test_consistency_words_left_outside_must_not_identify(
    language: str, entity_type: str, value: str, masked: str, consistent: bool
) -> None:
    doc = _doc(f"{label(entity_type, value)} és {label(entity_type, value)}.", language=language)
    offset = value.index(masked)
    reps = [(s.start + offset, s.start + offset + len(masked), "[[X_aaaa]]") for s in doc.spans]
    assert [r.consistent for r in consistency_report(doc, reps)] == [consistent]


def test_run_documents_reports_consistency() -> None:
    docs = [
        _doc(
            f"{label('PERSON', 'Próba Zsuzsanna')} és {label('PERSON', 'Próba Zsuzsannának')}, "
            f"{label('PERSON', 'Próba Zsuzsannát')}."
        )
    ]
    (result,) = run_documents(docs, FakeAnalyzer("Próba Zsuzsannának"))
    assert len({p for _, _, p in result.replacements}) == 1
    assert result.roundtrip
    block = summarize([result])
    assert block["consistency"]["entities"] == 1
    assert block["consistency"]["rate"] == 1.0
    assert block["consistency"]["multi_rate"] == 1.0
    assert block["consistency"]["per_type"]["PERSON"]["consistent"] == 1
    assert summarize([])["consistency"]["rate"] is None
