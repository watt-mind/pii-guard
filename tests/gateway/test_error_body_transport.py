"""Broken non-2xx upstream bodies are transport failures on both gateway APIs."""

import json
import logging
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi.testclient import TestClient
from gateway_helpers import TEST_TENANT_KEY, UPSTREAM_URL, FakeLlm

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.gateway import GatewayConfig, Mode, build_mode_detectors
from pii_guard.observability import ObservabilitySettings


@pytest.mark.parametrize("path", ["/v1/chat/completions", "/v1/responses"])
@pytest.mark.parametrize("status", [429, 404, 503])
@pytest.mark.parametrize(
    "error_type", [httpx.ReadError, httpx.RemoteProtocolError, httpx.ReadTimeout]
)
@pytest.mark.parametrize("stream", [False, True])
def test_error_body_transport_failure_is_sanitized_and_recorded(
    path: str,
    status: int,
    error_type: type[httpx.HTTPError],
    stream: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    body_marker = "synthetic-private-upstream-body"
    exception_marker = "synthetic-private-transport-detail"

    class BrokenBody(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield json.dumps({"error": {"message": body_marker}}).encode()
            raise error_type(exception_marker)

        async def aclose(self) -> None:
            self.closed = True

    broken = BrokenBody()
    settings = Settings(tenant_key=TEST_TENANT_KEY, upstream_base_url=UPSTREAM_URL)
    config = GatewayConfig(mode=Mode.AUDIT)
    app = create_app(settings, ObservabilitySettings(traffic_log="masked"))
    app.state.gateway_config = config
    app.state.gateway_detectors = build_mode_detectors(settings, config, llm_detector=FakeLlm())
    app.state.gateway_transport = httpx.MockTransport(
        lambda request: httpx.Response(status, stream=broken)
    )
    caplog.set_level(logging.INFO, logger="pii_guard")
    content = (
        {"messages": [{"role": "user", "content": "Hello."}]}
        if path.endswith("completions")
        else {"input": "Hello."}
    )
    with TestClient(app) as client:
        response = client.post(path, json={"model": "test-model", "stream": stream, **content})
        traffic = client.get("/v1/traffic").json()["events"]

    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "code": "upstream_unavailable",
            "message": f"upstream response failed ({error_type.__name__})",
        }
    }
    assert broken.closed
    (event,) = traffic
    assert event["outcome"] == "refused"
    assert event["error"] == {"code": "upstream_unavailable", "status": 502}
    front_end = "chat.completions" if path.endswith("completions") else "responses"
    assert any(
        record.getMessage().startswith(f"{front_end} upstream_unreachable ")
        for record in caplog.records
    )
    observable = response.text + json.dumps(traffic) + caplog.text
    assert body_marker not in observable
    assert exception_marker not in observable
