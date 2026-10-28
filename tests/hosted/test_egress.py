"""Socket-level egress policy tests. Addresses and credentials are synthetic."""

from __future__ import annotations

import asyncio
import ssl
from typing import Any

import httpcore
import httpx
import pytest

from pii_guard.hosted.egress import (
    EgressPolicyError,
    PublicNetworkBackend,
    SecureTransport,
    resolve_public,
    secure_client,
    validate_base_url,
    validate_destination,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/v1",
        "https://api.example.com:8443/v1",
        "https://user:secret@api.example.com/v1",
        "https://api.example.com/v1?key=secret",
        "https://api.example.com/v1#secret",
        "https://api.example.com/v1?",
        "https://api.example.com/v1#",
        "https://localhost/v1",
        "https://foo.local/v1",
        "https://foo.internal/v1",
        "https://127.0.0.1/v1",
        "https://[::1]/v1",
        "https://192.168.1.1/v1",
        "https://169.254.169.254/v1",
        "https://2130706433/v1",
        "https://127.1/v1",
        "https://0x7f000001/v1",
        "https://api.example.com./v1",
        "https://api.example.com\\@localhost/v1",
        "https://api.example.com\n/v1",
        "https://api.example.com:bad/v1",
        "https://api..example.com/v1",
        "https://-api.example.com/v1",
        "https://[invalid/v1",
        "",
        "https://%31%32%37.0.0.1",
    ],
)
def test_rejects_unsafe_url_syntax(url: str) -> None:
    with pytest.raises(EgressPolicyError) as exc:
        validate_base_url(url)
    assert "secret" not in str(exc.value)


def test_normalization() -> None:
    assert validate_base_url("https://API.EXAMPLE.COM:443/v1/") == "https://api.example.com/v1"


class RecordingStream(httpcore.AsyncNetworkStream):
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.writes: list[bytes] = []
        self.sni: list[str | None] = []
        self.closed = False

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        result, self.response = self.response, b""
        return result

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self.writes.append(buffer)

    async def aclose(self) -> None:
        self.closed = True

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> RecordingStream:
        assert ssl_context.verify_mode == ssl.CERT_REQUIRED
        assert ssl_context.check_hostname
        self.sni.append(server_hostname)
        return self


class RecordingBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, response: bytes = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok") -> None:
        self.hosts: list[tuple[str, int]] = []
        self.streams: list[RecordingStream] = []
        self.response = response

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> RecordingStream:
        self.hosts.append((host, port))
        stream = RecordingStream(self.response)
        self.streams.append(stream)
        return stream


async def public(host: str) -> tuple[str, ...]:
    assert host == "api.example.com"
    return ("93.184.216.34",)


def test_pins_actual_socket_preserves_host_and_tls_ignores_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")

    async def run() -> None:
        backend = RecordingBackend()
        transport = SecureTransport(resolver=public, backend=backend)
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.get(
                "https://api.example.com/v1/models",
                headers={"Host": "private.internal"},
                extensions={"sni_hostname": "private.internal"},
            )
        assert response.text == "ok"
        assert backend.hosts == [("93.184.216.34", 443)]
        assert backend.streams[0].sni == ["api.example.com"]
        wire = b"".join(backend.streams[0].writes)
        assert b"Host: api.example.com\r\n" in wire
        assert b"private.internal" not in wire

    asyncio.run(run())


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "0.0.0.0",  # noqa: S104 - adversarial DNS answer, never a bind
        "100.64.0.1",
        "192.0.2.1",
        "224.0.0.1",
        "255.255.255.255",
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "2001:db8::1",
        "ff02::1",
        "::ffff:127.0.0.1",
        "2002:7f00:1::",
        "invalid",
    ],
)
def test_rejects_any_bad_dns_answer_even_with_good_address(address: str) -> None:
    async def run() -> None:
        async def mixed(host: str) -> tuple[str, ...]:
            return ("93.184.216.34", address)

        backend = RecordingBackend()
        transport = SecureTransport(resolver=mixed, backend=backend)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(EgressPolicyError):
                await client.get("https://api.example.com/v1/models")
        assert backend.hosts == []

    asyncio.run(run())


def test_preflight_rebinding_and_every_new_connection() -> None:
    async def run() -> None:
        answers = iter([("93.184.216.34",), ("10.0.0.1",)])

        async def changing(host: str) -> tuple[str, ...]:
            return next(answers)

        assert await validate_destination("https://api.example.com/v1", resolver=changing)
        backend = RecordingBackend()
        async with httpx.AsyncClient(
            transport=SecureTransport(resolver=changing, backend=backend)
        ) as client:
            with pytest.raises(EgressPolicyError):
                await client.post(
                    "https://api.example.com/v1/responses",
                    headers={"Authorization": "Bearer fictional"},
                )
        assert not backend.hosts

        answers = iter([("93.184.216.34",), ("10.0.0.1",)])
        transport = SecureTransport(resolver=changing, backend=backend, max_keepalive_connections=0)
        async with httpx.AsyncClient(transport=transport) as client:
            assert (await client.get("https://api.example.com/v1/models")).status_code == 200
            with pytest.raises(EgressPolicyError):
                await client.get("https://api.example.com/v1/models")
        assert backend.hosts == [("93.184.216.34", 443)]

    asyncio.run(run())


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_redirects_refused_even_if_client_follows(code: int) -> None:
    async def run() -> None:
        response = (
            f"HTTP/1.1 {code} Redirect\r\n"
            "Location: https://private.internal/v1\r\nContent-Length: 0\r\n\r\n"
        ).encode()
        backend = RecordingBackend(response)
        async with httpx.AsyncClient(
            transport=SecureTransport(resolver=public, backend=backend),
            follow_redirects=True,
        ) as client:
            with pytest.raises(httpx.RemoteProtocolError, match="redirects are disabled"):
                await client.post(
                    "https://api.example.com/v1/chat/completions",
                    headers={"Authorization": "Bearer fictional"},
                )
        assert len(backend.hosts) == 1
        assert backend.streams[0].closed

    asyncio.run(run())


