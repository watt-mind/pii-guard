"""The real baseline tools. Skipped unless they are installed.

- Presidio: ``uv sync --extra baselines`` (in-process).
- LLM Guard and PrivAiTe: set ``PII_GUARD_BASELINE_WORKERS=1``; the first run builds their
  ``uv`` environments and downloads their models (a few GB), later runs reuse the caches.

All values are fictional (ADR 0005).
"""

from __future__ import annotations

import importlib.util
import os

import pytest

from pii_guard.eval.baselines import BaselineUnavailable, create_baseline
from pii_guard.types import EntityType

TEXT = (
    "Hi, I am Jane Doe, email jane.doe@example.com, phone +1 202 555 0143, "
    "IBAN GB82WEST12345698765432."
)


def _start(name: str):
    try:
        return create_baseline(name)
    except BaselineUnavailable as exc:
        pytest.skip(f"{name} unavailable: {exc.reason}")


@pytest.mark.skipif(
    importlib.util.find_spec("presidio_analyzer") is None,
    reason="presidio not installed (uv sync --extra baselines)",
)
def test_presidio_detects_and_masks() -> None:
    baseline = _start("presidio")
    try:
        out = baseline.process(TEXT, "en")
        types = {s.entity_type for s in out.spans}
        assert {EntityType.PERSON, EntityType.EMAIL, EntityType.BANK_ACCOUNT} <= types
        assert "jane.doe@example.com" not in out.masked_text
        assert "<EMAIL_ADDRESS>" in out.masked_text
        assert out.restored_text is None
        hu = baseline.process("Kovács Anna e-mail címe kovacs.anna@example.com.", "hu")
        assert EntityType.EMAIL in {s.entity_type for s in hu.spans}
    finally:
        baseline.close()


workers = pytest.mark.skipif(
    os.environ.get("PII_GUARD_BASELINE_WORKERS") != "1",
    reason="set PII_GUARD_BASELINE_WORKERS=1 to run the LLM Guard / PrivAiTe workers",
)


@workers
@pytest.mark.parametrize("name", ["llm-guard", "privaite"])
def test_worker_baselines_detect_mask_and_restore(name: str) -> None:
    baseline = _start(name)
    try:
        out = baseline.process(TEXT, "en")
        assert {EntityType.EMAIL, EntityType.BANK_ACCOUNT} <= {s.entity_type for s in out.spans}
        assert "jane.doe@example.com" not in out.masked_text
        assert out.restored_text == TEXT
        assert baseline.info["versions"]
    finally:
        baseline.close()
