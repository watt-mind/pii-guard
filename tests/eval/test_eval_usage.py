"""LLM detector usage and cost in the scorecard (LAB-1140). All values are fictional."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pii_guard.eval import DetectorAnalyzer, build_scorecard, load_fixtures, run_documents
from pii_guard.eval import cli as eval_cli
from pii_guard.eval.report import price_usage, render_markdown
from pii_guard.types import Span

REPO_ROOT = Path(__file__).resolve().parents[2]
EN = REPO_ROOT / "eval" / "fixtures" / "en-smoke.jsonl"


class _Metered:
    """A detector that finds nothing and meters one fake request per call."""

    name = "metered"

    def __init__(self) -> None:
        self.usage = {
            "requests": 0,
            "prompt_tokens": 0,
            "cached_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
            "invalid_outputs": 0,
            "refusals": 0,
        }

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        self.usage["requests"] += 1
        self.usage["prompt_tokens"] += 1000
        self.usage["cached_tokens"] += 400
        self.usage["completion_tokens"] += 100
        self.usage["reasoning_tokens"] += 20
        return []


def _patch(monkeypatch: pytest.MonkeyPatch) -> None:
    from pii_guard.eval import scorer

    real = scorer.create_detector
    monkeypatch.setattr(
        scorer, "create_detector", lambda name: _Metered() if name == "metered" else real(name)
    )


def test_analyzer_collects_usage_only_from_metered_detectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(monkeypatch)
    analyzer = DetectorAnalyzer(["rules", "metered"])
    analyzer.analyze("Hello there", "en")
    analyzer.analyze("Hello again", "en")
    usage = analyzer.usage()
    assert list(usage) == ["metered"]
    assert usage["metered"]["requests"] == 2
    assert usage["metered"]["prompt_tokens"] == 2000
    assert DetectorAnalyzer(["rules"]).usage() == {}


def test_scorecard_unchanged_without_usage() -> None:
    results = run_documents(load_fixtures(EN), DetectorAnalyzer(["rules"]))
    card = build_scorecard(results, detectors=["rules"], commit=("abc", False))
    assert "usage" not in card["meta"]
    assert "usage" not in render_markdown(card).lower()


def test_scorecard_usage_block_and_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch)
    docs = load_fixtures(EN)
    analyzer = DetectorAnalyzer(["metered"])
    results = run_documents(docs, analyzer)
    card = build_scorecard(
        results,
        detectors=analyzer.loaded,
        commit=("abc", False),
        usage=analyzer.usage(),
        price={"input": 1.0, "cached": 0.5, "output": 2.0},
    )
    block = card["meta"]["usage"]
    n = len(docs)
    assert block["messages"] == n
    assert block["total"]["requests"] == n
    assert block["detectors"]["metered"]["completion_tokens"] == 100 * n
    # per request: 600 uncached input @1, 400 cached @0.5, 100 output @2 per 1M tokens
    per_request = (600 * 1.0 + 400 * 0.5 + 100 * 2.0) / 1e6
    assert block["cost"]["usd"] == pytest.approx(per_request * n)
    assert block["cost"]["usd_per_1k_messages"] == pytest.approx(per_request * 1000)
    assert block["refusal_rate"] == 0.0
    text = render_markdown(card)
    assert "LLM usage" in text
    json.dumps(card)  # counts and numbers only


def test_price_usage_defaults_cached_to_input_rate() -> None:
    total = {"prompt_tokens": 1_000_000, "cached_tokens": 500_000, "completion_tokens": 0}
    cost = price_usage(total, messages=10, price={"input": 2.0, "output": 8.0})
    assert cost["usd"] == pytest.approx(2.0)
    assert cost["prices_per_1m_tokens"]["cached"] == 2.0


def test_cli_price_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(monkeypatch)
    out = tmp_path / "card.json"
    argv = ["--fixtures", str(EN), "--detectors", "rules,metered", "--json", str(out)]
    argv += ["--price-input", "1", "--price-cached", "0.5", "--price-output", "2"]
    assert eval_cli.main(argv) == 0
    card = json.loads(out.read_text(encoding="utf-8"))
    assert card["meta"]["usage"]["cost"]["usd_per_1k_messages"] > 0
    assert "LLM usage" in capsys.readouterr().out


def test_cli_price_without_metered_detector_is_harmless(tmp_path: Path) -> None:
    out = tmp_path / "card.json"
    argv = ["--fixtures", str(EN), "--json", str(out), "--price-input", "1"]
    assert eval_cli.main(argv) == 0
    assert "usage" not in json.loads(out.read_text(encoding="utf-8"))["meta"]


def test_cli_rejects_negative_price() -> None:
    with pytest.raises(SystemExit) as exc:
        eval_cli.main(["--fixtures", str(EN), "--price-output", "-1"])
    assert exc.value.code == 2


def test_priced_usage_becomes_a_valid_record_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    from pii_guard.eval.record import build_records, load_schema, validate

    _patch(monkeypatch)
    analyzer = DetectorAnalyzer(["metered"])
    results = run_documents(load_fixtures(EN), analyzer)
    card = build_scorecard(
        results,
        detectors=analyzer.loaded,
        fixture_paths=[EN],
        commit=("abc1234", False),
        usage=analyzer.usage(),
        price={"input": 1.0, "output": 2.0},
    )
    extra = eval_cli._with_usage_cost(None, card)
    assert extra is not None
    assert extra["cost"]["model_calls"] == len(results)
    record = build_records(card, slug="usage-test", extra=extra)[0]
    assert record["cost"]["estimated"] is True
    schema = load_schema(REPO_ROOT / "eval" / "results" / "schema" / "run.schema.json")
    assert validate(record, schema) == []
    own = {"cost": {"usd": 9.0}}
    assert eval_cli._with_usage_cost(own, card) is own
