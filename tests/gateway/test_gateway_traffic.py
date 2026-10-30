"""Traffic events, timing and the observability routes, end to end through the gateway.

The upstream is an ``httpx.MockTransport`` (some with a fixed delay); nothing leaves the
process. All values are fictional (ADR 0005).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gateway_helpers import (
    EMAILS,
    TEST_TENANT_KEY,
    UPSTREAM_KEY,
    UPSTREAM_URL,
    FakeLlm,
    MockUpstream,
    chunk,
    completion,
    conversation_turn_one,
)
from timing_helpers import VirtualClock
from timing_helpers import install as install_clock

from pii_guard.api.app import create_app
from pii_guard.api.routes.traffic import traffic_stream
from pii_guard.config import Settings
from pii_guard.gateway import GatewayConfig, Mode, build_mode_detectors
from pii_guard.observability import ObservabilitySettings, TrafficLogConfigError
from pii_guard.vault import PLACEHOLDER_RE

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

CLIENT_KEY = "sk-client-key-should-never-be-logged"


def make(
    upstream: MockUpstream | httpx.MockTransport,
    *,
    traffic: str = "masked",
    metrics: bool = False,
    server_timing: bool = False,
    settings: Settings | None = None,
) -> FastAPI:
    settings = settings or Settings(
        tenant_key=TEST_TENANT_KEY, upstream_base_url=UPSTREAM_URL, upstream_api_key=UPSTREAM_KEY
    )
    app = create_app(
        settings,
        ObservabilitySettings(traffic_log=traffic, metrics=metrics, server_timing=server_timing),
    )
    config = GatewayConfig(mode=Mode.AUDIT)
    app.state.gateway_config = config
    app.state.gateway_transport = (
        upstream.transport() if isinstance(upstream, MockUpstream) else upstream
    )
    app.state.gateway_detectors = build_mode_detectors(settings, config, llm_detector=FakeLlm())
    return app


def chat(client: TestClient, **extra: Any) -> httpx.Response:
    body = {"model": "test-model", "messages": conversation_turn_one(), **extra}
    return client.post(
        "/v1/chat/completions", json=body, headers={"Authorization": f"Bearer {CLIENT_KEY}"}
    )


def events(client: TestClient) -> list[dict[str, Any]]:
    r = client.get("/v1/traffic")
    assert r.status_code == 200
    return r.json()["events"]


# --- AC3: masked and full, nothing sensitive in the log ------------------------------------


def test_masked_event_holds_only_what_left_the_machine() -> None:
    with TestClient(make(MockUpstream())) as client:
        r = chat(client)
        assert r.status_code == 200
        (event,) = events(client)
    assert event["id"] == r.headers["x-pii-guard-request-id"]
    assert event["level"] == "masked" and event["outcome"] == "ok" and event["mode"] == "audit"
    assert event["detectors"] == ["llm", "rules"]
    assert event["entities"]["masked"]["EMAIL"] == 1
    assert event["usage"] == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert "original" not in event["request"] and "unmasked" not in event["response"]
    dumped = json.dumps(event, ensure_ascii=False)
    assert "[[EMAIL_" in dumped
    for value in ("Teszt Elek", EMAILS[0], "+36 30 123 4567"):
        assert value not in dumped


def test_event_never_holds_keys_headers_or_the_raw_session_id() -> None:
    with TestClient(make(MockUpstream(), traffic="full")) as client:
        r = chat(client)
        session = r.headers["x-pii-guard-session"]
        second = client.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": conversation_turn_one()},
            headers={"X-PII-Guard-Session": session, "Authorization": f"Bearer {CLIENT_KEY}"},
        )
        assert second.status_code == 200
        first, follow = events(client)
    dumped = json.dumps([first, follow])
    assert CLIENT_KEY not in dumped and UPSTREAM_KEY not in dumped
    assert "Bearer" not in dumped and "uthorization" not in dumped
    assert session not in dumped
    assert first["session_ref"] == follow["session_ref"]  # same conversation, same ref
    assert first["session_new"] and not follow["session_new"]
    assert (first["session_source"], follow["session_source"]) == ("default", "header")


def test_full_event_has_originals_side_by_side() -> None:
    with TestClient(make(MockUpstream(), traffic="full")) as client:
        assert chat(client).status_code == 200
        (event,) = events(client)
    original = event["request"]["original"]["messages"][1]["content"]
    masked = event["request"]["masked"]["messages"][1]["content"]
    assert EMAILS[0] in original and EMAILS[0] not in masked
    restored = event["response"]["unmasked"]["choices"][0]["message"]["content"]
    assert EMAILS[0] in restored
    assert EMAILS[0] not in event["response"]["masked"]["choices"][0]["message"]["content"]


def test_streamed_event_has_masked_and_restored_content() -> None:
    upstream = MockUpstream(stream_chunks=lambda a: [a[i : i + 4] for i in range(0, len(a), 4)])
    with TestClient(make(upstream, traffic="full")) as client:
        r = chat(client, stream=True)
        assert r.status_code == 200 and "data: [DONE]" in r.text
        (event,) = events(client)
    assert event["stream"] and event["outcome"] == "ok"
    assert "[[EMAIL_" in event["response"]["masked"]["content"]["0"]
    assert EMAILS[0] in event["response"]["unmasked"]["content"]["0"]
    assert event["response"]["chunks"] > 3


def streamed_tool_call_upstream() -> httpx.MockTransport:
    """Streams one ``send_email`` tool call whose arguments carry the request's email
    placeholder split across chunks, after a short text answer."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        found = PLACEHOLDER_RE.findall(json.dumps(body["messages"]))
        ident = next(i for kind, i in found if kind == "EMAIL")
        args = json.dumps({"to": f"[[EMAIL_{ident}]]"})
        cut = args.index("[[") + 4
        events = [
            chunk({"role": "assistant", "content": "Sending."}),
            chunk(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_0",
                            "type": "function",
                            "function": {"name": "send_email", "arguments": ""},
                        }
                    ]
                }
            ),
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": args[:cut]}}]}),
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": args[cut:]}}]}),
            chunk({}, finish="tool_calls"),
        ]
        out = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
        return httpx.Response(
            200, content=out.encode(), headers={"content-type": "text/event-stream"}
        )

    return httpx.MockTransport(handler)


