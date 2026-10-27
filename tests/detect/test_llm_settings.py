"""Model resolution for ``LlmDetector``: ``model`` argument > ``Settings`` > ``DEFAULT_MODEL``."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from pii_guard.api.deps import build_detector
from pii_guard.config import Settings
from pii_guard.detect.llm import DEFAULT_MODEL, LlmDetector
from pii_guard.registry import create_detector

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


# -- reasoning effort, max tokens, timeout --

LIMIT_ENVS = {
    "PII_GUARD_LLM_DETECTOR_REASONING_EFFORT": "llm_detector_reasoning_effort",
    "PII_GUARD_LLM_DETECTOR_MAX_TOKENS": "llm_detector_max_tokens",
    "PII_GUARD_LLM_DETECTOR_TIMEOUT": "llm_detector_timeout",
}


@pytest.fixture(autouse=True)
def _clean_limit_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in LIMIT_ENVS:
        monkeypatch.delenv(name, raising=False)


def _payload(detector: LlmDetector) -> dict[str, object]:
    return detector._payload("Kiss Béla", "hu")


def test_limits_default_to_none_and_builtins() -> None:
    settings = Settings(_env_file=None)
    assert settings.llm_detector_reasoning_effort is None
    assert settings.llm_detector_max_tokens is None
    assert settings.llm_detector_timeout is None
    detector = LlmDetector(settings=settings)
    assert detector.timeout == 60.0
    assert detector.max_tokens == 4096
    assert detector.reasoning_effort is None
    payload = _payload(detector)
    assert payload["max_tokens"] == 4096
    assert "reasoning_effort" not in payload


def test_limits_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_LLM_DETECTOR_REASONING_EFFORT", "low")
    monkeypatch.setenv("PII_GUARD_LLM_DETECTOR_MAX_TOKENS", "8192")
    monkeypatch.setenv("PII_GUARD_LLM_DETECTOR_TIMEOUT", "120")
    detector = LlmDetector(settings=Settings(_env_file=None))
    assert detector.timeout == 120.0
    assert detector._client().timeout == httpx.Timeout(120.0)
    payload = _payload(detector)
    assert payload["max_tokens"] == 8192
    assert payload["reasoning_effort"] == "low"


def test_limits_read_from_dotenv(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "PII_GUARD_LLM_DETECTOR_MAX_TOKENS=2048\nPII_GUARD_LLM_DETECTOR_TIMEOUT=30.5\n",
        encoding="utf-8",
    )
    settings = Settings(_env_file=env_file)
    assert (settings.llm_detector_max_tokens, settings.llm_detector_timeout) == (2048, 30.5)


def test_limit_arguments_beat_settings() -> None:
    settings = Settings(
        _env_file=None,
        llm_detector_reasoning_effort="low",
        llm_detector_max_tokens=8192,
        llm_detector_timeout=120,
    )
    detector = LlmDetector(
        settings=settings, reasoning_effort="minimal", max_tokens=1000, timeout=5.0
    )
    assert (detector.reasoning_effort, detector.max_tokens, detector.timeout) == (
        "minimal",
        1000,
        5.0,
    )


def test_explicit_none_max_tokens_omits_field() -> None:
    settings = Settings(_env_file=None, llm_detector_max_tokens=8192)
    assert "max_tokens" not in _payload(LlmDetector(settings=settings, max_tokens=None))


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PII_GUARD_LLM_DETECTOR_MAX_TOKENS", "10"),
        ("PII_GUARD_LLM_DETECTOR_MAX_TOKENS", "lots"),
        ("PII_GUARD_LLM_DETECTOR_TIMEOUT", "0"),
        ("PII_GUARD_LLM_DETECTOR_TIMEOUT", "soon"),
    ],
)
def test_invalid_limits_name_the_variable(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError) as info:
        Settings(_env_file=None)
    assert LIMIT_ENVS[name] in str(info.value) or name.lower() in str(info.value).lower()


def test_effort_reaches_registry_and_api_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_LLM_DETECTOR_REASONING_EFFORT", "low")
    settings = Settings(_env_file=None)
    for built in (create_detector("llm", settings=settings), build_detector("llm", settings)):
        assert isinstance(built, LlmDetector)
        assert _payload(built)["reasoning_effort"] == "low"
