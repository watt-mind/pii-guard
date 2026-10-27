"""Import the training scripts (not a package) by path."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_script(relpath: str, name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def corpus_mod() -> types.ModuleType:
    return load_script("training/distill/corpus.py", "distill_corpus")


@pytest.fixture(scope="session")
def label_mod() -> types.ModuleType:
    return load_script("training/distill/label.py", "distill_label")
