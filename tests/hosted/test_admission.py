"""Hosted admission integration: permits cover whole responses, including cancellation."""

from __future__ import annotations

import asyncio
import base64
import json
import threading
import time
from contextlib import suppress

import httpx
import pytest
from fastapi import Request

from pii_guard.api.app import create_app
from pii_guard.api.deps import RegistryAnalyzer
from pii_guard.config import Settings
from pii_guard.detect.rules import RuleDetector
from pii_guard.gateway.config import Mode
from pii_guard.gateway.detection import ModeDetector
from pii_guard.hosted.identity import easy_auth_principal
from pii_guard.hosted.middleware import HostedMiddleware
from pii_guard.hosted.quotas import QuotaLedger, QuotaLimits
from pii_guard.hosted.runtime import BoundedAnalyzer, HostedCapacityError, HostedService
from pii_guard.types import DetectionError

ORIGIN = "https://hosted.example.com"
MASTER_KEY = "b1" * 32


def identity(subject="synthetic-admission-user"):
    return base64.b64encode(
        json.dumps({"auth_typ": "google", "claims": [{"typ": "sub", "val": subject}]}).encode()
    ).decode()


def settings(**overrides):
    return Settings(
        _env_file=None,
        hosted=True,
        hosted_trust_easy_auth=True,
        hosted_single_process=True,
        hosted_public_origin=ORIGIN,
        allowed_hosts=("hosted.example.com",),
        tenant_key=MASTER_KEY,
        detectors=("rules",),
        **overrides,
    )


def ledger(**limits):
    return QuotaLedger(
        QuotaLimits(**limits),
        sponsored_allocation_microdollars=100_000_000,
        allocation_expires_at=time.time() + 3600,
        claim_allocation=lambda: True,
    )


def owner(subject="synthetic-admission-user"):
    return easy_auth_principal(
        identity(subject), master_key=bytes.fromhex(MASTER_KEY), trusted=True
    )


def scope(path="/v1/chat/completions", subject="synthetic-admission-user"):
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"host", b"hosted.example.com"),
            (b"origin", ORIGIN.encode()),
            (b"content-type", b"application/json"),
            (b"x-ms-client-principal", identity(subject).encode()),
        ],
        "server": ("hosted.example.com", 443),
        "client": ("192.0.2.1", 12345),
    }


def request_body(*, stream=False):
    return json.dumps(
        {
            "model": "muse-spark-1.3",
            "messages": [{"role": "user", "content": "Contact synthetic@example.com"}],
            "stream": stream,
        }
    ).encode()


def completion():
    return {
        "id": "chatcmpl-synthetic",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Synthetic reply"},
                "finish_reason": "stop",
            }
        ],
    }


async def invoke(app, request_scope=None, body=None, send=None):
    messages = []
    delivered = False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body or request_body(), "more_body": False}
        await asyncio.Future()

    async def collect(message):
        messages.append(message)

    await app(request_scope or scope(), receive, send or collect)
    return messages


def status(messages):
    return next(
        message["status"] for message in messages if message["type"] == "http.response.start"
    )


def test_concurrent_request_denied_before_upstream_and_owner_released(monkeypatch):
    async def exercise():
        entered, finish = asyncio.Event(), asyncio.Event()
        calls = []

        async def upstream(request):
            calls.append(request)
            entered.set()
            await finish.wait()
            return httpx.Response(200, json=completion())

        monkeypatch.setattr(
            "pii_guard.hosted.runtime.SecureTransport", lambda: httpx.MockTransport(upstream)
        )
        app = create_app(settings())
        app.state.analyzer = RegistryAnalyzer(("rules",), settings=app.state.settings)
        service = app.state.hosted
        service.quotas = ledger(principal_concurrency=1)
        first = asyncio.create_task(invoke(app))
        await asyncio.wait_for(entered.wait(), 2)
        assert service._runtimes[owner().id].active == 1
        assert status(await invoke(app)) == 429
        assert len(calls) == 1
        finish.set()
        assert status(await first) == 200
        assert service._runtimes[owner().id].active == 0
        assert service.quotas.usage(owner().id)["requests_today"] == 1
        assert status(await invoke(app)) == 200
        assert service.quotas.usage(owner().id)["requests_today"] == 2
        await service.close()

    asyncio.run(exercise())


