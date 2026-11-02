"""``scripts/ci/pii_in_diff.py``: the shared and the per-language allow-lists (LAB-1773)."""

from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "pii_in_diff.py"


@pytest.fixture
def module() -> dict[str, Any]:
    return runpy.run_path(str(SCRIPT))


def _point_at(module: dict[str, Any], shared: Path, directory: Path) -> None:
    # The functions read the paths from the namespace they were defined in.
    globals_ = module["load_allowlist"].__globals__
    globals_["ALLOWLIST"], globals_["ALLOWLIST_DIR"] = shared, directory


def test_the_per_language_lists_add_to_the_shared_one(
    module: dict[str, Any], tmp_path: Path
) -> None:
    shared = tmp_path / "pii-allowlist.txt"
    shared.write_text("# shared\n1234 5678  # fictional\n\n", encoding="utf-8")
    directory = tmp_path / "pii-allowlist.d"
    directory.mkdir()
    (directory / "fr.txt").write_text("# fr\nFR-76.30\n", encoding="utf-8")
    (directory / "README.md").write_text("4111111111111111\n", encoding="utf-8")  # not a list
    _point_at(module, shared, directory)
    assert module["load_allowlist"]() == {"12345678", "fr7630"}


def test_either_list_may_be_missing(module: dict[str, Any], tmp_path: Path) -> None:
    shared = tmp_path / "pii-allowlist.txt"
    _point_at(module, shared, tmp_path / "missing.d")
    assert module["load_allowlist"]() == set()
    shared.write_text("123456789\n", encoding="utf-8")
    assert module["load_allowlist"]() == {"123456789"}


def test_the_allow_lists_are_not_scanned(module: dict[str, Any]) -> None:
    scanned = module["scanned"]
    assert not scanned("scripts/ci/pii-allowlist.txt")
    assert not scanned("scripts/ci/pii-allowlist.d/fr.txt")
    assert scanned("scripts/ci/pii_in_diff.py")


def test_the_committed_lists_load(module: dict[str, Any]) -> None:
    assert "4111111111111111" in module["load_allowlist"]()
