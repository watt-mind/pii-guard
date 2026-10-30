"""LAB-1213: the benchmark report compares like with like and says how it scores.

- snapshots are keyed by fixture file version; runs on an earlier file or on fewer languages
  are flagged and kept out of the pooled charts;
- ignore regions (and the legacy per-type rule) keep policy-excluded labels out of precision
  and over-masking; stored records are re-scored from their own counts;
- comparison tools have no placeholder consistency (null, not 0.0);
- a record's rates must be its counts' ratios;
- ``ai4privacy fetch --check`` compares everything and writes nothing;
- the page and captions say what they pool and how.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, ClassVar

import pytest

from pii_guard.eval import report_charts as charts
from pii_guard.eval import rescore
from pii_guard.eval.baselines.base import BaselineOutput, baseline_section, run_baseline
from pii_guard.eval.fixtures import FixtureError, parse_document
from pii_guard.eval.public import ai4privacy as a4p
from pii_guard.eval.record import (
    SCHEMA_PATH,
    load_schema,
    rate_errors,
    text_metrics,
    validate,
)
from pii_guard.eval.report_cli import render_page
from pii_guard.eval.report_index import build_index
from pii_guard.eval.scorer import DocumentResult, summarize, unscored
from pii_guard.types import EntityType, Span

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "eval" / "results" / "runs"
SVG = "{http://www.w3.org/2000/svg}"
OLD, NEW = "a" * 64, "b" * 64
SCHEMA = load_schema(ROOT / SCHEMA_PATH)


def _load(run_id: str) -> dict[str, Any]:
    return json.loads((RUNS / f"{run_id}.json").read_text(encoding="utf-8"))


def _variant(
    base: dict[str, Any], run_id: str, system: str, *, sha: str, recorded_at: str
) -> dict[str, Any]:
    rec = copy.deepcopy(base)
    rec["run_id"] = run_id
    rec["recorded_at"] = recorded_at
    rec["system"]["key"] = system
    rec["system"]["label"] = f"pii-guard {system}"
    for f in rec["fixtures"]:
        f["sha256"] = sha
    rec["code"]["commit"] = "1111111" if sha == OLD else "2222222"
    return rec


@pytest.fixture(scope="module")
def mixed() -> list[dict[str, Any]]:
    """`smoke` in en + hu: `a` and `b` ran both on the new hu file, `c` hu only on the old one,
    `d` only hu (new), so `d` is incomplete; `a` also ran earlier on the old hu file."""
    hu = _load("2026-10-27-comparison-hu-smoke")
    en = _load("2026-10-27-comparison-en-smoke")
    out = [
        _variant(hu, "2026-10-27-a-hu-old", "a", sha=OLD, recorded_at="2026-10-27T01:00:00+00:00"),
        _variant(hu, "2026-10-27-c-hu-old", "c", sha=OLD, recorded_at="2026-10-27T02:00:00+00:00"),
        _variant(en, "2026-10-27-c-en", "c", sha="e" * 64, recorded_at="2026-10-27T02:30:00+00:00"),
    ]
    for system in ("a", "b"):
        out.append(
            _variant(
                hu,
                f"2026-10-27-{system}-hu",
                system,
                sha=NEW,
                recorded_at="2026-10-27T03:00:00+00:00",
            )
        )
        out.append(
            _variant(
                en,
                f"2026-10-27-{system}-en",
                system,
                sha="e" * 64,
                recorded_at="2026-10-27T03:00:00+00:00",
            )
        )
    out.append(
        _variant(hu, "2026-10-27-d-hu", "d", sha=NEW, recorded_at="2026-10-27T04:00:00+00:00")
    )
    for rec in out:
        rec["fixture_set"] = "mixed"
        for f in rec["fixtures"]:
            f["set"] = "mixed"
    return out


# --- 1. Snapshots by fixture version --------------------------------------------------------


def test_snapshots_use_only_the_current_fixture_file(mixed: list[dict[str, Any]]) -> None:
    index = build_index(mixed)
    assert index["fixture_sets"]["mixed"]["fixtures"] == {"en": "e" * 12, "hu": "b" * 12}
    snaps = {s["system"]: s for s in index["snapshots"] if s["fixture_set"] == "mixed"}
    assert snaps["a"]["run_ids"] == ["2026-10-27-a-en", "2026-10-27-a-hu"]  # not the old hu run
    assert snaps["a"]["fixtures"] == {"en": "e" * 12, "hu": "b" * 12}
    assert snaps["a"]["complete"] and not snaps["a"]["missing_languages"]
    # c ran hu only on the old file: its snapshot is en only, flagged, and hu goes to stale.
    assert set(snaps["c"]["languages"]) == {"en"}
    assert snaps["c"]["missing_languages"] == ["hu"] and not snaps["c"]["complete"]
    assert snaps["d"]["missing_languages"] == ["en"]
    stale = {s["system"]: s for s in index["stale_snapshots"]}
    assert set(stale) == {"c"}  # a has a current hu run, so its old one isn't listed
    assert stale["c"]["superseded"] == {"hu": "a" * 12}
    # Document counts of the set come from the current files only.
    docs = index["fixture_sets"]["mixed"]["documents"]
    assert docs == {"en": snaps["a"]["languages"]["en"]["documents"], "hu": 31}


def test_history_marks_points_on_other_documents(mixed: list[dict[str, Any]]) -> None:
    history = build_index(mixed)["history"]
    by_runs = {tuple(h["run_ids"]): h for h in history}
    assert by_runs[("2026-10-27-a-en", "2026-10-27-a-hu")]["comparable"] is True
    assert by_runs[("2026-10-27-d-hu",)]["comparable"] is False  # fewer languages
    old = by_runs[("2026-10-27-c-hu-old",)]
    assert old["comparable"] is False and old["fixtures"]["hu"] == "a" * 12


def test_page_flags_partial_rows_and_lists_earlier_files(mixed: list[dict[str, Any]]) -> None:
    index = build_index(mixed, featured=["a", "b", "c", "d"])
    page = render_page(index, headline_set="mixed", featured=index["featured"])
    table = page.split("### `mixed`")[1]
    assert "pii-guard c †" in table and "pii-guard d †" in table
    assert "pii-guard a |" in table  # complete rows carry no mark
    assert "† Not run on every language of the current fixture files (en + hu)" in table
    assert "On an earlier version of a fixture file" in table
    assert "`aaaaaaaaaaaa`" in table
    assert "| Commit |" in table


def test_pooled_charts_leave_out_partial_systems_and_say_so(mixed: list[dict[str, Any]]) -> None:
    index = build_index(mixed, featured=["a", "b", "c", "d"])
    for render in (charts.leak_vs_latency, charts.type_recall_heatmap):
        svg = render(index, fixture_set="mixed", systems=index["featured"])
        text = " ".join("".join(t.itertext()) for t in ET.fromstring(svg).iter(f"{SVG}text"))  # noqa: S314
        assert "en + hu pooled (micro-averaged)" in text
        assert "Not shown, not run on every current fixture file (en + hu): c, d." in text
        assert "hu + en pooled" not in text


def test_committed_headline_set_compares_one_version(
    committed_records: list[dict[str, Any]],
) -> None:
    index = build_index(committed_records)
    current = index["fixture_sets"]["smoke"]["fixtures"]
    for snap in index["snapshots"]:
        if snap["fixture_set"] == "smoke":
            assert all(current[lang] == sha for lang, sha in snap["fixtures"].items())
    for svg in (ROOT / "docs" / "benchmarks").glob("*.svg"):
        assert "hu + en pooled" not in svg.read_text(encoding="utf-8"), svg.name


# --- 2. Ignore regions and re-scoring ----------------------------------------------------


def _doc(text: str, spans: list[tuple[int, int, EntityType]], meta: dict[str, Any]) -> Any:
    record = {
        "id": "d1",
        "language": "en",
        "text": text,
        "spans": [{"start": s, "end": e, "entity_type": t.value} for s, e, t in spans],
        "meta": meta,
    }
    return parse_document(record)


def _span(start: int, end: int, t: EntityType) -> Span:
    return Span(start, end, t, "x" * (end - start), 0.9, "fake")


def _result(doc: Any, predicted: list[Span]) -> DocumentResult:
    return DocumentResult(
        document=doc,
        predicted=tuple(predicted),
        masked_spans=tuple(predicted),
        masked_text=doc.text,
        roundtrip=True,
        detect_ms=1.0,
        mask_ms=1.0,
        replacements=(),
    )


TEXT = "Dr Anna Minta, born 1990-01-02, lives in Szeged."
#       0123456789012345678901234567890123456789012345678
PERSON = (3, 13, EntityType.PERSON)
IGNORE = [
    {"start": 0, "end": 2, "label": "TITLE"},
    {"start": 20, "end": 30, "label": "DATE"},
    {"start": 41, "end": 47, "label": "CITY"},
]


def test_predictions_on_ignore_regions_are_neither_credited_nor_charged() -> None:
    doc = _doc(TEXT, [PERSON], {"ignore": IGNORE})
    title_and_name = _span(0, 13, EntityType.PERSON)  # overlaps the title, matches gold
    date = _span(20, 30, EntityType.DATE_OF_BIRTH)
    city = _span(41, 47, EntityType.ADDRESS)
    elsewhere = _span(32, 37, EntityType.ADDRESS)  # "lives": a real false positive
    assert not unscored(doc, title_and_name)
    assert unscored(doc, date) and unscored(doc, city)
    assert not unscored(doc, elsewhere)
    block = summarize([_result(doc, [title_and_name, date, city, elsewhere])])
    overlap = block["detection"]["overlap"]["micro"]
    assert (overlap["pred"], overlap["tp_pred"]) == (2, 1)
    assert overlap["recall"] == 1.0
    assert block["over_masking"]["masked"] == 2 and block["over_masking"]["over_masked"] == 1
    assert block["unscored_predictions"] == 2
    assert "DATE_OF_BIRTH" not in block["detection"]["overlap"]["per_type"]
    assert block["leak"]["values"] == 1


def test_a_sample_without_ignore_regions_falls_back_to_unscored_types() -> None:
    legacy = _doc(TEXT, [PERSON], {"kind": "public-ai4privacy"})
    assert unscored(legacy, _span(20, 30, EntityType.DATE_OF_BIRTH))
    # Ai4Privacy has no label for these either, so they can be neither confirmed nor
    # refuted there (LAB-1223).
    for entity_type in (
        EntityType.ORGANIZATION,
        EntityType.VEHICLE_PLATE,
        EntityType.PARCEL_NUMBER_HU,
        EntityType.COMPANY_ID_HU,
    ):
        assert unscored(legacy, _span(32, 37, entity_type))
    assert not unscored(legacy, _span(41, 47, EntityType.ADDRESS))  # needs regions
    other = _doc(TEXT, [PERSON], {"kind": "contract"})
    assert not unscored(other, _span(20, 30, EntityType.DATE_OF_BIRTH))


def test_ignore_regions_are_validated() -> None:
    with pytest.raises(FixtureError, match=r"meta\.ignore"):
        _doc(TEXT, [PERSON], {"ignore": [{"start": 40, "end": 99, "label": "CITY"}]})
    with pytest.raises(FixtureError, match=r"meta\.ignore"):
        _doc(TEXT, [PERSON], {"ignore": "all dates"})


def test_converter_keeps_policy_excluded_labels_as_ignore_regions() -> None:
    row = {
        "uid": 7,
        "language": "en",
        "region": "XX",
        "source_text": "Mr Tom Lee, 12 May 1990, from Paris",
        "privacy_mask": [
            {"label": "TITLE", "start": 0, "end": 2, "value": "Mr"},
            {"label": "GIVENNAME", "start": 3, "end": 6, "value": "Tom"},
            {"label": "SURNAME", "start": 7, "end": 10, "value": "Lee"},
            {"label": "DATE", "start": 12, "end": 23, "value": "12 May 1990"},
            {"label": "CITY", "start": 30, "end": 35, "value": "Paris"},
        ],
    }
    doc = a4p.convert_row(row).document
    assert [(s.start, s.end, s.entity_type) for s in doc.spans] == [(3, 10, EntityType.PERSON)]
    assert doc.meta["ignore"] == [
        {"start": 0, "end": 2, "label": "TITLE"},
        {"start": 12, "end": 23, "label": "DATE"},
        {"start": 30, "end": 35, "label": "CITY"},
    ]
    assert unscored(doc, _span(12, 23, EntityType.DATE_OF_BIRTH))


def test_drop_types_recomputes_from_counts() -> None:
    block = _load("2026-10-27-cued-numbers-after-ai4privacy-rules")["metrics"]["overall"]
    block = copy.deepcopy(block)
    block.pop("unscored_predictions", None)
    block["per_type"]["DATE_OF_BIRTH"] = {
        "gold": 0,
        "pred": 100,
        "exact_tp_gold": 0,
        "exact_tp_pred": 0,
        "overlap_tp_gold": 0,
        "overlap_tp_pred": 0,
        "leak": None,
        "over_masking": {"masked": 100, "over_masked": 90},
    }
    for mode in ("exact", "overlap"):
        block[mode]["pred"] += 100
    block["over_masking"]["masked"] += 100
    block["over_masking"]["over_masked"] += 90
    dropped, n = rescore.drop_types(block, ["DATE_OF_BIRTH"])
    original = _load("2026-10-27-cued-numbers-after-ai4privacy-rules")["metrics"]["overall"]
    assert n == 100 and dropped["unscored_predictions"] == 100
    assert "DATE_OF_BIRTH" not in dropped["per_type"]
    for mode in ("exact", "overlap"):
        assert dropped[mode]["pred"] == original[mode]["pred"]
        assert dropped[mode]["precision"] == pytest.approx(original[mode]["precision"], abs=1e-6)
    assert dropped["over_masking"] == original["over_masking"]
    assert not rate_errors(dropped, "$")
    # A type that has gold spans can't be dropped from counts alone.
    kept, n = rescore.drop_types(original, ["PERSON"])
    assert n == 0 and kept["per_type"]["PERSON"] == original["per_type"]["PERSON"]


def test_rescore_is_marked_idempotent_and_done_for_the_committed_records() -> None:
    rec = _load("2026-10-27-cued-numbers-after-ai4privacy-fast")
    assert rec["rescored"]["by"] == "LAB-1223"
    assert rec["rescored"]["unscored_types"] == ["ORGANIZATION"]
    assert "DATE_OF_BIRTH" not in rec["metrics"]["overall"]["per_type"]
    assert "ORGANIZATION" not in rec["metrics"]["overall"]["per_type"]
    assert rec["metrics"]["overall"]["unscored_predictions"] == 267
    assert rescore.rescore_record(rec) is None
    assert rescore.main(["--runs-dir", str(RUNS), "--check"]) == 0
    # The pre-LAB-1213 form of a record is re-scored, and the result validates.
    old = copy.deepcopy(rec)
    del old["rescored"]
    del old["metrics"]["overall"]["unscored_predictions"]
    old["metrics"]["overall"]["per_type"]["DATE_OF_BIRTH"] = {
        "gold": 0,
        "pred": 5,
        "exact_tp_gold": 0,
        "exact_tp_pred": 0,
        "overlap_tp_gold": 0,
        "overlap_tp_pred": 0,
        "leak": None,
        "over_masking": {"masked": 5, "over_masked": 5},
    }
    old["metrics"]["overall"]["per_type"]["ORGANIZATION"] = {
        "gold": 0,
        "pred": 7,
        "exact_tp_gold": 0,
        "exact_tp_pred": 0,
        "overlap_tp_gold": 0,
        "overlap_tp_pred": 0,
        "leak": None,
        "over_masking": None,
    }
    for mode in ("exact", "overlap"):
        old["metrics"]["overall"][mode]["pred"] += 12
    old["metrics"]["overall"]["over_masking"]["masked"] += 5
    old["metrics"]["overall"]["over_masking"]["over_masked"] += 5
    new = rescore.rescore_record(old)
    assert new is not None and new["rescored"]["method"] == "unscored-types"
    assert new["rescored"]["unscored_types"] == ["DATE_OF_BIRTH", "ORGANIZATION"]
    assert new["metrics"]["overall"]["unscored_predictions"] == 12
    assert list(new)[list(new).index("notes") + 1] == "rescored"
    assert not validate(new, SCHEMA)
    assert rescore.rescore_record(new) is None


def test_records_from_the_current_scorer_are_left_alone() -> None:
    rec = _load("2026-10-27-comparison-en-ai4privacy")
    del rec["rescored"]
    rec["metrics"]["overall"]["unscored_predictions"] = 0
    assert rescore.rescore_record(rec) is None


# --- 3. Baseline consistency ------------------------------------------------------------


class _Tool:
    name = "tool"
    info: ClassVar[dict[str, Any]] = {}
    reversible = True
    placeholder_re = re.compile(r"<[A-Z_]+>")

    def process(self, text: str, language: str) -> BaselineOutput:
        return BaselineOutput(
            spans=(_span(3, 13, EntityType.PERSON),),
            masked_text=text[:3] + "<PERSON>" + text[13:],
            restored_text=text,
            detect_ms=1.0,
            mask_ms=1.0,
            unmapped={},
        )

    def close(self) -> None:
        return None


def test_comparison_tools_have_no_consistency_number() -> None:
    doc = _doc(TEXT, [PERSON], {})
    results, unmapped = run_baseline([doc], _Tool())  # type: ignore[arg-type]
    section = baseline_section(_Tool(), results, unmapped)  # type: ignore[arg-type]
    assert section["overall"]["consistency"] is None
    assert text_metrics(section["overall"])["consistency"] is None
    for path in RUNS.glob("*.json"):
        rec = json.loads(path.read_text(encoding="utf-8"))
        if rec["kind"] == "text" and rec["system"]["family"] == "comparison":
            assert rec["metrics"]["overall"]["consistency"] is None, path.name


# --- 4. Rate validation -----------------------------------------------------------------


def test_validation_requires_rates_to_match_their_counts() -> None:
    rec = _load("2026-10-27-comparison-en-smoke")
    assert not validate(rec, SCHEMA)
    bad = copy.deepcopy(rec)
    bad["metrics"]["overall"]["leak"]["rate"] = 0.5
    assert any("leak.rate" in e for e in validate(bad, SCHEMA))
    bad = copy.deepcopy(rec)
    bad["metrics"]["languages"]["en"]["overlap"]["precision"] = 0.1
    assert any("languages.en.overlap.precision" in e for e in validate(bad, SCHEMA))
    empty = copy.deepcopy(rec)
    om = empty["metrics"]["overall"]["over_masking"]
    om["masked"], om["over_masked"], om["rate"] = 0, 0, 0.0
    assert any("denominator is 0" in e for e in validate(empty, SCHEMA))
    om["rate"] = None  # not measured is fine
    assert not [e for e in validate(empty, SCHEMA) if "$.metrics.overall.over_masking" in e]


# --- 5. ai4privacy --check ------------------------------------------------------------


def _fetch_args(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    rows = [
        {
            "uid": i,
            "language": "en",
            "region": "XX",
            "source_text": f"Hi Name{i}, 1 May 1990",
            "privacy_mask": [
                {"label": "GIVENNAME", "start": 3, "end": 8, "value": f"Name{i}"[:5]},
                {"label": "DATE", "start": 11, "end": 21, "value": "1 May 1990"},
            ],
        }
        for i in range(3)
    ]
    for r in rows:
        r["privacy_mask"][0]["end"] = 3 + len(f"Name{r['uid']}")
        r["privacy_mask"][0]["value"] = f"Name{r['uid']}"
        r["privacy_mask"][1]["start"] = r["privacy_mask"][0]["end"] + 2
        r["privacy_mask"][1]["end"] = r["privacy_mask"][1]["start"] + 10
    source = tmp_path / "validation.jsonl"
    source.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setattr(a4p, "FILE_SHA256", hashlib.sha256(source.read_bytes()).hexdigest())
    return [
        "fetch",
        "--source-file",
        str(source),
        "--sample",
        "en=2",
        "--out",
        str(tmp_path / "out"),
        "--manifest",
        str(tmp_path / "manifest.json"),
    ]


def test_fetch_check_compares_everything_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _fetch_args(tmp_path, monkeypatch)
    assert a4p.main(args) == 0
    fixture = tmp_path / "out" / "en-ai4privacy.jsonl"
    manifest = tmp_path / "manifest.json"
    assert a4p.main([*args, "--check"]) == 0
    # A hand-edited document (same ids) is caught, and --check leaves the file as it is.
    edited = fixture.read_text(encoding="utf-8").replace("Hi ", "Hello ", 1)
    fixture.write_text(edited, encoding="utf-8")
    assert a4p.main([*args, "--check"]) == 1
    assert fixture.read_text(encoding="utf-8") == edited
    assert "en-ai4privacy.jsonl: differs" in capsys.readouterr().err
    assert a4p.main(args) == 0
    # So is a changed label count in the manifest, with the uids untouched.
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["languages"]["en"]["policy_excluded"] = {}
    manifest.write_text(json.dumps(data), encoding="utf-8")
    before = manifest.read_text(encoding="utf-8")
    assert a4p.main([*args, "--check"]) == 1
    assert "languages.en.policy_excluded differs" in capsys.readouterr().err
    assert manifest.read_text(encoding="utf-8") == before
    # A missing fixture file is reported, not created.
    fixture.unlink()
    assert a4p.main([*args, "--check"]) == 1
    assert not fixture.exists()


# --- 6. Wording -------------------------------------------------------------------------


def test_page_defines_over_masking_by_spans_and_pooling_as_micro() -> None:
    page = (ROOT / "docs" / "benchmarks.md").read_text(encoding="utf-8")
    assert "masked characters" not in page
    assert "share of masked spans that overlap no gold span" in page
    assert "**micro-averaged**" in page
    assert "| Commit |" in page
