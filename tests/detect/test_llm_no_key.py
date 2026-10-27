"""No key, no request (LAB-1290): a keyless LLM detector never sends text anywhere.

Before LAB-1290 a detector without ``PII_GUARD_LLM_DETECTOR_API_KEY`` still POSTed the text to
the default endpoint (Baseten), unauthenticated, and only then failed on the 403. These tests
fail if any HTTP transport, injected or real, or any socket is touched. All text is fictional
(ADR 0005).
"""

from __future__ import annotations

import socket
from typing import Any

import httpx
import pytest

from pii_guard.config import Settings
from pii_guard.detect.llm import DEFAULT_BASE_URL, NO_KEY_MESSAGE, LlmDetector
from pii_guard.detect.pipeline import DetectionPipeline
from pii_guard.detect.rules import RuleDetector
from pii_guard.detect.stack import (
    CheckedDetector,
    DetectionUnavailableError,
    build_detector,
    unavailable_reason,
)
from pii_guard.types import DetectionError

TEXT = "Szia! Teszt Elek vagyok, e-mail: teszt.elek@example.com."  # fictional


class Tripwire:
    """Records every attempt to reach the network: the injected transport, httpx's real
    transports and raw sockets. A test passes only if :attr:`calls` stays empty."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[str] = []

        def sync_send(_self: Any, request: httpx.Request) -> httpx.Response:
            self.calls.append(f"HTTPTransport {request.url.host}")
            raise AssertionError("the HTTP transport must not be invoked")

        async def async_send(_self: Any, request: httpx.Request) -> httpx.Response:
            self.calls.append(f"AsyncHTTPTransport {request.url.host}")
            raise AssertionError("the HTTP transport must not be invoked")

        def connect(_self: Any, address: Any) -> None:
            self.calls.append(f"socket {address!r}")
            raise AssertionError("no socket may be opened")

        monkeypatch.setattr(httpx.HTTPTransport, "handle_request", sync_send)
        monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_send)
        monkeypatch.setattr(socket.socket, "connect", connect)

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.calls.append(f"MockTransport {request.url.host}")
            return httpx.Response(200, json={"choices": []})

        return httpx.MockTransport(handler)


@pytest.fixture
def tripwire(monkeypatch: pytest.MonkeyPatch) -> Tripwire:
    return Tripwire(monkeypatch)


def keyless(**kwargs: Any) -> LlmDetector:
    return LlmDetector(settings=Settings(_env_file=None), **kwargs)


def ok_completion(_: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": '{"entities": []}'}, "finish_reason": "stop"}]},
    )


# --- the detector ------------------------------------------------------------------------


def test_keyless_default_endpoint_refuses_without_touching_any_transport(
    tripwire: Tripwire,
) -> None:
    det = keyless(transport=tripwire.transport())
    assert det.url == DEFAULT_BASE_URL + "/chat/completions"
    with pytest.raises(DetectionUnavailableError) as excinfo:
        det.detect(TEXT)
    err = excinfo.value
    assert isinstance(err, DetectionError)  # everything that fails closed refuses this too
    assert (err.code, err.status_code) == ("detection_unavailable", 503)
    assert "audit mode needs PII_GUARD_LLM_DETECTOR_API_KEY" in err.message
    assert "Teszt" not in err.message
    assert tripwire.calls == []
    assert det.usage["requests"] == 0


def test_keyless_with_the_real_transport_opens_no_connection(tripwire: Tripwire) -> None:
    """No injected transport: httpx's own transport and sockets stay untouched."""
    with pytest.raises(DetectionUnavailableError):
        keyless().detect(TEXT)
    assert tripwire.calls == []


@pytest.mark.parametrize("text", ["", "   "])
def test_keyless_refuses_even_blank_text(tripwire: Tripwire, text: str) -> None:
    with pytest.raises(DetectionUnavailableError):
        keyless(transport=tripwire.transport()).detect(text)
    assert tripwire.calls == []


@pytest.mark.parametrize("key", ["", "   "])
def test_blank_key_counts_as_no_key(tripwire: Tripwire, key: str) -> None:
    with pytest.raises(DetectionUnavailableError):
        keyless(api_key=key, transport=tripwire.transport()).detect(TEXT)
    assert tripwire.calls == []


@pytest.mark.parametrize(
    "url",
    [
        "https://inference.baseten.co/v1",
        "https://vllm.internal/v1",
        "http://10.0.0.5:8000/v1",
        "http://localhost.example.com/v1",
        "http://127.0.0.1.example.com/v1",
    ],
)
def test_keyless_remote_endpoints_refuse(tripwire: Tripwire, url: str) -> None:
    det = keyless(base_url=url, transport=tripwire.transport())
    assert det.unavailable_reason == NO_KEY_MESSAGE
    with pytest.raises(DetectionUnavailableError):
        det.detect(TEXT)
    assert tripwire.calls == []


def test_the_client_itself_refuses_without_a_key(tripwire: Tripwire) -> None:
    """Every request goes through ``_client``: it refuses too, so no future caller (a
    challenge round, a validation pass) can build a keyless client."""
    with pytest.raises(DetectionUnavailableError):
        keyless(transport=tripwire.transport())._client()
    assert tripwire.calls == []


@pytest.mark.parametrize(
    "url", ["http://localhost:8000/v1", "http://127.0.0.1:8000/v1", "http://[::1]:8000/v1"]
)
def test_keyless_loopback_endpoint_is_allowed(url: str) -> None:
    """A self-hosted model on this machine: the text does not leave it, no key needed."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok_completion(request)

    det = keyless(base_url=url, transport=httpx.MockTransport(handler), challenge_empty=False)
    assert det.unavailable_reason is None
    assert det.detect(TEXT) == []
    assert len(seen) == 1
    assert "authorization" not in seen[0].headers


def test_keyed_detector_still_sends(tripwire: Tripwire) -> None:
    """Keyed audit mode is unchanged, and the tripwire really sees a request when one is made
    (so the empty ``calls`` above prove something)."""
    det = LlmDetector(
        api_key="test-key", transport=tripwire.transport(), settings=Settings(_env_file=None)
    )
    assert det.unavailable_reason is None
    with pytest.raises(DetectionError):  # the tripwire answers with no choices
        det.detect(TEXT)
    assert tripwire.calls and tripwire.calls[0].startswith("MockTransport")


def test_key_from_the_environment_makes_it_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_LLM_DETECTOR_API_KEY", "from-env")
    assert LlmDetector(settings=Settings(_env_file=None)).unavailable_reason is None


# --- through the stack and the pipeline --------------------------------------------------


def test_registry_built_llm_without_key_is_unavailable() -> None:
    det = build_detector("llm", Settings(_env_file=None))
    assert unavailable_reason([det]) == NO_KEY_MESSAGE
    assert unavailable_reason([CheckedDetector(det)]) == NO_KEY_MESSAGE  # wrappers looked through
    assert unavailable_reason([RuleDetector()]) is None


def test_pipeline_keeps_the_unavailable_error(tripwire: Tripwire) -> None:
    """Rules run, then the keyless LLM refuses: the pipeline keeps the specific error (not a
    generic detection_failed) and sends nothing."""
    llm = keyless(transport=tripwire.transport())
    pipeline = DetectionPipeline([CheckedDetector(RuleDetector()), CheckedDetector(llm)])
    with pytest.raises(DetectionUnavailableError):
        pipeline.detect(TEXT, "hu")
    assert tripwire.calls == []