@pytest.mark.parametrize("traffic", ["masked", "full"])
def test_streamed_tool_call_arguments_are_kept(traffic: str) -> None:
    with TestClient(make(streamed_tool_call_upstream(), traffic=traffic)) as client:
        r = chat(client, stream=True)
        assert r.status_code == 200 and "data: [DONE]" in r.text
        (event,) = events(client)
    response = event["response"]
    assert response["masked"]["content"] == {"0": "Sending."}
    (masked_call,) = response["masked"]["tool_calls"]["0"]
    assert masked_call["id"] == "call_0" and masked_call["type"] == "function"
    assert masked_call["function"]["name"] == "send_email"
    assert PLACEHOLDER_RE.search(masked_call["function"]["arguments"])
    assert EMAILS[0] not in json.dumps(response["masked"])
    if traffic == "masked":
        assert "unmasked" not in response
        return
    (restored_call,) = response["unmasked"]["tool_calls"]["0"]
    assert restored_call["function"]["name"] == "send_email"
    assert json.loads(restored_call["function"]["arguments"]) == {"to": EMAILS[0]}
    assert response["unmasked"]["content"]["0"] == "Sending."


def test_blocked_request_is_recorded_with_types_only() -> None:
    settings = Settings(
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url=UPSTREAM_URL,
        policy_overrides="EMAIL=block",
    )
    upstream = MockUpstream()
    with TestClient(make(upstream, settings=settings)) as client:
        assert chat(client).status_code == 422
        (event,) = events(client)
    assert upstream.requests == []
    assert event["outcome"] == "blocked"
    assert event["error"] == {"code": "blocked_entity", "status": 422, "entity_types": {"EMAIL": 1}}
    assert event["request"] == {"masked": None}
    assert EMAILS[0] not in json.dumps(event)