def test_global_concurrency_shared_between_owners(monkeypatch):
    async def exercise():
        entered, finish = asyncio.Event(), asyncio.Event()

        async def upstream(request):
            entered.set()
            await finish.wait()
            return httpx.Response(200, json=completion())

        monkeypatch.setattr(
            "pii_guard.hosted.runtime.SecureTransport", lambda: httpx.MockTransport(upstream)
        )
        app = create_app(settings())
        app.state.analyzer = RegistryAnalyzer(("rules",), settings=app.state.settings)
        service = app.state.hosted
        service.quotas = ledger(global_concurrency=1)
        first = asyncio.create_task(invoke(app))
        await asyncio.wait_for(entered.wait(), 2)
        assert status(await invoke(app, scope(subject="synthetic-other"))) == 429
        assert owner("synthetic-other").id not in service._runtimes
        finish.set()
        await first
        assert status(await invoke(app, scope(subject="synthetic-other"))) == 200
        await service.close()

    asyncio.run(exercise())


def test_cancelled_stream_holds_then_releases_runtime_and_permit(monkeypatch):
    async def exercise():
        streamed, hold, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                event = {
                    "id": "chatcmpl-synthetic",
                    "choices": [{"index": 0, "delta": {"content": "Synthetic reply "}}],
                }
                yield f"data: {json.dumps(event)}\n\n".encode()
                await hold.wait()
                yield b"data: [DONE]\n\n"

            async def aclose(self):
                closed.set()

        async def upstream(request):
            return httpx.Response(
                200, stream=Stream(), headers={"content-type": "text/event-stream"}
            )

        monkeypatch.setattr(
            "pii_guard.hosted.runtime.SecureTransport", lambda: httpx.MockTransport(upstream)
        )
        app = create_app(settings())
        app.state.analyzer = RegistryAnalyzer(("rules",), settings=app.state.settings)
        service = app.state.hosted
        service.quotas = ledger(principal_concurrency=1)

        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                streamed.set()

        task = asyncio.create_task(invoke(app, body=request_body(stream=True), send=send))
        await asyncio.wait_for(streamed.wait(), 2)
        assert service._runtimes[owner().id].active == 1
        assert status(await invoke(app)) == 429
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(closed.wait(), 2)
        assert service._runtimes[owner().id].active == 0
        assert service.quotas.usage(owner().id)["requests_today"] == 1
        # A cancelled paid operation retained its full charge; only its concurrency released.
        permit = service.quotas.admit(
            owner().id, authenticated=True, input_tokens=1, output_tokens=1, sponsored=False
        )
        permit.release()
        await service.close()

    asyncio.run(exercise())


def test_runtime_capacity_failure_releases_admission():
    async def exercise():
        service = HostedService(settings(hosted_max_principals=1))
        service.quotas = ledger(global_concurrency=1)
        held = service.acquire(owner("synthetic-other"))

        async def downstream(request_scope, receive, send):
            raise AssertionError("capacity failure must never route downstream")

        messages = await invoke(HostedMiddleware(downstream, service))
        assert status(messages) == 429
        assert service.quotas.usage(owner().id)["requests_today"] == 1
        permit = service.quotas.admit(
            owner().id, authenticated=True, input_tokens=1, output_tokens=1, sponsored=False
        )
        permit.release()
        service.release(held)
        await service.close()

    asyncio.run(exercise())


def test_cleanup_error_does_not_leak_runtime_or_admission():
    async def exercise():
        service = HostedService(settings())
        service.quotas = ledger(global_concurrency=1)

        class BrokenGateway:
            async def aclose(self):
                raise RuntimeError("synthetic transport close failure")

        async def downstream(request_scope, receive, send):
            request_scope["state"]["hosted_gateway"] = BrokenGateway()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        with suppress(RuntimeError):
            await invoke(HostedMiddleware(downstream, service))
        assert service._runtimes[owner().id].active == 0
        permit = service.quotas.admit(
            owner().id, authenticated=True, input_tokens=1, output_tokens=1, sponsored=False
        )
        permit.release()
        await service.close()

    asyncio.run(exercise())


def test_slow_body_is_covered_by_hosted_deadline():
    async def exercise():
        service = HostedService(settings(hosted_request_timeout=0.01))

        async def downstream(request_scope, receive, send):
            raise AssertionError("an incomplete body must never reach downstream")

        async def receive():
            await asyncio.Future()

        messages = []

        async def send(message):
            messages.append(message)

        await asyncio.wait_for(
            HostedMiddleware(downstream, service)(scope(), receive, send), timeout=0.5
        )
        assert status(messages) in (408, 504)
        await service.close()

    asyncio.run(exercise())


