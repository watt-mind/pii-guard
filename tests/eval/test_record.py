"""Run records: the schema, the validator, ``--record`` and ``eval record``. Fictional data only."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from pii_guard import cli
from pii_guard.eval import DetectorAnalyzer, build_scorecard, load_fixtures, run_documents
from pii_guard.eval.record import (
    RECORD_SCHEMA_VERSION,
    SUPPORTED_KEYWORDS,
    RecordError,
    build_records,
    load_records,
    load_schema,
    merge_extra,
    system_key,
    validate,
    write_records,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS = REPO_ROOT / "eval" / "results" / "runs"
SCHEMA = REPO_ROOT / "eval" / "results" / "schema" / "run.schema.json"
HU = REPO_ROOT / "eval" / "fixtures" / "hu-smoke.jsonl"


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return load_schema(SCHEMA)


@pytest.fixture(scope="module")
def scorecard() -> dict[str, Any]:
    documents = load_fixtures([HU])
    analyzer = DetectorAnalyzer(["rules"])
    return build_scorecard(
        run_documents(documents, analyzer), detectors=analyzer.loaded, fixture_paths=[HU]
    )


def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repo-shaped directory (schema + report config, no runs) as the working directory."""
    (tmp_path / "eval" / "results" / "schema").mkdir(parents=True)
    shutil.copy(SCHEMA, tmp_path / "eval" / "results" / "schema" / "run.schema.json")
    (tmp_path / "docs" / "benchmarks").mkdir(parents=True)
    config = {"headline_set": "smoke", "featured": ["rules"]}
    (tmp_path / "docs" / "benchmarks" / "config.json").write_text(json.dumps(config))
    monkeypatch.chdir(tmp_path)
    return tmp_path


# --- Committed records and schema ----------------------------------------------------------


def test_every_committed_record_is_valid(schema: dict[str, Any]) -> None:
    records = load_records(RUNS)  # validates each and checks file name == run_id
    assert len(records) >= 33
    for record in records:
        assert validate(record, schema) == [], record["run_id"]
        assert record["schema_version"] == RECORD_SCHEMA_VERSION


def test_backfill_covers_every_earlier_result() -> None:
    records = {r["run_id"]: r for r in load_records(RUNS)}
    imported = [r for r in records.values() if r["source"] == "imported"]
    assert len(imported) >= 33
    assert all(r["imported_from"]["path"] for r in imported)
    keys = {r["system"]["key"] for r in imported}
    # Baselines (LAB-1098), NER study (LAB-1106), Glimmer zero-shot (LAB-1109), visual runs.
    assert {"presidio", "llm-guard", "privaite", "rules"} <= keys
    assert {"rules+ner:xlmr-base-ft-s7", "rules+ner:xlmr-ner-hrl"} <= keys
    assert any(k.startswith("llm:muse-glimmer") for k in keys)
    assert any(k.startswith("rules+llm:muse-glimmer") for k in keys)
    assert any(r["kind"] == "visual" for r in imported)
    glimmer = [r for r in imported if "glimmer" in r["run_id"]]
    assert len(glimmer) == 3
    assert all(r["cost"] and r["cost"]["gpu_minutes"] for r in glimmer)


def test_schema_uses_only_keywords_the_validator_implements(schema: dict[str, Any]) -> None:
    def walk(node: Any, in_properties: bool = False) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if not in_properties:
                    assert key in SUPPORTED_KEYWORDS, key
                walk(value, in_properties=key in ("properties", "$defs"))
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    assert schema["properties"]["schema_version"]["const"] == RECORD_SCHEMA_VERSION


def test_validator_rejects_broken_records(schema: dict[str, Any]) -> None:
    good = load_records(RUNS)[0]
    assert validate(good, schema) == []

    missing = copy.deepcopy(good)
    del missing["code"]
    assert any("code" in e for e in validate(missing, schema))

    wrong_type = copy.deepcopy(good)
    wrong_type["code"]["dirty"] = "no"
    assert validate(wrong_type, schema)

    bad_source = copy.deepcopy(good)
    bad_source["source"] = "guessed"
    assert validate(bad_source, schema)

    bad_id = copy.deepcopy(good)
    bad_id["run_id"] = "1999-01-01-" + good["run_id"][11:]
    assert any("run date" in e for e in validate(bad_id, schema))


# --- Building records ----------------------------------------------------------------------


def test_record_from_live_scorecard(scorecard: dict[str, Any], schema: dict[str, Any]) -> None:
    (record,) = build_records(scorecard, slug="unit-test")
    assert validate(record, schema) == []
    assert record["run_id"].endswith("-unit-test")
    assert record["system"]["key"] == "rules"
    assert record["fixture_set"] == "smoke"
    assert record["languages"] == ["hu"]
    assert record["fixtures"][0]["origin"] == "hand-written"
    assert record["metrics"]["languages"]["hu"]["documents"] == 28
    # Like the scorecard, a record never carries a labelled value or document text.
    dumped = json.dumps(record, ensure_ascii=False)
    for document in load_fixtures([HU])[:5]:
        for span in document.spans:
            value = document.text[span.start : span.end]
            if len(value) >= 6:
                assert value not in dumped


