"""Live gateway check against the Meta Model API. Fictional conversation only (ADR 0005).

Skipped without ``META_API_KEY``. Upstream and LLM detector are both Muse Spark on the Meta
Model API; ``PII_GUARD_LIVE_DETECTOR_MODEL`` overrides the detector model.
"""

from __future__ import annotations

import os
import time

import httpx
import openai
import pytest
from fastapi.testclient import TestClient
from gateway_helpers import TEST_TENANT_KEY, conversation_turn_one, leaked_values

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.detect.llm import LlmDetector
from pii_guard.gateway import GatewayConfig, build_mode_detectors

LIVE_KEY = os.environ.get("META_API_KEY")
DETECTOR_MODEL = os.environ.get("PII_GUARD_LIVE_DETECTOR_MODEL", "muse-spark-1.3")
META_URL = "https://api.meta.ai/v1"

pytestmark = [
    pytest.mark.live,
    # A live check exercises the real detector stack, NER included when it is installed.
    pytest.mark.ner_autodetect,
    pytest.mark.skipif(not LIVE_KEY, reason="META_API_KEY not set"),
    pytest.mark.filterwarnings("ignore::DeprecationWarning"),
]


class RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.inner = httpx.AsyncHTTPTransport()
        self.bodies: list[bytes] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(request.content)
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self.inner.aclose()


@pytest.mark.parametrize("mode", ["strict", "fast"])
@pytest.mark.parametrize("stream", [False, True])
def test_live_meta_round_trip(mode: str, stream: bool) -> None:
    settings = Settings(
        tenant_key=TEST_TENANT_KEY, upstream_base_url=META_URL, upstream_api_key=LIVE_KEY
    )
    config = GatewayConfig(detection_timeout=60)
    llm = LlmDetector(
        base_url=META_URL,
        api_key=LIVE_KEY,
        model=DETECTOR_MODEL,
        reasoning_effort="minimal",
        settings=settings,
    )
    app = create_app(settings)
    transport = RecordingTransport()
    app.state.gateway_transport = transport
    app.state.gateway_detectors = build_mode_detectors(settings, config, llm_detector=llm)
    hint = (
        "Values like [[EMAIL_1a2b3c]] are the user's real data, masked for privacy. "
        "Copy them verbatim whenever you need them."
    )
    messages = [
        {"role": "system", "content": hint},
        *conversation_turn_one(),
        {"role": "user", "content": "Ismételd meg pontosan a nevemet és az e-mail címemet!"},
    ]
    with TestClient(app) as http:
        client = openai.OpenAI(base_url="http://testserver/v1", api_key="unused", http_client=http)
        started = time.perf_counter()
        result = client.chat.completions.create(
            model="muse-spark-1.3",
            messages=messages,
            stream=stream,
            reasoning_effort="minimal",
            extra_headers={"X-PII-Guard-Mode": mode},
        )
        if stream:
            answer = "".join(c.choices[0].delta.content or "" for c in result if c.choices)
        else:
            answer = result.choices[0].message.content or ""
        elapsed = time.perf_counter() - started
    print(f"live {mode} stream={stream}: {elapsed:.1f}s")
    assert transport.bodies, "nothing was forwarded"
    leaks = leaked_values(transport.bodies[-1])
    if mode == "strict":
        assert leaks == []
    else:
        # Rules only: emails and phones are always masked; names need the LLM pass.
        assert all("@" not in leak and "+36" not in leak for leak in leaks)
    assert "[[" not in answer  # every placeholder the model used was restored
    print(f"  answer has the email: {'teszt.elek@example.com' in answer}")