def test_incomplete_bodies_are_bounded_before_quota_admission():
    async def exercise():
        service = HostedService(settings())
        entered = 0
        full = asyncio.Event()

        async def downstream(request_scope, receive, send):
            raise AssertionError("an incomplete body must never reach downstream")

        async def receive():
            nonlocal entered
            entered += 1
            if entered == 32:
                full.set()
            await asyncio.Future()

        async def send(message):
            pass

        middleware = HostedMiddleware(downstream, service)
        tasks = [asyncio.create_task(middleware(scope(), receive, send)) for _ in range(32)]
        try:
            await asyncio.wait_for(full.wait(), 2)
            assert status(await invoke(middleware)) == 429
            assert not service._runtimes
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        assert service._ingress == 0
        assert service.quotas.usage(owner().id)["requests_today"] == 0
        await service.close()

    asyncio.run(exercise())


def test_cancelled_waiters_do_not_free_running_detector_slots():
    async def exercise():
        release, occupied = threading.Event(), threading.Event()
        lock = threading.Lock()
        count = 0

        class BlockingAnalyzer:
            def analyze(self, text, language):
                nonlocal count
                with lock:
                    count += 1
                    if count == 4:
                        occupied.set()
                assert release.wait(5)
                return []

        slots = threading.BoundedSemaphore(4)
        wrappers = [BoundedAnalyzer(BlockingAnalyzer(), slots) for _ in range(5)]
        tasks = [
            asyncio.create_task(asyncio.to_thread(wrapper.analyze, "synthetic", "en"))
            for wrapper in wrappers[:4]
        ]
        try:
            assert await asyncio.to_thread(occupied.wait, 2)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            with pytest.raises(HostedCapacityError):
                wrappers[4].analyze("synthetic", "en")
            assert count == 4
        finally:
            release.set()

    asyncio.run(exercise())


@pytest.mark.parametrize("refuse_second", [False, True])
def test_separate_request_gateways_share_session_holds(monkeypatch, refuse_second):
    async def exercise():
        barrier = threading.Barrier(2, timeout=3)
        creator_done = threading.Event()

        class GatedDetector:
            name = "synthetic-gated-rules"

            def detect(self, text, language):
                barrier.wait()
                if text.startswith("Refuse"):
                    raise DetectionError("synthetic refusal")
                assert creator_done.wait(3)
                if refuse_second:
                    raise DetectionError("synthetic second refusal")
                return RuleDetector().detect(text, language)

        monkeypatch.setattr(
            "pii_guard.hosted.runtime.SecureTransport",
            lambda: httpx.MockTransport(lambda request: httpx.Response(200, json=completion())),
        )
        app = create_app(settings())
        app.state.analyzer = RegistryAnalyzer(("rules",), settings=app.state.settings)
        app.state.gateway_detectors = {
            Mode.FAST: ModeDetector(
                Mode.FAST, GatedDetector(), "synthetic-test", app.state.policies, batches=True
            )
        }
        service = app.state.hosted
        runtime = service.acquire(owner())

        def gateway():
            request = Request({**scope(), "app": app, "state": {"hosted_runtime": runtime}})
            return service.gateway(request)

        first, second = gateway(), gateway()
        assert first is not second
        assert first._session_holds is second._session_holds
        assert first._holds_lock is second._holds_lock

        async def call(gw, text):
            body = {
                "model": "muse-spark-1.3",
                "messages": [{"role": "user", "content": text}],
            }
            return await gw.chat_completions(body, {}, path_session="synthetic-shared-session")

        async def refused():
            try:
                return await call(first, "Refuse synthetic@example.com")
            finally:
                creator_done.set()

        try:
            results = await asyncio.gather(
                refused(), call(second, "Serve synthetic@example.com"), return_exceptions=True
            )
            assert isinstance(results[0], DetectionError)
            if refuse_second:
                assert isinstance(results[1], DetectionError)
                assert len(runtime.vault) == 0
            else:
                assert not isinstance(results[1], BaseException), results[1]
                assert results[1][0].status_code == 200
                assert runtime.vault.session("synthetic-shared-session").entry_count == 1
            assert runtime.session_holds == {}
        finally:
            await first.aclose()
            await second.aclose()
            service.release(runtime)
            await service.close()

    asyncio.run(exercise())
