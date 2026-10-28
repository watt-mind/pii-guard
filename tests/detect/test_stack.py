"""One detector stack and one policy builder for the REST API and the gateway (LAB-1270)."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.detect import stack
from pii_guard.detect.stack import (
    NER_EXTRA_MISSING,
    CheckedDetector,
    build_detector,
    check_spans,
    default_detector_names,
    rest_detector_names,
)
from pii_guard.gateway import GatewayConfig, build_mode_detectors
from pii_guard.gateway.config import Mode
from pii_guard.gateway.detection import gateway_policies
from pii_guard.policy import Policy, PolicySet
from pii_guard.types import DetectionError, EntityType, Span

TEXT = "Teszt Elek ír."


class _NoLlm:
    name = "llm"
    model = "none"

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        return []


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "PII_GUARD_DETECTORS",
        "PII_GUARD_GATEWAY_KEEP_TYPES",
        "PII_GUARD_POLICY_OVERRIDES",
        "PII_GUARD_NER_MODEL",
        "PII_GUARD_NER_REVISION",
        "PII_GUARD_NER_DEVICE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(stack, "_warned_no_ner", False)


def _gateway_fast_names(settings: Settings) -> list[str]:
    fast = build_mode_detectors(settings, GatewayConfig(), llm_detector=_NoLlm())[Mode.FAST]
    return fast.config_id.removeprefix("fast:").split(";policies=")[0].split(";")


def _rest(settings: Settings) -> tuple[list[str], PolicySet]:
    app = create_app(settings)
    return app.state.detector_names, app.state.policies


@pytest.mark.parametrize(
    ("env", "rest_names", "gateway_names"),
    [
        ({}, ["rules"], ["rules"]),
        # An explicit PII_GUARD_DETECTORS wins for the REST API; the gateway keeps its stack.
        ({"PII_GUARD_DETECTORS": "rules,llm"}, ["rules", "llm"], ["rules"]),
        ({"PII_GUARD_GATEWAY_KEEP_TYPES": "PERSON"}, ["rules"], ["rules"]),
        (
            {"PII_GUARD_GATEWAY_KEEP_TYPES": "PERSON", "PII_GUARD_POLICY_OVERRIDES": "EMAIL=block"},
            ["rules"],
            ["rules"],
        ),
    ],
    ids=["default", "explicit-detectors", "deprecated-keep-types", "keep-types-and-overrides"],
)
def test_rest_and_gateway_share_the_stack_and_policies(
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    rest_names: list[str],
    gateway_names: list[str],
) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    settings = Settings()
    names, rest_policies = _rest(settings)
    assert names == rest_names
    assert _gateway_fast_names(settings) == gateway_names
    if "PII_GUARD_DETECTORS" not in env:
        assert names == _gateway_fast_names(settings)
    assert rest_policies == gateway_policies(settings, GatewayConfig())
    assert rest_policies == PolicySet.from_settings(settings)


def test_deprecated_keep_types_apply_to_the_rest_api_too(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_GATEWAY_KEEP_TYPES", "PERSON")
    settings = Settings()
    rest = PolicySet.from_settings(settings).of(EntityType.PERSON)
    gateway = gateway_policies(settings, GatewayConfig()).of(EntityType.PERSON)
    assert (rest, gateway) == (Policy.KEEP, Policy.KEEP)
    assert PolicySet.from_settings(settings).of(EntityType.ORGANIZATION) is Policy.MASK


def test_deprecated_keep_types_still_warn(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("PII_GUARD_GATEWAY_KEEP_TYPES", "PERSON")
    with caplog.at_level(logging.WARNING, logger="pii_guard.policy"):
        PolicySet.from_settings(Settings())
    assert "PII_GUARD_GATEWAY_KEEP_TYPES is deprecated" in caplog.text


def test_default_stack_adds_ner_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stack, "_ner_available", lambda: True)
    monkeypatch.setenv("PII_GUARD_NER_FALLBACK", "download")  # the default outside tests
    settings = Settings()
    assert default_detector_names(settings) == ("rules", "ner")
    assert rest_detector_names(settings) == ("rules", "ner")
    assert rest_detector_names(Settings(detectors="rules")) == ("rules",)


@pytest.mark.parametrize("where", ["stack", "rest", "gateway"])
def test_configured_but_missing_ner_fails_closed(
    monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    monkeypatch.setenv("PII_GUARD_NER_MODEL", "./models/fictional-ner")
    settings = Settings()
    with pytest.raises(DetectionError, match=NER_EXTRA_MISSING):
        if where == "stack":
            default_detector_names(settings)
        elif where == "rest":
            create_app(settings)
        else:
            build_mode_detectors(settings, GatewayConfig(), llm_detector=_NoLlm())


def test_unconfigured_missing_ner_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="pii_guard.detect.stack"):
        for _ in range(3):
            assert default_detector_names(Settings()) == ("rules",)
    assert [r.levelno for r in caplog.records].count(logging.WARNING) == 1
    assert "ner detector unavailable" in caplog.text


def test_ner_settings_reach_the_detector(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_create(name: str, **kwargs: Any) -> object:
        seen.update(name=name, **kwargs)
        return object()

    monkeypatch.setattr(stack, "create_detector", fake_create)
    monkeypatch.setenv("PII_GUARD_NER_MODEL", "./models/fictional-ner")
    monkeypatch.setenv("PII_GUARD_NER_REVISION", "abc123")
    monkeypatch.setenv("PII_GUARD_NER_DEVICE", "cpu")
    monkeypatch.setenv("PII_GUARD_NER_PUBLISHED_MODEL", "fictional/pii-guard-ner@abc")
    build_detector("ner", Settings())
    assert seen == {
        "name": "ner",
        "model": "./models/fictional-ner",
        "revision": "abc123",
        "device": "cpu",
        "published": "fictional/pii-guard-ner@abc",
        "fallback": "cached",
    }
    seen.clear()
    for name in ("REVISION", "DEVICE", "PUBLISHED_MODEL", "FALLBACK"):
        monkeypatch.delenv(f"PII_GUARD_NER_{name}")
    build_detector("ner", Settings())
    assert seen == {
        "name": "ner",
        "model": "./models/fictional-ner",
        "published": "watt-mind/pii-guard-ner-xlmr-base",
        "fallback": "download",
    }


def test_default_stack_without_a_resolvable_model_is_rules_only(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The extra is there but the fallback is off (or not cached): rules only, one warning."""
    monkeypatch.setattr(stack, "_ner_available", lambda: True)
    monkeypatch.setenv("PII_GUARD_NER_FALLBACK", "off")
    with caplog.at_level(logging.WARNING, logger="pii_guard.detect.stack"):
        assert default_detector_names(Settings()) == ("rules",)
    assert "PII_GUARD_NER_FALLBACK=off" in caplog.text
    monkeypatch.setenv("PII_GUARD_NER_FALLBACK", "cached")  # empty model cache (conftest)
    assert default_detector_names(Settings()) == ("rules",)
    monkeypatch.setenv("PII_GUARD_NER_MODEL", "./models/fictional-ner")
    assert default_detector_names(Settings()) == ("rules", "ner")


@pytest.mark.parametrize(
    "found",
    [
        {"not": "a list"},
        ["nope"],
        [Span(0, 4, EntityType.PERSON, "Elek", 0.9, "x")],
        [Span(10, 18, EntityType.PERSON, "Elek ír.", 0.9, "x")],
    ],
    ids=["not-a-list", "not-a-span", "wrong-offsets", "past-the-end"],
)
def test_check_spans_rejects_bad_output(found: object) -> None:
    with pytest.raises(DetectionError) as info:
        check_spans(found, TEXT, "x")
    assert "Teszt" not in str(info.value)


def test_checked_detector_hides_exception_text() -> None:
    class Boom:
        name = "boom"

        def detect(self, text: str, language: str = "hu") -> list[Span]:
            raise RuntimeError(f"cannot parse {text!r}")

    with pytest.raises(DetectionError) as info:
        CheckedDetector(Boom()).detect(TEXT)
    assert "Teszt" not in str(info.value)
    good = [Span(0, 10, EntityType.PERSON, "Teszt Elek", 0.9, "x")]
    assert check_spans(good, TEXT, "x") == good
