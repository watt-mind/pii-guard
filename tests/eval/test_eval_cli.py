"""``pii-guard eval`` and the committed smoke fixtures. All values are fictional (ADR 0005)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from pii_guard import cli
from pii_guard.detect.checksums import is_valid_hu_tax_id, is_valid_iban, is_valid_taj
from pii_guard.eval import (
    DetectorAnalyzer,
    build_scorecard,
    dump_document,
    load_fixtures,
    render_markdown,
    run_documents,
)
from pii_guard.eval import cli as eval_cli
from pii_guard.types import TEXT_ENTITY_TYPES, DetectionError, EntityType, Span

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "eval" / "fixtures"
HU = FIXTURES / "hu-smoke.jsonl"
EN = FIXTURES / "en-smoke.jsonl"


def _builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_smoke", FIXTURES / "build_smoke.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- Committed fixtures ------------------------------------------------------------------


def test_committed_fixtures_match_the_builder() -> None:
    builder = _builder()
    for name, build in builder.OUTPUTS.items():
        expected = "\n".join(dump_document(d) for d in build()) + "\n"
        assert (FIXTURES / name).read_text(encoding="utf-8") == expected, (
            f"{name} is stale: run `uv run python eval/fixtures/build_smoke.py`"
        )


def test_hu_smoke_covers_every_text_entity_type() -> None:
    docs = load_fixtures(HU)
    assert 25 <= len(docs) <= 40
    assert {d.language for d in docs} == {"hu"}
    # SECRET (API keys, passwords) is not Hungarian prose: eval/fixtures/secrets covers it.
    expected = set(TEXT_ENTITY_TYPES) - {EntityType.SECRET}
    assert {s.entity_type for d in docs for s in d.spans} == expected
    negatives = [d for d in docs if "hard-negative" in d.meta.get("tags", [])]
    assert len(negatives) >= 3
    assert all(not d.spans for d in negatives)


def test_en_smoke_is_english() -> None:
    docs = load_fixtures(EN)
    assert {d.language for d in docs} == {"en"}
    types = {s.entity_type for d in docs for s in d.spans}
    assert {EntityType.PERSON, EntityType.EMAIL, EntityType.PHONE, EntityType.BANK_ACCOUNT} <= types


def test_checksummed_identifiers_are_valid() -> None:
    for doc in load_fixtures([HU, EN]):
        for span in doc.spans:
            compact = "".join(ch for ch in span.text if ch.isalnum())
            if span.entity_type is EntityType.NATIONAL_ID_HU_TAX:
                assert is_valid_hu_tax_id(compact), doc.id
            elif span.entity_type is EntityType.NATIONAL_ID_HU_TAJ:
                assert is_valid_taj(compact), doc.id
            elif span.entity_type is EntityType.BANK_ACCOUNT and compact[:2].isalpha():
                assert is_valid_iban(compact), doc.id


def test_rules_raise_no_alarms_on_hard_negatives() -> None:
    docs = [d for d in load_fixtures([HU, EN]) if "hard-negative" in d.meta.get("tags", [])]
    analyzer = DetectorAnalyzer(["rules"])
    assert all(analyzer.analyze(d.text, d.language) == [] for d in docs)


# --- CLI ---------------------------------------------------------------------------------


def test_eval_via_top_level_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out" / "card.json"
    md = tmp_path / "out" / "card.md"
    code = cli.main(
        ["eval", "--fixtures", str(HU), "--fixtures", str(EN), "--detectors", "rules",
         "--json", str(out), "--markdown", str(md)]
    )  # fmt: skip
    assert code == 0
    stdout = capsys.readouterr().out
    assert "| `hu` |" in stdout and "| `en` |" in stdout and "**overall**" in stdout
    assert md.read_text(encoding="utf-8") == stdout
    card = json.loads(out.read_text(encoding="utf-8"))
    assert card["schema_version"] == 1
    assert card["meta"]["detectors"] == ["rules"]
    assert [f["path"] for f in card["meta"]["fixtures"]] == [str(HU), str(EN)]
    assert all(len(f["sha256"]) == 64 for f in card["meta"]["fixtures"])
    assert set(card["languages"]) == {"hu", "en"}
    assert card["overall"]["documents"] == sum(b["documents"] for b in card["languages"].values())
    # No document text or labelled value ever lands in the scorecard.
    blob = out.read_text(encoding="utf-8")
    for doc in load_fixtures([HU, EN]):
        for span in doc.spans:
            if len(span.text) >= 6:
                assert span.text not in blob


def test_eval_language_filter_and_directory(capsys: pytest.CaptureFixture[str]) -> None:
    assert eval_cli.main(["--fixtures", str(FIXTURES), "--language", "en"]) == 0
    stdout = capsys.readouterr().out
    assert "| `en` |" in stdout
    assert "| `hu` |" not in stdout
    assert "language filter: en" in stdout


def test_eval_skips_unknown_detectors_with_warning(capsys: pytest.CaptureFixture[str]) -> None:
    assert eval_cli.main(["--fixtures", str(HU), "--detectors", "rules,nosuchdetector"]) == 0
    captured = capsys.readouterr()
    assert "skipping detector 'nosuchdetector'" in captured.err
    assert "skipped detector `nosuchdetector`" in captured.out


@pytest.mark.parametrize(
    "argv",
    [
        ["--fixtures", "missing.jsonl"],
        ["--detectors", "nosuchdetector"],
        ["--language", "xx"],
    ],
)
def test_eval_usage_errors_exit_2(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    if "--fixtures" not in argv:
        argv = ["--fixtures", str(HU), *argv]
    assert eval_cli.main(argv) == 2
    assert "pii-guard eval:" in capsys.readouterr().err


def test_eval_bad_arguments_exit_2() -> None:
    with pytest.raises(SystemExit) as exc:
        eval_cli.main(["--detectors", ","])
    assert exc.value.code == 2


def test_eval_fails_closed_when_a_detector_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Failing:
        name = "failing"

        def detect(self, text: str, language: str = "hu") -> list[Span]:
            raise DetectionError("detector 'failing' failed")

    monkeypatch.setattr("pii_guard.eval.scorer.create_detector", lambda name: Failing())
    assert eval_cli.main(["--fixtures", str(HU), "--detectors", "failing"]) == 1
    captured = capsys.readouterr()
    assert "detection_failed" in captured.err
    assert captured.out == ""


def test_scorecard_api_for_other_tools() -> None:
    docs = load_fixtures(EN)
    results = run_documents(docs, DetectorAnalyzer(["rules"]))
    card = build_scorecard(results, detectors=["rules"], commit=("abc123", False))
    assert card["meta"]["commit"] == "abc123"
    assert card["meta"]["fixtures"] == []
    text = render_markdown(card)
    assert "`abc123`" in text
    assert "## Per entity type: `en`" in text


def test_record_to_custom_runs_dir_leaves_benchmarks_untouched(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LAB-1368: --record --runs-dir DIR must not rewrite docs/benchmarks.md."""
    import hashlib

    from pii_guard.eval.cli import _record

    monkeypatch.chdir(REPO_ROOT)
    before = (REPO_ROOT / "docs" / "benchmarks.md").read_bytes()
    digest_before = hashlib.sha256(before).hexdigest()
    card = build_scorecard(
        run_documents(load_fixtures([HU]), DetectorAnalyzer(["rules"])),
        detectors=["rules"],
        fixture_paths=[HU],
    )
    runs_dir = tmp_path / "runs"
    assert _record(card, "probe-custom-dir", None, runs_dir) == 0
    assert list(runs_dir.glob("*.json")), "the probe record lands in the custom dir"
    after = (REPO_ROOT / "docs" / "benchmarks.md").read_bytes()
    assert hashlib.sha256(after).hexdigest() == digest_before
