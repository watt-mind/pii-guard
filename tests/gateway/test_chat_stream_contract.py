"""LAB-1577: chat streaming requires SSE. All data is synthetic, upstream is local."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway_helpers import MockUpstream, completion, make_app, sse_body

from pii_guard.observability import Observability, ObservabilitySettings

CHAT = "/v1/chat/completions"
SENTINEL = "rejected-body-synthetic@example.com"


class TrackedBody(httpx.AsyncByteStream):
    def __init__(self, body: bytes, *, fail_close: bool = False) -> None:
        self.body = body
        self.read = False
        self.closed = False
        self.fail_close = fail_close

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.read = True
        yield self.body

    async def aclose(self) -> None:
        self.closed = True
        if self.fail_close:
            raise httpx.ReadError(SENTINEL)


def post(client: TestClient, stream: bool = True) -> httpx.Response:
    return client.post(
        CHAT,
        json={
            "model": "test-model",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": stream,
        },
    )


@pytest.mark.parametrize("content_type", [None, "application/json", "text/plain"])
@pytest.mark.parametrize("status", [200, 204])
@pytest.mark.parametrize("fail_close", [False, True])
def test_non_sse_stream_is_sanitized_and_closed(
    content_type: str | None, status: int, fail_close: bool, caplog: pytest.LogCaptureFixture
) -> None:
    body = TrackedBody(json.dumps(completion(SENTINEL)).encode(), fail_close=fail_close)
    app = make_app(MockUpstream())
    # Full recording must not capture a rejected upstream body either.
    app.state.observability = Observability(ObservabilitySettings(traffic_log="full"))
    app.state.gateway_transport = httpx.MockTransport(
        lambda _: httpx.Response(
            status, stream=body, headers={"content-type": content_type} if content_type else {}
        )
    )
    with TestClient(app) as client:
        response = post(client)
        assert response.status_code == 502
        assert response.json() == {
            "error": {
                "code": "upstream_did_not_stream",
                "message": "upstream did not return an event stream; retry without stream",
            }
        }
        assert response.headers["content-type"].startswith("application/json")
        assert body.closed and not body.read
        assert app.state.gateway._session_holds == {}
        (event,) = client.get("/v1/traffic").json()["events"]
        assert event["outcome"] == "upstream_failed"  # forwarded, not refused (LAB-1629)
        assert event["error"]["code"] == "upstream_did_not_stream"
        assert event["upstream"]["status"] == status
        assert SENTINEL not in json.dumps(event)
    assert SENTINEL not in response.text + caplog.text


@pytest.mark.parametrize("stream", [False, True])
def test_success_contracts_remain_supported(stream: bool) -> None:
    payload = (
        sse_body(["synthetic answer"])
        if stream
        else json.dumps(completion("synthetic answer")).encode()
    )
    body = TrackedBody(payload)
    app = make_app(MockUpstream())
    app.state.gateway_transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            stream=body,
            headers={
                "content-type": "text/event-stream; charset=utf-8" if stream else "application/json"
            },
        )
    )
    with TestClient(app) as client:
        response = post(client, stream)
        assert response.status_code == 200
        if stream:
            assert response.headers["content-type"].startswith("text/event-stream")
            assert "data: [DONE]" in response.text
        else:
            assert response.json()["choices"][0]["message"]["content"] == "synthetic answer"
        assert body.read and body.closed
        assert app.state.gateway._session_holds == {}


@pytest.mark.parametrize("status", [400, 429, 503])
@pytest.mark.parametrize("stream", [False, True])
def test_http_errors_keep_status_and_sanitization(status: int, stream: bool) -> None:
    body = TrackedBody(
        json.dumps(
            {
                "error": {
                    "message": SENTINEL,
                    "type": "invalid_request_error",
                    "code": "synthetic_error",
                }
            }
        ).encode()
    )
    app = make_app(MockUpstream())
    app.state.gateway_transport = httpx.MockTransport(
        lambda _: httpx.Response(status, stream=body, headers={"content-type": "application/json"})
    )
    with TestClient(app) as client:
        response = post(client, stream)
        assert response.status_code == status
        assert response.json()["error"] == {
            "code": "upstream_error",
            "message": f"upstream returned HTTP {status}",
            "type": "upstream_error",
            "upstream_type": "invalid_request_error",
            "upstream_code": "synthetic_error",
        }
        assert body.read and body.closed
        assert app.state.gateway._session_holds == {}
    assert SENTINEL not in response.text
