"""Sticky vault sessions for clients without ``X-PII-Guard-Session`` (LAB-1286).

Resolution order: header, URL path (``/s/<session>/v1/...``), ``prompt_cache_key``, the
client's default session. Fictional values only (ADR 0005).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway_helpers import (
    TEST_TENANT_KEY,
    UPSTREAM_KEY,
    UPSTREAM_URL,
    FakeLlm,
    MockUpstream,
    conversation_turn_one,
    leaked_values,
    make_app,
)

from pii_guard.config import Settings
from pii_guard.gateway import InvalidChatRequestError, sessions
from pii_guard.gateway.sessions import (
    SESSION_RE,
    SessionSource,
    client_identity,
    resolve_session,
)
from pii_guard.vault import PLACEHOLDER_RE, SessionNotFoundError, Vault

KEY_A = bytes.fromhex(TEST_TENANT_KEY)
KEY_B = bytes(range(32))
BEARER_1 = {"authorization": "Bearer client-one-not-a-key"}
BEARER_2 = {"authorization": "Bearer client-two-not-a-key"}
GATEWAY_TOKEN = "gateway-token-not-a-key"  # noqa: S105 - a test token


# --- resolution order (unit) ---------------------------------------------------------------


def test_header_wins_and_stays_strict() -> None:
    vault = Vault(KEY_A)
    known = vault.session()
    headers = {"X-PII-Guard-Session": known.session_id, **BEARER_1}
    session, created, source = resolve_session(
        vault, headers, {"prompt_cache_key": "conv-1"}, "path-id"
    )
    assert (session, created, source) == (known, False, SessionSource.HEADER)
    # Unknown header id: still 404, even with a path session and a prompt_cache_key.
    with pytest.raises(SessionNotFoundError):
        resolve_session(vault, {"X-PII-Guard-Session": "s_gone"}, {"prompt_cache_key": "k"}, "p")
    with pytest.raises(InvalidChatRequestError):
        resolve_session(vault, {"X-PII-Guard-Session": "bad id!"}, {}, None)


def test_path_session_is_created_on_first_use_and_wins_over_the_cache_key() -> None:
    vault = Vault(KEY_A)
    first, created, source = resolve_session(
        vault, BEARER_1, {"prompt_cache_key": "conv-1"}, "client-chosen_1"
    )
    assert (first.session_id, created, source) == ("client-chosen_1", True, SessionSource.PATH)
    again, created, _ = resolve_session(vault, BEARER_2, {}, "client-chosen_1")
    assert again is first and not created
    with pytest.raises(InvalidChatRequestError):
        resolve_session(vault, {}, {}, "bad id!")


def test_prompt_cache_key_session_per_client_and_key() -> None:
    vault = Vault(KEY_A)

    def resolve(headers: dict[str, str], key: str) -> Any:
        return resolve_session(vault, headers, {"prompt_cache_key": key}, None)

    a, created, source = resolve(BEARER_1, "conv-1")
    assert created and source is SessionSource.PROMPT_CACHE_KEY
    assert SESSION_RE.match(a.session_id) and a.session_id.startswith("d_")
    assert resolve(BEARER_1, "conv-1")[:2] == (a, False)
    assert resolve(BEARER_1, "conv-2")[0] is not a  # another conversation
    assert resolve(BEARER_2, "conv-1")[0] is not a  # another client, same key
    assert "conv-1" not in a.session_id


MUSE_MAIN = "tbh:main:01a17f61-2bc6-7b91-b9e6-8198ed7af1bf"
MUSE_OBSERVERS = (
    "tbh:skill-reminder:01a17f61:f350a679:a8f4452d",
    "tbh:goal-reminder:01a17f61:cb6542df:ed07a9ef",
    "tbh:verify-reminder:01a17f61:ab8c6967:3508f1e3",
)


def test_muse_observer_keys_share_the_main_conversations_session() -> None:
    """LAB-1300: Muse's reminder observers send their own prompt_cache_key; they land in the
    session of the main key whose UUID starts with their 8-hex prefix."""
    vault = Vault(KEY_A)

    def resolve(headers: dict[str, str], key: str) -> Any:
        return resolve_session(vault, headers, {"prompt_cache_key": key}, None)

    main, created, source = resolve(BEARER_1, MUSE_MAIN)
    assert created and source is SessionSource.PROMPT_CACHE_KEY
    for key in MUSE_OBSERVERS:
        assert resolve(BEARER_1, key) == (main, False, SessionSource.PROMPT_CACHE_KEY)
    # Never across clients: another bearer's observer with the same prefix gets its own.
    other = resolve(BEARER_2, MUSE_OBSERVERS[0])[0]
    assert other is not main
    # A second conversation with the same prefix (UUIDv7: same ~65 s) keeps its own session;
    # observers follow the newest one.
    second = resolve(BEARER_1, "tbh:main:01a17f61-77b0-7d82-b7ef-857659db09bc")[0]
    assert second is not main
    assert resolve(BEARER_1, MUSE_OBSERVERS[0])[0] is second
    assert resolve(BEARER_1, MUSE_MAIN)[0] is main


def test_muse_main_key_takes_over_the_session_of_an_observer_that_came_first() -> None:
    """LAB-1341: Muse sends its first main turn and first observer at the same time; when the
    observer is resolved first, the main key joins its session instead of starting a second
    one (two sessions: one value under two placeholders within one task)."""
    vault = Vault(KEY_A)

    def resolve(key: str, headers: dict[str, str] = BEARER_1) -> Any:
        return resolve_session(vault, headers, {"prompt_cache_key": key}, None)

    first, created, source = resolve(MUSE_OBSERVERS[0])
    assert created and source is SessionSource.PROMPT_CACHE_KEY
    assert resolve(MUSE_OBSERVERS[1])[:2] == (first, False)  # another observer, same task
    assert resolve(MUSE_MAIN)[:2] == (first, False)  # the main key takes it over
    for key in (MUSE_MAIN, *MUSE_OBSERVERS):
        assert resolve(key)[0] is first
    # Never across clients: another bearer's main key with the same prefix gets its own.
    assert resolve(MUSE_MAIN, BEARER_2)[0] is not first
    # Only the first main key takes an observer's session over: a second conversation with
    # the same prefix keeps its own, and observers follow the newest main key, as before.
    second = resolve("tbh:main:01a17f61-77b0-7d82-b7ef-857659db09bc")[0]
    assert second is not first
    assert resolve(MUSE_OBSERVERS[0])[0] is second
    assert resolve(MUSE_MAIN)[0] is first
    # Look-alikes outside the grammar are ordinary keys.
    for key in ("tbh:main:01a17f61", "tbh:skill-reminder:01A17F61:x", "x:skill-reminder:01a17f61:"):
        assert resolve(key)[0] not in (first, second)


def test_muse_conversation_index_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sessions, "MAX_CONVERSATIONS", 2)
    vault = Vault(KEY_A)

    def resolve(key: str) -> Any:
        return resolve_session(vault, BEARER_1, {"prompt_cache_key": key}, None)[0]

    mains = [resolve(f"tbh:main:0000000{i}-2bc6-7b91-b9e6-8198ed7af1bf") for i in range(3)]
    observer = "tbh:skill-reminder:0000000{}:f350a679:a8f4452d"
    assert resolve(observer.format(0)) not in mains  # the oldest was forgotten
    assert resolve(observer.format(1)) is mains[1]
    assert resolve(observer.format(2)) is mains[2]


def test_default_session_per_client_identity() -> None:
    vault = Vault(KEY_A)
    one, created, source = resolve_session(vault, BEARER_1, {}, None)
    assert created and source is SessionSource.DEFAULT
    assert resolve_session(vault, BEARER_1, {"prompt_cache_key": ""}, None)[:3] == (
        one,
        False,
        SessionSource.DEFAULT,
    )
    two = resolve_session(vault, BEARER_2, {}, None)[0]
    anonymous = resolve_session(vault, {}, {}, None)[0]
    assert len({one.session_id, two.session_id, anonymous.session_id}) == 3
    assert client_identity({}) == "anonymous"
    assert client_identity(BEARER_1) != client_identity(BEARER_2)
    assert "client-one" not in client_identity(BEARER_1)


def test_derived_ids_differ_across_tenant_keys() -> None:
    a, b = Vault(KEY_A), Vault(KEY_B)
    for body in ({}, {"prompt_cache_key": "conv-1"}):
        id_a = resolve_session(a, BEARER_1, body, None)[0].session_id
        id_b = resolve_session(b, BEARER_1, body, None)[0].session_id
        assert id_a != id_b
    # Stable within a deployment: a restarted process with the same key derives the same ids.
    assert resolve_session(Vault(KEY_A), BEARER_1, {}, None)[0].session_id == (
        resolve_session(a, BEARER_1, {}, None)[0].session_id
    )


# --- the gateway (HTTP) --------------------------------------------------------------------


def chat(http: TestClient, path: str = "/v1/chat/completions", **headers: str) -> httpx.Response:
    return http.post(
        path, json={"model": "m", "messages": conversation_turn_one()}, headers=headers
    )


def test_path_url_session_is_sticky_and_reported() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        a = chat(http, "/s/my-laptop_1/v1/chat/completions")
        b = chat(http, "/s/my-laptop_1/v1/chat/completions")
        other = chat(http, "/s/another/v1/chat/completions")
    assert a.status_code == b.status_code == other.status_code == 200
    assert a.headers["x-pii-guard-session"] == b.headers["x-pii-guard-session"] == "my-laptop_1"
    assert a.headers["x-pii-guard-session-source"] == "path"
    assert b.headers["x-pii-guard-cache-misses"] == "0"
    first, second, third = upstream.bodies
    assert first["messages"] == second["messages"]
    assert first["messages"] != third["messages"]  # another session, other placeholders
    assert all(leaked_values(r.content) == [] for r in upstream.requests)


def test_path_url_errors() -> None:
    with TestClient(make_app(MockUpstream())) as http:
        bad = chat(http, "/s/bad.id/v1/chat/completions")
        assert bad.status_code == 400
        assert bad.json()["error"]["code"] == "invalid_request"
        assert chat(http, "/s/x/healthz").status_code == 404  # only /v1 and /muse-code
        # A header session still has to exist, whatever the path says.
        gone = chat(http, "/s/x/v1/chat/completions", **{"X-PII-Guard-Session": "s_gone"})
        assert gone.status_code == 404


def test_path_url_still_needs_the_api_token() -> None:
    settings = Settings(
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url=UPSTREAM_URL,
        upstream_api_key=UPSTREAM_KEY,
        api_token=GATEWAY_TOKEN,
    )
    with TestClient(make_app(MockUpstream(), settings=settings)) as http:
        assert chat(http, "/s/x/v1/chat/completions").status_code == 401
        ok = chat(http, "/s/x/v1/chat/completions", **{"X-PII-Guard-Token": GATEWAY_TOKEN})
        assert ok.status_code == 200 and ok.headers["x-pii-guard-session"] == "x"


def test_two_bearers_get_two_default_sessions() -> None:
    upstream = MockUpstream()
    settings = Settings(tenant_key=TEST_TENANT_KEY, upstream_base_url=UPSTREAM_URL)
    with TestClient(make_app(upstream, settings=settings)) as http:
        one = chat(http, Authorization="Bearer client-one-not-a-key")
        two = chat(http, Authorization="Bearer client-two-not-a-key")
        one_again = chat(http, Authorization="Bearer client-one-not-a-key")
    assert one.headers["x-pii-guard-session"] != two.headers["x-pii-guard-session"]
    assert one.headers["x-pii-guard-session"] == one_again.headers["x-pii-guard-session"]
    assert {r.headers["x-pii-guard-session-source"] for r in (one, two)} == {"default"}


def test_default_session_detects_system_prompt_and_tools_once() -> None:
    # LAB-1281: without a session header, the system prompt and the tool definitions are
    # served from the session's detection cache from the second request on.
    llm = FakeLlm()
    upstream = MockUpstream()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "send_mail",
                "description": "Send a mail. Escalations go to Minta Mária.",
                "parameters": {"type": "object", "properties": {"to": {"type": "string"}}},
            },
        }
    ]
    system = {"role": "system", "content": "Jogi asszisztens vagy. Az ügyfél neve Teszt Elek."}
    calls = []
    with TestClient(make_app(upstream, llm=llm)) as http:
        for turn, question in enumerate(("Első kérdés?", "Második kérdés?", "Harmadik?")):
            body = {
                "model": "m",
                "messages": [system, {"role": "user", "content": question}],
                "tools": tools,
            }
            r = http.post("/v1/chat/completions", json=body, headers={"X-PII-Guard-Mode": "strict"})
            assert r.status_code == 200
            if turn:
                assert r.headers["x-pii-guard-cache-misses"] == "1"  # only the new question
                assert int(r.headers["x-pii-guard-cache-hits"]) >= 2
            calls.append(llm.calls)
    assert calls[1] - calls[0] == calls[2] - calls[1] == 1  # then only the new question


# --- Responses API: prompt_cache_key, stable placeholders, restore across turns ----------------


class ResponsesUpstream:
    """Answers ``/responses`` with the placeholders it is told to repeat."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.say: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        text = "Noted: " + ", ".join(self.say)
        return httpx.Response(
            200,
            json={
                "id": f"resp_{len(self.bodies)}",
                "object": "response",
                "status": "completed",
                "model": body["model"],
                "output": [
                    {
                        "type": "message",
                        "id": "msg_1",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": text, "annotations": []}],
                    }
                ],
            },
        )


