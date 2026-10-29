"""The agent-text fixture (LAB-1470): committed files match the builder, and the guards keep
every fictional value in it masked. All values are fictional (ADR 0005)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from pii_guard.detect.ner_context import guard_spans
from pii_guard.detect.rules import RuleDetector
from pii_guard.eval.fixtures import dump_document, load_fixtures
from pii_guard.types import EntityType, Span

FIXTURES = Path(__file__).resolve().parents[2] / "eval" / "fixtures"


def _builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_agent_text", FIXTURES / "build_agent_text.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_fixture_matches_the_builder() -> None:
    builder = _builder()
    for lang in builder.LANGUAGES:
        path = FIXTURES / "agent-text" / f"{lang}-agent-text.jsonl"
        expected = "\n".join(dump_document(d) for d in builder.build(lang)) + "\n"
        assert path.read_text(encoding="utf-8") == expected, (
            f"{path.name} is stale: run `uv run python eval/fixtures/build_agent_text.py`"
        )


def test_guards_never_drop_a_gold_value() -> None:
    """Fail closed: a gold value the NER proposes survives every guard, or the rules (which
    the guards never touch) find it, as for an IBAN in an export path."""
    rules = RuleDetector()
    docs = load_fixtures(FIXTURES / "agent-text")
    assert any(d.spans for d in docs) and any(not d.spans for d in docs)
    for doc in docs:
        spans = [
            Span(g.start, g.end, EntityType(g.entity_type), g.text, 0.9, "ner") for g in doc.spans
        ]
        kept = {(s.start, s.end) for s in guard_spans(doc.text, spans, doc.language)}
        kept |= {(s.start, s.end) for s in rules.detect(doc.text, doc.language)}
        for g in doc.spans:
            assert (g.start, g.end) in kept, (doc.id, g.entity_type)