def test_one_record_per_comparison_tool(scorecard: dict[str, Any], schema: dict[str, Any]) -> None:
    card = copy.deepcopy(scorecard)
    card["baselines"] = {
        "presidio": {
            "overall": card["overall"],
            "languages": card["languages"],
            "reversible": False,
            "info": {"versions": {"presidio-analyzer": "2.2.365"}, "models": ["hu_core_news_lg"]},
        }
    }
    ours, theirs = build_records(card, slug="with-tools")
    assert theirs["run_id"] == ours["run_id"] + "-presidio"
    assert theirs["system"]["family"] == "comparison"
    assert theirs["system"]["label"] == "Presidio"
    assert theirs["metrics"]["overall"]["roundtrip"] is None
    assert validate(theirs, schema) == []


def test_extra_merges_models_and_settings_into_the_system_key(
    scorecard: dict[str, Any], schema: dict[str, Any]
) -> None:
    card = copy.deepcopy(scorecard)
    card["meta"]["detectors"] = ["rules", "llm"]
    (record,) = build_records(card, slug="glimmer")
    merge_extra(
        record,
        {
            "system": {
                "detectors": {
                    "llm": {"model": "muse-glimmer", "settings": {"reasoning_strength": "low"}}
                }
            },
            "cost": {"usd": 1.5, "estimated": True},
            "notes": ["ran on a test box"],
        },
    )
    assert record["system"]["key"] == system_key(record["system"])
    assert "muse-glimmer" in record["system"]["key"]
    assert "reasoning_strength=low" in record["system"]["key"]
    assert record["cost"]["usd"] == 1.5
    assert "ran on a test box" in record["notes"]
    assert record["cost"]["gpu_minutes"] is None  # a partial cost is completed with nulls
    assert validate(record, schema) == []


def test_bad_slug_and_non_scorecard_are_rejected(scorecard: dict[str, Any]) -> None:
    with pytest.raises(RecordError):
        build_records(scorecard, slug="Has Spaces")
    with pytest.raises(RecordError):
        build_records({"hello": 1}, slug="x")


def test_write_refuses_to_overwrite(
    scorecard: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    runs = root / "eval" / "results" / "runs"
    records = build_records(scorecard, slug="once")
    (path,) = write_records(records, runs)
    assert path.name == records[0]["run_id"] + ".json"
    with pytest.raises(RecordError, match="exists"):
        write_records(records, runs)
    write_records(records, runs, overwrite=True)
    broken = copy.deepcopy(records)
    broken[0]["kind"] = "audio"
    with pytest.raises(RecordError, match="invalid"):
        write_records(broken, runs, overwrite=True)


# --- CLI -----------------------------------------------------------------------------------


def test_eval_record_flag_writes_a_record_and_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    extra = root / "extra.json"
    extra.write_text(json.dumps({"hardware": {"description": "test laptop"}}))
    code = cli.main(
        ["eval", "--fixtures", str(HU), "--record", "cli-run", "--record-extra", str(extra)]
    )
    assert code == 0
    (path,) = (root / "eval" / "results" / "runs").glob("*-cli-run.json")
    record = json.loads(path.read_text())
    assert record["source"] == "recorded"
    assert record["hardware"]["description"] == "test laptop"
    assert record["hardware"]["cpu_count"]  # host_info, merged under the extra
    assert (root / "eval" / "results" / "index.json").is_file()
    assert (root / "docs" / "benchmarks.md").is_file()
    assert (root / "docs" / "benchmarks" / "leak-vs-latency.svg").is_file()
    # A second run with the same slug the same day is refused, not overwritten.
    assert cli.main(["eval", "--fixtures", str(HU), "--record", "cli-run"]) == 2
    assert "exists" in capsys.readouterr().err


def test_record_extra_needs_record(tmp_path: Path) -> None:
    extra = tmp_path / "extra.json"
    extra.write_text("{}")
    assert cli.main(["eval", "--fixtures", str(HU), "--record-extra", str(extra)]) == 2


def test_eval_record_subcommand_from_saved_scorecard(
    scorecard: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, monkeypatch)
    saved = root / "card.json"
    saved.write_text(json.dumps(scorecard))
    code = cli.main(
        ["eval", "record", str(saved), "--slug", "saved", "--source", "imported", "--no-report"]
    )
    assert code == 0
    (path,) = (root / "eval" / "results" / "runs").glob("*-saved.json")
    record = json.loads(path.read_text())
    assert record["source"] == "imported"
    assert record["imported_from"]["path"] == str(saved)
    assert not (root / "eval" / "results" / "index.json").exists()
    assert cli.main(["eval", "record", str(root / "missing.json"), "--slug", "x"]) == 2
