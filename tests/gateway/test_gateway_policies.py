"""Entity policies in the gateway: block refuses and forwards nothing; keep stays in place.

All values are fictional (ADR 0005).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from gateway_helpers import (
    EMAILS,
    TEST_TENANT_KEY,
    UPSTREAM_KEY,
    UPSTREAM_URL,
    FakeLlm,
    MockUpstream,
    conversation_turn_one,
    make_app,
)

from pii_guard.config import Settings
from pii_guard.gateway import GatewayConfig
from pii_guard.gateway.detection import gateway_policies
from pii_guard.policy import Policy
from pii_guard.types import EntityType, Span

ORG = "Minta Kft"


def _settings(**extra: object) -> Settings:
    return Settings(
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url=UPSTREAM_URL,
        upstream_api_key=UPSTREAM_KEY,
        **extra,
    )


@pytest.mark.parametrize("stream", [False, True])
def test_block_policy_refuses_and_forwards_nothing(stream: bool) -> None:
    upstream = MockUpstream()
    app = make_app(upstream, settings=_settings(policy_overrides="EMAIL=block"))
    with TestClient(app) as http:
        response = http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": conversation_turn_one(), "stream": stream},
        )
        assert len(app.state.gateway.vault) == 0
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "blocked_entity"
    assert "EMAIL" in response.json()["error"]["message"]
    assert upstream.requests == []
    for value in (*EMAILS, "Teszt Elek"):
        assert value not in response.text


def test_keep_policy_leaves_values_and_override_masks_them() -> None:
    messages = [{"role": "user", "content": f"Teszt Elek a {ORG} nevében ír."}]

    class OrgLlm(FakeLlm):
        def detect(self, text: str, language: str = "hu") -> list[Span]:
            spans = super().detect(text, language)
            start = text.find(ORG)
            if start >= 0:
                end = start + len(ORG)
                spans.append(Span(start, end, EntityType.ORGANIZATION, ORG, 0.9, self.name))
            return spans

    for overrides, org_forwarded in ((None, True), ("ORGANIZATION=mask", False)):
        upstream = MockUpstream()
        app = make_app(upstream, llm=OrgLlm(), settings=_settings(policy_overrides=overrides))
        with TestClient(app) as http:
            response = http.post("/v1/chat/completions", json={"model": "m", "messages": messages})
        assert response.status_code == 200
        forwarded = upstream.requests[0].content.decode()
        assert "Teszt Elek" not in forwarded
        assert (ORG in forwarded) is org_forwarded


def test_deprecated_keep_types_alias() -> None:
    settings = _settings()
    assert gateway_policies(settings, GatewayConfig()).keep_types == {
        EntityType.ORGANIZATION,
        EntityType.COMPANY_ID_HU,
        EntityType.STAMP,
    }
    legacy = gateway_policies(settings, GatewayConfig(keep_types="ORGANIZATION,PHONE"))
    assert legacy.of(EntityType.PHONE) is Policy.KEEP
    assert legacy.of(EntityType.COMPANY_ID_HU) is Policy.MASK
    assert legacy.of(EntityType.ORGANIZATION) is Policy.KEEP
    assert gateway_policies(settings, GatewayConfig(keep_types="")).keep_types == frozenset()
    # Explicit policy overrides win over the legacy keep set.
    both = gateway_policies(
        _settings(policy_overrides="PHONE=block"), GatewayConfig(keep_types="PHONE")
    )
    assert both.of(EntityType.PHONE) is Policy.BLOCK
