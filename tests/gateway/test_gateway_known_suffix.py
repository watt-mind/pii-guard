"""A pre-loaded known value keeps its Hungarian suffix outside the placeholder (LAB-1182).

The known detector cuts ``Gyakorló Tihamérnak`` at the stem (``[[PERSON_x]]nak``). When the
session had already confirmed the inflected surface whole (a detector labelled it before the
value was pre-loaded), the gateway's widening step stretched the stem span over ``-nak`` again,
so the upstream saw ``[[PERSON_y]]`` without the case while ``/v1/mask`` kept it. All values
are fictional (ADR 0005); the upstream is a mock.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from gateway_helpers import FakeLlm, MockUpstream, make_app

from pii_guard.vault import PLACEHOLDER_RE

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

TEXT = "A ház kulcsait Gyakorló Tihamérnak kell átadni."
KNOWN = {"known_values": [{"value": "Gyakorló Tihamér", "entity_type": "PERSON"}]}


def echo(body: dict) -> str:
    return body["messages"][-1]["content"]


def chat(http: TestClient, session: str | None, messages: list[dict[str, str]]):
    headers = {"X-PII-Guard-Mode": "audit"}
    if session:
        headers["X-PII-Guard-Session"] = session
    return http.post(
        "/v1/chat/completions", json={"model": "m", "messages": messages}, headers=headers
    )


def stem_only(masked: str) -> str:
    """The placeholder of ``masked``, asserting it is followed by the suffix ``nak``."""
    token = PLACEHOLDER_RE.search(masked).group(0)
    assert masked == f"A ház kulcsait {token}nak kell átadni."
    return token


def test_known_value_keeps_its_suffix_through_the_gateway() -> None:
    upstream = MockUpstream(answer=echo)
    with TestClient(make_app(upstream, llm=FakeLlm(["Gyakorló Tihamérnak"]))) as http:
        session = http.post("/v1/sessions", json=KNOWN).json()["session_id"]
        response = chat(http, session, [{"role": "user", "content": TEXT}])
        mask = http.post("/v1/mask", json={"text": TEXT, "session_id": session, "language": "hu"})
    assert response.status_code == 200, response.text
    token = stem_only(upstream.bodies[-1]["messages"][-1]["content"])
    assert stem_only(mask.json()["masked_text"]) == token
    assert response.json()["choices"][0]["message"]["content"] == TEXT


def test_known_value_loaded_after_the_inflected_surface_was_confirmed() -> None:
    upstream = MockUpstream(answer=echo)
    with TestClient(make_app(upstream, llm=FakeLlm(["Gyakorló Tihamérnak"]))) as http:
        first = chat(http, None, [{"role": "user", "content": TEXT}])
        assert first.status_code == 200, first.text
        session = first.headers["x-pii-guard-session"]
        added = http.post(f"/v1/sessions/{session}/known-values", json=KNOWN)
        assert added.status_code == 200, added.text
        history = [
            {"role": "user", "content": TEXT},
            {"role": "assistant", "content": first.json()["choices"][0]["message"]["content"]},
            {"role": "user", "content": TEXT},
        ]
        second = chat(http, session, history)
        mask = http.post("/v1/mask", json={"text": TEXT, "session_id": session, "language": "hu"})
    assert second.status_code == 200, second.text
    sent = [m["content"] for m in upstream.bodies[-1]["messages"]]
    tokens = {stem_only(text) for text in sent}
    assert len(tokens) == 1  # one placeholder for the value in every message
    assert stem_only(mask.json()["masked_text"]) in tokens
    assert second.json()["choices"][0]["message"]["content"] == TEXT
