"""Browser mutations cannot spend a local gateway's provider key (LAB-1757)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.gateway.config import GatewayConfig, Mode

ORIGIN = "http://127.0.0.1:8787"
TOKEN = "fixture-guard-token"  # noqa: S105 - synthetic
PATHS = (
    "/v1/chat/completions",
    "/v1/responses",
    "/v1/messages",
    "/v1/messages/count_tokens",
)


def body_for(path: str) -> dict[str, Any]:
    body: dict[str, Any] = {"model": "fixture-model"}
    if path.endswith("/responses"):
        body["input"] = "Hello"
    else:
        body["messages"] = [{"role": "user", "content": "Hello"}]
        if "/messages" in path:
            body["max_tokens"] = 16
    return body


def form_body(path: str) -> bytes:
    # A text/plain form serializes name + '=' + value + CRLF. Put its separator inside a
    # supported string field, so the body is valid JSON without any attacker-added header.
    body = body_for(path)
    field = "metadata" if "/messages" in path else "user"
    body[field] = {"user_id": "="} if field == "metadata" else "="
    return (json.dumps(body) + "\r\n").encode()


async def request(
    path: str,
    content: bytes,
    headers: list[tuple[str, str]],
    *,
    token: str | None = None,
) -> tuple[httpx.Response, int, bool]:
    outbound: list[httpx.Request] = []

    def upstream(sent: httpx.Request) -> httpx.Response:
        outbound.append(sent)
        if sent.url.path.endswith("/responses"):
            data: dict[str, Any] = {"id": "resp_fixture", "object": "response", "output": []}
        elif sent.url.path.endswith("/count_tokens"):
            data = {"input_tokens": 1}
        elif sent.url.path.endswith("/messages"):
            data = {
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "Hello"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        else:
            data = {
                "id": "chat_fixture",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hello"},
                        "finish_reason": "stop",
                    }
                ],
            }
        return httpx.Response(200, json=data)

    app = create_app(
        Settings(
            detectors=("rules",),
            ner_fallback="off",
            tenant_key="11" * 32,
            api_token=token,
            upstream_base_url="https://upstream.test/v1",
            upstream_api_key="fixture-provider-key",
        )
    )
    app.state.gateway_config = GatewayConfig(mode=Mode.FAST)
    app.state.gateway_transport = httpx.MockTransport(upstream)
    # No lifespan: no model warmup. Only the actual rules detector runs for accepted calls.
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 30000)), base_url=ORIGIN
        ) as client:
            response = await client.post(path, content=content, headers=headers)
        return response, len(outbound), getattr(app.state, "gateway", None) is not None
    finally:
        gateway = getattr(app.state, "gateway", None)
        if gateway is not None:
            await gateway.aclose()


@pytest.mark.parametrize("canonical", PATHS)
@pytest.mark.parametrize("prefix", ("", "/s/fixture", "/e/fixture"))
def test_foreign_forms_rejected_before_gateway(canonical: str, prefix: str) -> None:
    response, calls, initialized = asyncio.run(
        request(
            prefix + canonical,
            form_body(canonical),
            [
                ("origin", "https://attacker.example"),
                ("sec-fetch-site", "cross-site"),
                ("content-type", "text/plain"),
            ],
        )
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "cross_origin_request_denied"
    assert "attacker.example" not in response.text
    assert calls == 0
    assert not initialized


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("prefix", ("", "/s/fixture", "/e/fixture"))
@pytest.mark.parametrize(
    "media", ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data")
)
def test_explicit_non_json_gateway_requests_rejected(path: str, prefix: str, media: str) -> None:
    response, calls, initialized = asyncio.run(
        request(prefix + path, form_body(path), [("content-type", media)])
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
    assert calls == 0
    assert not initialized


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("prefix", ("", "/s/fixture"))
@pytest.mark.parametrize("browser", (False, True))
def test_sdk_and_same_origin_browser_requests_work(path: str, prefix: str, browser: bool) -> None:
    headers = (
        [
            ("origin", ORIGIN),
            ("sec-fetch-site", "same-origin"),
            ("content-type", "application/json"),
        ]
        if browser
        else []  # Compatibility with SDKs that omit Content-Type and browser headers.
    )
    response, calls, _ = asyncio.run(
        request(prefix + path, json.dumps(body_for(path)).encode(), headers)
    )
    assert response.status_code == 200
    assert calls == 1


@pytest.mark.parametrize(
    "headers",
    [
        [("origin", "null")],
        [("origin", ORIGIN), ("origin", "https://attacker.example")],
        [("sec-fetch-site", "cross-site")],
        [("sec-fetch-site", "same-site")],
        [("sec-fetch-site", "same-origin"), ("sec-fetch-site", "cross-site")],
        [("origin", "https://127.0.0.1:8787")],
    ],
)
def test_browser_header_ambiguity_is_refused(headers: list[tuple[str, str]]) -> None:
    response, calls, initialized = asyncio.run(
        request(PATHS[0], json.dumps(body_for(PATHS[0])).encode(), headers)
    )
    assert response.status_code == 403
    assert calls == 0
    assert not initialized


@pytest.mark.parametrize("authenticated", (False, True))
def test_token_still_required_for_same_origin_requests(authenticated: bool) -> None:
    headers = [("origin", ORIGIN), ("content-type", "application/vnd.fixture+json")]
    if authenticated:
        headers.append(("authorization", "Bearer " + TOKEN))
    response, calls, _ = asyncio.run(
        request(PATHS[0], json.dumps(body_for(PATHS[0])).encode(), headers, token=TOKEN)
    )
    assert response.status_code == (200 if authenticated else 401)
    assert calls == int(authenticated)
    assert TOKEN not in response.text


def test_token_does_not_bypass_foreign_browser_check() -> None:
    response, calls, initialized = asyncio.run(
        request(
            PATHS[0],
            form_body(PATHS[0]),
            [("origin", "https://attacker.example"), ("authorization", "Bearer " + TOKEN)],
            token=TOKEN,
        )
    )
    assert response.status_code == 403
    assert calls == 0
    assert not initialized
    assert TOKEN not in response.text


def test_ambiguous_gateway_media_type_is_refused() -> None:
    response, calls, initialized = asyncio.run(
        request(
            PATHS[0],
            form_body(PATHS[0]),
            [("content-type", "application/json"), ("content-type", "text/plain")],
        )
    )
    assert response.status_code == 415
    assert calls == 0
    assert not initialized