def responses_app(upstream: ResponsesUpstream) -> Any:
    app = make_app(MockUpstream())
    app.state.gateway_transport = httpx.MockTransport(upstream.handler)
    return app


def turn(http: TestClient, text: str, key: str | None, path: str = "/v1/responses") -> Any:
    body: dict[str, Any] = {
        "model": "muse-spark-1.3",
        "input": [{"type": "message", "role": "user", "content": text}],
        "store": False,
    }
    if key is not None:
        body["prompt_cache_key"] = key
    return http.post(path, json=body, headers={"Authorization": "Bearer muse-not-a-key"})


def test_prompt_cache_key_keeps_placeholders_and_restores_earlier_turns() -> None:
    upstream = ResponsesUpstream()
    with TestClient(responses_app(upstream)) as http:
        one = turn(http, "Mail teszt.elek@example.com about the refund.", "conv-1")
        placeholder = PLACEHOLDER_RE.search(json.dumps(upstream.bodies[0])).group(0)
        # Turn 2 doesn't carry the value; the model refers to the turn-1 placeholder.
        upstream.say = [placeholder]
        two = turn(http, "Draft the mail now.", "conv-1")
        three = turn(http, "Mail teszt.elek@example.com again.", "conv-1")
        other = turn(http, "Mail teszt.elek@example.com about the refund.", "conv-2")
    assert {r.status_code for r in (one, two, three, other)} == {200}
    assert {r.headers["x-pii-guard-session-source"] for r in (one, two)} == {"prompt_cache_key"}
    session = one.headers["x-pii-guard-session"]
    assert two.headers["x-pii-guard-session"] == three.headers["x-pii-guard-session"] == session
    assert other.headers["x-pii-guard-session"] != session
    answer = two.json()["output"][0]["content"][0]["text"]
    assert answer == "Noted: teszt.elek@example.com"  # restored from the earlier turn
    assert two.headers["x-pii-guard-unresolved"] == "0"
    assert placeholder in json.dumps(upstream.bodies[2])  # same value, same placeholder
    assert placeholder not in json.dumps(upstream.bodies[3])
    # The key itself is forwarded as sent (it is not personal data here).
    assert upstream.bodies[0]["prompt_cache_key"] == "conv-1"


