"""Open-source comparison baselines for the evaluation harness. See ``docs/evaluation.md``.

``pii-guard eval --baselines presidio,llm-guard,privaite`` runs each tool over the same
fixtures as pii-guard, scores it with the same rules and adds it to the scorecard under
``baselines``. Each tool runs with its default configuration:

- ``presidio``: Microsoft Presidio analyzer + anonymizer, in-process
  (``uv sync --extra baselines``); spaCy ``en_core_web_lg`` / huSpaCy ``hu_core_news_lg``.
- ``llm-guard``: Protect AI LLM Guard ``Anonymize`` / ``Deanonymize`` with its ``Vault``.
- ``privaite``: PrivAiTe's PII engine with its shipped proxy config (``onnx`` preset).

LLM Guard and PrivAiTe can't share one environment (conflicting pins), so they run as worker
processes in their own pinned ``uv`` environments (:mod:`pii_guard.eval.baselines.worker`).
A baseline that can't start is skipped with a reason, like a detector that can't load.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any

from pii_guard.eval.baselines.base import (
    Baseline,
    BaselineOutput,
    BaselineUnavailable,
    baseline_section,
    host_info,
    run_baseline,
)
from pii_guard.eval.baselines.mapping import LABEL_MAP, map_label, to_spans
from pii_guard.eval.fixtures import Document

__all__ = [
    "BASELINES",
    "LABEL_MAP",
    "Baseline",
    "BaselineOutput",
    "BaselineUnavailable",
    "baseline_section",
    "create_baseline",
    "map_label",
    "render_comparison",
    "run_baseline",
    "run_baselines",
    "to_spans",
]


def render_comparison(scorecards: Sequence[dict[str, Any]]) -> str:
    """See :func:`pii_guard.eval.baselines.compare.render_comparison`."""
    # Imported lazily so ``python -m pii_guard.eval.baselines.compare`` runs cleanly.
    from pii_guard.eval.baselines.compare import render_comparison as render

    return render(scorecards)


def _presidio() -> Baseline:
    from pii_guard.eval.baselines.presidio import PresidioBaseline

    return PresidioBaseline()


def _llm_guard() -> Baseline:
    from pii_guard.eval.baselines.worker import llm_guard

    return llm_guard()


def _privaite() -> Baseline:
    from pii_guard.eval.baselines.worker import privaite

    return privaite()


BASELINES: dict[str, Callable[[], Baseline]] = {
    "presidio": _presidio,
    "llm-guard": _llm_guard,
    "privaite": _privaite,
}


def create_baseline(name: str) -> Baseline:
    """Start one baseline by name; :class:`BaselineUnavailable` if it can't run here."""
    try:
        factory = BASELINES[name]
    except KeyError:
        raise BaselineUnavailable(
            f"unknown baseline (known: {', '.join(sorted(BASELINES))})"
        ) from None
    return factory()


def run_baselines(
    documents: Iterable[Document],
    names: Sequence[str],
    *,
    factories: dict[str, Callable[[], Baseline]] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str]]]:
    """Run each named baseline over ``documents``, one at a time.

    Returns ``({name: scorecard section}, [(skipped name, reason)])``. A baseline that fails
    on a document raises (fail closed), after its worker has been shut down.
    """
    documents = list(documents)
    sections: dict[str, dict[str, Any]] = {}
    skipped: list[tuple[str, str]] = []
    for name in names:
        try:
            factory = (factories or {}).get(name)
            baseline = factory() if factory else create_baseline(name)
        except BaselineUnavailable as exc:
            skipped.append((name, exc.reason))
            continue
        try:
            results, unmapped = run_baseline(documents, baseline)
        finally:
            baseline.close()
        section = baseline_section(baseline, results, unmapped)
        section["info"] = {**section["info"], "host": host_info()}
        sections[name] = section
    return sections, skipped
