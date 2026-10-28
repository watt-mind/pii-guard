"""Hosted public-HTTPS egress, enforced on the socket rather than a DNS preflight.

The pool retains the original URL/Host/TLS name. Its network backend resolves all A/AAAA
answers, checks every address, and connects only to a checked numeric address. A later
connection resolves and checks again; a DNS change cannot redirect a preflight-approved
hostname to the private network. No environment proxy, redirects or transport retries.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import ssl
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpcore
import httpx

from pii_guard.types import PiiGuardError

MAX_RESPONSE_BYTES = 2 * 1024 * 1024

Resolver = Callable[[str], Awaitable[tuple[str, ...]]]
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".test", ".invalid")


class EgressPolicyError(PiiGuardError):
    code = "upstream_destination_not_allowed"
    status_code = 422

    def __init__(self) -> None:
        super().__init__("upstream must use a public HTTPS destination on port 443")


def _hostname(host: str) -> str:
    try:
        host = host.encode("idna").decode("ascii").lower()
        ipaddress.ip_address(host)
    except UnicodeError:
        raise EgressPolicyError() from None
    except ValueError:
        pass
    else:
        raise EgressPolicyError()
    if (
        len(host) > 253
        or "." not in host
        or not any(c.isalpha() for c in host.rsplit(".", 1)[-1])
        or host.endswith(_LOCAL_SUFFIXES)
        or any(not _HOST_LABEL.fullmatch(label) for label in host.split("."))
    ):
        raise EgressPolicyError()
    return host


def validate_base_url(value: str) -> str:
    """Normalize an endpoint base; errors contain no caller-supplied URL or credentials."""
    try:
        if not value or len(value) > 2048 or any(ord(c) <= 32 or ord(c) == 127 for c in value):
            raise EgressPolicyError()
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.port not in (None, 443)
            or "?" in value
            or "#" in value
            or "\\" in value
        ):
            raise EgressPolicyError()
        host = _hostname(parts.hostname)
        return urlunsplit(("https", host, parts.path.rstrip("/"), "", ""))
    except (ValueError, UnicodeError):
        raise EgressPolicyError() from None


def _check_addresses(addresses: tuple[str, ...]) -> tuple[str, ...]:
    if not addresses:
        raise EgressPolicyError()
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            raise EgressPolicyError() from None
        # is_global alone includes multicast and some IPv6 transition mechanisms.
        if (
            not ip.is_global
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
            or ip.is_loopback
            or ip.is_link_local
            or (
                isinstance(ip, ipaddress.IPv6Address)
                and (ip.ipv4_mapped or ip.sixtofour or ip.teredo)
            )
        ):
            raise EgressPolicyError()
    return tuple(dict.fromkeys(addresses))


async def resolve_public(host: str) -> tuple[str, ...]:
    """Resolve both address families; every answer must be globally routable."""
    host = _hostname(host)
    try:
        answers = await asyncio.get_running_loop().getaddrinfo(
            host, 443, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
        )
    except (OSError, UnicodeError):
        raise httpx.ConnectError("upstream DNS resolution failed") from None
    return _check_addresses(tuple(str(answer[4][0]) for answer in answers))


async def validate_destination(value: str, *, resolver: Resolver = resolve_public) -> str:
    """Connection-create feedback only; socket-time policy remains authoritative."""
    normalized = validate_base_url(value)
    try:
        async with asyncio.timeout(10):
            _check_addresses(await resolver(urlsplit(normalized).hostname or ""))
    except TimeoutError:
        raise httpx.ConnectTimeout("upstream DNS resolution timed out") from None
    return normalized


class PublicNetworkBackend(httpcore.AsyncNetworkBackend):
    """httpcore calls this for each new socket, before it negotiates original-host TLS."""

    def __init__(
        self,
        *,
        resolver: Resolver = resolve_public,
        backend: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._resolver = resolver
        self._backend = backend if backend is not None else httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        host = _hostname(host)
        if port != 443 or local_address is not None:
            raise EgressPolicyError()
        try:
            async with asyncio.timeout(timeout if timeout is not None else 10):
                addresses = _check_addresses(await self._resolver(host))
                # Numeric address only: the backend never receives the untrusted DNS name.
                return await self._backend.connect_tcp(
                    addresses[0], port, timeout=timeout, socket_options=socket_options
                )
        except TimeoutError:
            raise httpcore.ConnectTimeout("upstream connection timed out") from None

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise EgressPolicyError()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class BoundedResponseStream(httpx.AsyncByteStream):
    """Bound total raw response bytes before delivery, for catalogs and streamed answers."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream

    async def __aiter__(self) -> AsyncIterator[bytes]:
        total = 0
        try:
            async for chunk in self._stream:
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    await self._stream.aclose()
                    raise httpx.ReadError("upstream response exceeds hosted size limit")
                yield chunk
        except (httpcore.NetworkError, httpcore.ProtocolError, httpcore.TimeoutException):
            raise httpx.ReadError("upstream response interrupted") from None

    async def aclose(self) -> None:
        await self._stream.aclose()


