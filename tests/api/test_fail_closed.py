"""Fail closed (ADR 0006): errors never return masked, partially masked or input text."""

from __future__ import annotations

import logging

import pytest
from api_helpers import FAKE_EMAIL, SAMPLE_TEXT, TEST_TENANT_KEY
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.api.deps import RegistryAnalyzer
from pii_guard.config import Settings
from pii_guard.registry import register_detector
from pii_guard.types import DetectionError, EntityType, Span


class _Boom:
    """Raises an unexpected exception that quotes its input."""

    name = "boom"

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        raise RuntimeError(f"cannot parse {text!r}")


class _Timeout:
    name = "timeout"

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        raise DetectionError("detector 'timeout' timed out")


class _Garbage:
    name = "garbage"

    def detect(self, text: str, language: str = "hu") -> object:
        return {"not": "a list"}


class _NotSpans:
    name = "notspans"

    def detect(self, text: str, language: str = "hu") -> list[object]:
        return ["nope"]


class _WrongOffsets:
    """Returns a span whose text does not match the request text."""

    name = "wrongoffsets"

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        return [Span(0, 4, EntityType.PERSON, "Elek", 0.9, self.name)]


class _Overlapping:
    """Overlapping spans in one detector; the analyzer must resolve them before masking."""

    name = "overlapping"

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        return [
            Span(0, 4, EntityType.PERSON, text[:4], 0.9, self.name),
            Span(2, 6, EntityType.PERSON, text[2:6], 0.9, self.name),
        ]


_DETECTORS = {
    "boom": _Boom,
    "timeout": _Timeout,
    "garbage": _Garbage,
    "notspans": _NotSpans,
    "wrongoffsets": _WrongOffsets,
    "overlapping": _Overlapping,
}


@pytest.fixture(scope="module", autouse=True)
def _register() -> None:
    for name, cls in _DETECTORS.items():
        register_detector(f"apitest_{name}", f"{__name__}:{cls.__name__}", replace=True)


def _client(*names: str) -> TestClient:
    app = create_app(Settings(tenant_key=TEST_TENANT_KEY))
    app.state.detector_names = ["rules", *(f"apitest_{n}" for n in names)]
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("detector", ["boom", "timeout", "garbage", "notspans", "wrongoffsets"])
@pytest.mark.parametrize("path", ["/v1/mask", "/v1/analyze"])
def test_detector_failure_blocks_the_request(
    detector: str, path: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    with _client(detector) as client:
        response = client.post(path, json={"text": SAMPLE_TEXT})
    assert response.status_code == 503
    assert set(response.json()) == {"error"}
    assert response.json()["error"]["code"] == "detection_failed"
    assert FAKE_EMAIL not in response.text
    assert "[[EMAIL_" not in response.text
    assert FAKE_EMAIL not in caplog.text


def test_overlapping_spans_are_resolved_before_masking() -> None:
    with _client("overlapping") as client:
        response = client.post("/v1/mask", json={"text": SAMPLE_TEXT})
    assert response.status_code == 200
    assert response.json()["masked_text"].startswith("[[PERSON_")


def test_masking_error_blocks_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    class Overlaps:
        def analyze(self, text: str, language: str) -> list[Span]:
            return [
                Span(0, 4, EntityType.PERSON, text[:4], 0.9, "x"),
                Span(2, 6, EntityType.PERSON, text[2:6], 0.9, "x"),
            ]

    app = create_app(Settings(tenant_key=TEST_TENANT_KEY))
    app.state.analyzer = Overlaps()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/v1/mask", json={"text": SAMPLE_TEXT})
    assert response.status_code == 500
    assert set(response.json()) == {"error"}
    assert response.json()["error"]["code"] == "masking_failed"
    assert FAKE_EMAIL not in response.text


def test_unexpected_error_is_opaque() -> None:
    class Crash:
        def analyze(self, text: str, language: str) -> list[Span]:
            raise RuntimeError(f"crash on {text}")

    app = create_app(Settings(tenant_key=TEST_TENANT_KEY))
    app.state.analyzer = Crash()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/v1/mask", json={"text": SAMPLE_TEXT})
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_error", "message": "internal error"}}


def test_registry_analyzer_wraps_unexpected_errors() -> None:
    analyzer = RegistryAnalyzer(["apitest_boom"])
    with pytest.raises(DetectionError) as exc:
        analyzer.analyze(SAMPLE_TEXT, "hu")
    assert FAKE_EMAIL not in str(exc.value)


# --- request size --------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/v1/analyze", "/v1/mask", "/v1/unmask"])
def test_oversized_text_is_413(path: str) -> None:
    app = create_app(Settings(tenant_key=TEST_TENANT_KEY))
    app.state.max_text_chars = 50
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(path, json={"text": "a" * 51, "session_id": "s_x"})
        ok = client.post("/v1/analyze", json={"text": "a" * 50})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert ok.status_code == 200


def test_oversized_body_is_rejected_before_parsing() -> None:
    app = create_app(Settings(tenant_key=TEST_TENANT_KEY))
    app.state.max_text_chars = 10
    with TestClient(app, raise_server_exceptions=False) as client:
        # Not even valid JSON: rejected on the declared size, never parsed.
        response = client.post(
            "/v1/mask",
            content=b"x" * 100_000,
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 413
    assert response.json()["error"] == {
        "code": "payload_too_large",
        "message": "request body is too large",
    }


def test_default_limit_accepts_ordinary_text(api: TestClient) -> None:
    response = api.post("/v1/mask", json={"text": SAMPLE_TEXT * 200})
    assert response.status_code == 200
