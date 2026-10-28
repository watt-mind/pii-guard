"""The vault inspector, ``/v1/vault/sessions*`` (LAB-1328).

``masked`` (the default) never returns an original value or form; ``full`` reveals them on
demand, loopback only, like ``PII_GUARD_TRAFFIC_LOG=full`` (``tests/gateway/test_api_exposure.py``).
All values are fictional (ADR 0005).
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from api_helpers import TEST_TENANT_KEY
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.api.routes.vault import VaultInspectConfigError, hint
from pii_guard.config import Settings
from pii_guard.observability import TrafficLevel
from pii_guard.types import EntityType, Span
from pii_guard.vault import Vault, VaultSession
from pii_guard.vault.inspect import entries_of
from pii_guard.vault.known import KnownValue

sys.path.insert(0, str(Path(__file__).parents[1] / "gateway"))
from gateway_helpers import FakeLlm, MockUpstream, make_app

TOKEN = "test-api-token-not-a-secret"  # noqa: S105 - fictional
LAN_SERVER = "http://192.0.2.10:8787"  # TEST-NET-1: a non-loopback socket address
LAN_CLIENT = ("192.0.2.77", 50000)

#: One fictional value per text entity type.
VALUES: dict[EntityType, str] = {
    EntityType.PERSON: "Teszt Elek",
    EntityType.ADDRESS: "1052 Budapest, Próba utca 12.",
    EntityType.EMAIL: "teszt.elek@example.com",
    EntityType.PHONE: "+36 30 123 4567",
    EntityType.DATE_OF_BIRTH: "1987.03.14",
    EntityType.NATIONAL_ID_HU_TAX: "8123456789",
    EntityType.NATIONAL_ID_HU_TAJ: "123 456 788",
    EntityType.ID_DOCUMENT: "AB1234567",
    EntityType.BANK_ACCOUNT: "HU42 1177 3016 1111 1018 0000 0000",
    EntityType.COMPANY_ID_HU: "01-09-123456",
    EntityType.ORGANIZATION: "Mintavállalat Kft.",
    EntityType.PARCEL_NUMBER_HU: "Budapest 12345/6",
    EntityType.VEHICLE_PLATE: "ABC-123",
    EntityType.SECRET: "ghp_FAKE0000000000000000000000000000test",
}
TEXT_TYPES = [t for t in EntityType if not t.is_visual]
KNOWN = "Gyakorló Tihamér"
PENDING_KNOWN = "Próba Zsuzsanna"


def _span(text: str, value: str, entity_type: EntityType, detector: str = "test") -> Span:
    start = text.index(value)
    return Span(start, start + len(value), entity_type, value, 1.0, detector)


def fill(session: VaultSession) -> None:
    """Every text entity type, an inflected form, a casing variant and known values."""
    session.known_values.add(
        [KnownValue(KNOWN, EntityType.PERSON), KnownValue(PENDING_KNOWN, EntityType.PERSON)]
    )
    text = " | ".join(VALUES.values()) + f" | {KNOWN}nak írtunk | Teszt Eleknek"
    spans = [_span(text, v, t) for t, v in VALUES.items()]
    spans.append(_span(text, KNOWN, EntityType.PERSON, "known"))
    session.mask(text, sorted(spans, key=lambda s: s.start), language="hu")
    session.mask(
        "Levél TESZT ELEK részére, Minta Máriának",
        [Span(26, 40, EntityType.PERSON, "Minta Máriának", 1.0, "test")],
    )


def secrets_of(session: VaultSession) -> set[str]:
    entries, pending = entries_of(session)
    found = {e.original for e in entries} | {f for e in entries for f in e.forms}
    found |= {k.value for k in pending}
    found |= set(VALUES.values()) | {KNOWN, PENDING_KNOWN}
    return {v for v in found if v}


def _app(mode: str = "masked", **settings: Any) -> tuple[FastAPI, Vault]:
    app = create_app(Settings(tenant_key=TEST_TENANT_KEY, vault_inspect=mode, **settings))
    vault = Vault.from_settings(app.state.settings)
    app.state.vault = vault
    return app, vault


@pytest.fixture
def masked() -> Iterator[tuple[TestClient, VaultSession]]:
    app, vault = _app("masked")
    session = vault.session()
    fill(session)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, session


@pytest.fixture
def full() -> Iterator[tuple[TestClient, VaultSession]]:
    app, vault = _app("full")
    session = vault.session()
    fill(session)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, session


def _ref(client: TestClient) -> str:
    sessions = client.get("/v1/vault/sessions").json()["sessions"]
    assert len(sessions) == 1
    return str(sessions[0]["ref"])


# --- masked: never an original ---------------------------------------------------------------


def test_the_fixture_covers_every_text_entity_type() -> None:
    assert set(VALUES) == set(TEXT_TYPES)


def test_masked_mode_returns_no_original_value_or_form(
    masked: tuple[TestClient, VaultSession],
) -> None:
    client, session = masked
    listing = client.get("/v1/vault/sessions")
    ref = listing.json()["sessions"][0]["ref"]
    detail = client.get(f"/v1/vault/sessions/{ref}")
    refused = client.get(f"/v1/vault/sessions/{ref}?reveal=true")
    status = client.get("/v1/status")
    bodies = [listing, detail, refused, status]
    assert [r.status_code for r in bodies] == [200, 200, 403, 200]
    hidden = secrets_of(session)
    assert len(hidden) > len(VALUES)  # forms and variants are in the set too
    for response in bodies:
        text = response.text
        for value in hidden:
            assert value not in text, (response.url, value)
            assert value.casefold() not in text.casefold(), (response.url, value)
    assert session.session_id not in "".join(r.text for r in bodies)
    body = detail.json()
    assert body["revealed"] is False and body["session_id"] is None
    assert {i["entity_type"] for i in body["items"]} == {t.value for t in TEXT_TYPES}
    assert all(i["original"] is None and i["known_forms"] is None for i in body["items"])
    assert refused.json()["error"]["code"] == "vault_reveal_disabled"


def test_detail_reports_origin_counts_variants_and_pending_known_values(
    masked: tuple[TestClient, VaultSession],
) -> None:
    client, _ = masked
    items = client.get(f"/v1/vault/sessions/{_ref(client)}").json()["items"]
    by_hint = {i["hint"]: i for i in items}
    person = by_hint["T•••• E•••"]
    assert person["origin"] == "detected"
    assert person["count"] >= 2  # "Teszt Elek" and "Teszt Eleknek"
    known = by_hint["G••••••• T••••••"]
    assert known["origin"] == "known" and known["placeholder"].startswith("[[PERSON_")
    pending = by_hint["P•••• Z••••••••"]
    assert pending == {
        **pending,
        "placeholder": None,
        "origin": "known",
        "count": 0,
    }
    assert any(i["forms"] >= 1 for i in items)  # Minta Máriának -> Minta Mária + nak


def test_listing_reports_counts_and_source_without_extending_the_ttl() -> None:
    clock = [1000.0]
    app = create_app(Settings(tenant_key=TEST_TENANT_KEY))
    vault = Vault.from_settings(app.state.settings, clock=lambda: clock[0], ttl_seconds=100)
    app.state.vault = vault
    session = vault.session()
    fill(session)
    clock[0] += 40
    with TestClient(app) as client:
        first = client.get("/v1/vault/sessions").json()
        ref = first["sessions"][0]["ref"]
        detail = client.get(f"/v1/vault/sessions/{ref}").json()
        again = client.get("/v1/vault/sessions").json()["sessions"][0]
    summary = first["sessions"][0]
    assert first["mode"] == "masked" and first["ttl_seconds"] == 100
    assert summary["source"] == "api" and summary["client"] is None
    assert summary["created"] is None
    assert summary["ttl_left_seconds"] == pytest.approx(60, abs=0.5)
    assert again["ttl_left_seconds"] == pytest.approx(60, abs=0.5)  # reads touch nothing
    assert summary["known_values"] == 2
    assert summary["entity_counts"]["PERSON"] >= 3
    assert sum(summary["entity_counts"].values()) == summary["entries"]
    assert summary["occurrences"] == sum(i["count"] for i in detail["items"]) > 0


# --- full: reveal on demand, loopback only ---------------------------------------------------


def test_full_mode_reveals_on_demand_and_logs_without_values(
    full: tuple[TestClient, VaultSession], caplog: pytest.LogCaptureFixture
) -> None:
    client, session = full
    ref = _ref(client)
    plain = client.get(f"/v1/vault/sessions/{ref}").json()
    assert plain["revealed"] is False and plain["mode"] == "full"
    assert VALUES[EntityType.EMAIL] not in str(plain)
    with caplog.at_level(logging.INFO, logger="pii_guard.api.vault"):
        revealed = client.get(f"/v1/vault/sessions/{ref}?reveal=true").json()
    assert revealed["revealed"] is True
    assert revealed["session_id"] == session.session_id
    originals = {i["original"] for i in revealed["items"]}
    assert set(VALUES.values()) <= originals
    assert PENDING_KNOWN in originals
    assert any(i["known_forms"] for i in revealed["items"])
    logs = [r.getMessage() for r in caplog.records if "revealed" in r.getMessage()]
    assert len(logs) == 1 and ref in logs[0]
    log_text = caplog.text
    assert session.session_id not in log_text
    assert all(value not in log_text for value in secrets_of(session))


def test_full_is_refused_on_a_non_loopback_bind() -> None:
    with pytest.raises(VaultInspectConfigError, match="loopback"):
        create_app(Settings(tenant_key=TEST_TENANT_KEY, vault_inspect="full", host="0.0.0.0"))  # noqa: S104
    with pytest.raises(VaultInspectConfigError, match="ALLOWED_HOSTS"):
        create_app(Settings(tenant_key=TEST_TENANT_KEY, vault_inspect="full", allowed_hosts="*"))
    # masked is fine anywhere
    create_app(Settings(tenant_key=TEST_TENANT_KEY, host="0.0.0.0", api_token=TOKEN))  # noqa: S104


def test_full_refuses_a_connection_on_a_non_loopback_socket() -> None:
    app, vault = _app("full")
    fill(vault.session())
    paths = [("get", "/v1/vault/sessions"), ("get", "/v1/vault/sessions/s_00?reveal=true")]
    with TestClient(app, base_url=LAN_SERVER, client=LAN_CLIENT) as client:
        responses = [client.request(m, p, headers={"Host": "localhost"}) for m, p in paths]
    with TestClient(app, base_url=LAN_SERVER, client=("127.0.0.1", 1)) as client:
        responses.append(client.get("/v1/vault/sessions", headers={"Host": "localhost"}))
    for response in responses:
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "vault_inspect_not_local"
    with TestClient(app) as client:  # loopback on both ends
        assert client.get("/v1/vault/sessions").status_code == 200


@pytest.mark.parametrize("mode", ["masked", "full"])
def test_a_set_token_is_required(mode: str) -> None:
    app, vault = _app(mode, api_token=TOKEN)
    fill(vault.session())
    with TestClient(app) as client:
        good = {"Authorization": f"Bearer {TOKEN}"}
        ref = client.get("/v1/vault/sessions", headers=good).json()["sessions"][0]["ref"]
        for method, path in [
            ("get", "/v1/vault/sessions"),
            ("get", f"/v1/vault/sessions/{ref}?reveal=true"),
            ("delete", f"/v1/vault/sessions/{ref}"),
        ]:
            missing = client.request(method, path)
            wrong = client.request(method, path, headers={"Authorization": "Bearer nope"})
            assert missing.status_code == wrong.status_code == 401, path
            assert missing.json()["error"]["code"] == "unauthorized"
            assert VALUES[EntityType.PERSON] not in missing.text + wrong.text
        assert client.get(f"/v1/vault/sessions/{ref}", headers=good).status_code == 200


def test_foreign_host_header_is_refused(full: tuple[TestClient, VaultSession]) -> None:
    client, _ = full
    response = client.get("/v1/vault/sessions", headers={"Host": "attacker.example"})
    assert response.status_code == 400
    assert "sessions" not in response.text


# --- off, unknown refs, drop -------------------------------------------------------------------


def test_off_answers_404_on_every_route_and_status_says_so() -> None:
    app, vault = _app("off")
    fill(vault.session())
    with TestClient(app) as client:
        for method, path in [
            ("get", "/v1/vault/sessions"),
            ("get", "/v1/vault/sessions/s_0123"),
            ("delete", "/v1/vault/sessions/s_0123"),
        ]:
            response = client.request(method, path)
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "vault_inspect_disabled"
        assert client.get("/v1/status").json()["vault_inspect"] == "off"


def test_status_reports_the_inspect_mode(full: tuple[TestClient, VaultSession]) -> None:
    client, _ = full
    assert client.get("/v1/status").json()["vault_inspect"] == "full"


def test_unknown_and_malformed_refs(masked: tuple[TestClient, VaultSession]) -> None:
    client, session = masked
    unknown = client.get("/v1/vault/sessions/s_0123456789abcdef")
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "not_found"
    # The raw session id is not a ref: a guessed or leaked id gives nothing away here.
    raw = client.get(f"/v1/vault/sessions/{session.session_id}")
    assert raw.status_code in (404, 422)
    assert client.get("/v1/vault/sessions/not-a-ref!").status_code == 422


def test_drop_forgets_the_session(masked: tuple[TestClient, VaultSession]) -> None:
    client, session = masked
    ref = _ref(client)
    assert client.delete(f"/v1/vault/sessions/{ref}").status_code == 204
    assert client.get(f"/v1/vault/sessions/{ref}").status_code == 404
    assert client.delete(f"/v1/vault/sessions/{ref}").status_code == 404
    assert client.get("/v1/vault/sessions").json()["sessions"] == []
    gone = client.post("/v1/unmask", json={"session_id": session.session_id, "text": "x"})
    assert gone.status_code == 404


# --- where gateway sessions come from ------------------------------------------------------------


def _chat(client: TestClient, path: str = "/v1/chat/completions", **kw: Any) -> Any:
    body = {"model": "m", "messages": [{"role": "user", "content": "Szia, Teszt Elek vagyok."}]}
    body.update(kw.pop("body", {}))
    response = client.post(path, json=body, **kw)
    assert response.status_code == 200, response.text
    return response


def test_gateway_sessions_show_their_source_and_link_to_the_traffic_log() -> None:
    upstream = MockUpstream()
    app = make_app(upstream, llm=FakeLlm())
    app.state.observability.traffic.level = TrafficLevel.MASKED
    with TestClient(app) as client:
        _chat(client)  # default, anonymous
        _chat(client, headers={"Authorization": "Bearer client-own-key"})  # default, another client
        _chat(client, "/s/case-4711/v1/chat/completions")  # path
        _chat(client, body={"prompt_cache_key": "conv-1"})  # prompt_cache_key
        header = _chat(client).headers["x-pii-guard-session"]
        _chat(client, headers={"X-PII-Guard-Session": header})  # header: same session, kept
        sessions = client.get("/v1/vault/sessions").json()["sessions"]
        events = client.get("/v1/traffic").json()["events"]
    sources = sorted(s["source"] for s in sessions)
    # A session keeps the source it was created by; naming it in the header later reuses it.
    assert sources == ["default", "default", "path", "prompt_cache_key"]
    clients = {s["client"] for s in sessions}
    assert "anonymous" in clients
    assert all(c == "anonymous" or len(c) == 12 for c in clients)
    assert "client-own-key" not in str(sessions)
    assert all(s["created"] is not None for s in sessions)
    # A traffic event's session_ref is the inspector's ref.
    assert {e["session_ref"] for e in events} == {s["ref"] for s in sessions}
    assert "case-4711" not in str(sessions)


def test_sessions_can_be_filtered_by_source() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream, llm=FakeLlm())) as client:
        _chat(client)
        _chat(client, "/s/case-4711/v1/chat/completions")
        only = client.get("/v1/vault/sessions?source=path").json()["sessions"]
        bad = client.get("/v1/vault/sessions?source=nope")
    assert [s["source"] for s in only] == ["path"]
    assert bad.status_code == 422


# --- hints ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "entity_type", "expected"),
    [
        ("Teszt Elek", EntityType.PERSON, "T•••• E•••"),
        ("Jo Kft.", EntityType.ORGANIZATION, "•• K••."),
        ("teszt.elek@example.com", EntityType.EMAIL, "t••••.e•••@e••••••.c••"),
        ("+36 30 123 4567", EntityType.PHONE, "+•• •• ••• ••67"),
        ("HU42 1177 3016", EntityType.BANK_ACCOUNT, "•••• •••• ••16"),
        ("1234", EntityType.ID_DOCUMENT, "••••"),
        ("ghp_FAKE0000000000000000test", EntityType.SECRET, "••••••••••••"),
    ],
)
def test_hint(value: str, entity_type: EntityType, expected: str) -> None:
    assert hint(value, entity_type) == expected


@pytest.mark.parametrize("entity_type", TEXT_TYPES)
def test_a_hint_never_contains_its_value(entity_type: EntityType) -> None:
    value = VALUES[entity_type]
    out = hint(value, entity_type)
    assert value not in out
    assert len(out) <= max(len(value), 12)
