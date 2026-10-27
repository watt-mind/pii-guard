"""Exposure guards of the API (``docs/operations.md``, "Exposure and authentication").

- :func:`allowed_hosts`: the ``Host`` headers the API answers. A page on another site can make
  the browser talk to ``127.0.0.1`` through DNS rebinding, but its requests still carry the
  attacker's host name; refusing unknown hosts closes that path.
- :class:`LoopbackOnlyMiddleware`: with ``PII_GUARD_TRAFFIC_LOG=full``, every request must arrive
  on a loopback socket from a loopback client. The startup check only sees the configured host;
  ``uvicorn --host 0.0.0.0`` (or any other launcher) can bind elsewhere, and uvicorn binds its
  sockets after the app's lifespan has started, so the check runs on each request.
- :class:`BearerTokenMiddleware`: the optional ``PII_GUARD_API_TOKEN``. Off by default: the API
  has no authentication unless it is set.
"""

from __future__ import annotations

import hmac
import json

from starlette.types import ASGIApp, Receive, Scope, Send

from pii_guard.config import Settings
from pii_guard.observability import is_loopback

__all__ = [
    "DEFAULT_ALLOWED_HOSTS",
    "TOKEN_HEADER",
    "BearerTokenMiddleware",
    "LoopbackOnlyMiddleware",
    "allowed_hosts",
]

DEFAULT_ALLOWED_HOSTS: tuple[str, ...] = ("localhost", "127.0.0.1", "[::1]")
TOKEN_HEADER = "x-pii-guard-token"  # noqa: S105 - a header name
_WILDCARD_BINDS = {"0.0.0.0", "::", "[::]", ""}  # noqa: S104 - names, not a bind
_PUBLIC_PATHS = frozenset({"/healthz"})


def _host_pattern(host: str) -> str:
    host = host.strip().lower()
    if ":" in host and not host.startswith("["):
        return f"[{host}]"  # an IPv6 literal, as it appears in a Host header
    return host


def allowed_hosts(settings: Settings) -> list[str]:
    """Loopback names, ``PII_GUARD_HOST`` (unless a wildcard) and ``PII_GUARD_ALLOWED_HOSTS``.

    ``*`` in ``PII_GUARD_ALLOWED_HOSTS`` turns the check off (``["*"]``).
    """
    hosts = list(DEFAULT_ALLOWED_HOSTS)
    if settings.host.strip() not in _WILDCARD_BINDS:
        hosts.append(_host_pattern(settings.host))
    for host in settings.allowed_hosts:
        if host == "*":
            return ["*"]
        hosts.append(_host_pattern(host))
    return list(dict.fromkeys(hosts))


async def _send_error(send: Send, status: int, code: str, message: str, **headers: str) -> None:
    body = json.dumps({"error": {"code": code, "message": message}}).encode()
    raw = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        *((k.encode(), v.encode()) for k, v in headers.items()),
    ]
    await send({"type": "http.response.start", "status": status, "headers": raw})
    await send({"type": "http.response.body", "body": body})


def _addr_is_loopback(addr: object) -> bool:
    if addr is None:
        return True  # a Unix socket: local by construction
    host = addr[0] if isinstance(addr, list | tuple) and addr else addr
    return isinstance(host, str) and is_loopback(host)


class LoopbackOnlyMiddleware:
    """403 ``traffic_log_not_local`` unless both ends of the connection are loopback."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or (
            _addr_is_loopback(scope.get("server")) and _addr_is_loopback(scope.get("client"))
        ):
            await self.app(scope, receive, send)
            return
        await _send_error(
            send,
            403,
            "traffic_log_not_local",
            "PII_GUARD_TRAFFIC_LOG=full only serves loopback connections; this server is "
            "reachable from other machines. Bind to 127.0.0.1 or use 'masked'",
        )


class BearerTokenMiddleware:
    """Require ``PII_GUARD_API_TOKEN`` on every route but ``/healthz``.

    The token is accepted as ``X-PII-Guard-Token: <token>`` or ``Authorization: Bearer <token>``.
    A token sent in ``Authorization`` is removed from the request after the check, so the
    gateway never forwards it upstream. Clients that bring their own upstream key (no
    ``PII_GUARD_UPSTREAM_API_KEY``) send it in ``Authorization`` and the token in the header.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token.encode()

    def _matches(self, value: bytes) -> bool:
        return hmac.compare_digest(value.strip(), self.token)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in _PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        headers: list[tuple[bytes, bytes]] = list(scope.get("headers") or [])
        ok = False
        for name, value in headers:
            if name.lower() == TOKEN_HEADER.encode() and self._matches(value):
                ok = True
        if not ok:
            for i, (name, value) in enumerate(headers):
                scheme, _, credential = value.partition(b" ")
                if (
                    name.lower() == b"authorization"
                    and scheme.lower() == b"bearer"
                    and self._matches(credential)
                ):
                    ok = True
                    del headers[i]  # never forwarded upstream as a "bring your own key"
                    break
        if not ok:
            await _send_error(
                send,
                401,
                "unauthorized",
                "this server requires PII_GUARD_API_TOKEN: send 'Authorization: Bearer <token>' "
                f"or '{TOKEN_HEADER}: <token>'",
                **{"www-authenticate": 'Bearer realm="pii-guard"'},
            )
            return
        await self.app({**scope, "headers": headers}, receive, send)
