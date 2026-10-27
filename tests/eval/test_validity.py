"""LAB-1201: number-validity breakdown (valid vs invalid identifiers) on public sets.

- every validated type is classified with the language packs' own validators;
- the breakdown adds up to the headline counts and leaves them unchanged;
- it is an optional, backward-compatible field of the run record, validated for consistency;
- a re-run attaches it to an existing record without touching the headline;
- the report renders a table and a chart for it. Fictional values only.
"""

from __future__ import annotations

import copy
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from pii_guard.detect.checksums import hu_tax_id_check_digit, iban_check_digits, taj_check_digit
from pii_guard.detect.rules.common import luhn_check_digit
from pii_guard.eval import report_charts as charts
from pii_guard.eval import validity as v
from pii_guard.eval.fixtures import Document, GoldSpan
from pii_guard.eval.record import SCHEMA_PATH, load_schema, text_metrics, validate
from pii_guard.eval.report_cli import render_page, validity_sets
from pii_guard.eval.report_index import build_index, compact_validity, pool_validity
from pii_guard.eval.scorer import DocumentResult, leak_report, run_documents, summarize
from pii_guard.languages.de.checksums import steuer_id_check_digit
from pii_guard.types import EntityType, Span

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "eval" / "results" / "runs"
SCHEMA = load_schema(ROOT / SCHEMA_PATH)
E = EntityType


def _bump(value: str) -> str:
    """The same value with its last digit changed: the check digit no longer matches."""
    return value[:-1] + str((int(value[-1]) + 1) % 10)


def _card() -> str:
    payload = "400000000000000"  # Visa prefix, fictional
    return payload + str(luhn_check_digit(payload))


def _iban() -> str:
    bban = "117730161111101800000000"
    return "HU" + iban_check_digits("HU", bban) + bban


def _taj() -> str:
    return "12345678" + str(taj_check_digit("12345678"))


def _tax() -> str:
    check = hu_tax_id_check_digit("812345678")
    assert check is not None
    return "812345678" + str(check)


def _steuer_id() -> str:
    return "1234567891" + str(steuer_id_check_digit("1234567891"))


# --- Classification, one test per validated type ----------------------------------------


@pytest.mark.parametrize(
    ("valid", "invalid", "entity_type", "language"),
    [
        pytest.param(_card(), _bump(_card()), E.BANK_ACCOUNT, "en", id="card-luhn"),
        pytest.param(_iban(), "HU00" + _iban()[4:], E.BANK_ACCOUNT, "hu", id="iban"),
        pytest.param(_taj(), _bump(_taj()), E.NATIONAL_ID_HU_TAJ, "hu", id="hu-taj"),
        pytest.param(_tax(), _bump(_tax()), E.NATIONAL_ID_HU_TAX, "hu", id="hu-tax-id"),
        pytest.param(_steuer_id(), _bump(_steuer_id()), E.ID_DOCUMENT, "de", id="de-steuer-id"),
        pytest.param("+36 30 123 4567", "+36 99 123 4567", E.PHONE, "hu", id="phone-plan"),
    ],
)
def test_classify_valid_and_invalid(
    valid: str, invalid: str, entity_type: EntityType, language: str
) -> None:
    assert v.classify(valid, entity_type, language) == "valid"
    assert v.classify(invalid, entity_type, language) == "invalid"


def test_classify_ignores_grouping_and_needs_the_right_type() -> None:
    taj = _taj()
    assert v.classify(f"{taj[:3]} {taj[3:6]} {taj[6:]}", E.NATIONAL_ID_HU_TAJ, "hu") == "valid"
    # A valid TAJ labelled as a tax ID is not a valid tax ID.
    assert v.classify(taj, E.NATIONAL_ID_HU_TAX, "hu") == "invalid"
    assert v.classify("", E.PHONE, "hu") == "invalid"


def test_cued_numbers_do_not_make_a_value_valid() -> None:
    # "TAJ 123456789" is masked by a cue even though the check digit fails: still invalid.
    assert v.classify("TAJ " + _bump(_taj()), E.NATIONAL_ID_HU_TAJ, "hu") == "invalid"


@pytest.mark.parametrize("entity_type", [E.PERSON, E.ADDRESS, E.EMAIL, E.DATE_OF_BIRTH])
def test_non_number_types_are_not_classified(entity_type: EntityType) -> None:
    assert entity_type not in v.NUMBER_TYPES
    assert v.classify("Minta Anna", entity_type, "hu") is None


