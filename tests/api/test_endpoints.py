"""``/v1/analyze``, ``/v1/mask`` and ``/v1/unmask`` against the rules detector and vault."""

from __future__ import annotations

import logging

import pytest
from api_helpers import FAKE_EMAIL, FAKE_PHONE, SAMPLE_TEXT, TEST_TENANT_KEY
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.api.deps import RegistryAnalyzer
from pii_guard.config import Settings
from pii_guard.types import DetectionError, EntityType, Span
from pii_guard.vault import PLACEHOLDER_RE

# --- analyze -------------------------------------------------------------------------------


def test_analyze_returns_sorted_public_spans(api: TestClient) -> None:
    response = api.post("/v1/analyze", json={"text": SAMPLE_TEXT, "language": "hu"})
    assert response.status_code == 200
    spans = response.json()["spans"]
    assert [s["entity_type"] for s in spans] == ["EMAIL", "PHONE", "EMAIL"]
    assert [s["start"] for s in spans] == sorted(s["start"] for s in spans)
    for span in spans:
        assert set(span) == {"start", "end", "entity_type", "score", "detector", "policy"}
        assert span["detector"] == "rules"
        assert span["policy"] == "mask"
        assert SAMPLE_TEXT[span["start"] : span["end"]] in {FAKE_EMAIL, FAKE_PHONE}
    assert FAKE_EMAIL not in response.text
    assert FAKE_PHONE not in response.text


def test_analyze_without_tenant_key_works(client: TestClient) -> None:
    response = client.post("/v1/analyze", json={"text": SAMPLE_TEXT})
    assert response.status_code == 200
    assert len(response.json()["spans"]) == 3


def test_analyze_empty_text(api: TestClient) -> None:
    assert api.post("/v1/analyze", json={"text": ""}).json() == {"spans": []}


def test_language_defaults_to_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    class Recorder:
        def analyze(self, text: str, language: str) -> list[Span]:
            seen.append(language)
            return []

    app = create_app(Settings(tenant_key=TEST_TENANT_KEY, default_language="de"))
    app.state.analyzer = Recorder()
    with TestClient(app) as client:
        client.post("/v1/analyze", json={"text": "x"})
        client.post("/v1/mask", json={"text": "x", "language": "hu"})
    assert seen == ["de", "hu"]


# --- mask / unmask -------------------------------------------------------------------------


def test_mask_then_unmask_round_trip(api: TestClient) -> None:
    response = api.post("/v1/mask", json={"text": SAMPLE_TEXT, "session_id": None})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"masked_text", "session_id", "entities", "kept"}
    assert body["kept"] == []
    masked = body["masked_text"]
    assert FAKE_EMAIL not in masked
    assert FAKE_PHONE not in masked
    assert FAKE_EMAIL not in response.text
    assert body["session_id"].startswith("s_")

    by_type = {e["entity_type"]: e for e in body["entities"]}
    assert set(by_type) == {"EMAIL", "PHONE"}
    assert by_type["EMAIL"]["count"] == 2
    assert by_type["PHONE"]["count"] == 1
    for entity in body["entities"]:
        assert PLACEHOLDER_RE.fullmatch(entity["placeholder"])
        assert masked.count(entity["placeholder"]) == entity["count"]

    answer = f"Rendben, {by_type['EMAIL']['placeholder']} címre írok."
    response = api.post("/v1/unmask", json={"text": answer, "session_id": body["session_id"]})
    assert response.status_code == 200
    assert response.json() == {"text": f"Rendben, {FAKE_EMAIL} címre írok.", "unresolved": []}

    response = api.post("/v1/unmask", json={"text": masked, "session_id": body["session_id"]})
    assert response.json()["text"] == SAMPLE_TEXT


def test_mask_counts_are_per_request(api: TestClient) -> None:
    first = api.post("/v1/mask", json={"text": SAMPLE_TEXT}).json()
    session_id = first["session_id"]
    second = api.post("/v1/mask", json={"text": f"Csak {FAKE_EMAIL}", "session_id": session_id})
    assert second.status_code == 200
    body = second.json()
    assert body["session_id"] == session_id
    email = next(e for e in first["entities"] if e["entity_type"] == "EMAIL")
    # Same value, same placeholder across calls; counts cover this call only.
    assert body["entities"] == [
        {"placeholder": email["placeholder"], "entity_type": "EMAIL", "count": 1}
    ]

    nothing = api.post("/v1/mask", json={"text": "Semmi.", "session_id": session_id}).json()
    assert nothing["entities"] == []
    assert nothing["masked_text"] == "Semmi."


def test_mask_new_sessions_are_distinct(api: TestClient) -> None:
    a = api.post("/v1/mask", json={"text": SAMPLE_TEXT}).json()
    b = api.post("/v1/mask", json={"text": SAMPLE_TEXT}).json()
    assert a["session_id"] != b["session_id"]


