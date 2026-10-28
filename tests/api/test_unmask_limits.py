"""``/v1/mask`` + ``/v1/unmask``: case-sensitive secrets and the restore limit (LAB-1350).

Every value is fictional (ADR 0005); the tokens are built at runtime.
"""

from __future__ import annotations

from api_helpers import TEST_TENANT_KEY
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.vault import PLACEHOLDER_RE

_PREFIX = "gh" + "p_"
TOKEN_A = _PREFIX + "AbCdEfGhIjKlMnOpQrStUvWxYz" + "0123456789"
TOKEN_B = _PREFIX + "aBcDeFgHiJkLmNoPqRsTuVwXyZ" + "0123456789"
# A synthetic PEM block (1,678 characters), split so no literal looks like a key.
_ARMOR = "PRIVATE " + "KEY-----"
PEM = "\n".join(["-----BEGIN " + _ARMOR, *["MIIEv" + "Q" * 59] * 25, "-----END " + _ARMOR])


def _client(**settings: int) -> TestClient:
    return TestClient(
        create_app(Settings(tenant_key=TEST_TENANT_KEY, **settings)),
        raise_server_exceptions=False,
    )


def test_two_tokens_that_differ_only_in_case_round_trip() -> None:
    text = f"first token {TOKEN_A} second token {TOKEN_B}"
    with _client() as api:
        masked = api.post("/v1/mask", json={"text": text})
        assert masked.status_code == 200, masked.text
        body = masked.json()
        placeholders = [m.group(0) for m in PLACEHOLDER_RE.finditer(body["masked_text"])]
        assert len(placeholders) == 2
        assert placeholders[0] != placeholders[1]
        restored = api.post(
            "/v1/unmask", json={"text": body["masked_text"], "session_id": body["session_id"]}
        )
    assert restored.status_code == 200
    assert restored.json()["text"] == text


def test_unmask_over_the_restore_limit_is_413() -> None:
    with _client(unmask_max_restored_chars=200) as api:
        body = api.post("/v1/mask", json={"text": f"key {TOKEN_A}"}).json()
        placeholder = body["masked_text"][len("key ") :]
        assert PLACEHOLDER_RE.fullmatch(placeholder)
        ok = api.post(
            "/v1/unmask",
            json={"text": " ".join([placeholder] * 5), "session_id": body["session_id"]},
        )
        too_many = api.post(
            "/v1/unmask",
            json={"text": " ".join([placeholder] * 50), "session_id": body["session_id"]},
        )
    assert ok.status_code == 200
    assert ok.json()["text"].count(TOKEN_A) == 5
    assert too_many.status_code == 413
    assert too_many.json()["error"]["code"] == "unmask_output_too_large"
    assert TOKEN_A not in too_many.text


def test_default_limit_refuses_a_placeholder_amplification() -> None:
    """The reviewed reproduction at the default limit: a PEM placeholder repeated in a text
    of the maximum size would restore about 18M characters."""
    with _client() as api:
        body = api.post("/v1/mask", json={"text": f"key: {PEM}"}).json()
        [placeholder] = [m.group(0) for m in PLACEHOLDER_RE.finditer(body["masked_text"])]
        text = " ".join([placeholder] * (200_000 // (len(placeholder) + 1)))
        response = api.post("/v1/unmask", json={"text": text, "session_id": body["session_id"]})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "unmask_output_too_large"
    assert "MIIEv" not in response.text
