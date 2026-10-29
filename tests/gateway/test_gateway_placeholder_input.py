"""Gateway: a placeholder issued earlier in the session is refused in a later message (LAB-1092)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from gateway_helpers import MockUpstream, conversation_turn_one, make_app

from pii_guard.vault import PLACEHOLDER_RE


def test_issued_placeholder_in_a_later_message_is_422() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream), raise_server_exceptions=False) as http:
        first = http.post(
            "/v1/chat/completions", json={"model": "m", "messages": conversation_turn_one()}
        )
        assert first.status_code == 200, first.text
        session = first.headers["x-pii-guard-session"]
        sent = upstream.requests[0].content.decode()
        token = PLACEHOLDER_RE.search(sent)
        assert token is not None
        response = http.post(
            "/v1/chat/completions",
            headers={"X-PII-Guard-Session": session},
            json={
                "model": "m",
                "messages": [{"role": "user", "content": f"Mi az a {token.group(0)}?"}],
            },
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "placeholder_in_input"
    assert token.group(0) not in response.text
    assert len(upstream.requests) == 1  # nothing forwarded for the refused request