def test_without_a_cache_key_responses_use_the_default_session() -> None:
    upstream = ResponsesUpstream()
    with TestClient(responses_app(upstream)) as http:
        one = turn(http, "Mail teszt.elek@example.com.", None)
        two = turn(http, "Mail teszt.elek@example.com.", None)
        path = turn(http, "Mail teszt.elek@example.com.", "conv-1", "/s/muse-box/v1/responses")
    assert one.headers["x-pii-guard-session"] == two.headers["x-pii-guard-session"]
    assert one.headers["x-pii-guard-session-source"] == "default"
    assert path.headers["x-pii-guard-session-source"] == "path"
    assert path.headers["x-pii-guard-session"] == "muse-box"


def test_full_session_rotates_to_a_new_generation() -> None:
    upstream = MockUpstream()
    settings = Settings(
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url=UPSTREAM_URL,
        upstream_api_key=UPSTREAM_KEY,
        vault_max_entries=2,
    )
    with TestClient(make_app(upstream, settings=settings)) as http:
        first = chat(http, "/s/box/v1/chat/completions")  # 4+ values: over the cap
        second = chat(http, "/s/box/v1/chat/completions")
        third = chat(http, "/s/box/v1/chat/completions")
    assert first.headers["x-pii-guard-session"] == "box"
    rotated = second.headers["x-pii-guard-session"]
    assert rotated != "box" and SESSION_RE.match(rotated)
    assert third.headers["x-pii-guard-session"] != rotated  # full again: the next generation
    assert {r.status_code for r in (first, second, third)} == {200}
    assert all(leaked_values(r.content) == [] for r in upstream.requests)
