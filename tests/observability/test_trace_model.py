"""The traffic event never holds a model name the gateway has not checked (LAB-1358).

``model`` goes upstream verbatim and is checked like an identifier (LAB-1563); a refused or
failed call never got that far, so its model string is withheld from the event, the ``full``
original included. The upstream's reported model is kept only when it is model-id shaped.
All values are fictional (ADR 0005).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.gateway.config import Mode
from pii_guard.gateway.outbound import OutboundCheck
from pii_guard.gateway.service import RequestStats
from pii_guard.gateway.trace import MODEL_WITHHELD, CallTrace
from pii_guard.observability import Observability, ObservabilitySettings, RequestTimer
from pii_guard.types import PiiGuardError

TENANT_KEY = "0" * 32  # fixed test key (avoids gitleaks generic-api-key)
UPSTREAM_URL = "http://upstream.test/v1"
PII_MODEL = "gpt-4o-teszt.elek@example.com"
MESSAGES = [{"role": "user", "content": "Szia! Hogy vagy?"}]


def _observability(level: str = "full") -> Observability:
    return Observability(ObservabilitySettings(traffic_log=level))


def _event(obs: Observability) -> dict[str, Any]:
    (event,) = obs.traffic.recent()
    return event


def _trace(obs: Observability, model: str) -> CallTrace:
    trace = CallTrace(obs, RequestTimer(), {"model": model, "messages": MESSAGES})
    trace.stats = RequestStats(mode=Mode.FAST)
    return trace


# --- unit: CallTrace -----------------------------------------------------------------------


def test_refused_call_withholds_the_model_everywhere_in_a_full_event() -> None:
    obs = _observability()
    _trace(obs, PII_MODEL).fail(PiiGuardError("personal data in model"))
    event = _event(obs)
    assert event["outcome"] == "refused"
    assert event["model"] == MODEL_WITHHELD
    assert event["request"]["original"]["model"] == MODEL_WITHHELD
    assert "example.com" not in json.dumps(event)


def test_unexpected_error_withholds_the_model() -> None:
    obs = _observability()
    _trace(obs, PII_MODEL).fail(RuntimeError("boom"))
    event = _event(obs)
    assert event["outcome"] == "error"
    assert "example.com" not in json.dumps(event)


def test_blocked_outbound_check_withholds_the_model() -> None:
    obs = _observability("masked")
    trace = _trace(obs, PII_MODEL)
    assert trace.stats is not None
    trace.stats.outbound = OutboundCheck(texts=2)
    trace.stats.outbound.hits["EMAIL"] = 1
    trace.finish()
    assert _event(obs)["model"] == MODEL_WITHHELD


def test_checked_model_is_kept_and_upstream_model_must_be_id_shaped() -> None:
    obs = _observability()
    trace = _trace(obs, "gpt-4o-mini")
    assert trace.stats is not None
    trace.stats.outbound = OutboundCheck(texts=2)
    trace.stats.upstream_status = 200
    trace.upstream_body = json.dumps({"model": "Teszt Elek <teszt.elek@example.com>"}).encode()
    trace.finish()
    event = _event(obs)
    assert event["model"] == "gpt-4o-mini"
    assert event["request"]["original"]["model"] == "gpt-4o-mini"
    assert event["upstream"]["model"] == MODEL_WITHHELD
    assert event["response"]["masked"]["model"] == MODEL_WITHHELD
    assert "teszt.elek" not in json.dumps(event)


def test_real_model_ids_pass_the_shape_check() -> None:
    for model in (
        "gpt-4o-2024-08-06",
        "claude-3-5-sonnet@20240620",
        "accounts/fireworks/models/llama-v3p1-8b-instruct",
        "meta-llama/Llama-3.1-8B-Instruct:free",
    ):
        obs = _observability("masked")
        trace = _trace(obs, model)
        assert trace.stats is not None
        trace.stats.outbound = OutboundCheck(texts=1)
        trace.upstream_body = json.dumps({"model": model}).encode()
        trace.finish()
        event = _event(obs)
        assert event["model"] == model and event["upstream"]["model"] == model


# --- end to end: the gateway refuses a PII-shaped model, the event does not hold it --------


def _app(level: str, requests: list[httpx.Request]) -> Any:
    settings = Settings(
        tenant_key=TENANT_KEY, upstream_base_url=UPSTREAM_URL, upstream_api_key="sk-up-0000"
    )
    app = create_app(settings, ObservabilitySettings(traffic_log=level))

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1_800_000_000,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Rendben."},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    app.state.gateway_transport = httpx.MockTransport(handler)
    return app


def test_gateway_refusal_of_a_pii_model_leaves_no_trace_of_it() -> None:
    requests: list[httpx.Request] = []
    with TestClient(_app("full", requests)) as client:
        r = client.post("/v1/chat/completions", json={"model": PII_MODEL, "messages": MESSAGES})
        assert r.status_code >= 400, r.text
        (event,) = client.get("/v1/traffic").json()["events"]
    assert requests == []  # fail closed: nothing went upstream
    assert event["outcome"] in {"refused", "blocked"}
    assert event["model"] == MODEL_WITHHELD
    assert "example.com" not in json.dumps(event)


def test_gateway_success_keeps_the_checked_model() -> None:
    requests: list[httpx.Request] = []
    with TestClient(_app("full", requests)) as client:
        r = client.post("/v1/chat/completions", json={"model": "test-model", "messages": MESSAGES})
        assert r.status_code == 200, r.text
        (event,) = client.get("/v1/traffic").json()["events"]
    assert event["outcome"] == "ok"
    assert event["model"] == "test-model"
    assert event["upstream"]["model"] == "test-model"
