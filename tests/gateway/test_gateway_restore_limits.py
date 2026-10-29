"""Gateway: case-sensitive secrets and the per-response restore limit (LAB-1350).

Every value is fictional (ADR 0005); the tokens are built at runtime. The mock upstream
answers with the placeholders it received, repeated as a test needs.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from gateway_helpers import (
    TEST_TENANT_KEY,
    UPSTREAM_KEY,
    UPSTREAM_URL,
    MockUpstream,
    make_app,
)

from pii_guard.config import Settings
from pii_guard.gateway.responses_restore import ResponsesSseRestorer
from pii_guard.types import EntityType, Span
from pii_guard.vault import PLACEHOLDER_RE, UnmaskOutputTooLargeError, Vault

_PREFIX = "gh" + "p_"
TOKEN_A = _PREFIX + "AbCdEfGhIjKlMnOpQrStUvWxYz" + "0123456789"
TOKEN_B = _PREFIX + "aBcDeFgHiJkLmNoPqRsTuVwXyZ" + "0123456789"


def _settings(**extra: Any) -> Settings:
    return Settings(
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url=UPSTREAM_URL,
        upstream_api_key=UPSTREAM_KEY,
        **extra,
    )


def _echo(times: int) -> Any:
    def answer(body: dict[str, Any]) -> str:
        sent = body["messages"][-1]["content"]
        tokens = [m.group(0) for m in PLACEHOLDER_RE.finditer(sent)]
        return " ".join(tokens * times)

    return answer


def _messages() -> list[dict[str, str]]:
    return [{"role": "user", "content": f"first {TOKEN_A} second {TOKEN_B}"}]


def test_tokens_that_differ_only_in_case_round_trip_through_the_gateway() -> None:
    upstream = MockUpstream(answer=_echo(1))
    with TestClient(make_app(upstream, settings=_settings()), raise_server_exceptions=False) as c:
        response = c.post("/v1/chat/completions", json={"model": "m", "messages": _messages()})
    assert response.status_code == 200, response.text
    sent = upstream.requests[0].content.decode()
    assert TOKEN_A not in sent and TOKEN_B not in sent
    placeholders = list(dict.fromkeys(m.group(0) for m in PLACEHOLDER_RE.finditer(sent)))
    assert len(placeholders) == 2
    assert response.json()["choices"][0]["message"]["content"] == f"{TOKEN_A} {TOKEN_B}"


def test_response_over_the_restore_limit_is_413() -> None:
    upstream = MockUpstream(answer=_echo(20))
    app = make_app(upstream, settings=_settings(unmask_max_restored_chars=400))
    with TestClient(app, raise_server_exceptions=False) as c:
        response = c.post("/v1/chat/completions", json={"model": "m", "messages": _messages()})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "unmask_output_too_large"
    assert TOKEN_A not in response.text and TOKEN_B not in response.text


def test_response_under_the_restore_limit_is_restored() -> None:
    upstream = MockUpstream(answer=_echo(4))
    app = make_app(upstream, settings=_settings(unmask_max_restored_chars=400))
    with TestClient(app, raise_server_exceptions=False) as c:
        response = c.post("/v1/chat/completions", json={"model": "m", "messages": _messages()})
    assert response.status_code == 200, response.text
    content = response.json()["choices"][0]["message"]["content"]
    assert content.count(TOKEN_A) == 4 and content.count(TOKEN_B) == 4


def test_stream_over_the_restore_limit_ends_with_an_error_event() -> None:
    upstream = MockUpstream(answer=_echo(20), stream_chunks=lambda a: a.split(" "))
    app = make_app(upstream, settings=_settings(unmask_max_restored_chars=400))
    with TestClient(app, raise_server_exceptions=False) as c:
        response = c.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": _messages(), "stream": True},
        )
    events = [
        json.loads(line[len("data: ") :])
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    assert events[-1]["error"]["code"] == "unmask_output_too_large"
    restored = "".join(
        choice["delta"].get("content") or ""
        for event in events
        for choice in event.get("choices", [])
    )
    assert len(restored) <= 400 + len(" ") * 40
    assert restored.count(TOKEN_A) + restored.count(TOKEN_B) <= 400 // len(TOKEN_A)


def test_responses_stream_shares_one_budget_across_its_deltas() -> None:
    """Responses API streaming: every delta stream of a response draws on one budget."""
    session = Vault(bytes.fromhex(TEST_TENANT_KEY), max_restored_chars=200).session()
    text = f"k {TOKEN_A}"
    span = Span(2, len(text), EntityType.SECRET, TOKEN_A, 1.0, "test")
    placeholder = session.mask(text, [span])[2:]
    restorer = ResponsesSseRestorer(session)

    def delta(index: int) -> str:
        return json.dumps(
            {
                "type": "response.output_text.delta",
                "output_index": index,
                "content_index": 0,
                "delta": placeholder + " ",
            }
        )

    with pytest.raises(UnmaskOutputTooLargeError):
        for index in range(10):  # a new stream per output index, one shared budget
            restorer.process("response.output_text.delta", delta(index))
