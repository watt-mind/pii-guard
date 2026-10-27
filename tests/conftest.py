"""Shared fixtures. All test data is synthetic (ADR 0005)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.config import Settings, get_settings

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Isolate every test from the developer's environment and any local ``.env``."""
    for key in list(os.environ):
        if key.startswith("PII_GUARD_") or key == "META_API_KEY":
            monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


NER_AUTODETECT = "ner_autodetect"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{NER_AUTODETECT}: let build_mode_detectors add NER when the ner extra is installed "
        "(by default the suite pins the gateway base detectors to rules only)",
    )


@pytest.fixture(autouse=True)
def rules_only_mode_detectors(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Make implicit ``build_mode_detectors`` calls independent of the installed extras.

    Without ``base=``, ``build_mode_detectors`` adds ``ner`` whenever the ner extra is importable,
    so a venv synced with ``uv sync --extra ner`` would see different spans, detector lists and
    system keys than CI. Tests get rules only unless they pass ``base=`` themselves or are marked
    ``@pytest.mark.ner_autodetect`` to keep the real, environment-dependent selection.
    """
    if request.node.get_closest_marker(NER_AUTODETECT) is None:
        monkeypatch.setattr("pii_guard.gateway.detection._ner_available", lambda: False)


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c
