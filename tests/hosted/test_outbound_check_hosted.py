"""The outbound re-check on the hosted service: guests and owners alike (LAB-1500).

Hosted requests go through the same :class:`~pii_guard.gateway.Gateway` as local ones, behind
the hosted middleware; a refusal must reach the client with its code and the
``X-PII-Guard-Outbound-Check`` header, and nothing may reach the upstream. All identities and
values are synthetic.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from test_boundary import EMAIL, ORIGIN, auth, boundary, chat

from pii_guard.gateway import Gateway
from pii_guard.gateway.request import TextSlot

__all__ = ["boundary"]  # the fixture, re-used

HEADER = "x-pii-guard-outbound-check"


@pytest.fixture
def leak(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """A masking fault: every text goes back as the client sent it."""

    def install() -> None:
        original = Gateway._write

        def faulty(slots: list[TextSlot], masked: list[str], *args: Any, **kwargs: Any) -> None:
            original(slots, masked, *args, **kwargs)
            for slot in slots:
                if slot.kind != "identifier":
                    slot.write(slot.text)

        monkeypatch.setattr(Gateway, "_write", staticmethod(faulty))

    return install


def test_owner_request_passes_with_the_header(
    boundary: tuple[TestClient, list[httpx.Request]],
) -> None:
    client, seen = boundary
    response = chat(client, auth())
    assert response.status_code == 200, response.text
    assert response.headers[HEADER] == "passed"
    assert len(seen) == 1 and EMAIL not in seen[0].content.decode()


def test_owner_request_is_blocked_before_the_upstream(
    boundary: tuple[TestClient, list[httpx.Request]], leak: Callable[[], None]
) -> None:
    client, seen = boundary
    leak()
    response = chat(client, auth())
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "outbound_check_failed"
    assert response.headers[HEADER] == "blocked"
    assert EMAIL not in response.text
    assert seen == []
    service = client.app.state.hosted
    assert service._ingress == service.quotas._active == 0


def test_guest_demo_is_checked_too(
    boundary: tuple[TestClient, list[httpx.Request]], leak: Callable[[], None]
) -> None:
    client, seen = boundary
    passed = client.post("/v1/demo", json={"sample_id": "en-support"}, headers={"origin": ORIGIN})
    assert passed.status_code == 200, passed.text
    assert len(seen) == 1
    leak()
    client.cookies.clear()
    blocked = client.post("/v1/demo", json={"sample_id": "en-support"}, headers={"origin": ORIGIN})
    assert blocked.status_code == 422, blocked.text
    assert blocked.json()["error"]["code"] == "outbound_check_failed"
    assert len(seen) == 1
