"""The eval suite's ``escalate`` system (LAB-1766), with a fake LLM: no network, fictional data."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pii_guard.eval.baselines import suite
from pii_guard.types import EntityType, Span

ROOT = Path(__file__).resolve().parents[2]
EN_SMOKE = ROOT / "eval" / "fixtures" / "en-smoke.jsonl"


class FakeLlm:
    name = "llm"
    model = "fake-llm"

    def __init__(self) -> None:
        self.calls = 0
        self.usage = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0}

    def detect(self, text: str, language: str = "en") -> list[Span]:
        self.calls += 1
        self.usage["requests"] += 1
        self.usage["prompt_tokens"] += 1000
        self.usage["completion_tokens"] += 100
        return [
            Span(m.start(), m.end(), EntityType.PERSON, m.group(0), 0.9, "llm")
            for m in re.finditer(r"(?<=Mr\. )[A-Z][a-z]+", text)
        ]


def test_escalate_analyzer_adds_spans_and_measures_added_latency() -> None:
    analyzer = suite.EscalateAnalyzer(["rules"], llm=FakeLlm())
    assert analyzer.loaded == ["rules", "llm"]
    analyzer.analyze("Warm-up text without personal data.", "en")
    spans = analyzer.analyze("Please call Mr. Quill today.", "en")
    assert [(s.text, s.entity_type) for s in spans] == [("Quill", EntityType.PERSON)]
    block = suite._escalation_block(analyzer, documents=1)
    assert block["escalation_rate"] == 1.0
    assert block["usage"]["escalated_texts"] == 1
    assert block["added_ms"]["p50"] is not None


def test_suite_writes_the_escalation_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = suite.EscalateAnalyzer
    monkeypatch.setattr(suite, "EscalateAnalyzer", lambda names: real(["rules"], llm=FakeLlm()))
    out = tmp_path / "card.json"
    code = suite.main(["--system", "escalate", "--fixtures", str(EN_SMOKE), "--json", str(out)])
    assert code == 0
    run = json.loads(out.read_text(encoding="utf-8"))["run"]
    assert run["system"] == "pii-guard escalate"
    escalation = run["escalation"]
    assert 0 <= escalation["escalation_rate"] <= 1
    assert escalation["settings"]["window"] == 200
    assert run["llm"]["usage"]["requests"] == escalation["usage"]["escalated_texts"]
