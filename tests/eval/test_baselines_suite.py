"""``python -m pii_guard.eval.baselines.suite``: one system, one fixture, plus the run block."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pii_guard.eval.baselines import suite
from pii_guard.eval.scorer import DetectorAnalyzer
from pii_guard.types import Span

ROOT = Path(__file__).resolve().parents[2]
EN_SMOKE = ROOT / "eval" / "fixtures" / "en-smoke.jsonl"


def test_cost_counts_cached_and_output_tokens():
    usage = {"prompt_tokens": 1_000_000, "cached_tokens": 400_000, "completion_tokens": 100_000}
    # 600k full-price input + 400k cached + 100k output
    assert suite.cost_usd(usage) == pytest.approx(0.6 * 1.25 + 0.4 * 0.15 + 0.1 * 4.25)
    assert suite.cost_usd({}) == 0


def test_ner_identity_hashes_a_local_checkpoint(tmp_path, monkeypatch):
    (tmp_path / "model.safetensors").write_bytes(b"weights")
    (tmp_path / "training_meta.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("PII_GUARD_NER_MODEL", str(tmp_path))
    monkeypatch.delenv("PII_GUARD_NER_DEVICE", raising=False)
    info = suite.ner_identity()
    assert info["safetensors_sha256"] == {
        "model.safetensors": hashlib.sha256(b"weights").hexdigest()
    }
    assert info["training_meta_sha256"] == hashlib.sha256(b"{}").hexdigest()
    assert info["device"] == "auto"
    monkeypatch.setenv("PII_GUARD_NER_MODEL", "org/hub-model")
    assert "safetensors_sha256" not in suite.ner_identity()


def test_rules_run_writes_scorecard_with_run_block(tmp_path):
    out = tmp_path / "card.json"
    md = tmp_path / "card.md"
    code = suite.main(
        [
            "--system",
            "rules",
            "--fixtures",
            str(EN_SMOKE),
            "--json",
            str(out),
            "--markdown",
            str(md),
        ]
    )
    assert code == 0
    card = json.loads(out.read_text(encoding="utf-8"))
    assert card["meta"]["detectors"] == ["rules"]
    run = card["run"]
    assert run["system"] == "pii-guard rules"
    assert run["documents"] == card["overall"]["documents"]
    assert run["warmup_calls"] == 1
    assert "llm" not in run
    assert "ner" not in run
    assert md.read_text(encoding="utf-8")


class _FakeLlm:
    name = "llm"
    url = "https://example.invalid/v1"
    model = "fake-model"
    reasoning_effort = "low"

    def __init__(self) -> None:
        self.usage = {
            "requests": 0,
            "prompt_tokens": 0,
            "cached_tokens": 0,
            "completion_tokens": 0,
            "refusals": 0,
            "invalid_outputs": 0,
        }

    def detect(self, text: str, language: str) -> list[Span]:
        self.usage["requests"] += 1
        self.usage["prompt_tokens"] += 1000
        self.usage["completion_tokens"] += 500
        return []


def test_llm_usage_excludes_the_warmup_call(tmp_path, monkeypatch):
    fake = _FakeLlm()

    class Analyzer(DetectorAnalyzer):
        def __init__(self, names):
            super().__init__(["rules"])
            self.detectors.append(fake)
            self.loaded = list(names)

        def analyze(self, text, language):
            fake.detect(text, language)
            return super().analyze(text, language)

    monkeypatch.setattr(suite, "DetectorAnalyzer", Analyzer)
    monkeypatch.setattr(suite, "SYSTEMS", {**suite.SYSTEMS, "fake": ["rules", "llm"]})
    out = tmp_path / "card.json"
    assert suite.main(["--system", "fake", "--fixtures", str(EN_SMOKE), "--json", str(out)]) == 0
    llm = json.loads(out.read_text(encoding="utf-8"))["run"]["llm"]
    docs = json.loads(out.read_text(encoding="utf-8"))["run"]["documents"]
    assert llm["usage"]["requests"] == docs
    assert llm["usage_incl_warmup"]["requests"] == docs + 1
    assert llm["cost_usd"] == pytest.approx(suite.cost_usd(llm["usage"]), abs=1e-4)
    assert llm["usd_per_1k_messages"] == pytest.approx(llm["cost_usd"] / docs * 1000, abs=0.01)
    assert llm["model"] == "fake-model"
    assert "key" not in json.dumps(llm).lower()


def test_unavailable_detector_fails_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(suite, "SYSTEMS", {"broken": ["no-such-detector"]})
    out = tmp_path / "card.json"
    assert suite.main(["--system", "broken", "--fixtures", str(EN_SMOKE), "--json", str(out)]) == 2
    assert not out.exists()


def test_bad_fixture_path_exits_2(tmp_path):
    code = suite.main(
        [
            "--system",
            "rules",
            "--fixtures",
            str(tmp_path / "missing.jsonl"),
            "--json",
            str(tmp_path / "x.json"),
        ]
    )
    assert code == 2


def test_a_failing_document_is_blocked_not_fatal(tmp_path, monkeypatch):
    from pii_guard.types import DetectionError

    calls = {"n": 0}

    class Analyzer(DetectorAnalyzer):
        def analyze(self, text, language):
            calls["n"] += 1
            if calls["n"] == 3:  # the warm-up is call 1
                raise DetectionError("llm detector failed: completion truncated")
            return super().analyze(text, language)

    monkeypatch.setattr(suite, "DetectorAnalyzer", Analyzer)
    out = tmp_path / "card.json"
    assert suite.main(["--system", "rules", "--fixtures", str(EN_SMOKE), "--json", str(out)]) == 0
    card = json.loads(out.read_text(encoding="utf-8"))
    assert card["run"]["blocked"] == 1
    assert card["run"]["blocked_documents"][0]["error"].startswith("llm detector failed")
    assert card["overall"]["documents"] == card["run"]["documents"] - 1
