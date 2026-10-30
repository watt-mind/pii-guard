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

import base64
import binascii
import hmac
import json
import re

from starlette.types import ASGIApp, Receive, Scope, Send

from pii_guard.config import Settings
from pii_guard.observability import is_loopback

__all__ = [
    "DEFAULT_ALLOWED_HOSTS",
    "ENDPOINT_KEY_PREFIX",
    "TOKEN_HEADER",
    "BearerTokenMiddleware",
    "LoopbackOnlyMiddleware",
    "allowed_hosts",
    "looks_like_endpoint_key",
]

DEFAULT_ALLOWED_HOSTS: tuple[str, ...] = ("localhost", "127.0.0.1", "[::1]")
TOKEN_HEADER = "x-pii-guard-token"  # noqa: S105 - a header name
ENDPOINT_KEY_PREFIX = "pg_ep_"


def looks_like_endpoint_key(credential: str) -> bool:
    """Whether a credential claims to be an endpoint key, in any letter case.

    One predicate for every layer (LAB-1562): a credential the token middleware
    treats as an endpoint key must be resolved as one by ``ProjectMiddleware``,
    never fall through to another admission path. Real keys are issued with the
    exact lowercase prefix; a differently cased one simply fails resolution.
    """
    return credential.strip().lower().startswith(ENDPOINT_KEY_PREFIX)


# ASCII letters and digits: a token occurrence touching one of these continues a longer word.
_TOKEN_BYTES = frozenset(b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


# A run of base64 characters (both alphabets) and its padding; disjoint classes, no backtracking.
_BASE64_RUN = re.compile(rb"[A-Za-z0-9+/_-]+=*")


def _base64_decodings(field: bytes) -> list[bytes]:
    """``field`` decoded as standard and as URL-safe base64, padding optional (LAB-1591)."""
    padded = field.rstrip(b"=") + b"=" * (-len(field.rstrip(b"=")) % 4)
    decodings = []
    for altchars in (None, b"-_"):
        try:
            decodings.append(base64.b64decode(padded, altchars=altchars, validate=True))
        except (binascii.Error, ValueError):
            continue
    return decodings


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
    An ``Authorization`` header carrying the token in any shape (another scheme, a tab, extra
    padding or punctuation as separator, no scheme at all, inside an HTTP ``Basic`` credential)
    authenticates too, and is removed from the request after the check, so the gateway never
    forwards it upstream (LAB-1570, LAB-1591). So is an
    ``x-api-key`` carrying it (Anthropic clients, LAB-1605). Clients that bring
    their own upstream key (no ``PII_GUARD_UPSTREAM_API_KEY``) send it in ``Authorization`` and
    the token in the header.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        if not token.strip():
            # Fail closed: an empty token would match an empty header (LAB-1570).
            raise ValueError("PII_GUARD_API_TOKEN is set but empty")
        self.app = app
        self.token = token.encode()

    def _matches(self, value: bytes) -> bool:
        return hmac.compare_digest(value.strip(), self.token)

    def _scan(self, data: bytes) -> tuple[bool, bool]:
        """Whether the token occurs anywhere in ``data``, and whether it occurs standalone.

        Every window of ``data`` the length of the token is compared in constant time, with no
        early exit, so the time taken depends on the length of ``data`` only. An occurrence is
        standalone when no ASCII letter or digit touches it on either side: ``key:<token>``,
        ``"<token>"`` or ``token=<token>`` are standalone, ``<token>x`` is not (LAB-1591).
        """
        size = len(self.token)
        found = standalone = False
        for i in range(len(data) - size + 1):  # no early exit: every window is compared
            hit = hmac.compare_digest(data[i : i + size], self.token)
            before = i == 0 or data[i - 1] not in _TOKEN_BYTES
            after = i + size == len(data) or data[i + size] not in _TOKEN_BYTES
            found |= hit
            standalone |= hit & before & after
        return found, standalone

    def _carries_token(self, value: bytes) -> tuple[bool, bool]:
        """Whether a credential header carries the token: ``(strip, authenticate)``.

        The raw value is scanned (LAB-1570: any scheme, any separator, whitespace or
        punctuation; LAB-1591), and so is every run of base64 characters in it that decodes,
        standard or URL-safe: an HTTP ``Basic`` credential such as
        ``base64(user:<token>)`` or ``base64(<token>:)``, with or without the scheme. Any
        occurrence strips the header, fail closed, so no spelling of the token reaches the
        upstream provider; a standalone occurrence also authenticates. A token glued to other
        letters or digits (``<token>x``) is stripped but does not authenticate.
        """
        found, standalone = self._scan(value)
        for field in _BASE64_RUN.findall(value):
            for decoded in _base64_decodings(field):
                hit, alone = self._scan(decoded)
                found |= hit
                standalone |= alone
        return found, standalone

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in _PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        headers: list[tuple[bytes, bytes]] = list(scope.get("headers") or [])

        # Endpoint authentication is confined and checked by ProjectMiddleware,
        # which recognizes endpoint keys with this same predicate and the same
        # Latin-1 header decoding as Starlette (LAB-1562, LAB-1570).
        def bearer_credential(value: bytes) -> bytes | None:
            scheme, _, credential = value.partition(b" ")
            return credential.strip() if scheme.lower() == b"bearer" else None

        path = scope.get("path", "")
        if (path.startswith("/e/") or path == "/muse-code/models") and any(
            name.lower() == b"authorization"
            and (credential := bearer_credential(value)) is not None
            and looks_like_endpoint_key(credential.decode("latin-1"))
            for name, value in headers
        ):
            await self.app(scope, receive, send)
            return
        ok = any(
            name.lower() == TOKEN_HEADER.encode() and self._matches(value)
            for name, value in headers
        )
        # Strip every Authorization carrying the token, in any shape and whichever
        # header authenticated, so the gateway never forwards it upstream
        # (LAB-1562, LAB-1570).
        kept: list[tuple[bytes, bytes]] = []
        for name, value in headers:
            # ``x-api-key`` too: Anthropic clients send their key there, and /v1/messages
            # passes it upstream as a "bring your own key" (LAB-1605).
            if name.lower() in (b"authorization", b"x-api-key"):
                strip, authenticates = self._carries_token(value)
                ok |= authenticates
                if strip:
                    continue  # never forwarded upstream as a "bring your own key"
            kept.append((name, value))
        headers = kept
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
