"""Evaluation harness: fixture format, scorer and scorecard. See ``docs/evaluation.md``.

The small public API, for the CLI and for corpus generators / red-team scorers::

    from pii_guard.eval import (
        Document, GoldSpan, load_fixtures, write_fixtures, from_markup, label,  # fixtures
        find_surface_forms, register_language_forms, LanguageForms,            # surface forms
        DetectorAnalyzer, run_documents, summarize, match_counts, prf,         # scoring
        leak_report, over_masked, build_scorecard, render_markdown,
    )

    docs = load_fixtures(["eval/fixtures/hu-smoke.jsonl", "eval/fixtures/en-smoke.jsonl"])
    results = run_documents(docs, DetectorAnalyzer(["rules"]))
    card = build_scorecard(results, detectors=["rules"])
    print(render_markdown(card))

A generator locates every inserted value (inflected forms included) with
``find_surface_forms(text, value, entity_type, language)`` and writes records with
``write_fixtures``. A re-identification scorer reuses ``leak_report(doc, masked_text)``.
"""

from pii_guard.eval.fixtures import (
    Document,
    FixtureError,
    GoldSpan,
    dump_document,
    file_sha256,
    from_markup,
    label,
    load_fixtures,
    parse_document,
    write_fixtures,
)
from pii_guard.eval.forms import (
    CODE_ENTITY_TYPES,
    LanguageForms,
    find_surface_forms,
    language_forms,
    register_language_forms,
    surface_pattern,
)
from pii_guard.eval.report import SCHEMA_VERSION, build_scorecard, git_commit, render_markdown
from pii_guard.eval.scorer import (
    DEFAULT_POLICY,
    EVAL_TENANT_KEY,
    Analyzer,
    DetectorAnalyzer,
    DocumentResult,
    EntityConsistency,
    TypeCounts,
    ValueLeak,
    consistency_report,
    leak_report,
    match_counts,
    over_masked,
    prf,
    run_documents,
    summarize,
)

__all__ = [
    "CODE_ENTITY_TYPES",
    "DEFAULT_POLICY",
    "EVAL_TENANT_KEY",
    "SCHEMA_VERSION",
    "Analyzer",
    "DetectorAnalyzer",
    "Document",
    "DocumentResult",
    "EntityConsistency",
    "FixtureError",
    "GoldSpan",
    "LanguageForms",
    "TypeCounts",
    "ValueLeak",
    "build_scorecard",
    "consistency_report",
    "dump_document",
    "file_sha256",
    "find_surface_forms",
    "from_markup",
    "git_commit",
    "label",
    "language_forms",
    "leak_report",
    "load_fixtures",
    "match_counts",
    "over_masked",
    "parse_document",
    "prf",
    "register_language_forms",
    "render_markdown",
    "run_documents",
    "summarize",
    "surface_pattern",
    "write_fixtures",
]
