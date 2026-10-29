"""Signed-in console reads have their own allowance (LAB-1437); identities are synthetic.

The shared console (ADR 0013) loads more than ten owner-scoped GETs at once. They draw on a
read bucket, so a page load never answers 429, while work keeps the 10-request burst.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.hosted.abuse import AbuseAdmission
from pii_guard.hosted.quotas import QuotaLimits

ORIGIN = "https://guard.example"
INTERNAL = "https://synthetic-app.internal.example"


def auth(subject: str = "synthetic-reader") -> dict[str, str]:
    encoded = base64.b64encode(
        json.dumps({"auth_typ": "google", "claims": [{"typ": "sub", "val": subject}]}).encode()
    ).decode()
    return {"x-ms-client-principal": encoded, "origin": ORIGIN}


def settings(**overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        **{
            "hosted": True,
            "hosted_public_origin": ORIGIN,
            "hosted_trust_easy_auth": True,
            "hosted_single_process": True,
            "tenant_key": bytes(range(32)).hex(),
            "allowed_hosts": ("guard.example", "synthetic-app.internal.example"),
            "detectors": ("rules",),
            "ner_fallback": "off",
            **overrides,
        },
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(settings()), base_url=INTERNAL) as test_client:
        # A frozen clock: no refill, so every limit below is exact.
        test_client.app.state.hosted.abuse = AbuseAdmission(clock=lambda: 100.0)
        yield test_client


def test_thirty_rapid_signed_in_console_reads_all_succeed(client: TestClient) -> None:
    for index in range(30):
        path = "/v1/traffic" if index % 2 else "/v1/status"
        res = client.get(path, headers=auth())
        assert res.status_code == 200, (index, path, res.text)


def test_signed_in_work_is_still_limited_after_burst_ten(client: TestClient) -> None:
    for _ in range(30):
        assert client.get("/v1/traffic", headers=auth()).status_code == 200
    body = {"text": "Contact synthetic@example.com"}
    for index in range(10):
        res = client.post("/v1/analyze", json=body, headers=auth())
        assert res.status_code == 200, (index, res.text)
    denied = client.post("/v1/analyze", json=body, headers=auth())
    assert denied.status_code == 429
    assert denied.json()["error"]["code"] == "abuse_throttled"
    assert denied.headers["retry-after"] == "2"
    # Exhausted work leaves the console readable.
    assert client.get("/v1/status", headers=auth()).status_code == 200


def test_signed_in_reads_are_still_bounded(client: TestClient) -> None:
    # The daily request quota (100) is a separate ledger; lift it to reach the read burst.
    client.app.state.hosted.quotas.limits = QuotaLimits(user_requests=1000)
    for _ in range(120):
        assert client.get("/v1/traffic", headers=auth()).status_code == 200
    denied = client.get("/v1/traffic", headers=auth())
    assert denied.status_code == 429
    assert denied.headers["retry-after"] == "1"
    # Another owner has its own read allowance.
    assert client.get("/v1/traffic", headers=auth("synthetic-other")).status_code == 200


def test_anonymous_reads_are_unchanged(client: TestClient) -> None:
    origin = {"origin": ORIGIN}
    assert client.get("/v1/traffic", headers=origin).status_code == 401
    assert client.get("/v1/account", headers=origin).status_code == 200
    abuse = client.app.state.hosted.abuse
    assert not abuse._reads
    assert not abuse._principals
