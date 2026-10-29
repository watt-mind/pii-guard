"""One upstream HTTP client per gateway (LAB-1176).

Building an ``httpx.AsyncClient`` costs ~4.5 ms of blocking TLS and proxy setup on the event
loop, so the gateway builds one, lazily, and shares it between ``/v1/chat/completions`` and
``/v1/responses``. Each call sets its own timeout, closes its own response (never the client),
and the app's lifespan closes the client on shutdown. Every value here is fictional (ADR 0005).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway_helpers import (
    TEST_TENANT_KEY,
    UPSTREAM_URL,
    MockUpstream,
    completion,
    conversation_turn_one,
    make_app,
)

from pii_guard.config import Settings
from pii_guard.gateway import Gateway, GatewayConfig
from pii_guard.gateway import service as gateway_service
from pii_guard.vault import Vault


class BothApis(MockUpstream):
    """Answers Chat Completions and the Responses API; records each request's timeout."""

    def __init__(self) -> None:
        super().__init__()
        self.timeouts: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.timeouts.append(request.extensions["timeout"])
        if request.url.path.endswith("/responses"):
            self.requests.append(request)
            output = [
                {
                    "type": "message",
                    "id": "msg_1",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Rendben."}],
                }
            ]
            return httpx.Response(
                200, json={"id": "resp_1", "object": "response", "output": output}
            )
        return super().handler(request)


@pytest.fixture
def constructed(monkeypatch: pytest.MonkeyPatch) -> list[httpx.AsyncClient]:
    """Every ``httpx.AsyncClient`` the gateway builds."""
    built: list[httpx.AsyncClient] = []

    class Counting(httpx.AsyncClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            built.append(self)

    monkeypatch.setattr(gateway_service.httpx, "AsyncClient", Counting)
    return built


def _chat(stream: bool = False) -> dict[str, Any]:
    return {"model": "test-model", "messages": conversation_turn_one(), "stream": stream}


def test_every_call_shares_one_client_and_shutdown_closes_it(
    constructed: list[httpx.AsyncClient],
) -> None:
    upstream = BothApis()
    app = make_app(upstream)
    with TestClient(app) as http:
        for _ in range(5):
            assert http.post("/v1/chat/completions", json=_chat()).status_code == 200
        for _ in range(3):
            response = http.post("/v1/chat/completions", json=_chat(stream=True))
            assert response.status_code == 200
            assert "data: [DONE]" in response.text
        for _ in range(3):
            response = http.post(
                "/v1/responses", json={"model": "test-model", "input": "Szia, Teszt Elek vagyok."}
            )
            assert response.status_code == 200, response.text
        upstream.status = 429
        assert http.post("/v1/chat/completions", json=_chat()).status_code == 429
        assert len(constructed) == 1
        assert not constructed[0].is_closed
    # 12 upstream calls used to build 12 clients; now one, closed by the app's lifespan.
    assert len(upstream.timeouts) == 12
    assert constructed[0].is_closed
    assert app.state.gateway._client is None


def test_the_upstream_timeout_is_set_per_request() -> None:
    upstream = BothApis()
    app = make_app(upstream, config=GatewayConfig(upstream_timeout=7.5))
    with TestClient(app) as http:
        assert http.post("/v1/chat/completions", json=_chat()).status_code == 200
        assert http.post("/v1/responses", json={"model": "m", "input": "Szia!"}).status_code == 200
    expected = {"connect": 10.0, "read": 7.5, "write": 7.5, "pool": 7.5}
    assert upstream.timeouts == [expected, expected]


def test_an_unreachable_upstream_does_not_close_the_shared_client(
    constructed: list[httpx.AsyncClient],
) -> None:
    upstream = MockUpstream()
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("connection refused", request=request)
        body = json.loads(request.content)
        return httpx.Response(200, json=completion("Rendben.", model=body["model"]))

    app = make_app(upstream)
    app.state.gateway_transport = httpx.MockTransport(flaky)
    with TestClient(app) as http:
        failed = http.post("/v1/chat/completions", json=_chat())
        assert failed.status_code == 502
        assert "connection refused" not in failed.text
        assert http.post("/v1/chat/completions", json=_chat()).status_code == 200
        assert len(constructed) == 1
        assert not constructed[0].is_closed


def _gateway(config: GatewayConfig | None = None) -> Gateway:
    settings = Settings(tenant_key=TEST_TENANT_KEY, upstream_base_url=UPSTREAM_URL)
    return Gateway(settings=settings, vault=Vault.from_settings(settings), config=config)


def test_pool_limits_come_from_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_GATEWAY_UPSTREAM_MAX_CONNECTIONS", "7")
    monkeypatch.setenv("PII_GUARD_GATEWAY_UPSTREAM_MAX_KEEPALIVE", "3")
    monkeypatch.setenv("PII_GUARD_GATEWAY_UPSTREAM_KEEPALIVE_EXPIRY", "12.5")
    gateway = _gateway(GatewayConfig())

    async def main() -> Any:
        client = gateway.upstream_client()
        assert gateway.upstream_client() is client
        pool = client._transport._pool  # type: ignore[attr-defined]
        await gateway.aclose()
        assert client.is_closed
        return pool

    pool = asyncio.run(main())
    assert pool._max_connections == 7
    assert pool._max_keepalive_connections == 3
    assert pool._keepalive_expiry == 12.5


def test_default_pool_keeps_connections_alive() -> None:
    config = GatewayConfig()
    assert config.upstream_max_connections == 100
    assert config.upstream_max_keepalive > 0
    assert config.upstream_keepalive_expiry > 0


def test_a_new_event_loop_gets_its_own_client() -> None:
    """Pooled connections belong to the loop that opened them."""
    gateway = _gateway()

    async def client() -> httpx.AsyncClient:
        return gateway.upstream_client()

    first = asyncio.run(client())
    second = asyncio.run(client())
    assert first is not second
    asyncio.run(gateway.aclose())
    asyncio.run(gateway.aclose())  # idempotent
