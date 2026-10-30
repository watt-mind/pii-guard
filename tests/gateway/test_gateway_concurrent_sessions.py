"""Concurrent requests on one client-named session (LAB-1316).

Muse Code sends its main turn and its reminder observers at the same time, on one path
session. When the request that created the session is refused, it must not drop the session
under a request that is still using it (that one got ``404 session_not_found``). A refused
request whose session nobody else used is still dropped (fail closed). Fictional values only
(ADR 0005).
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

import httpx
import pytest
from gateway_helpers import TEST_TENANT_KEY, UPSTREAM_KEY, UPSTREAM_URL, FakeLlm, completion

from pii_guard.config import Settings
from pii_guard.gateway import Gateway, GatewayConfig, Mode, build_mode_detectors
from pii_guard.gateway.responses import ResponsesGateway
from pii_guard.gateway.sessions import SESSION_HEADER
from pii_guard.types import DetectionError, MaskingError, Span
from pii_guard.vault import PLACEHOLDER_RE, SessionNotFoundError, Vault

REFUSE = "Refuse this one, Teszt Elek."
SERVE = "Mail Minta Mária about the refund."
BEARER = {"authorization": "Bearer muse-not-a-key"}


class GatedLlm(FakeLlm):
    """Both requests reach detection together (a barrier); the refused one fails at once, the
    other one finishes only after the refused request has returned."""

    def __init__(self, refuse_first: bool = True, refuse_second: bool = False) -> None:
        super().__init__()
        self.barrier = threading.Barrier(2, timeout=5)
        self.refused = threading.Event()
        self.refuse_second = refuse_second

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        self.barrier.wait()
        if text == REFUSE:
            raise DetectionError("fake llm refused")
        assert self.refused.wait(5), "the refused request never finished"
        if self.refuse_second:
            raise DetectionError("fake llm refused the second one too")
        return super().detect(text, language)


def _upstream(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    if request.url.path.endswith("/responses"):
        return httpx.Response(
            200,
            json={
                "id": "resp_1",
                "object": "response",
                "status": "completed",
                "model": body["model"],
                "output": [
                    {
                        "type": "message",
                        "id": "msg_1",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "Noted.", "annotations": []}],
                    }
                ],
            },
        )
    return httpx.Response(200, json=completion("Rendben.", model=body["model"]))


def _gateway(llm: FakeLlm) -> Gateway:
    settings = Settings(
        tenant_key=TEST_TENANT_KEY, upstream_base_url=UPSTREAM_URL, upstream_api_key=UPSTREAM_KEY
    )
    config = GatewayConfig(mode=Mode.AUDIT)
    return Gateway(
        settings=settings,
        vault=Vault.from_settings(settings),
        config=config,
        detectors=build_mode_detectors(settings, config, llm_detector=llm),
        transport=httpx.MockTransport(_upstream),
    )


def _body(endpoint: str, text: str, key: str | None) -> dict[str, Any]:
    if endpoint == "chat":
        body: dict[str, Any] = {"model": "m", "messages": [{"role": "user", "content": text}]}
    else:
        body = {
            "model": "muse-spark-1.3",
            "input": [{"type": "message", "role": "user", "content": text}],
            "store": False,
        }
    if key is not None:
        body["prompt_cache_key"] = key
    return body


# How each of the two requests names the session: (path session, headers, prompt_cache_key).
SOURCES: dict[str, tuple[tuple[str | None, dict[str, str], str | None], ...]] = {
    "path": (("box", BEARER, None), ("box", BEARER, None)),
    "header": (("box", BEARER, None), (None, {**BEARER, SESSION_HEADER: "box"}, None)),
    "prompt_cache_key": ((None, BEARER, "conv-1"), (None, BEARER, "conv-1")),
    "default": ((None, BEARER, None), (None, BEARER, None)),
}


async def _pair(
    gw: Gateway, llm: GatedLlm, endpoint: str, source: str
) -> tuple[BaseException | None, Any]:
    """Run the refused request and the served one concurrently; return what each got."""
    responses = ResponsesGateway(gw)
    first, second = SOURCES[source]

    async def call(spec: tuple[str | None, dict[str, str], str | None], text: str) -> Any:
        path, headers, key = spec
        body = _body(endpoint, text, key)
        if endpoint == "chat":
            return await gw.chat_completions(body, headers, path_session=path)
        return await responses.responses(body, headers, path_session=path)

    async def refused() -> BaseException | None:
        try:
            await call(first, REFUSE)
        except BaseException as exc:
            return exc
        finally:
            llm.refused.set()
        return None

    async def served() -> Any:
        await asyncio.sleep(0)  # the refused request resolves (creates) the session first
        try:
            return await call(second, SERVE)
        except BaseException as exc:
            return exc

    try:
        return tuple(await asyncio.gather(refused(), served()))  # type: ignore[return-value]
    finally:
        await gw.aclose()


@pytest.mark.parametrize("source", list(SOURCES))
@pytest.mark.parametrize("endpoint", ["chat", "responses"])
def test_refused_creator_does_not_drop_the_session_of_a_concurrent_request(
    endpoint: str, source: str
) -> None:
    llm = GatedLlm()
    gw = _gateway(llm)
    error, result = asyncio.run(_pair(gw, llm, endpoint, source))
    assert isinstance(error, DetectionError)
    assert not isinstance(result, SessionNotFoundError), "the concurrent request got a 404"
    assert not isinstance(result, BaseException), result
    response, _ = result
    assert response.status_code == 200
    # The served request's mapping lives on: its session is the one the refused one created.
    session_id = response.headers[SESSION_HEADER]
    if source in ("path", "header"):
        assert session_id == "box"
    session = gw.vault.session(session_id)
    assert session.entry_count >= 1
    assert gw._session_holds == {}  # no hold leaks past the requests


@pytest.mark.parametrize("endpoint", ["chat", "responses"])
def test_both_refused_still_drops_the_new_session(endpoint: str) -> None:
    llm = GatedLlm(refuse_second=True)
    gw = _gateway(llm)
    error, result = asyncio.run(_pair(gw, llm, endpoint, "path"))
    assert isinstance(error, DetectionError)
    assert isinstance(result, DetectionError)
    assert len(gw.vault) == 0  # nobody succeeded: fail closed, nothing kept
    assert gw._session_holds == {}


@pytest.mark.parametrize("endpoint", ["chat", "responses"])
def test_a_lone_refused_request_drops_its_new_path_session(endpoint: str) -> None:
    gw = _gateway(FakeLlm(fail=True))

    async def main() -> BaseException | None:
        body = _body(endpoint, REFUSE, None)
        try:
            if endpoint == "chat":
                await gw.chat_completions(body, BEARER, path_session="box")
            else:
                await ResponsesGateway(gw).responses(body, BEARER, path_session="box")
        except BaseException as exc:
            return exc
        finally:
            await gw.aclose()
        return None

    assert isinstance(asyncio.run(main()), DetectionError)
    assert len(gw.vault) == 0
    assert gw._session_holds == {}


def test_placeholders_of_the_served_request_restore_after_the_refusal() -> None:
    llm = GatedLlm()
    gw = _gateway(llm)
    _, result = asyncio.run(_pair(gw, llm, "chat", "path"))
    assert result[0].status_code == 200
    session = gw.vault.session("box")
    placeholders = [p for p, _, _ in session.entities()]
    assert placeholders and all(PLACEHOLDER_RE.fullmatch(p) for p in placeholders)
    assert "Minta Mária" in session.unmask(" ".join(placeholders))


@pytest.mark.parametrize("endpoint", ["chat", "responses"])
@pytest.mark.parametrize("cancel", [False, True])
def test_slow_upstream_keeps_session_pinned_until_completion_or_cancel(
    endpoint: str, cancel: bool
) -> None:
    gw = _gateway(FakeLlm())
    gw.vault = Vault(bytes.fromhex(TEST_TENANT_KEY), max_sessions=2)

    async def main() -> None:
        entered = asyncio.Event()
        resume = asyncio.Event()

        async def upstream(request: httpx.Request) -> httpx.Response:
            entered.set()
            await resume.wait()
            return _upstream(request)

        gw._transport = httpx.MockTransport(upstream)
        body = _body(endpoint, SERVE, None)
        call = (
            gw.chat_completions(body, BEARER, path_session="active")
            if endpoint == "chat"
            else ResponsesGateway(gw).responses(body, BEARER, path_session="active")
        )
        task = asyncio.create_task(call)
        try:
            await asyncio.wait_for(entered.wait(), 5)
            active = gw.vault.session("active")
            for _ in range(5):
                gw.vault.session()
                assert not active.expired
            assert gw.vault._leases[active] == 1
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                resume.set()
                response, _ = await task
                assert response.status_code == 200
            assert not gw.vault._leases
            assert not gw._session_holds
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await gw.aclose()

    asyncio.run(main())


@pytest.mark.parametrize("endpoint", ["chat", "responses"])
@pytest.mark.parametrize("close_early", [False, True])
def test_stream_keeps_pin_until_iterator_cleanup(endpoint: str, close_early: bool) -> None:
    gw = _gateway(FakeLlm())
    gw.vault = Vault(bytes.fromhex(TEST_TENANT_KEY), max_sessions=1)

    class Events(httpx.AsyncByteStream):
        async def __aiter__(self):
            if endpoint == "chat":
                yield b'data: {"choices":[{"index":0,"delta":{"content":"Noted."}}]}\n\n'
                yield b"data: [DONE]\n\n"
            else:
                yield (
                    b"event: response.output_text.delta\n"
                    b'data: {"type":"response.output_text.delta",'
                    b'"output_index":0,"content_index":0,"delta":"Noted."}\n\n'
                )
                yield (
                    b'event: response.completed\ndata: {"type":"response.completed",'
                    b'"response":{"id":"resp_1","status":"completed","output":[]}}\n\n'
                )

    def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Events())

    gw._transport = httpx.MockTransport(upstream)

    async def main() -> None:
        body = _body(endpoint, SERVE, None)
        body["stream"] = True
        try:
            if endpoint == "chat":
                response, _ = await gw.chat_completions(body, BEARER, path_session="active")
            else:
                response, _ = await ResponsesGateway(gw).responses(
                    body, BEARER, path_session="active"
                )
            assert gw.vault._leases
            with pytest.raises(MaskingError):
                gw.vault.session()
            iterator = response.body_iterator
            await anext(iterator)
            if close_early:
                await iterator.aclose()
            else:
                async for _ in iterator:
                    pass
            assert not gw.vault._leases
            assert not gw._session_holds
            gw.vault.session()  # capacity is available again
        finally:
            await gw.aclose()

    asyncio.run(main())


@pytest.mark.parametrize("endpoint", ["chat", "responses"])
def test_stream_lease_released_when_client_leaves_before_the_body(endpoint: str) -> None:
    """Starlette never starts the body iterator when the client is gone at
    ``http.response.start``; the lease must still be released (LAB-1573)."""
    gw = _gateway(FakeLlm())
    gw.vault = Vault(bytes.fromhex(TEST_TENANT_KEY), max_sessions=1)

    def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=b"data: [DONE]\n\n"
        )

    gw._transport = httpx.MockTransport(upstream)

    async def main() -> None:
        body = _body(endpoint, SERVE, None)
        body["stream"] = True
        try:
            if endpoint == "chat":
                response, _ = await gw.chat_completions(body, BEARER, path_session="active")
            else:
                response, _ = await ResponsesGateway(gw).responses(
                    body, BEARER, path_session="active"
                )
            assert gw.vault._leases

            async def receive() -> dict[str, Any]:
                return {"type": "http.disconnect"}

            async def send(message: dict[str, Any]) -> None:
                raise OSError("client went away")  # at http.response.start

            scope = {"type": "http", "asgi": {"spec_version": "2.4"}, "method": "POST"}
            with pytest.raises(Exception):  # noqa: B017 - Starlette's own disconnect error
                await response(scope, receive, send)
            assert not gw.vault._leases
            gw.vault.session()  # capacity is available again
        finally:
            await gw.aclose()

    asyncio.run(main())


def test_one_client_over_its_lease_cap_gets_503_while_others_are_served() -> None:
    """LAB-1584: in-flight requests of one identity are capped, so a flood of long streams
    from one client can't pin every vault slot and 503 everyone else."""
    gw = _gateway(FakeLlm())
    gw.vault = Vault(bytes.fromhex(TEST_TENANT_KEY), max_sessions=10, max_leases_per_identity=2)
    other = {"authorization": "Bearer other-client-not-a-key"}

    async def main() -> None:
        resume = asyncio.Event()
        entered = 0

        async def upstream(request: httpx.Request) -> httpx.Response:
            nonlocal entered
            entered += 1
            await resume.wait()
            return _upstream(request)

        gw._transport = httpx.MockTransport(upstream)

        def call(headers: dict[str, str], path: str) -> Any:
            return gw.chat_completions(_body("chat", SERVE, None), headers, path_session=path)

        held = [asyncio.create_task(call(BEARER, f"flood-{n}")) for n in range(2)]
        try:
            while entered < 2:
                await asyncio.sleep(0.01)
            with pytest.raises(MaskingError) as error:
                await call(BEARER, "flood-2")
            assert error.value.code == "vault_capacity_exhausted"
            assert error.value.status_code == 503
            served = asyncio.create_task(call(other, "other-box"))
            while entered < 3:
                await asyncio.sleep(0.01)
            resume.set()
            response, _ = await served
            assert response.status_code == 200
            for task in held:
                response, _ = await task
                assert response.status_code == 200
            assert not gw.vault._leases
            assert not gw.vault._identity_leases
        finally:
            resume.set()
            for task in held:
                task.cancel()
            await asyncio.gather(*held, return_exceptions=True)
            await gw.aclose()

    asyncio.run(main())