def test_traffic_routes_are_404_when_off_and_nothing_is_recorded() -> None:
    app = make(MockUpstream(), traffic="off")
    with TestClient(app) as client:
        assert chat(client).status_code == 200
        r = client.get("/v1/traffic")
        assert r.status_code == 404 and r.json()["error"]["code"] == "traffic_log_disabled"
        assert client.get("/v1/traffic/stream").status_code == 404
        assert client.get("/metrics").status_code == 404
    assert app.state.observability.traffic.recent() == []


def test_ring_buffer_size_and_limit() -> None:
    settings = Settings(tenant_key=TEST_TENANT_KEY, upstream_base_url=UPSTREAM_URL)
    app = create_app(settings, ObservabilitySettings(traffic_log="masked", traffic_log_size=2))
    app.state.gateway_transport = MockUpstream().transport()
    app.state.gateway_detectors = build_mode_detectors(
        settings, GatewayConfig(), llm_detector=FakeLlm()
    )
    with TestClient(app) as client:
        ids = [chat(client).headers["x-pii-guard-request-id"] for _ in range(3)]
        assert [e["id"] for e in events(client)] == ids[1:]
        assert [e["id"] for e in client.get("/v1/traffic?limit=1").json()["events"]] == ids[2:]


def test_boot_id_is_stable_per_process_and_new_after_a_restart() -> None:
    # LAB-1357: seq restarts at 1 with the process; the boot id lets a poller notice.
    app = make(MockUpstream())
    with TestClient(app) as client:
        chat(client)
        first = client.get("/v1/traffic").json()
        assert first["boot"].startswith("b_") and len(first["boot"]) == 18
        assert client.get("/v1/traffic?after=1").json()["boot"] == first["boot"]
    with TestClient(make(MockUpstream())) as restarted:
        chat(restarted)
        second = restarted.get("/v1/traffic").json()
        assert second["boot"] != first["boot"]
        assert [e["seq"] for e in second["events"]] == [1]


def test_full_is_refused_on_a_non_loopback_bind() -> None:
    with pytest.raises(TrafficLogConfigError):
        create_app(Settings(host="0.0.0.0"), ObservabilitySettings(traffic_log="full"))  # noqa: S104
    create_app(Settings(host="0.0.0.0"), ObservabilitySettings(traffic_log="masked"))  # noqa: S104
    create_app(Settings(host="127.0.0.1"), ObservabilitySettings(traffic_log="full"))


def test_serve_refuses_full_on_a_public_host(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from pii_guard import cli

    monkeypatch.setenv("PII_GUARD_TRAFFIC_LOG", "full")
    started = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: started.append(k))
    assert cli.main(["serve", "--host", "0.0.0.0"]) == 2  # noqa: S104
    assert "loopback" in capsys.readouterr().err
    assert started == []
    assert cli.main(["serve", "--host", "127.0.0.1"]) == 0
    assert started[0]["host"] == "127.0.0.1"


# --- AC4: timing with a fake upstream delay ------------------------------------------------

# The upstream's delays are jumps of a virtual clock (LAB-1275), not sleeps: wall-clock bounds on
# a few dozen ms flaked at 162-249 ms on loaded runners. DELAY is "seconds" of virtual time, far
# above scheduling noise, so overhead < DELAY / 2 still fails by seconds if the gateway counts
# the upstream's time as its own (or a real regression adds that much to its own work).
DELAY = 2.0
OVERHEAD_BOUND_MS = DELAY * 1000 / 2


async def _wait(clock: VirtualClock, seconds: float) -> None:
    clock.skip(seconds)
    await asyncio.sleep(0)


def slow_upstream(clock: VirtualClock, *, stream: bool) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if not stream:
            await _wait(clock, DELAY)
            return httpx.Response(200, json=completion("Rendben.", model=body["model"]))

        async def chunks() -> AsyncIterator[bytes]:
            await _wait(clock, DELAY)  # the model "thinks" before its first token
            for event in (chunk({"role": "assistant", "content": "Ren"}), chunk({"content": "d"})):
                yield f"data: {json.dumps(event)}\n\n".encode()
            await _wait(clock, DELAY / 2)
            yield b"data: [DONE]\n\n"

        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=chunks())

    return httpx.MockTransport(handler)


