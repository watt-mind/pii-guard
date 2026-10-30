"""No unfilled metric placeholder reaches the public copy (LAB-1656).

Phase 1 of LAB-1656 rewrote the stale hand-typed copy with ``⟦...⟧`` placeholders where a
number has to come from the NER release's run records; this test fails until every one is
filled from a committed record, and keeps a stray placeholder from shipping later.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = [
    "README.md",
    "training/ner/model-card.md",
    *(str(p.relative_to(ROOT)) for p in sorted((ROOT / "docs").glob("*.md"))),
    *(str(p.relative_to(ROOT)) for p in sorted((ROOT / "ui/src").rglob("*.ts*"))),
]


@pytest.mark.parametrize("path", PUBLIC)
def test_no_unfilled_placeholder(path: str) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    left = [line.strip() for line in text.splitlines() if "⟦" in line]
    assert not left, f"{path}: {len(left)} unfilled ⟦…⟧ placeholder line(s), first: {left[0][:120]}"
