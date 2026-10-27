"""Exposure guards (LAB-1203): Host allow-list, loopback-only ``full`` log, optional API token.

All values are fictional (ADR 0005). Each test reproduces a finding of the 2026-10-27 review.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from gateway_helpers import TEST_TENANT_KEY, UPSTREAM_URL, MockUpstream, make_app

from pii_guard.api.app import create_app
from pii_guard.api.security import allowed_hosts
from pii_guard.config import Settings, get_settings
from pii_guard.observability import ObservabilitySettings, TrafficLogConfigError

FULL = ObservabilitySettings(traffic_log="full")
TOKEN = "test-api-token-not-a-secret"  # noqa: S105 - fictional
LAN_SERVER = "http://192.0.2.10:8787"  # TEST-NET-1: a non-loopback socket address
LAN_CLIENT = ("192.0.2.77", 50000)


# --- 1. DNS rebinding: the Host header -------------------------------------------------------


@pytest.mark.parametrize("host", ["attacker.example", "attacker.example:8787", "192.0.2.10"])
def test_foreign_host_header_is_refused(host: str) -> None:
    with TestClient(create_app(Settings(), FULL)) as client:
        response = client.get("/v1/traffic", headers={"Host": host})
    assert response.status_code == 400
    assert "level" not in response.text


@pytest.mark.parametrize(
    "host", ["localhost:5173", "localhost", "127.0.0.1:8787", "[::1]:8787", "LOCALHOST:4173"]
)
def test_loopback_host_headers_are_answered(host: str) -> None:
    # The UI's Vite proxy (changeOrigin) sends 127.0.0.1:<port>; a browser sends localhost:<port>.
    with TestClient(create_app(Settings(), FULL)) as client:
        response = client.get("/v1/traffic", headers={"Host": host})
    assert response.status_code == 200
    assert response.json()["level"] == "full"


def test_allowed_hosts_setting_and_configured_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_ALLOWED_HOSTS", "demo-api, gw.internal.test")
    settings = Settings(host="10.0.0.5")
    assert allowed_hosts(settings) == [
        "localhost",
        "127.0.0.1",
        "[::1]",
        "10.0.0.5",
        "demo-api",
        "gw.internal.test",
    ]
    with TestClient(create_app(settings)) as client:
        assert client.get("/healthz", headers={"Host": "demo-api:8787"}).status_code == 200
        assert client.get("/healthz", headers={"Host": "10.0.0.5"}).status_code == 200
        assert client.get("/healthz", headers={"Host": "other.test"}).status_code == 400


def test_wildcard_bind_is_not_an_allowed_host_and_star_allows_any() -> None:
    assert "0.0.0.0" not in allowed_hosts(Settings(host="0.0.0.0"))  # noqa: S104
    assert allowed_hosts(Settings(host="::1")) == ["localhost", "127.0.0.1", "[::1]"]
    settings = Settings(allowed_hosts="*")
    assert allowed_hosts(settings) == ["*"]
    with TestClient(create_app(settings)) as client:
        assert client.get("/healthz", headers={"Host": "anything.test"}).status_code == 200


@pytest.mark.parametrize("hosts", ["*", "demo-api", "localhost,gw.example"])
def test_full_refuses_non_loopback_allowed_hosts(hosts: str) -> None:
    with pytest.raises(TrafficLogConfigError, match="ALLOWED_HOSTS"):
        create_app(Settings(allowed_hosts=hosts), FULL)
    create_app(Settings(allowed_hosts="127.0.0.2,::1"), FULL)


# --- 2. full: the real socket, not the configured host ---------------------------------------


def test_full_refuses_a_connection_on_a_non_loopback_socket() -> None:
    # `uvicorn --factory pii_guard.api.app:create_app --host 0.0.0.0` with PII_GUARD_HOST unset:
    # the configured host is loopback, so startup passes; a LAN connection must still be refused,
    # even with a Host header that is allowed.
    app = create_app(Settings(), FULL)
    with TestClient(app, base_url=LAN_SERVER, client=LAN_CLIENT) as client:
        response = client.get("/v1/traffic", headers={"Host": "localhost"})
        stream = client.get("/v1/traffic/stream", headers={"Host": "localhost"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "traffic_log_not_local"
    assert stream.status_code == 403
    # A loopback client on a public socket (e.g. curl to the LAN IP from the same machine).
    with TestClient(app, base_url=LAN_SERVER, client=("127.0.0.1", 1)) as client:
        assert client.get("/v1/traffic", headers={"Host": "localhost"}).status_code == 403
    with TestClient(app) as client:  # loopback on both ends
        assert client.get("/v1/traffic").status_code == 200


def test_masked_is_served_on_a_non_loopback_socket() -> None:
    app = create_app(Settings(), ObservabilitySettings(traffic_log="masked"))
    with TestClient(app, base_url=LAN_SERVER, client=LAN_CLIENT) as client:
        response = client.get("/v1/traffic", headers={"Host": "localhost"})
    assert response.status_code == 200
    assert response.json()["level"] == "masked"


def test_serve_checks_the_cli_host_not_the_env_host(monkeypatch: pytest.MonkeyPatch) -> None:
    # PII_GUARD_HOST=0.0.0.0 + `serve --host 127.0.0.1` is a loopback server: the app built by
    # uvicorn's factory must not refuse it.
    from pii_guard import cli

    monkeypatch.setenv("PII_GUARD_HOST", "0.0.0.0")  # noqa: S104
    monkeypatch.setenv("PII_GUARD_TRAFFIC_LOG", "full")
    get_settings.cache_clear()
    apps = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: apps.append(create_app()))
    assert cli.main(["serve", "--host", "127.0.0.1"]) == 0
    assert apps[0].state.settings.host == "127.0.0.1"


# --- 3. optional bearer token ----------------------------------------------------------------


def _token_app(**settings: object) -> TestClient:
    return TestClient(create_app(Settings(api_token=TOKEN, **settings)))


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/v1/analyze"),
        ("post", "/v1/unmask"),
        ("get", "/v1/traffic"),
        ("get", "/metrics"),
        ("post", "/v1/chat/completions"),
    ],
)
def test_token_is_required_when_set(method: str, path: str) -> None:
    with _token_app() as client:
        response = client.request(method, path, json={})
        wrong = client.request(method, path, json={}, headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert wrong.status_code == 401
    assert TOKEN not in response.text


def test_token_accepted_as_bearer_or_header_and_healthz_stays_open() -> None:
    body = {"text": "Szia, Teszt Elek vagyok."}
    with _token_app() as client:
        assert client.get("/healthz").status_code == 200
        bearer = client.post("/v1/analyze", json=body, headers={"Authorization": f"Bearer {TOKEN}"})
        header = client.post("/v1/analyze", json=body, headers={"X-PII-Guard-Token": TOKEN})
    assert bearer.status_code == 200
    assert header.status_code == 200


def test_no_token_by_default() -> None:
    with TestClient(create_app(Settings())) as client:
        assert client.post("/v1/analyze", json={"text": "Szia!"}).status_code == 200


def _chat(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "user", "content": "Szia!"}]},
        headers=headers,
    )
    return response.status_code


def test_token_is_never_forwarded_upstream() -> None:
    # No PII_GUARD_UPSTREAM_API_KEY: the gateway passes the client's Authorization through
    # (bring your own key). A pii-guard token sent as the bearer must not reach the upstream.
    upstream = MockUpstream()
    settings = Settings(tenant_key=TEST_TENANT_KEY, upstream_base_url=UPSTREAM_URL, api_token=TOKEN)
    with TestClient(make_app(upstream, settings=settings)) as client:
        assert _chat(client, {"Authorization": f"Bearer {TOKEN}"}) == 200
        byok = {"Authorization": "Bearer client-own-key", "X-PII-Guard-Token": TOKEN}
        assert _chat(client, byok) == 200
    assert "authorization" not in upstream.requests[0].headers
    assert upstream.requests[1].headers["authorization"] == "Bearer client-own-key"
    assert all(TOKEN not in str(dict(r.headers)) for r in upstream.requests)


def test_public_bind_without_token_warns(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="pii_guard.api"):
        create_app(Settings(host="0.0.0.0"))  # noqa: S104
        create_app(Settings(host="127.0.0.1"))
        create_app(Settings(host="0.0.0.0", api_token=TOKEN))  # noqa: S104
    warnings = [r for r in caplog.records if "without authentication" in r.getMessage()]
    assert len(warnings) == 1
