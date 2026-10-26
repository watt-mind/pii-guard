"""Entity policies in ``/v1/analyze`` and ``/v1/mask``, and ``PII_GUARD_DETECTORS``.

All values are fictional (ADR 0005).
"""

from __future__ import annotations

import logging
import re

import pytest
from api_helpers import FAKE_EMAIL, TEST_TENANT_KEY
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.api.deps import build_detector
from pii_guard.config import Settings
from pii_guard.registry import register_detector
from pii_guard.types import DetectionError, EntityType, Span

NAME = "Teszt Elek"
ORG = "Minta Kft"
COMPANY_ID = "01-09-123456"
TEXT = f"{NAME} ({FAKE_EMAIL}) a {ORG} nevében ír, Cg. {COMPANY_ID}. Másolat: {FAKE_EMAIL}"


class _Names:
    """Stands in for NER/LLM: finds the fictional person and organisation."""

    name = "apitest_names"

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        spans = []
        for value, entity_type in ((NAME, EntityType.PERSON), (ORG, EntityType.ORGANIZATION)):
            for m in re.finditer(re.escape(value), text):
                spans.append(Span(m.start(), m.end(), entity_type, value, 0.9, self.name))
        return spans


@pytest.fixture(scope="module", autouse=True)
def _register() -> None:
    register_detector("apitest_names", f"{__name__}:_Names", replace=True)


def _app(**settings: object) -> TestClient:
    base = {"tenant_key": TEST_TENANT_KEY, "detectors": ("rules", "apitest_names")}
    app = create_app(Settings(**{**base, **settings}))
    return TestClient(app, raise_server_exceptions=False)


def test_detectors_come_from_settings() -> None:
    with _app() as client:
        body = client.post("/v1/mask", json={"text": TEXT}).json()
        assert client.app.state.detector_names == ["rules", "apitest_names"]
    assert NAME not in body["masked_text"]
    assert "[[PERSON_" in body["masked_text"]


def test_unknown_detector_fails_at_startup() -> None:
    with pytest.raises(DetectionError):
        create_app(Settings(tenant_key=TEST_TENANT_KEY, detectors=("rules", "no_such_one")))


def test_keep_types_stay_in_place_and_are_reported() -> None:
    with _app() as client:
        response = client.post("/v1/mask", json={"text": TEXT})
    assert response.status_code == 200
    body = response.json()
    masked = body["masked_text"]
    assert ORG in masked
    assert COMPANY_ID in masked
    assert FAKE_EMAIL not in masked and NAME not in masked
    assert body["kept"] == [
        {"entity_type": "COMPANY_ID_HU", "count": 1},
        {"entity_type": "ORGANIZATION", "count": 1},
    ]
    assert {e["entity_type"] for e in body["entities"]} == {"PERSON", "EMAIL"}
    # Kept values are never echoed outside the text the caller sent.
    assert response.text.count(ORG) == 1


def test_overrides_mask_a_keep_type() -> None:
    with _app(policy_overrides="ORGANIZATION=mask") as client:
        body = client.post("/v1/mask", json={"text": TEXT}).json()
    assert ORG not in body["masked_text"]
    assert "[[ORGANIZATION_" in body["masked_text"]
    assert body["kept"] == [{"entity_type": "COMPANY_ID_HU", "count": 1}]


def test_block_refuses_without_echo_or_storage(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    with _app(policy_overrides="EMAIL=block") as client:
        response = client.post("/v1/mask", json={"text": TEXT})
        vault = client.app.state.vault
        assert len(vault) == 0  # the session this request created was dropped
    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    error = response.json()["error"]
    assert error["code"] == "blocked_entity"
    assert "EMAIL (2)" in error["message"]
    for value in (FAKE_EMAIL, NAME, ORG, "[[PERSON_"):
        assert value not in response.text
        assert value not in caplog.text
    access = [r.getMessage() for r in caplog.records if r.name == "pii_guard.api.access"]
    assert any(
        "422" in a and "error=blocked_entity" in a and "blocked=EMAIL:2" in a for a in access
    )


def test_block_keeps_an_existing_session_unchanged() -> None:
    with _app(policy_overrides="EMAIL=block") as client:
        first = client.post("/v1/mask", json={"text": f"{NAME} ír."}).json()
        session = first["session_id"]
        refused = client.post("/v1/mask", json={"text": TEXT, "session_id": session})
        assert refused.status_code == 422
        entities = client.app.state.vault.session(session).entities()
        again = client.post(
            "/v1/unmask", json={"text": first["masked_text"], "session_id": session}
        )
    assert [(t, n) for _, t, n in entities] == [(EntityType.PERSON, 1)]
    assert again.json()["text"] == f"{NAME} ír."


def test_analyze_reports_each_spans_policy() -> None:
    with _app(policy_overrides="EMAIL=block") as client:
        response = client.post("/v1/analyze", json={"text": TEXT})
    assert response.status_code == 200  # analyze reports block spans, it doesn't refuse
    policies = {(s["entity_type"], s["policy"]) for s in response.json()["spans"]}
    assert policies == {
        ("PERSON", "mask"),
        ("EMAIL", "block"),
        ("ORGANIZATION", "keep"),
        ("COMPANY_ID_HU", "keep"),
    }
    assert FAKE_EMAIL not in response.text


def test_llm_detector_gets_settings_and_reasoning_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_LLM_DETECTOR_REASONING_EFFORT", "minimal")
    settings = Settings(llm_detector_url="https://llm.test/v1", llm_detector_api_key="k-test")
    detector = build_detector("llm", settings)
    assert detector.name == "llm"
    assert detector.url == "https://llm.test/v1/chat/completions"  # type: ignore[attr-defined]
    assert detector.reasoning_effort == "minimal"  # type: ignore[attr-defined]
    assert "k-test" not in repr(detector)
