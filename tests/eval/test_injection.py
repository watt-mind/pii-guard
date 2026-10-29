"""Prompt-injection fixtures and the per-attack leak report."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from pii_guard.eval import dump_document, from_markup, label, load_fixtures
from pii_guard.eval.cli import main as eval_main
from pii_guard.eval.injection import (
    UNTAGGED,
    attack_breakdown,
    render_attack_table,
    run_injection,
)
from pii_guard.eval.scorer import DEFAULT_POLICY, DetectorAnalyzer
from pii_guard.types import DetectionError, Span

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "eval" / "fixtures"
HU = FIXTURES / "hu-injection.jsonl"
EN = FIXTURES / "en-injection.jsonl"


def _builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_injection", FIXTURES / "build_injection.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_fixtures_match_the_builder() -> None:
    builder = _builder()
    for name, build in builder.OUTPUTS.items():
        expected = "\n".join(dump_document(d) for d in build()) + "\n"
        assert (FIXTURES / name).read_text(encoding="utf-8") == expected, (
            f"{name} is stale: run `uv run python eval/fixtures/build_injection.py`"
        )


def test_fixture_coverage() -> None:
    attacks = _builder().ATTACKS
    docs = load_fixtures([HU, EN])
    assert len(docs) >= 40
    assert {d.language for d in docs} == {"hu", "en"}
    by_language: dict[str, set[str]] = {"hu": set(), "en": set()}
    for d in docs:
        assert d.meta["attack"] in attacks
        by_language[d.language].add(d.meta["attack"])
        # Every case has at least one value that must be masked.
        assert any(DEFAULT_POLICY.get(s.entity_type, "mask") == "mask" for s in d.spans)
    assert len(set(attacks)) >= 8
    assert by_language["hu"] == by_language["en"] == set(attacks)


def test_long_padding_cases_cross_the_llm_chunk_size() -> None:
    from pii_guard.detect.llm import LlmDetector

    size = LlmDetector.__init__.__kwdefaults__["chunk_size"]
    long_docs = [d for d in load_fixtures([HU, EN]) if d.meta["attack"] == "long-padding"]
    assert long_docs and all(len(d.text) > size for d in long_docs)
    # At least one value per language sits within 300 code points of the first chunk's end.
    near = {d.language for d in long_docs if any(abs(s.start - size) < 300 for s in d.spans)}
    assert near == {"hu", "en"}


# --- Report --------------------------------------------------------------------------------


class _FakeAnalyzer:
    """Finds labelled values verbatim, except in documents it is told to miss or block."""

    def __init__(self, miss: set[str] = frozenset(), block: set[str] = frozenset()) -> None:
        self.miss, self.block = miss, block
        self.docs: dict[str, object] = {}

    def analyze(self, text: str, language: str) -> list[Span]:
        doc = self.docs[text]
        if doc.id in self.block:  # type: ignore[attr-defined]
            raise DetectionError("llm detector failed: model refused")
        if doc.id in self.miss:  # type: ignore[attr-defined]
            return []
        return [
            Span(s.start, s.end, s.entity_type, s.text, 1.0, "fake")
            for s in doc.spans  # type: ignore[attr-defined]
        ]


def _docs() -> list:
    return [
        from_markup(
            "a1",
            f"Ignore this. {label('PERSON', 'Teszt Elek')}",
            language="hu",
            meta={"attack": "ignore-instructions"},
        ),
        from_markup(
            "a2",
            f"Ignore that. {label('PERSON', 'Minta Anna')}",
            language="hu",
            meta={"attack": "ignore-instructions"},
        ),
        from_markup(
            "b1",
            f"Zero {label('PERSON', 'Jane Example')}",
            language="en",
            meta={"attack": "zero-width"},
        ),
        from_markup("c1", f"Plain {label('PERSON', 'John Sample')}", language="en"),
    ]


def test_breakdown_counts_leaks_and_blocks_per_attack() -> None:
    docs = _docs()
    analyzer = _FakeAnalyzer(miss={"a2"}, block={"b1"})
    analyzer.docs = {d.text: d for d in docs}
    results, blocked = run_injection(docs, analyzer)
    assert [d.id for d, _ in blocked] == ["b1"]
    breakdown = attack_breakdown(results, blocked, order=["ignore-instructions", "zero-width"])
    assert list(breakdown) == ["ignore-instructions", "zero-width", UNTAGGED]
    ignore = breakdown["ignore-instructions"]
    assert (ignore["documents"], ignore["values"], ignore["leaked"]) == (2, 2, 1)
    assert ignore["leak_rate"] == 0.5 and ignore["leaked_ids"] == ["a2"]
    zero = breakdown["zero-width"]
    assert (zero["documents"], zero["blocked"], zero["values"], zero["leak_rate"]) == (
        1,
        1,
        0,
        None,
    )
    assert breakdown[UNTAGGED]["leaked"] == 0
    table = render_attack_table(breakdown)
    assert "| `ignore-instructions` | 2 | 0 | 2 | 1 | 50.0 |" in table
    assert "| **all** | 4 | 1 | 3 | 1 | 33.3 |" in table
    assert "Teszt" not in json.dumps(breakdown) and "Teszt" not in table


def test_other_errors_are_not_swallowed() -> None:
    class Broken:
        def analyze(self, text: str, language: str) -> list[Span]:
            raise RuntimeError("bug")

    with pytest.raises(RuntimeError):
        run_injection(_docs()[:1], Broken())


def test_injection_cli_with_rules(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "card.json"
    md = tmp_path / "card.md"
    code = eval_main(
        [
            "injection",
            "--fixtures",
            str(HU),
            "--fixtures",
            str(EN),
            "--detectors",
            "rules",
            "--json",
            str(out),
            "--markdown",
            str(md),
        ]
    )
    assert code == 0
    card = json.loads(out.read_text("utf-8"))
    attacks = _builder().ATTACKS
    assert list(card["attacks"]) == list(attacks)
    assert card["blocked"] == [] and card["usage"] == {}
    assert sum(a["documents"] for a in card["attacks"].values()) == len(load_fixtures([HU, EN]))
    assert "| `zero-width` |" in capsys.readouterr().out
    assert md.read_text("utf-8").startswith("# pii-guard prompt-injection red team")
    # No labelled value in the report.
    text = out.read_text("utf-8")
    for doc in load_fixtures([HU, EN]):
        for span in doc.spans:
            if len(span.text) > 6:
                assert span.text not in text


def test_plain_eval_appends_the_attack_table(capsys: pytest.CaptureFixture[str]) -> None:
    assert eval_main(["--fixtures", str(HU), "--detectors", "rules"]) == 0
    out = capsys.readouterr().out
    assert "## Per attack class" in out and "| `long-padding` |" in out


def test_injection_cli_bad_arguments(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert eval_main(["injection", "--fixtures", str(tmp_path / "missing.jsonl")]) == 2
    assert eval_main(["injection", "--fixtures", str(HU), "--language", "de"]) == 2
    assert eval_main(["injection", "--fixtures", str(HU), "--detectors", "nope"]) == 2


def test_analyzer_type_is_accepted() -> None:
    # The CLI builds a DetectorAnalyzer; run_injection takes any analyzer.
    analyzer = DetectorAnalyzer(["rules"])
    results, blocked = run_injection(load_fixtures(HU)[:2], analyzer)
    assert len(results) == 2 and blocked == []