def test_network_backend_refuses_unix_and_other_ports() -> None:
    async def run() -> None:
        backend = PublicNetworkBackend(resolver=public)
        with pytest.raises(EgressPolicyError):
            await backend.connect_unix_socket("/nonexistent/blocked/socket")
        with pytest.raises(EgressPolicyError):
            await backend.connect_tcp("api.example.com", 80)
        with pytest.raises(EgressPolicyError):
            await backend.connect_tcp("api.example.com", 443, local_address="127.0.0.1")
        await backend.sleep(0)

    asyncio.run(run())


def test_dns_resolution_failure_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        async def failure(*args: Any, **kwargs: Any) -> Any:
            raise OSError("synthetic-sensitive-detail")

        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", failure)
        with pytest.raises(httpx.ConnectError) as exc:
            await resolve_public("api.example.com")
        assert "synthetic-sensitive-detail" not in str(exc.value)

    asyncio.run(run())


def test_empty_dns_and_dns_timeout() -> None:
    async def run() -> None:
        async def empty(host: str) -> tuple[str, ...]:
            return ()

        async def slow(host: str) -> tuple[str, ...]:
            await asyncio.sleep(1)
            return ()

        with pytest.raises(EgressPolicyError):
            await validate_destination("https://api.example.com/v1", resolver=empty)
        with pytest.raises(httpcore.ConnectTimeout):
            await PublicNetworkBackend(resolver=slow).connect_tcp(
                "api.example.com", 443, timeout=0.001
            )
        async with secure_client() as client:
            assert not client.follow_redirects
            assert not client.trust_env

    asyncio.run(run())


def test_public_ipv6_answers_are_pinned_and_all_resolver_results_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        async def answer(*args: Any, **kwargs: Any) -> Any:
            return [(10, 1, 6, "", ("2606:4700:4700::1111", 443, 0, 0))]

        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", answer)
        backend = RecordingBackend()
        transport = SecureTransport(backend=backend)
        async with httpx.AsyncClient(transport=transport) as client:
            assert (await client.get("https://api.example.com/v1/models")).status_code == 200
        assert backend.hosts == [("2606:4700:4700::1111", 443)]
        assert backend.streams[0].sni == ["api.example.com"]

    asyncio.run(run())


@pytest.mark.parametrize("exception", [httpcore.ConnectError, httpcore.ConnectTimeout])
def test_connection_failures_sanitized_without_retry(exception: type[Exception]) -> None:
    async def run() -> None:
        class FailingBackend(RecordingBackend):
            async def connect_tcp(
                self,
                host: str,
                port: int,
                timeout: float | None = None,
                local_address: str | None = None,
                socket_options: Any = None,
            ) -> RecordingStream:
                self.hosts.append((host, port))
                raise exception("synthetic-sensitive-detail")

        backend = FailingBackend()
        async with httpx.AsyncClient(
            transport=SecureTransport(resolver=public, backend=backend)
        ) as client:
            with pytest.raises(httpx.TransportError) as exc:
                await client.get("https://api.example.com/v1/models")
        assert "synthetic-sensitive-detail" not in str(exc.value)
        assert len(backend.hosts) == 1

    asyncio.run(run())


def test_broken_response_stream_sanitized_and_closed() -> None:
    async def run() -> None:
        backend = RecordingBackend(b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\nshort")
        async with httpx.AsyncClient(
            transport=SecureTransport(resolver=public, backend=backend)
        ) as client:
            with pytest.raises(httpx.ReadError, match="upstream response interrupted"):
                await client.get("https://api.example.com/v1/models")
        assert backend.streams[0].closed

    asyncio.run(run())


def test_preflight_timeout_is_sanitized() -> None:
    async def run() -> None:
        async def timed_out(host: str) -> tuple[str, ...]:
            raise TimeoutError("synthetic-sensitive-detail")

        with pytest.raises(httpx.ConnectTimeout) as exc:
            await validate_destination("https://api.example.com/v1", resolver=timed_out)
        assert "synthetic-sensitive-detail" not in str(exc.value)

    asyncio.run(run())


def test_secure_client_preserves_structured_timeout() -> None:
    async def run() -> None:
        configured = httpx.Timeout(connect=3, read=12, write=7, pool=2)
        async with secure_client(timeout=configured) as client:
            assert client.timeout == configured
            assert client.timeout.connect == 3
            assert client.timeout.read == 12
            assert client.timeout.write == 7
            assert client.timeout.pool == 2
        async with secure_client(timeout=45) as client:
            assert client.timeout == httpx.Timeout(45, connect=10)

    asyncio.run(run())