# --- The breakdown in a scorecard --------------------------------------------------------


def _doc(doc_id: str, parts: list[tuple[str, EntityType | None]], kind: str) -> Document:
    text, spans = "", []
    for chunk, entity_type in parts:
        if entity_type is not None:
            spans.append(GoldSpan(len(text), len(text) + len(chunk), entity_type, chunk))
        text += chunk
    return Document(doc_id, "hu", text, tuple(spans), {"kind": kind})


def _docs(kind: str = "public-ai4privacy") -> list[Document]:
    return [
        _doc(
            "a",
            [
                ("Teszt Elek TAJ-száma ", None),
                (_taj(), E.NATIONAL_ID_HU_TAJ),
                (", adóazonosítója ", None),
                (_bump(_tax()), E.NATIONAL_ID_HU_TAX),
                (", neve ", None),
                ("Teszt Elek", E.PERSON),
                (".", None),
            ],
            kind,
        ),
        _doc(
            "b",
            [
                ("Kártya: ", None),
                (_bump(_card()), E.BANK_ACCOUNT),
                (", e-mail: ", None),
                ("teszt.elek@example.com", E.EMAIL),
                (".", None),
            ],
            kind,
        ),
    ]


class _Fixed:
    """Analyzer returning a fixed set of spans per document text."""

    def __init__(self, spans: dict[str, list[Span]]) -> None:
        self.spans = spans

    def analyze(self, text: str, language: str) -> list[Span]:
        return self.spans.get(text, [])


def _results(kind: str = "public-ai4privacy") -> list[DocumentResult]:
    docs = _docs(kind)
    a, b = docs
    taj, person = a.spans[0], a.spans[2]
    found = {
        a.text: [
            Span(taj.start, taj.end, E.NATIONAL_ID_HU_TAJ, taj.text, 0.9, "t"),
            Span(person.start, person.end, E.PERSON, person.text, 0.9, "t"),
        ],
        b.text: [],
    }
    return run_documents(docs, _Fixed(found))


def test_breakdown_splits_the_headline_and_adds_up() -> None:
    block = summarize(_results())
    val = block["validity"]
    # valid TAJ found and masked; invalid tax ID and card missed and leaked; person masked,
    # e-mail leaked.
    assert val["valid"] == {"gold": 1, "found": 1, "values": 1, "leaked": 0}
    assert val["invalid"] == {"gold": 2, "found": 0, "values": 2, "leaked": 2}
    assert val["excluding_number_types"] == {"gold": 2, "found": 1, "values": 2, "leaked": 1}
    assert val["per_type"]["NATIONAL_ID_HU_TAJ"]["valid"]["gold"] == 1
    assert val["per_type"]["BANK_ACCOUNT"]["invalid"]["leaked"] == 1
    assert val["source"] is None
    leak, micro = block["leak"], block["detection"]["overlap"]["micro"]
    total = v._sums(val)
    assert total == {
        "gold": micro["gold"],
        "found": micro["tp_gold"],
        "values": leak["values"],
        "leaked": leak["leaked"],
    }


def test_headline_is_the_same_with_or_without_the_breakdown() -> None:
    public, private = summarize(_results()), summarize(_results("synthetic"))
    assert "validity" in public and "validity" not in private
    public.pop("validity")
    for block in (public, private):
        block.pop("latency_ms")  # wall-clock timing
    assert public == private


def test_breakdown_never_contains_a_value() -> None:
    dumped = json.dumps(summarize(_results())["validity"])
    for doc in _docs():
        for span in doc.spans:
            assert span.text not in dumped
    leak = leak_report(_docs()[0], _docs()[0].text)[0]
    assert leak.value and leak.value not in repr(leak) and "value" not in leak.to_dict()


# --- Run records -------------------------------------------------------------------------


def _record(block: dict[str, Any]) -> dict[str, Any]:
    rec = json.loads((RUNS / "2026-10-27-comparison-hu-ai4privacy.json").read_text("utf-8"))
    metrics = text_metrics(block)
    rec["metrics"] = {"overall": metrics, "languages": {"hu": copy.deepcopy(metrics)}}
    rec["rescored"] = None
    return rec


