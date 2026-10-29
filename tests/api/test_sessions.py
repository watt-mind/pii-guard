"""``POST /v1/sessions``, ``POST /v1/sessions/{id}/known-values`` and their use by ``/v1/mask``
and the gateway. All values are fictional (ADR 0005)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from api_helpers import TEST_TENANT_KEY
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.policy import Policy
from pii_guard.types import EntityType, Span
from pii_guard.vault import PLACEHOLDER_RE, Vault

NAME = "Gyakorló Tihamér"
FORMS = ("Gyakorló Tihamérnak", "Gyakorló Tihamért", "Gyakorló Tihamérral", "Gyakorló Tihaméré")
TEXT = (
    "Gyakorló Tihamérnak megküldtük az ajánlatot. Gyakorló Tihamér holnap válaszol, "
    "Gyakorló Tihamért hívjuk, Gyakorló Tihamérral egyeztetünk. E-mail: teszt@example.com"
)
INTERNAL_ID = "KX-77-3021"
RSQUO = "\N{RIGHT SINGLE QUOTATION MARK}"  # the typographic apostrophe


def preload(api: TestClient, *items: tuple[str, str]) -> str:
    response = api.post(
        "/v1/sessions",
        json={"known_values": [{"value": v, "entity_type": t} for v, t in items]},
    )
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


class FixedAnalyzer:
    """An analyzer that 'detects' given values, as the LLM detector would."""

    def __init__(self, *found: tuple[str, EntityType]) -> None:
        self.found = found

    def analyze(self, text: str, language: str) -> list[Span]:
        spans = []
        for value, entity_type in self.found:
            start = text.find(value)
            while start >= 0:
                spans.append(Span(start, start + len(value), entity_type, value, 0.8, "llm"))
                start = text.find(value, start + len(value))
        return sorted(spans, key=lambda s: s.start)


# --- creating sessions and adding values ---------------------------------------------------


def test_create_empty_session(api: TestClient) -> None:
    response = api.post("/v1/sessions")
    assert response.status_code == 201
    body = response.json()
    assert body["added"] == 0 and body["total"] == 0
    assert body["session_id"].startswith("s_")
    # The session works with /v1/mask and /v1/unmask.
    masked = api.post("/v1/mask", json={"text": "x", "session_id": body["session_id"]})
    assert masked.status_code == 200


def test_create_with_values_returns_counts_only(api: TestClient) -> None:
    response = api.post(
        "/v1/sessions",
        json={
            "known_values": [
                {"value": NAME, "entity_type": "PERSON"},
                {"value": "gyakorló  tihamér", "entity_type": "PERSON"},  # a duplicate
                {"value": INTERNAL_ID, "entity_type": "ID_DOCUMENT"},
            ]
        },
    )
    assert response.status_code == 201
    assert set(response.json()) == {"session_id", "added", "total"}
    assert response.json()["added"] == 2 and response.json()["total"] == 2
    assert "Tihamér" not in response.text and INTERNAL_ID not in response.text


def test_add_known_values_to_an_existing_session(api: TestClient) -> None:
    session_id = preload(api, (NAME, "PERSON"))
    response = api.post(
        f"/v1/sessions/{session_id}/known-values",
        json={"known_values": [{"value": INTERNAL_ID, "entity_type": "ID_DOCUMENT"}]},
    )
    assert response.status_code == 200
    assert response.json() == {"session_id": session_id, "added": 1, "total": 2}


def test_add_to_unknown_session_is_404(api: TestClient) -> None:
    response = api.post(
        "/v1/sessions/s_nope/known-values",
        json={"known_values": [{"value": NAME, "entity_type": "PERSON"}]},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_known_values_also_work_on_a_session_made_by_mask(api: TestClient) -> None:
    session_id = api.post("/v1/mask", json={"text": "Szia!"}).json()["session_id"]
    api.post(
        f"/v1/sessions/{session_id}/known-values",
        json={"known_values": [{"value": NAME, "entity_type": "PERSON"}]},
    )
    masked = api.post("/v1/mask", json={"text": TEXT, "session_id": session_id}).json()
    assert "Tihamér" not in masked["masked_text"]


# --- validation and limits (errors never echo values) --------------------------------------


@pytest.mark.parametrize(
    ("item", "code"),
    [
        ({"value": "Al", "entity_type": "PERSON"}, "invalid_known_value"),
        ({"value": "   ", "entity_type": "PERSON"}, "invalid_known_value"),
        ({"value": "Gyakorló Tihamér", "entity_type": "NOPE"}, "invalid_known_value"),
        ({"value": "Gyakorló Tihamér", "entity_type": "SIGNATURE"}, "invalid_known_value"),
        ({"value": "Gyakorló Tihamér"}, "invalid_request"),
    ],
)
def test_invalid_values_are_refused_and_create_nothing(
    api: TestClient, item: dict[str, str], code: str
) -> None:
    response = api.post("/v1/sessions", json={"known_values": [item]})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    assert "Tihamér" not in response.text and '"Al"' not in response.text
    vault = api.app.state.vault
    assert len(vault) == 0


def test_short_value_error_is_clear(api: TestClient) -> None:
    response = api.post(
        "/v1/sessions", json={"known_values": [{"value": "Al", "entity_type": "PERSON"}]}
    )
    message = response.json()["error"]["message"]
    assert "known value 0 (PERSON)" in message and "3 characters" in message


def limited_api(**limits: int) -> TestClient:
    settings = Settings(tenant_key=TEST_TENANT_KEY, **limits)
    return TestClient(create_app(settings), raise_server_exceptions=False)


def test_max_values_per_session() -> None:
    with limited_api(known_values_max=2) as api:
        session_id = preload(api, (NAME, "PERSON"), (INTERNAL_ID, "ID_DOCUMENT"))
        response = api.post(
            f"/v1/sessions/{session_id}/known-values",
            json={"known_values": [{"value": "Minta Rozália", "entity_type": "PERSON"}]},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "too_many_known_values"
        # A duplicate is not a new value, so it still fits.
        again = api.post(
            f"/v1/sessions/{session_id}/known-values",
            json={"known_values": [{"value": NAME, "entity_type": "PERSON"}]},
        )
        assert again.json() == {"session_id": session_id, "added": 0, "total": 2}
        too_many = api.post(
            "/v1/sessions",
            json={
                "known_values": [
                    {"value": v, "entity_type": "PERSON"}
                    for v in ("Első Név", "Második Név", "Harmadik Név")
                ]
            },
        )
        assert too_many.status_code == 422
        assert len(api.app.state.vault) == 1  # the refused session was dropped


def test_max_value_length() -> None:
    with limited_api(known_values_max_length=10) as api:
        response = api.post(
            "/v1/sessions", json={"known_values": [{"value": NAME, "entity_type": "PERSON"}]}
        )
        assert response.status_code == 422
        assert "longer than 10" in response.json()["error"]["message"]
        assert "Tihamér" not in response.text


# --- AC1: /v1/mask with only the rules detector masks every inflected form ------------------


def test_mask_uses_known_values_without_the_llm(api: TestClient) -> None:
    session_id = preload(api, (NAME, "PERSON"))
    response = api.post("/v1/mask", json={"text": TEXT, "session_id": session_id})
    assert response.status_code == 200
    body = response.json()
    assert "Tihamér" not in body["masked_text"]
    person = [e for e in body["entities"] if e["entity_type"] == "PERSON"]
    assert len(person) == 1 and person[0]["count"] == 4
    assert {e["entity_type"] for e in body["entities"]} == {"PERSON", "EMAIL"}
    unmasked = api.post(
        "/v1/unmask", json={"text": body["masked_text"], "session_id": session_id}
    ).json()
    assert unmasked["text"] == TEXT


def test_mask_english_possessive(api: TestClient) -> None:
    session_id = preload(api, ("Quillon Ashgrove", "PERSON"))
    text = f"Quillon Ashgrove's account was closed; Quillon Ashgrove{RSQUO}s card too."
    body = api.post(
        "/v1/mask", json={"text": text, "language": "en", "session_id": session_id}
    ).json()
    assert "Quillon" not in body["masked_text"]
    assert "]]'s account" in body["masked_text"] and f"]]{RSQUO}s card" in body["masked_text"]


def test_known_value_of_a_keep_type_is_masked(api: TestClient) -> None:
    session_id = preload(api, ("Próbaüzem Kft.", "ORGANIZATION"))
    text = "A Próbaüzem Kft. és a Másik Bt. szerződött."
    api.app.state.analyzer = FixedAnalyzer(
        ("Próbaüzem Kft.", EntityType.ORGANIZATION), ("Másik Bt.", EntityType.ORGANIZATION)
    )
    body = api.post("/v1/mask", json={"text": text, "session_id": session_id}).json()
    assert "Próbaüzem" not in body["masked_text"]
    assert "Másik Bt." in body["masked_text"]  # detected, not pre-loaded: kept by policy
    assert body["kept"] == [{"entity_type": "ORGANIZATION", "count": 1}]


def test_known_value_of_a_block_type_refuses() -> None:
    settings = Settings(
        tenant_key=TEST_TENANT_KEY, policy_overrides={EntityType.ID_DOCUMENT: Policy.BLOCK}
    )
    with TestClient(create_app(settings), raise_server_exceptions=False) as api:
        session_id = preload(api, (INTERNAL_ID, "ID_DOCUMENT"))
        response = api.post(
            "/v1/mask", json={"text": f"Azonosító: {INTERNAL_ID}", "session_id": session_id}
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "blocked_entity"
    assert INTERNAL_ID not in response.text


# --- AC3: pre-loaded and detected -> one placeholder -----------------------------------------


def test_preloaded_and_detected_value_has_one_placeholder(api: TestClient) -> None:
    session_id = preload(api, (NAME, "PERSON"))
    # The "LLM" reports whole inflected words, and once a different type.
    api.app.state.analyzer = FixedAnalyzer(
        ("Gyakorló Tihamérnak", EntityType.PERSON), ("Gyakorló Tihamért", EntityType.ORGANIZATION)
    )
    body = api.post("/v1/mask", json={"text": TEXT, "session_id": session_id}).json()
    placeholders = {f"[[{t}_{i}]]" for t, i in PLACEHOLDER_RE.findall(body["masked_text"])}
    persons = {p for p in placeholders if p.startswith("[[PERSON_")}
    assert len(persons) == 1
    assert "]]nak megküldtük" in body["masked_text"]


# --- AC2: never in logs or error bodies; AC4: expiry ----------------------------------------


def test_known_values_never_logged(api: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    session_id = preload(api, (NAME, "PERSON"), (INTERNAL_ID, "ID_DOCUMENT"))
    api.post(
        f"/v1/sessions/{session_id}/known-values",
        json={"known_values": [{"value": "Al", "entity_type": "PERSON"}]},
    )
    api.post("/v1/mask", json={"text": TEXT, "session_id": session_id})
    assert "Tihamér" not in caplog.text and INTERNAL_ID not in caplog.text
    # The app's own log lines (not the test client's) never carry the session id either.
    ours = " ".join(r.getMessage() for r in caplog.records if r.name.startswith("pii_guard"))
    assert session_id not in ours
    assert "POST /v1/sessions/{session_id}/known-values 422" in ours
    assert "known_added=2" in ours


def test_session_expiry_removes_known_values(api: TestClient) -> None:
    now = [0.0]
    api.app.state.vault = Vault(
        bytes.fromhex(TEST_TENANT_KEY), ttl_seconds=60, clock=lambda: now[0]
    )
    session_id = preload(api, (NAME, "PERSON"))
    vault: Vault = api.app.state.vault
    store = vault.session(session_id).known_values
    assert len(store) == 1
    now[0] = 61.0
    response = api.post(
        f"/v1/sessions/{session_id}/known-values",
        json={"known_values": [{"value": INTERNAL_ID, "entity_type": "ID_DOCUMENT"}]},
    )
    assert response.status_code == 404
    assert len(store) == 0
    assert api.post("/v1/mask", json={"text": TEXT, "session_id": session_id}).status_code == 404


# --- the gateway ---------------------------------------------------------------------------


def test_gateway_uses_known_values() -> None:
    sys.path.insert(0, str(Path(__file__).parents[1] / "gateway"))
    from gateway_helpers import FakeLlm, MockUpstream, make_app

    upstream = MockUpstream()
    with TestClient(
        make_app(upstream, llm=FakeLlm(names=())), raise_server_exceptions=False
    ) as api:
        session_id = preload(api, (NAME, "PERSON"))
        response = api.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": [{"role": "user", "content": TEXT}]},
            headers={"X-PII-Guard-Session": session_id, "X-PII-Guard-Mode": "fast"},
        )
        assert response.status_code == 200, response.text
        sent = upstream.bodies[0]["messages"][0]["content"]
        assert "Tihamér" not in sent
        assert len({i for t, i in PLACEHOLDER_RE.findall(sent) if t == "PERSON"}) == 1
        assert all(form not in sent for form in FORMS)
        # The answer echoes the placeholders; they come back restored.
        assert NAME in response.json()["choices"][0]["message"]["content"]
