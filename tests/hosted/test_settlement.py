"""Settling sponsored and per-user reservations to actual usage (LAB-1662).

Every identity, prompt and key is synthetic; the upstream is an in-process fake and the
durable ledger an in-memory blob with ETag compare-and-swap. No cloud or provider calls.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import threading
import time
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.gateway.meter import UPSTREAM_METER, UpstreamMeter, record_usage, scan_usage
from pii_guard.hosted.middleware import HostedMiddleware, settled_tokens
from pii_guard.hosted.quotas import QuotaLedger, QuotaLimits, SponsoredUnavailableError
from pii_guard.hosted.runtime import HostedService
from pii_guard.hosted.spend import Approval, Conflict, DurableSpend

ORIGIN = "https://hosted.example.com"
MASTER_KEY = "c3" * 32
SUBJECT = "synthetic-settlement-user"
MODEL = "muse-spark-1.3"
IN_RATE, OUT_RATE = 5, 30  # the default sponsored microdollars per token


def cost(tokens_in: int, tokens_out: int) -> int:
    return tokens_in * IN_RATE + tokens_out * OUT_RATE


# --- the durable ledger -------------------------------------------------------------------


class Store:
    """A versioned blob with ETag compare-and-swap and scriptable synthetic failures."""

    def __init__(self, document: dict[str, Any]) -> None:
        self.raw = json.dumps(document).encode()
        self.version = 0
        self.lock = threading.Lock()
        self.force_conflicts = 0
        self.fail_after_commit = False
        self.fail_write = False

    def read(self) -> tuple[bytes, str]:
        with self.lock:
            return self.raw, f'"synthetic-{self.version}"'

    def compare_and_swap(self, value: bytes, etag: str) -> None:
        with self.lock:
            if self.fail_write:
                raise RuntimeError("synthetic private write failure")
            if self.force_conflicts or etag != f'"synthetic-{self.version}"':
                self.force_conflicts = max(0, self.force_conflicts - 1)
                raise Conflict
            self.raw, self.version = bytes(value), self.version + 1
            if self.fail_after_commit:
                raise TimeoutError("synthetic unknown commit outcome")

    def document(self) -> dict[str, Any]:
        with self.lock:
            return json.loads(self.raw)

    def close(self) -> None:
        pass


class Clock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def durable(
    *, ceiling: int = 10_000_000, daily: int = 5_000_000, now: float | None = None
) -> tuple[DurableSpend, Store, Clock]:
    clock = Clock(time.time() if now is None else now)
    expires = int(clock.value) + 3 * 86_400
    approval = Approval("dev", "synthetic-allocation", ceiling, expires)
    store = Store(
        {
            "version": 1,
            "environment": "dev",
            "allocation_id": "synthetic-allocation",
            "ceiling_microdollars": ceiling,
            "expires_at": expires,
            "charged_total": 0,
            "day": datetime.fromtimestamp(clock.value, UTC).date().isoformat(),
            "daily_charged": 0,
            "enabled": True,
        }
    )
    spend = DurableSpend(store, approval, daily_ceiling=daily, clock=clock)
    spend.refresh()
    return spend, store, clock


def test_refund_lowers_a_charge_once_per_request_id_and_never_raises_it() -> None:
    spend, store, _ = durable()
    spend.charge(1000, threading.Event(), "req-a")
    assert spend.refund("req-a", 300, threading.Event()) == 700
    doc = store.document()
    assert doc["charged_total"] == doc["daily_charged"] == 1000
    assert doc["refunded_total"] == doc["daily_refunded"] == 700
    # Idempotent: the open charge is consumed by the first settlement.
    assert spend.refund("req-a", 0, threading.Event()) == 0
    assert store.document()["refunded_total"] == 700
    # Settling at or above the charge, or to nonsense, refunds nothing.
    spend.charge(500, threading.Event(), "req-b")
    assert spend.refund("req-b", 9_999, threading.Event()) == 0
    spend.charge(500, threading.Event(), "req-c")
    assert spend.refund("req-c", -1, threading.Event()) == 0
    assert store.document()["refunded_total"] == 700
    # An unknown request id (another process's, or never charged) refunds nothing.
    assert spend.refund("req-unknown", 0, threading.Event()) == 0


def test_refund_retries_conflicts_and_an_unknown_outcome_never_refunds_twice() -> None:
    spend, store, _ = durable()
    spend.charge(1000, threading.Event(), "req-a")
    store.force_conflicts = 2
    assert spend.refund("req-a", 0, threading.Event()) == 1000
    spend.charge(1000, threading.Event(), "req-b")
    store.fail_after_commit = True
    with pytest.raises(SponsoredUnavailableError):
        spend.refund("req-b", 0, threading.Event())
    store.fail_after_commit = False
    # The write may have landed; a retry must not refund again.
    assert spend.refund("req-b", 0, threading.Event()) == 0
    assert store.document()["refunded_total"] == 2000


def test_failed_refund_leaves_the_charge_in_full() -> None:
    spend, store, _ = durable()
    spend.charge(1000, threading.Event(), "req-a")
    store.fail_write = True
    with pytest.raises(SponsoredUnavailableError) as raised:
        spend.refund("req-a", 0, threading.Event())
    assert "synthetic private" not in str(raised.value)
    store.fail_write = False
    doc = store.document()
    assert doc["charged_total"] == 1000 and "refunded_total" not in doc


def test_refunds_free_ceiling_room_but_ceilings_stay_closed() -> None:
    spend, store, _ = durable(ceiling=3000, daily=2000)
    spend.charge(2000, threading.Event(), "req-a")
    with pytest.raises(SponsoredUnavailableError):
        spend.charge(1, threading.Event(), "req-b")  # the daily ceiling is reached
    assert spend.refund("req-a", 500, threading.Event()) == 1500
    spend.charge(1500, threading.Event(), "req-c")  # net daily is 500 + 1500
    with pytest.raises(SponsoredUnavailableError):
        spend.charge(1, threading.Event(), "req-d")
    doc = store.document()
    assert doc["daily_charged"] - doc["daily_refunded"] == 2000


def test_a_charge_from_a_previous_day_refunds_only_the_total() -> None:
    start = datetime(2026, 10, 30, 23, 59, tzinfo=UTC).timestamp()
    spend, store, clock = durable(now=start)
    spend.charge(1000, threading.Event(), "req-a")
    clock.value = start + 120  # past UTC midnight
    spend.charge(200, threading.Event(), "req-b")
    assert spend.refund("req-a", 0, threading.Event()) == 1000
    doc = store.document()
    assert doc["day"] == "2026-10-31"
    assert doc["daily_charged"] == 200 and doc["daily_refunded"] == 0
    assert doc["charged_total"] == 1200 and doc["refunded_total"] == 1000


def test_blob_without_refund_fields_still_parses_and_rollback_is_detected() -> None:
    spend, store, _ = durable()
    spend.charge(1000, threading.Event(), "req-a")
    assert "refunded_total" not in store.document()  # unchanged until the first refund
    spend.refund("req-a", 400, threading.Event())
    restored = store.document()
    restored["refunded_total"] = restored["daily_refunded"] = 0
    with store.lock:
        store.raw = json.dumps(restored).encode()
        store.version += 1
    with pytest.raises(SponsoredUnavailableError):
        spend.charge(1, threading.Event(), "req-b")


# --- the in-memory ledger -----------------------------------------------------------------


def memory_ledger() -> QuotaLedger:
    return QuotaLedger(
        QuotaLimits(),
        sponsored_allocation_microdollars=100_000_000,
        allocation_expires_at=time.time() + 3600,
        claim_allocation=lambda: True,
    )


def test_reservation_settles_down_once_and_keeps_the_request_count() -> None:
    quotas = memory_ledger()
    reservation = quotas.admit(
        "synthetic-owner", authenticated=True, input_tokens=1000, output_tokens=100, sponsored=True
    )
    assert reservation.settle(150, cost(100, 50)) == (950, cost(1000, 100) - cost(100, 50))
    assert reservation.settle(0, 0) == (0, 0)
    usage = quotas.usage("synthetic-owner")
    assert usage["tokens_today"] == 150 and usage["requests_today"] == 1
    assert quotas._spent_today == quotas._spent_allocation == cost(100, 50)
    reservation.release()
    # A settlement above the reservation never charges more.
    again = quotas.admit(
        "synthetic-owner", authenticated=True, input_tokens=10, output_tokens=0, sponsored=False
    )
    assert again.settle(10_000, 10_000) == (0, 0)
    assert quotas.usage("synthetic-owner")["tokens_today"] == 160


# --- the meter and the settlement rule -----------------------------------------------------


def test_settled_tokens_rules() -> None:
    meter = UpstreamMeter()
    assert settled_tokens(500, 100, meter, fixed_input=False) == (0, 0, "no_upstream")
    meter.forwarded, meter.payload_bytes, meter.received_bytes = True, 320, 40
    assert settled_tokens(500, 100, meter, fixed_input=False) == (320, 40, "estimated")
    meter.received_bytes = 10_000  # never above the reservation
    assert settled_tokens(500, 100, meter, fixed_input=False) == (320, 100, "estimated")
    meter.input_tokens, meter.output_tokens = 90, 12
    assert settled_tokens(500, 100, meter, fixed_input=False) == (90, 12, "usage")
    assert settled_tokens(500, 100, meter, fixed_input=True) == (500, 12, "usage")
    meter.input_tokens = 9_000
    assert settled_tokens(500, 100, meter, fixed_input=False) == (500, 12, "usage")


def test_meter_reads_chat_and_responses_usage_and_ignores_garbage() -> None:
    meter = UpstreamMeter()
    token = UPSTREAM_METER.set(meter)
    try:
        record_usage({"prompt_tokens": True, "completion_tokens": 3})
        assert meter.input_tokens is None
        scan_usage('{"choices":[],"usage":{"prompt_tokens":7,"completion_tokens":3}}')
        assert (meter.input_tokens, meter.output_tokens) == (7, 3)
        scan_usage(
            '{"type":"response.completed","response":{"usage":{"input_tokens":9,'
            '"output_tokens":4}}}',
            nested=True,
        )
        assert (meter.input_tokens, meter.output_tokens) == (9, 4)
        scan_usage('not json with "usage"')
    finally:
        UPSTREAM_METER.reset(token)
    record_usage({"prompt_tokens": 1, "completion_tokens": 1})  # no meter: a no-op


# --- end to end through the hosted app ------------------------------------------------------


def identity() -> str:
    return base64.b64encode(
        json.dumps({"auth_typ": "google", "claims": [{"typ": "sub", "val": SUBJECT}]}).encode()
    ).decode()


def settings(**overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        hosted=True,
        hosted_trust_easy_auth=True,
        hosted_single_process=True,
        hosted_public_origin=ORIGIN,
        allowed_hosts=("hosted.example.com",),
        tenant_key=MASTER_KEY,
        detectors=("rules",),
        ner_fallback="off",
        upstream_api_key="synthetic-sponsored-key",
        **overrides,
    )


def scope() -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/v1/chat/completions",
        "raw_path": b"/v1/chat/completions",
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"host", b"hosted.example.com"),
            (b"origin", ORIGIN.encode()),
            (b"content-type", b"application/json"),
            (b"x-ms-client-principal", identity().encode()),
        ],
        "server": ("hosted.example.com", 443),
        "client": ("192.0.2.1", 12345),
    }


def body(*, stream: bool = False) -> bytes:
    return json.dumps(
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": "Write to synthetic@example.com please"}],
            "stream": stream,
        }
    ).encode()


async def call(
    app: Any, payload: bytes, *, gone_after_chunks: int | None = None
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    delivered = False

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": payload, "more_body": False}
        await asyncio.Future()
        raise AssertionError

    async def send(message: dict[str, Any]) -> None:
        bodies = sum(m["type"] == "http.response.body" for m in messages)
        if gone_after_chunks is not None and bodies >= gone_after_chunks:
            raise OSError("synthetic client went away")
        messages.append(message)

    await app(scope(), receive, send)
    return messages


def status(messages: list[dict[str, Any]]) -> int:
    return next(m["status"] for m in messages if m["type"] == "http.response.start")


Handler = Callable[[httpx.Request], Any]


def hosted_app(
    monkeypatch: pytest.MonkeyPatch, handler: Handler, *, with_durable: bool
) -> tuple[Any, HostedService, Store | None, list[bytes]]:
    sent: list[bytes] = []

    async def upstream(request: httpx.Request) -> httpx.Response:
        sent.append(request.content)
        response = handler(request)
        return await response if asyncio.iscoroutine(response) else response

    monkeypatch.setattr(
        "pii_guard.hosted.runtime.SecureTransport", lambda: httpx.MockTransport(upstream)
    )
    app = create_app(settings())
    service: HostedService = app.state.hosted
    service.quotas = memory_ledger()
    store = None
    if with_durable:
        service.spend, store, _ = durable()
    return app, service, store, sent


def reserved(service: HostedService) -> tuple[int, int]:
    """The (input, output) tokens admission reserves for ``body()``."""
    from pii_guard.hosted.quotas import upstream_payload_bound

    sized = json.loads(body())
    sized.pop("max_tokens", None)
    sized["max_completion_tokens"] = service.settings.hosted_max_output_tokens
    return (
        upstream_payload_bound(len(json.dumps(sized).encode())),
        service.settings.hosted_max_output_tokens,
    )


def answer(usage: dict[str, int] | None) -> httpx.Response:
    document: dict[str, Any] = {
        "id": "chatcmpl-synthetic",
        "object": "chat.completion",
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Synthetic reply"},
                "finish_reason": "stop",
            }
        ],
    }
    if usage is not None:
        document["usage"] = usage
    return httpx.Response(200, json=document)


@pytest.mark.parametrize("with_durable", [False, True])
def test_completion_settles_to_reported_usage(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, with_durable: bool
) -> None:
    usage = {"prompt_tokens": 40, "completion_tokens": 9, "total_tokens": 49}
    app, service, store, _ = hosted_app(
        monkeypatch, lambda request: answer(usage), with_durable=with_durable
    )

    async def exercise() -> list[dict[str, Any]]:
        try:
            return await call(app, body())
        finally:
            await service.close()

    with caplog.at_level(logging.INFO, logger="pii_guard.hosted.settlement"):
        messages = asyncio.run(exercise())
    assert status(messages) == 200
    principal_usage = next(iter(service.quotas._users.values()))
    assert principal_usage.tokens == 49 and principal_usage.requests == 1
    if store is not None:
        doc = store.document()
        assert doc["charged_total"] - doc["refunded_total"] == cost(40, 9)
        assert service.quotas._spent_allocation == 0
    else:
        assert service.quotas._spent_allocation == cost(40, 9)
    lines = [r.getMessage() for r in caplog.records if r.name == "pii_guard.hosted.settlement"]
    assert len(lines) == 1
    line = lines[0]
    assert "route=/v1/chat/completions" in line and "outcome=usage" in line
    assert f"settled_microdollars={cost(40, 9)}" in line
    for secret in (SUBJECT, "synthetic@example.com", "synthetic-sponsored-key", MASTER_KEY):
        assert secret not in line


def test_upstream_5xx_settles_to_the_masked_input_estimate(monkeypatch: pytest.MonkeyPatch) -> None:
    error = b'{"error":{"message":"synthetic overload"}}'
    app, service, store, sent = hosted_app(
        monkeypatch, lambda request: httpx.Response(503, content=error), with_durable=True
    )

    async def exercise() -> list[dict[str, Any]]:
        try:
            return await call(app, body())
        finally:
            await service.close()

    messages = asyncio.run(exercise())
    assert status(messages) == 503
    assert store is not None and len(sent) == 1
    reserved_in, reserved_out = reserved(service)
    # Input: the masked payload's bytes (never under its tokens); output: the error bytes.
    settled = cost(len(sent[0]), len(error))
    doc = store.document()
    assert doc["charged_total"] == cost(reserved_in, reserved_out)
    assert doc["charged_total"] - doc["refunded_total"] == settled
    assert next(iter(service.quotas._users.values())).tokens == len(sent[0]) + len(error)


def test_stream_without_usage_aborted_by_the_client_settles_to_what_streamed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    streamed: list[bytes] = []

    async def chunks() -> AsyncIterator[bytes]:
        for index in range(1000):
            chunk = (
                "data: "
                + json.dumps(
                    {
                        "id": "chatcmpl-synthetic",
                        "object": "chat.completion.chunk",
                        "choices": [{"index": 0, "delta": {"content": f"part {index} "}}],
                    }
                )
                + "\n\n"
            ).encode()
            streamed.append(chunk)
            yield chunk
            await asyncio.sleep(0.01)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=chunks())

    app, service, store, sent = hosted_app(monkeypatch, handler, with_durable=True)

    async def exercise() -> list[dict[str, Any]]:
        try:
            return await call(app, body(stream=True), gone_after_chunks=5)
        finally:
            await service.close()

    with contextlib.suppress(Exception):  # the disconnect surfaces as ClientDisconnect
        asyncio.run(exercise())
    assert store is not None
    reserved_in, reserved_out = reserved(service)
    received = sum(len(chunk) for chunk in streamed)
    assert 0 < received < reserved_out
    doc = store.document()
    net = doc["charged_total"] - doc["refunded_total"]
    # At most what was streamed (a chunk may be in flight when the stream closed).
    assert cost(len(sent[0]), 1) <= net <= cost(len(sent[0]), received)
    assert net < cost(reserved_in, reserved_out)


def test_no_upstream_call_refunds_the_whole_reservation() -> None:
    async def exercise() -> tuple[HostedService, Store]:
        service = HostedService(settings())
        service.quotas = memory_ledger()
        service.spend, store, _ = durable()

        async def downstream(*args: Any) -> None:
            raise RuntimeError("synthetic failure before any upstream call")

        with pytest.raises(RuntimeError):
            await call(HostedMiddleware(downstream, service), body())
        await service.close()
        return service, store

    service, store = asyncio.run(exercise())
    doc = store.document()
    assert doc["charged_total"] > 0 and doc["refunded_total"] == doc["charged_total"]
    usage = next(iter(service.quotas._users.values()))
    assert usage.tokens == 0 and usage.requests == 1 and usage.active == 0


def test_hosted_timeout_before_upstream_refunds_the_whole_reservation() -> None:
    async def exercise() -> tuple[HostedService, Store, list[dict[str, Any]]]:
        service = HostedService(settings(hosted_request_timeout=0.05))
        service.quotas = memory_ledger()
        service.spend, store, _ = durable()

        async def downstream(*args: Any) -> None:
            await asyncio.sleep(5)

        messages = await call(HostedMiddleware(downstream, service), body())
        await service.close()
        return service, store, messages

    service, store, messages = asyncio.run(exercise())
    assert status(messages) == 504
    doc = store.document()
    assert doc["refunded_total"] == doc["charged_total"] > 0
    assert next(iter(service.quotas._users.values())).tokens == 0


def test_a_failed_durable_charge_rolls_back_the_in_memory_tokens() -> None:
    async def exercise() -> tuple[HostedService, list[dict[str, Any]]]:
        service = HostedService(settings())
        service.quotas = memory_ledger()
        service.spend, store, _ = durable()
        store.fail_write = True

        async def downstream(*args: Any) -> None:
            raise AssertionError("no paid work after a failed charge")

        messages = await call(HostedMiddleware(downstream, service), body())
        await service.close()
        return service, messages

    service, messages = asyncio.run(exercise())
    assert status(messages) == 503
    usage = next(iter(service.quotas._users.values()))
    assert usage.tokens == 0 and usage.requests == 1 and usage.active == 0