def test_record_keeps_the_breakdown_and_validates() -> None:
    rec = _record(summarize(_results()))
    assert rec["metrics"]["overall"]["validity"]["valid"]["found"] == 1
    assert validate(rec, SCHEMA) == []


def test_records_without_a_breakdown_still_validate() -> None:
    rec = _record(summarize(_results("synthetic")))
    assert "validity" not in rec["metrics"]["overall"]
    assert validate(rec, SCHEMA) == []


def test_validate_rejects_a_breakdown_that_does_not_add_up() -> None:
    rec = _record(summarize(_results()))
    rec["metrics"]["overall"]["validity"]["invalid"]["leaked"] = 1
    errors = validate(rec, SCHEMA)
    assert any("add up to" in e for e in errors)
    assert any("per_type" in e for e in errors)


def test_attach_validity_leaves_the_headline_and_flags_a_mismatch() -> None:
    rec = _record(summarize(_results("synthetic")))
    before = copy.deepcopy(rec)
    card = {"overall": summarize(_results()), "languages": {"hu": summarize(_results())}}
    v.attach_validity(rec, card, by="LAB-1201", commit="abc1234", date="2026-10-27", note="n")
    source = rec["metrics"]["overall"]["validity"]["source"]
    assert source["matches_headline"] is True and source["rerun_headline"] is None
    for block, old in ((rec["metrics"]["overall"], before["metrics"]["overall"]),):
        assert {k: x for k, x in block.items() if k != "validity"} == old
    assert validate(rec, SCHEMA) == []

    # A re-run that missed one more value than the record: kept, flagged, still consistent.
    other = copy.deepcopy(card)
    for block in (other["overall"], other["languages"]["hu"]):
        block["leak"]["leaked"] += 1
        block["validity"]["valid"]["leaked"] += 1
        block["validity"]["per_type"]["NATIONAL_ID_HU_TAJ"]["valid"]["leaked"] += 1
    rec2 = _record(summarize(_results("synthetic")))
    v.attach_validity(rec2, other, by="LAB-1201", commit="abc1234", date="2026-10-27", note="n")
    source = rec2["metrics"]["overall"]["validity"]["source"]
    assert source["matches_headline"] is False
    assert source["rerun_headline"]["leaked"] == rec2["metrics"]["overall"]["leak"]["leaked"] + 1
    assert validate(rec2, SCHEMA) == []


def test_attach_validity_needs_a_breakdown_in_the_scorecard() -> None:
    rec = _record(summarize(_results("synthetic")))
    card = {"overall": summarize(_results("synthetic")), "languages": {"hu": {}}}
    with pytest.raises(KeyError):
        v.attach_validity(rec, card, by="LAB-1201", commit="abc1234", date="2026-10-27", note="n")


# --- Report ------------------------------------------------------------------------------


def test_pool_and_compact() -> None:
    block = text_metrics(summarize(_results()))
    pooled = pool_validity([block, block])
    assert pooled is not None
    assert pooled["invalid"] == {"gold": 4, "found": 0, "values": 4, "leaked": 4}
    assert pool_validity([block, text_metrics(summarize(_results("synthetic")))]) is None
    compact = compact_validity(pooled)
    assert compact is not None
    assert compact["valid"]["recall"] == 1.0 and compact["invalid"]["leak"] == 1.0
    assert compact["matches_headline"] is True and compact["rerun"] is False


def test_committed_ai4privacy_records_carry_the_breakdown() -> None:
    """Acceptance: every system shown on ai4privacy (hu/en/de) has a breakdown."""
    from pii_guard.eval.record import load_records

    index = build_index(load_records(RUNS), featured=[])
    snaps = [s for s in index["snapshots"] if s["fixture_set"] == "ai4privacy"]
    assert snaps
    for s in snaps:
        for lang in ("hu", "en", "de"):
            assert s["languages"][lang].get("validity"), (s["system"], lang)
    # Every public set gets the breakdown (LAB-1226 added gretel-finance, nemotron-pii, ...).
    assert "ai4privacy" in validity_sets(index)
    page = render_page(index, headline_set="smoke", featured=index["featured"])
    assert "Number validity" in page and "validity-ai4privacy.svg" in page
    svg = charts.number_validity(index, fixture_set="ai4privacy")
    ET.fromstring(svg)  # noqa: S314 - our own generated SVG
    assert "Leak rate by number validity" in svg
