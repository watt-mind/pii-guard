"""Escalate mode through the gateway (LAB-1766): header and traffic counts, the per-session
decision cache, no key -> unavailable, local-only refusal, fast mode untouched.

The LLM detector is a fake (no network); all values are fictional (ADR 0005).
"""

from __future__ import annotations

import re
import threading
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway_helpers import TEST_TENANT_KEY, UPSTREAM_KEY, UPSTREAM_URL, MockUpstream

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.detect.rules import RuleDetector
from pii_guard.gateway import GatewayConfig, Mode, build_mode_detectors
from pii_guard.observability import ObservabilitySettings
from pii_guard.types import DetectionError, EntityType, Span

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

NAME = "Quillfeather"
EMAIL = "jane.placeholder@example.net"


class NameLlm:
    """Finds the fictional surname; records what it was sent."""

    name = "llm"
    model = "fake-llm"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[str] = []
        self._lock = threading.Lock()

    def detect(self, text: str, language: str = "en") -> list[Span]:
        with self._lock:
            self.sent.append(text)
        if self.fail:
            raise DetectionError("fake llm failed")
        return [
            Span(m.start(), m.end(), EntityType.PERSON, NAME, 0.9, self.name)
            for m in re.finditer(NAME, text)
        ]


def settings() -> Settings:
    return Settings(
        _env_file=None,
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url=UPSTREAM_URL,
        upstream_api_key=UPSTREAM_KEY,
    )


def make(llm: Any, upstream: MockUpstream, **config: Any) -> TestClient:
    s = settings()
    app = create_app(s, ObservabilitySettings(traffic_log="masked"))
    cfg = GatewayConfig(**config)
    app.state.gateway_config = cfg
    app.state.gateway_transport = upstream.transport()
    app.state.gateway_detectors = build_mode_detectors(
        s, cfg, base=[RuleDetector()], escalate_llm=llm, llm_detector=llm
    )
    return TestClient(app)


def chat(client: TestClient, content: str, mode: str | None = "escalate", **headers: str):
    if mode is not None:
        headers["X-PII-Guard-Mode"] = mode
    return client.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "user", "content": content}]},
        headers=headers,
    )


def test_escalate_masks_what_the_llm_adds_and_reports_the_count() -> None:
    upstream, llm = MockUpstream(), NameLlm()
    client = make(llm, upstream)
    r = chat(client, f"Please write to Ms. {NAME} at {EMAIL}.")
    assert r.status_code == 200, r.text
    assert r.headers["X-PII-Guard-Mode"] == "escalate"
    assert r.headers["X-PII-Guard-Escalations"] == "1"
    sent = upstream.bodies[0]["messages"][-1]["content"]
    assert NAME not in sent and EMAIL not in sent
    assert all(EMAIL not in text for text in llm.sent)
    [event] = client.get("/v1/traffic").json()["events"]
    assert event["mode"] == "escalate"
    assert event["audit_escalations"] == 1


def test_nothing_uncertain_makes_no_llm_call() -> None:
    upstream, llm = MockUpstream(), NameLlm()
    client = make(llm, upstream)
    r = chat(client, f"Send the report to {EMAIL}.")
    assert r.headers["X-PII-Guard-Escalations"] == "0"
    assert llm.sent == []


def test_the_session_cache_avoids_a_second_call() -> None:
    upstream, llm = MockUpstream(), NameLlm()
    client = make(llm, upstream)
    first = chat(client, f"Hello Ms. {NAME}.")
    session = first.headers["X-PII-Guard-Session"]
    second = chat(client, f"Hello Ms. {NAME}.", **{"X-PII-Guard-Session": session})
    assert second.status_code == 200
    assert len(llm.sent) == 1
    assert second.headers["X-PII-Guard-Escalations"] == "0"


def test_a_failing_llm_fails_closed_and_the_request_goes_on() -> None:
    upstream, llm = MockUpstream(), NameLlm(fail=True)
    client = make(llm, upstream)
    r = chat(client, f"Please write to Ms. {NAME}.")
    assert r.status_code == 200, r.text
    assert r.headers["X-PII-Guard-Escalation-Failures"] == "1"
    assert NAME not in upstream.bodies[0]["messages"][-1]["content"]


def test_fast_mode_is_unchanged() -> None:
    upstream, llm = MockUpstream(), NameLlm()
    client = make(llm, upstream)
    r = chat(client, f"Please write to Ms. {NAME} at {EMAIL}.", mode=None)
    assert r.headers["X-PII-Guard-Mode"] == "fast"
    assert "X-PII-Guard-Escalations" not in r.headers
    assert llm.sent == []
    [event] = client.get("/v1/traffic").json()["events"]
    assert "audit_escalations" not in event


def test_escalate_without_a_key_is_unavailable_and_sends_nothing() -> None:
    upstream = MockUpstream()
    s = settings()
    app = create_app(s)
    app.state.gateway_transport = upstream.transport()
    app.state.gateway_detectors = build_mode_detectors(s, GatewayConfig(), base=[RuleDetector()])
    r = chat(TestClient(app), f"Please write to Ms. {NAME}.")
    assert r.status_code == 503, r.text
    error = r.json()["error"]
    assert error["code"] == "detection_unavailable"
    assert "escalate mode needs PII_GUARD_LLM_DETECTOR_API_KEY" in error["message"]
    assert upstream.requests == []


def test_local_only_refuses_escalate() -> None:
    s = Settings(
        _env_file=None,
        detection_profile="local-only",
        detectors=("rules",),
        tenant_key="42" * 32,
        ner_fallback="off",
        upstream_base_url="https://synthetic-model.example/v1",
    )
    assert set(build_mode_detectors(s, GatewayConfig())) == {Mode.FAST}
    app = create_app(s)
    app.state.gateway_transport = httpx.MockTransport(lambda request: pytest.fail("forwarded"))
    r = chat(TestClient(app), f"Please write to Ms. {NAME}.")
    assert r.status_code >= 400
    assert r.json()["error"]["code"] == "detection_profile_denied"
    assert "escalate" in r.json()["error"]["message"]


def test_status_lists_escalate_between_fast_and_audit() -> None:
    upstream, llm = MockUpstream(), NameLlm()
    client = make(llm, upstream)
    modes = client.get("/v1/status", headers={"host": "localhost:8787"}).json()["gateway"]["modes"]
    assert list(modes) == ["fast", "escalate", "audit"]
    assert modes["escalate"]["detectors"][-1] == "llm"