def test_overhead_excludes_the_upstream_delay_non_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = install_clock(monkeypatch)
    app = make(slow_upstream(clock, stream=False), server_timing=True, metrics=True)
    with TestClient(app) as client:
        started = time.perf_counter()
        r = chat(client)
        client_ms = (time.perf_counter() - started) * 1000
        assert r.status_code == 200
        (event,) = events(client)
        metrics = client.get("/metrics").text
    t = event["timing"]
    assert t["upstream_ms"] >= DELAY * 1000
    assert t["stages_ms"]["upstream_ttfb"] >= DELAY * 1000
    assert t["overhead_ms"] == pytest.approx(t["total_ms"] - t["upstream_ms"], abs=0.01)
    assert t["overhead_ms"] < OVERHEAD_BOUND_MS  # the delay is not counted as pii-guard's time
    assert t["total_ms"] <= client_ms
    assert t["stages_ms"]["detect"] > 0 and t["stages_ms"]["response"] > 0
    assert t["detectors_ms"]["rules"] > 0 and "llm" in t["detectors_ms"]
    assert t["added_ttft_ms"] is None
    header = r.headers["server-timing"]
    assert "overhead;dur=" in header and "upstream;dur=" in header
    assert 'pii_guard_gateway_requests_total{mode="audit",outcome="ok"} 1' in metrics


def test_overhead_and_added_ttft_streaming(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = install_clock(monkeypatch)
    with TestClient(make(slow_upstream(clock, stream=True))) as client:
        r = chat(client, stream=True)
        assert r.status_code == 200 and "Ren" in r.text and "[DONE]" in r.text
        (event,) = events(client)
    t = event["timing"]
    assert t["upstream_ms"] >= DELAY * 1.5 * 1000  # first-token wait + the pause before [DONE]
    assert t["upstream_ttft_ms"] >= DELAY * 1000
    assert t["added_ttft_ms"] == pytest.approx(t["ttft_ms"] - t["upstream_ttft_ms"], abs=0.01)
    assert t["added_ttft_ms"] < OVERHEAD_BOUND_MS
    # Streams also take out the time spent handing events to the client (LAB-1212).
    client_ms = t["stages_ms"]["client"]
    assert t["overhead_ms"] == pytest.approx(t["total_ms"] - t["upstream_ms"] - client_ms, abs=0.01)
    assert t["overhead_ms"] < OVERHEAD_BOUND_MS
    assert t["stages_ms"]["unmask"] > 0


def test_server_timing_is_off_by_default() -> None:
    with TestClient(make(MockUpstream())) as client:
        r = chat(client)
    assert "server-timing" not in r.headers
    assert r.headers["x-pii-guard-request-id"].startswith("req_")


# --- SSE -----------------------------------------------------------------------------------


def test_sse_stream_replays_and_pushes_new_events() -> None:
    app = make(MockUpstream())
    with TestClient(app) as client:
        assert chat(client).status_code == 200
    traffic = app.state.observability.traffic

    class FakeRequest:
        def __init__(self) -> None:
            self.app = app

        async def is_disconnected(self) -> bool:
            return False

    async def scenario() -> list[str]:
        response = await traffic_stream(FakeRequest(), replay=1)  # type: ignore[arg-type]
        body = response.body_iterator
        out = [await anext(body), await anext(body)]  # comment + the replayed event
        traffic.publish({"id": "req_new", "outcome": "ok"})
        out.append(await asyncio.wait_for(anext(body), timeout=2))
        await body.aclose()  # type: ignore[attr-defined]
        return [o.decode() if isinstance(o, bytes) else str(o) for o in out]

    comment, replayed, pushed = asyncio.run(scenario())
    assert comment.startswith(": pii-guard traffic (masked)")
    assert replayed.startswith("id: 1\nevent: traffic\ndata: ") and '"outcome":"ok"' in replayed
    assert pushed.startswith("id: 2\n") and "req_new" in pushed
    assert traffic.subscribers == 0
