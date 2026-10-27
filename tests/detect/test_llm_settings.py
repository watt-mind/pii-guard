"""Model resolution for ``LlmDetector``: ``model`` argument > ``Settings`` > ``DEFAULT_MODEL``."""

from __future__ import annotations

from pathlib import Path

import pytest

from pii_guard.config import Settings
from pii_guard.detect.llm import DEFAULT_MODEL, LlmDetector

ENV = "PII_GUARD_LLM_DETECTOR_MODEL"


def test_settings_default_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV, raising=False)
    assert Settings(_env_file=None).llm_detector_model is None


def test_settings_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV, "org/env-model")
    assert Settings(_env_file=None).llm_detector_model == "org/env-model"


def test_settings_reads_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(ENV, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(f"{ENV}=org/dotenv-model\n", encoding="utf-8")
    assert Settings(_env_file=env_file).llm_detector_model == "org/dotenv-model"


def test_detector_defaults_to_builtin_model() -> None:
    assert LlmDetector(settings=Settings(_env_file=None)).model == DEFAULT_MODEL


def test_detector_uses_settings_model() -> None:
    settings = Settings(_env_file=None, llm_detector_model="org/settings-model")
    assert LlmDetector(settings=settings).model == "org/settings-model"


def test_detector_argument_beats_settings() -> None:
    settings = Settings(_env_file=None, llm_detector_model="org/settings-model")
    assert LlmDetector(model="org/arg-model", settings=settings).model == "org/arg-model"