# Kept for callers that used the original internal transport adapter name.
_ResponseStream = BoundedResponseStream


class SecureTransport(httpx.AsyncBaseTransport):
    """HTTPS transport with connection-time DNS enforcement and redirects refused outright."""

    def __init__(
        self,
        *,
        resolver: Resolver = resolve_public,
        backend: httpcore.AsyncNetworkBackend | None = None,
        max_connections: int = 20,
        max_keepalive_connections: int = 10,
    ) -> None:
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            network_backend=PublicNetworkBackend(resolver=resolver, backend=backend),
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
            keepalive_expiry=15,
            retries=0,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        validate_base_url(str(request.url))
        # Do not permit a mismatched Host or caller-selected TLS name, even via extensions.
        headers = [
            (k, v) for k, v in request.headers.raw if k.lower() not in (b"host", b"accept-encoding")
        ]
        headers.insert(0, (b"Host", request.url.raw_host))
        headers.append((b"Accept-Encoding", b"identity"))
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=b"https",
                host=request.url.raw_host,
                port=443,
                target=request.url.raw_path,
            ),
            headers=headers,
            content=request.stream,
            extensions={"timeout": request.extensions.get("timeout", {})},
        )
        try:
            response = await self._pool.handle_async_request(core_request)
        except httpcore.TimeoutException:
            raise httpx.ConnectTimeout("upstream connection timed out") from None
        except (httpcore.NetworkError, httpcore.ProtocolError):
            raise httpx.ConnectError("upstream connection failed") from None
        if 300 <= response.status < 400:
            await response.aclose()
            raise httpx.RemoteProtocolError("upstream redirects are disabled")
        for name, value in response.headers:
            if name.lower() == b"content-encoding" and value.strip().lower() != b"identity":
                await response.aclose()
                raise httpx.ReadError("compressed upstream responses are disabled")
            if name.lower() == b"content-length":
                try:
                    length = int(value)
                except ValueError:
                    await response.aclose()
                    raise httpx.ReadError("invalid upstream response size") from None
                if length < 0 or length > MAX_RESPONSE_BYTES:
                    await response.aclose()
                    raise httpx.ReadError("upstream response exceeds hosted size limit")
        return httpx.Response(
            response.status,
            headers=response.headers,
            stream=BoundedResponseStream(response.stream),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


def secure_client(*, timeout: float | httpx.Timeout = 60.0) -> httpx.AsyncClient:
    """A standalone hosted catalog/probe client; Gateway can inject SecureTransport directly."""
    return httpx.AsyncClient(
        transport=SecureTransport(),
        timeout=timeout
        if isinstance(timeout, httpx.Timeout)
        else httpx.Timeout(timeout, connect=10),
        trust_env=False,
        follow_redirects=False,
    )
