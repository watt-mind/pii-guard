"""The baseline contract and the runner that scores a baseline like pii-guard is scored."""

from __future__ import annotations

import os
import platform
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from pii_guard.eval.fixtures import Document
from pii_guard.eval.scorer import DocumentResult, summarize
from pii_guard.types import Span

__all__ = [
    "Baseline",
    "BaselineOutput",
    "BaselineUnavailable",
    "baseline_section",
    "host_info",
    "run_baseline",
]

_OBJECT = "￼"  # what the scorer substitutes for a pii-guard placeholder


class BaselineUnavailable(Exception):
    """The baseline can't run here (extra not installed, no ``uv``, worker failed to start)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class BaselineOutput:
    """One document through a baseline tool. ``masked_text`` is the tool's own output."""

    spans: tuple[Span, ...]
    masked_text: str
    restored_text: str | None
    detect_ms: float
    mask_ms: float
    unmapped: Counter[str] = field(default_factory=Counter)

    def __repr__(self) -> str:
        return f"BaselineOutput(spans={len(self.spans)}, unmapped={sum(self.unmapped.values())})"


class Baseline(Protocol):
    """A third-party tool wrapped for the harness.

    ``info`` holds tool versions, model names and the configuration used. ``reversible`` is
    False when the tool's default masking can't be undone (round trip is then reported as
    n/a). ``placeholder_re`` matches the tool's placeholders, which are blanked out before
    the leak search exactly like pii-guard's (``[REDACTED_EMAIL_ADDRESS_1]`` must not count
    as a surviving ``address`` token).
    """

    name: str
    info: dict[str, Any]
    reversible: bool
    placeholder_re: re.Pattern[str]

    def process(self, text: str, language: str) -> BaselineOutput: ...

    def close(self) -> object: ...


def run_baseline(
    documents: Iterable[Document], baseline: Baseline
) -> tuple[list[DocumentResult], Counter[str]]:
    """Run ``baseline`` over ``documents``: one :class:`DocumentResult` per document, plus
    the per-label count of unmapped spans (masked by the tool, not scored for P/R).

    Every span the tool reports is one it masked, so ``masked_spans`` is all of them, not
    only pii-guard's ``mask``-policy types. Leak rate is measured on the tool's own masked
    text. Errors propagate (a failing baseline fails the run, like a failing detector).
    """
    results: list[DocumentResult] = []
    unmapped: Counter[str] = Counter()
    for doc in documents:
        out = baseline.process(doc.text, doc.language)
        results.append(
            DocumentResult(
                document=doc,
                predicted=out.spans,
                masked_spans=out.spans,
                masked_text=baseline.placeholder_re.sub(_OBJECT, out.masked_text),
                roundtrip=out.restored_text == doc.text,
                detect_ms=out.detect_ms,
                mask_ms=out.mask_ms,
            )
        )
        unmapped.update(out.unmapped)
    return results, unmapped


def baseline_section(
    baseline: Baseline, results: Sequence[DocumentResult], unmapped: Counter[str]
) -> dict[str, Any]:
    """The scorecard block for one baseline: info, unmapped labels, overall and per language."""
    by_language: dict[str, list[DocumentResult]] = defaultdict(list)
    for r in results:
        by_language[r.document.language].append(r)
    return {
        "name": baseline.name,
        "info": baseline.info,
        "reversible": baseline.reversible,
        "unmapped_labels": dict(sorted(unmapped.items())),
        "overall": summarize(results),
        "languages": {lang: summarize(by_language[lang]) for lang in sorted(by_language)},
    }


def host_info() -> dict[str, Any]:
    """Where the latency numbers were measured."""
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "cpu_count": os.cpu_count(),
        "python": sys.version.split()[0],
    }
