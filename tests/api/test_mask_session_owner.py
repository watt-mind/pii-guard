"""LAB-1590: REST routes that take an existing ``session_id`` honor the gateway owner binding.

``/v1/unmask`` already refuses a bound session to a different identity (LAB-1580). The same
check now guards ``/v1/mask``, ``/v1/mask/image``, ``/v1/analyze`` and
``/v1/sessions/{id}/known-values``: a foreign identity gets the 404 of a missing session, reads
nothing (no placeholder, no ``known`` span) and writes nothing. Unbound and anonymous-owned
sessions stay open to every caller, and none of these routes claims a session.

All values are fictional (ADR 0005).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from test_image_endpoint import card_image, make_app
from test_sessions import preload

from pii_guard.gateway.sessions import client_identity
from pii_guard.vault import PLACEHOLDER_RE, Vault, VaultSession

OWNER = {"authorization": "Bearer owner-one-not-a-key"}
OTHER = {"authorization": "Bearer other-two-not-a-key"}
EMAIL = "teszt.elek@example.com"
TEXT = f"Írj Teszt Eleknek: {EMAIL}"
NAME = "Gyakorló Tihamér"
ANALYZE_TEXT = "Üdv, Gyakorló Tihamérnak!"
# Every identity that is not the owner: another bearer, and none at all (dropping
# ``Authorization`` must not bypass the binding).
FOREIGN = [pytest.param(OTHER, id="other-bearer"), pytest.param({}, id="no-credential")]


def vault_of(http: TestClient) -> Vault:
    vault = http.app.state.vault  # type: ignore[attr-defined]
    assert isinstance(vault, Vault)
    return vault


def live(http: TestClient, session_id: str) -> VaultSession:
    return vault_of(http).session(session_id)


def bind(http: TestClient, session_id: str, headers: dict[str, str]) -> VaultSession:
    """Record an owner the way a gateway request would (``check_and_bind``)."""
    session = live(http, session_id)
    session.owner = client_identity(headers)
    return session


def masked_session(http: TestClient) -> tuple[str, str]:
    """``(session_id, masked_text)`` of an unbound ``/v1/mask`` session holding ``EMAIL``."""
    response = http.post("/v1/mask", json={"text": TEXT})
    assert response.status_code == 200, response.text
    body = response.json()
    assert PLACEHOLDER_RE.search(body["masked_text"])
    return body["session_id"], body["masked_text"]


def assert_refused(response: httpx.Response, *secrets: str) -> None:
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"
    assert not PLACEHOLDER_RE.search(response.text)
    for secret in secrets:
        assert secret not in response.text


@pytest.fixture
def image_api() -> Iterator[TestClient]:
    with TestClient(make_app(), raise_server_exceptions=False) as http:
        yield http


# --- /v1/mask ------------------------------------------------------------------------------


@pytest.mark.parametrize("headers", FOREIGN)
def test_mask_into_a_foreign_bound_session_is_404_and_writes_nothing(
    api: TestClient, headers: dict[str, str]
) -> None:
    session_id, _ = masked_session(api)
    session = bind(api, session_id, OWNER)
    before = session.entry_count

    # A value already in the session: answering with its placeholder would be an oracle.
    known = api.post("/v1/mask", json={"text": TEXT, "session_id": session_id}, headers=headers)
    assert_refused(known, session_id, EMAIL)
    # A new value: it must not be written into the victim's session.
    new = api.post(
        "/v1/mask",
        json={"text": "Másik: masik.cim@example.com", "session_id": session_id},
        headers=headers,
    )
    assert_refused(new, session_id)
    assert session.entry_count == before
    assert session.owner == client_identity(OWNER)


def test_mask_by_the_owner_still_reuses_the_placeholder(api: TestClient) -> None:
    session_id, masked = masked_session(api)
    bind(api, session_id, OWNER)
    again = api.post("/v1/mask", json={"text": TEXT, "session_id": session_id}, headers=OWNER)
    assert again.status_code == 200, again.text
    assert again.json()["masked_text"] == masked


def test_mask_into_unbound_and_anonymous_sessions_is_unchanged(api: TestClient) -> None:
    session_id, masked = masked_session(api)
    for headers in ({}, OWNER, OTHER):
        body = {"text": TEXT, "session_id": session_id}
        response = api.post("/v1/mask", json=body, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["masked_text"] == masked
    # Masking never claims a session: it is still unbound.
    assert live(api, session_id).owner is None

    anon_id, _ = masked_session(api)
    bind(api, anon_id, {})
    for headers in ({}, OWNER):
        body = {"text": TEXT, "session_id": anon_id}
        assert api.post("/v1/mask", json=body, headers=headers).status_code == 200
    assert live(api, anon_id).owner == "anonymous"


def test_mask_without_session_id_is_unaffected_by_credentials(api: TestClient) -> None:
    for headers in ({}, OWNER, OTHER):
        response = api.post("/v1/mask", json={"text": TEXT}, headers=headers)
        assert response.status_code == 200, response.text
        assert live(api, response.json()["session_id"]).owner is None


def test_a_refused_mask_logs_neither_the_session_nor_the_value(
    api: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    session_id, _ = masked_session(api)
    bind(api, session_id, OWNER)
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        body = {"text": TEXT, "session_id": session_id}
        assert_refused(api.post("/v1/mask", json=body, headers=OTHER))
    for record in caplog.records:
        line = record.getMessage() + repr(record.__dict__)
        assert session_id not in line
        assert EMAIL not in line


# --- /v1/sessions/{id}/known-values ---------------------------------------------------------


@pytest.mark.parametrize("headers", FOREIGN)
def test_known_values_into_a_foreign_bound_session_is_404_and_adds_nothing(
    api: TestClient, headers: dict[str, str]
) -> None:
    session_id = preload(api, (NAME, "PERSON"))
    session = bind(api, session_id, OWNER)
    before = len(session.known_values)
    response = api.post(
        f"/v1/sessions/{session_id}/known-values",
        json={"known_values": [{"value": "Próba Ödön", "entity_type": "PERSON"}]},
        headers=headers,
    )
    assert_refused(response, session_id, "Próba Ödön", NAME)
    assert len(session.known_values) == before


def test_known_values_for_the_owner_and_unbound_sessions_are_unchanged(api: TestClient) -> None:
    item = {"known_values": [{"value": "Próba Ödön", "entity_type": "PERSON"}]}
    bound = preload(api, (NAME, "PERSON"))
    bind(api, bound, OWNER)
    response = api.post(f"/v1/sessions/{bound}/known-values", json=item, headers=OWNER)
    assert response.status_code == 200, response.text

    unbound = preload(api, (NAME, "PERSON"))
    for headers in ({}, OWNER, OTHER):
        response = api.post(f"/v1/sessions/{unbound}/known-values", json=item, headers=headers)
        assert response.status_code == 200, response.text
    assert live(api, unbound).owner is None


# --- /v1/analyze ---------------------------------------------------------------------------


@pytest.mark.parametrize("headers", FOREIGN)
def test_analyze_with_a_foreign_bound_session_reveals_no_known_spans(
    api: TestClient, headers: dict[str, str]
) -> None:
    session_id = preload(api, (NAME, "PERSON"))
    bind(api, session_id, OWNER)
    body = {"text": ANALYZE_TEXT, "session_id": session_id}
    response = api.post("/v1/analyze", json=body, headers=headers)
    assert_refused(response, session_id, NAME)
    assert '"known"' not in response.text


def test_analyze_for_the_owner_and_unbound_sessions_reports_known_spans(
    api: TestClient,
) -> None:
    def known(headers: dict[str, str], session_id: str) -> list[dict[str, Any]]:
        body = {"text": ANALYZE_TEXT, "session_id": session_id}
        response = api.post("/v1/analyze", json=body, headers=headers)
        assert response.status_code == 200, response.text
        return [s for s in response.json()["spans"] if s["detector"] == "known"]

    bound = preload(api, (NAME, "PERSON"))
    bind(api, bound, OWNER)
    assert len(known(OWNER, bound)) == 1

    unbound = preload(api, (NAME, "PERSON"))
    for headers in ({}, OWNER, OTHER):
        assert len(known(headers, unbound)) == 1
    assert live(api, unbound).owner is None


# --- /v1/mask/image ------------------------------------------------------------------------


def post_image(http: TestClient, session_id: str, headers: dict[str, str]) -> httpx.Response:
    return http.post(
        "/v1/mask/image",
        content=card_image(),
        params={"session_id": session_id, "render": "labels"},
        headers={"Content-Type": "image/png", **headers},
    )


@pytest.mark.parametrize("headers", FOREIGN)
def test_image_mask_into_a_foreign_bound_session_is_404_and_writes_nothing(
    image_api: TestClient, headers: dict[str, str]
) -> None:
    session_id, _ = masked_session(image_api)
    session = bind(image_api, session_id, OWNER)
    before = session.entry_count
    response = post_image(image_api, session_id, headers)
    assert_refused(response, session_id)
    assert session.entry_count == before


def test_image_mask_for_the_owner_and_unbound_sessions_is_unchanged(
    image_api: TestClient,
) -> None:
    bound, _ = masked_session(image_api)
    bind(image_api, bound, OWNER)
    response = post_image(image_api, bound, OWNER)
    assert response.status_code == 200, response.text
    assert response.json()["session_id"] == bound

    unbound, _ = masked_session(image_api)
    for headers in ({}, OTHER):
        response = post_image(image_api, unbound, headers)
        assert response.status_code == 200, response.text
    assert live(image_api, unbound).owner is None
