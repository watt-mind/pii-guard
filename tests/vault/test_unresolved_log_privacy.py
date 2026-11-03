"""Unresolved tokens are untrusted input and must not enter logs (LAB-1758)."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.vault import StreamUnmasker, Vault

UNRESOLVED = "[[SYNTHETIC_PERSON_123456789_abcd]]"


def assert_count_only(caplog: pytest.LogCaptureFixture) -> None:
    records = [r for r in caplog.records if r.name == "pii_guard.vault.session"]
    assert records
    assert all(r.getMessage() == "unmask left 1 unresolved placeholders" for r in records)
    assert UNRESOLVED not in caplog.text
    assert "123456789" not in caplog.text


def test_rest_unmask_does_not_log_unknown_token(caplog: pytest.LogCaptureFixture) -> None:
    app = create_app(Settings(detectors="rules", tenant_key="ab" * 32))
    caplog.set_level(logging.WARNING, logger="pii_guard.vault.session")
    with TestClient(app) as client:
        created = client.post("/v1/sessions", json={})
        assert created.status_code == 201
        response = client.post(
            "/v1/unmask", json={"session_id": created.json()["session_id"], "text": UNRESOLVED}
        )
    assert response.status_code == 200
    assert response.json()["unresolved"] == [UNRESOLVED]
    assert_count_only(caplog)


def test_stream_unmask_does_not_log_unknown_token(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="pii_guard.vault.session")
    stream = StreamUnmasker(Vault(b"x" * 32).session())
    output = stream.feed(UNRESOLVED[:12]) + stream.feed(UNRESOLVED[12:] + " ") + stream.flush()
    assert output == UNRESOLVED + " "
    assert stream.unresolved == (UNRESOLVED,)
    assert_count_only(caplog)
