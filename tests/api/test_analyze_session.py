"""``POST /v1/analyze`` with ``session_id``: the session's known values are reported as
``detector: "known"`` spans, as ``/v1/mask`` would find them. All values are fictional
(ADR 0005)."""

from __future__ import annotations

import logging

import pytest
from api_helpers import TEST_TENANT_KEY
from fastapi.testclient import TestClient
from test_sessions import FixedAnalyzer, preload

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.policy import Policy
from pii_guard.types import EntityType

NAME = "Gyakorló Tihamér"
TEXT = "Üdv, Gyakorló Tihamérnak!"
INTERNAL_ID = "KX-77-3021"


def known_spans(body: dict) -> list[dict]:
    return [s for s in body["spans"] if s["detector"] == "known"]


def test_known_value_reported_with_stem_span(api: TestClient) -> None:
    session_id = preload(api, (NAME, "PERSON"))
    response = api.post("/v1/analyze", json={"text": TEXT, "session_id": session_id})
    assert response.status_code == 200
    spans = known_spans(response.json())
    assert len(spans) == 1
    span = spans[0]
    assert TEXT[span["start"] : span["end"]] == NAME  # suffix "nak" stays outside
    assert span["entity_type"] == "PERSON" and span["policy"] == "mask"
    assert "value" not in span and "text" not in span


def test_without_session_id_no_known_span(api: TestClient) -> None:
    preload(api, (NAME, "PERSON"))
    body = api.post("/v1/analyze", json={"text": TEXT}).json()
    assert known_spans(body) == []


def test_known_value_of_a_keep_type_reports_mask(api: TestClient) -> None:
    session_id = preload(api, ("Próbaüzem Kft.", "ORGANIZATION"))
    text = "A Próbaüzem Kft. és a Másik Bt. szerződött."
    api.app.state.analyzer = FixedAnalyzer(("Másik Bt.", EntityType.ORGANIZATION))
    body = api.post("/v1/analyze", json={"text": text, "session_id": session_id}).json()
    (known,) = known_spans(body)
    assert text[known["start"] : known["end"]] == "Próbaüzem Kft." and known["policy"] == "mask"
    detected = [s for s in body["spans"] if s["detector"] != "known"]
    assert [s["policy"] for s in detected] == ["keep"]  # detected, not pre-loaded


def test_known_value_of_a_block_type_reports_block_without_refusing() -> None:
    settings = Settings(
        tenant_key=TEST_TENANT_KEY, policy_overrides={EntityType.ID_DOCUMENT: Policy.BLOCK}
    )
    with TestClient(create_app(settings), raise_server_exceptions=False) as api:
        session_id = preload(api, (INTERNAL_ID, "ID_DOCUMENT"))
        response = api.post(
            "/v1/analyze", json={"text": f"Azonosító: {INTERNAL_ID}", "session_id": session_id}
        )
    assert response.status_code == 200
    (span,) = known_spans(response.json())
    assert span["entity_type"] == "ID_DOCUMENT" and span["policy"] == "block"


def test_unknown_session_is_404_without_text(api: TestClient) -> None:
    response = api.post("/v1/analyze", json={"text": TEXT, "session_id": "s_nope"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert "Tihamér" not in response.text


def test_no_session_id_needs_no_tenant_key() -> None:
    with TestClient(create_app(Settings()), raise_server_exceptions=False) as api:
        response = api.post("/v1/analyze", json={"text": TEXT})
    assert response.status_code == 200


def test_analyze_stores_nothing(api: TestClient) -> None:
    session_id = preload(api, (NAME, "PERSON"))
    vault = api.app.state.vault
    before_entities = vault.session(session_id).entities()
    before_known = len(vault.session(session_id).known_values)
    api.post("/v1/analyze", json={"text": TEXT, "session_id": session_id})
    after = vault.session(session_id)
    assert after.entities() == before_entities == []
    assert len(after.known_values) == before_known


def test_log_has_counts_but_no_values_or_session_id(
    api: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    session_id = preload(api, (NAME, "PERSON"), (INTERNAL_ID, "ID_DOCUMENT"))
    api.post("/v1/analyze", json={"text": TEXT, "session_id": session_id})
    assert "Tihamér" not in caplog.text and INTERNAL_ID not in caplog.text
    ours = " ".join(r.getMessage() for r in caplog.records if r.name.startswith("pii_guard"))
    assert session_id not in ours
    assert "POST /v1/analyze 200" in ours and "known=1" in ours and "session=True" in ours
