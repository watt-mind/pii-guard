"""Rejected requests cannot copy synthetic personal data into API errors or traces."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gateway_helpers import MockUpstream, make_app
from pydantic import BaseModel, ConfigDict

from pii_guard.api.errors import install_error_handlers
from pii_guard.observability import Observability, ObservabilitySettings

SYNTHETIC_VALUES = ("fixture.person@example.com", "sk_fixture_private_12345")


@pytest.mark.parametrize("value", SYNTHETIC_VALUES)
@pytest.mark.parametrize(
    ("path", "location", "body"),
    [
        (
            "/v1/chat/completions",
            "messages.0.content.0",
            {"messages": [{"role": "user", "content": [{"type": None}]}]},
        ),
        ("/v1/responses", "input.0", {"input": [{"type": None}]}),
        (
            "/v1/responses",
            "input.0.content.0",
            {"input": [{"role": "user", "content": [{"type": None}]}]},
        ),
        ("/v1/responses", "tools.0", {"input": "hello", "tools": [{"type": None}]}),
        (
            "/v1/messages",
            "messages.0.content.0",
            {"messages": [{"role": "user", "content": [{"type": None}]}]},
        ),
        (
            "/v1/messages",
            "tools.0",
            {"messages": [{"role": "user", "content": "hello"}], "tools": [{"type": None}]},
        ),
    ],
)
def test_unknown_types_never_echo_values(
    value: str, path: str, location: str, body: dict[str, Any]
) -> None:
    # Replace the one sentinel without mutating parametrized request dictionaries.
    payload = json.loads(json.dumps(body).replace("null", json.dumps(value)))
    payload["model"] = "fixture-model"
    if path == "/v1/messages":
        payload["max_tokens"] = 16
    upstream = MockUpstream()
    app = make_app(upstream)
    app.state.observability = Observability(ObservabilitySettings(traffic_log="masked"))
    with TestClient(app) as client:
        response = client.post(path, json=payload)
        events = client.get("/v1/traffic").json()["events"]
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_content"
    assert location in response.json()["error"]["message"]
    assert value not in response.text
    assert len(events) == 1
    assert value not in json.dumps(events)
    assert not upstream.requests


@pytest.mark.parametrize("value", SYNTHETIC_VALUES)
def test_unknown_keys_never_echo_values(value: str) -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "fixture-model",
                "messages": [{"role": "user", "content": "hello", value: True}],
            },
        )
    assert response.status_code == 400
    assert "messages.0.#2" in response.json()["error"]["message"]
    assert value not in response.text
    assert not upstream.requests


@pytest.mark.parametrize("value", SYNTHETIC_VALUES)
def test_validation_locations_only_contain_schema_fields(value: str) -> None:
    class Body(BaseModel):
        model_config = ConfigDict(extra="forbid")
        counts: dict[str, int]
        text: str

    app = FastAPI()
    install_error_handlers(app)

    # Bind explicitly: postponed annotations on this local class are not resolvable by FastAPI.
    def endpoint(body: Body) -> None:
        pass

    endpoint.__annotations__["body"] = Body
    app.post("/fixture")(endpoint)
    with TestClient(app) as client:
        response = client.post(
            "/fixture", json={"counts": {value: "invalid"}, "text": 1, value: True}
        )
    assert response.status_code == 422
    assert value not in response.text
    assert "body.counts.<field>" in response.json()["error"]["message"]
    assert "body.text" in response.json()["error"]["message"]
