"""LAB-1253: the example runs without relying on the conftest TestClient patch."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "which_parties_have_an_id.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("which_parties_demo", EXAMPLE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_example_runs_on_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    demo = _load_demo()
    monkeypatch.chdir(Path(__file__).resolve().parents[2])
    result = demo.run()
    assert result["score"]["correct"] == 3 and result["score"]["answered"] == 3


def test_example_uses_loopback_client() -> None:
    source = EXAMPLE.read_text(encoding="utf-8")
    assert 'base_url="http://127.0.0.1"' in source