def test_unmask_reports_unresolved(api: TestClient) -> None:
    session_id = api.post("/v1/mask", json={"text": SAMPLE_TEXT}).json()["session_id"]
    response = api.post(
        "/v1/unmask",
        json={"text": "Kedves [[PERSON_beef]] és [[PERSON_beef]]!", "session_id": session_id},
    )
    assert response.status_code == 200
    assert response.json() == {
        "text": "Kedves [[PERSON_beef]] és [[PERSON_beef]]!",
        "unresolved": ["[[PERSON_beef]]"],
    }


def test_unknown_session_is_404(api: TestClient) -> None:
    for path in ("/v1/unmask", "/v1/mask"):
        response = api.post(path, json={"text": SAMPLE_TEXT, "session_id": "s_doesnotexist"})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
        assert FAKE_EMAIL not in response.text


def test_unmask_requires_session_id(api: TestClient) -> None:
    response = api.post("/v1/unmask", json={"text": "x"})
    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "invalid_request",
        "message": "invalid request body: body.session_id",
    }


def test_validation_error_does_not_echo_text(api: TestClient) -> None:
    response = api.post("/v1/mask", json={"text": SAMPLE_TEXT, "language": 12345678})
    assert response.status_code == 422
    assert FAKE_EMAIL not in response.text


# --- configuration -------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/v1/mask", "/v1/unmask"])
def test_vault_endpoints_fail_closed_without_tenant_key(client: TestClient, path: str) -> None:
    response = client.post(path, json={"text": SAMPLE_TEXT, "session_id": "s_x"})
    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "vault_not_configured"
    assert "PII_GUARD_TENANT_KEY" in error["message"]
    assert "masked_text" not in response.text
    assert FAKE_EMAIL not in response.text


def test_invalid_tenant_key_fails_closed_without_echo() -> None:
    bad_key = "zz-not-hex-zz"
    with TestClient(create_app(Settings(tenant_key=bad_key))) as client:
        response = client.post("/v1/mask", json={"text": SAMPLE_TEXT})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "vault_not_configured"
    assert bad_key not in response.text


def test_detector_names_are_configurable() -> None:
    app = create_app(Settings(tenant_key=TEST_TENANT_KEY))
    app.state.detector_names = ["no_such_detector"]
    with TestClient(app) as client:
        response = client.post("/v1/mask", json={"text": SAMPLE_TEXT})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "detection_failed"
    assert "masked_text" not in response.text


def test_registry_analyzer_requires_detectors() -> None:
    with pytest.raises(DetectionError):
        RegistryAnalyzer([])


def test_registry_analyzer_uses_the_pipeline_resolver() -> None:
    """A person inside an organisation name stays a PERSON (keep types lose overlaps)."""

    class Org:
        name = "org"

        def detect(self, text: str, language: str = "hu") -> list[Span]:
            return [Span(0, 15, EntityType.ORGANIZATION, text, 0.6, self.name)]

    class Person:
        name = "person"

        def detect(self, text: str, language: str = "hu") -> list[Span]:
            return [Span(0, 10, EntityType.PERSON, text[:10], 0.9, self.name)]

    analyzer = RegistryAnalyzer(["rules"])
    analyzer.pipeline.detectors = [Org(), Person()]
    spans = analyzer.analyze("Teszt Elek Kft.", "hu")
    assert [(s.entity_type, s.start, s.end) for s in spans] == [
        (EntityType.PERSON, 0, 10),
        (EntityType.ORGANIZATION, 11, 14),
    ]


# --- logging -------------------------------------------------------------------------------


def test_logs_never_contain_raw_values(api: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    api.post("/v1/analyze", json={"text": SAMPLE_TEXT})
    masked = api.post("/v1/mask", json={"text": SAMPLE_TEXT}).json()
    api.post("/v1/unmask", json={"text": masked["masked_text"], "session_id": masked["session_id"]})
    api.post("/v1/unmask", json={"text": SAMPLE_TEXT, "session_id": "s_nope"})
    api.post("/v1/mask", json={"text": SAMPLE_TEXT, "language": 12345678})

    access = [r.getMessage() for r in caplog.records if r.name == "pii_guard.api.access"]
    assert any(line.startswith("POST /v1/analyze 200") for line in access)
    assert any(line.startswith("POST /v1/mask 200") and "replaced=3" in line for line in access)
    assert any(line.startswith("POST /v1/unmask 200") for line in access)
    assert any("404" in line and "error=not_found" in line for line in access)
    assert any("422" in line and "error=invalid_request" in line for line in access)

    logged = caplog.text + "\n".join(r.getMessage() for r in caplog.records)
    for value in (FAKE_EMAIL, FAKE_PHONE, "teszt.elek", masked["session_id"]):
        assert value not in logged
