"""Shared pieces of the ``/v1/*`` routers (not a router itself: the ``_`` prefix skips it).

- :class:`LoggedRoute` logs one access line per request -- method, path, status, duration
  and, for masking, entity counts. It never logs bodies, text, session ids or values.
  It also rejects a body far beyond the text limit before it is parsed: a declared
  ``Content-Length`` at once, and any body (chunked included) as soon as the bytes read so
  far pass the limit, so an oversized body is never buffered whole (LAB-1207).
- :func:`v1_router` builds a router with that route class.
- :func:`ephemeral_session` resolves a request's vault session and drops it again when the
  request created it and then fails (ADR 0006: a refused request leaves nothing in the vault).
- :func:`owned_session` looks up an existing session the caller names, refusing a session a
  gateway request bound to a different client identity (LAB-1590).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import TYPE_CHECKING, Any, overload

from fastapi import APIRouter, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Message

from pii_guard.api.deps import PayloadTooLargeError, get_max_text_chars
from pii_guard.gateway.sessions import check_owner, client_identity
from pii_guard.policy import BlockedEntityError
from pii_guard.types import PiiGuardError
from pii_guard.vault import Vault, VaultSession

if TYPE_CHECKING:
    from pii_guard.observability.metrics import LatencyMetrics

__all__ = [
    "BODY_READ_TIMEOUT_SECONDS",
    "BodyReadTimeoutError",
    "ClientDisconnectedError",
    "LoggedRoute",
    "body_read_timeout",
    "check_text_size",
    "ensure_connected",
    "ephemeral_session",
    "log_extra",
    "owned_session",
    "request_metrics",
    "text_body_limit",
    "v1_router",
]

access_logger = logging.getLogger("pii_guard.api.access")

# One code point is at most 12 bytes of JSON (an astral character escaped as a surrogate
# pair); allow that plus room for the other fields, so a legal text is never rejected here.
_BODY_BYTES_PER_CHAR = 12
_BODY_OVERHEAD_BYTES = 16_384

#: Default whole request-body read deadline (LAB-1566): bytes alone do not stop a slow-loris
#: client from holding a request open. ``PII_GUARD_BODY_READ_TIMEOUT``
#: (``Settings.body_read_timeout``, LAB-1581) overrides it; this applies without app settings.
BODY_READ_TIMEOUT_SECONDS = 30.0


def body_read_timeout(request: Request) -> float:
    """The body-read deadline in seconds: ``Settings.body_read_timeout``, else the default."""
    app = request.scope.get("app")
    settings = getattr(getattr(app, "state", None), "settings", None)
    timeout = getattr(settings, "body_read_timeout", None)
    return float(timeout) if timeout is not None else BODY_READ_TIMEOUT_SECONDS


def request_metrics(request: Request) -> LatencyMetrics | None:
    """The app's Prometheus metrics collector when enabled."""
    scope = getattr(request, "scope", None)
    app = scope.get("app") if isinstance(scope, dict) else getattr(request, "app", None)
    state = getattr(app, "state", None)
    if state is None:
        return None
    obs = getattr(state, "observability", None)
    return getattr(obs, "metrics", None)


class BodyReadTimeoutError(PiiGuardError):
    """The request body did not arrive within the deadline; nothing was processed."""

    code = "request_timeout"
    status_code = 408


class ClientDisconnectedError(PiiGuardError):
    """The client went away before its request was processed (no detection, no upstream)."""

    code = "client_disconnected"
    status_code = 499


async def ensure_connected(request: Request) -> None:
    """Fail before detection/upstream work if the client already disconnected (LAB-1566)."""
    if await request.is_disconnected():
        raise ClientDisconnectedError("client disconnected before the request was processed")


def log_extra(request: Request, **fields: object) -> None:
    """Attach safe fields (counts, entity types) to this request's access log line."""
    extra = getattr(request.state, "log_fields", None)
    if extra is None:
        extra = {}
        request.state.log_fields = extra
    extra.update(fields)


class LoggedRoute(APIRoute):
    """An ``APIRoute`` that writes a body-free access log line for every request.

    Subclasses with larger bodies (images) override :meth:`max_body_bytes`.
    """

    def max_body_bytes(self, request: Request) -> int:
        """The largest declared body accepted before parsing; derived from the text limit."""
        return text_body_limit(request)

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def logged(request: Request) -> Response:
            started = time.perf_counter()
            status = 500
            error_code: str | None = None
            try:
                limit = self.max_body_bytes(request)
                _check_body_size(request, limit)
                request = await _read_body_capped(request, limit)
                response = await handler(request)
                status = response.status_code
                return response
            except PiiGuardError as exc:
                status, error_code = exc.status_code, exc.code
                raise
            except StarletteHTTPException as exc:
                status = exc.status_code
                raise
            except RequestValidationError:
                status, error_code = 422, "invalid_request"
                raise
            except Exception as exc:
                # Never the exception text: it may contain raw values.
                error_code = type(exc).__name__
                raise
            finally:
                duration_ms = (time.perf_counter() - started) * 1000
                if self.path != "/metrics" and (metrics := request_metrics(request)) is not None:
                    metrics.observe_http(request.method, self.path, status, duration_ms)
                fields = getattr(request.state, "log_fields", None) or {}
                access_logger.info(
                    "%s %s %d %.1fms%s%s",
                    request.method,
                    self.path,  # the template: never a session id from the URL
                    status,
                    duration_ms,
                    f" error={error_code}" if error_code else "",
                    "".join(f" {key}={value}" for key, value in sorted(fields.items())),
                )

        return logged


def text_body_limit(request: Request) -> int:
    """The body size (bytes) a request at the text limit can legally have, as JSON."""
    return get_max_text_chars(request) * _BODY_BYTES_PER_CHAR + _BODY_OVERHEAD_BYTES


def _check_body_size(request: Request, limit: int) -> None:
    """Reject bodies whose declared size is beyond ``limit``, before parsing."""
    declared = request.headers.get("content-length")
    if declared is None or not declared.isdigit():
        return
    if int(declared) > limit:
        raise PayloadTooLargeError("request body is too large")


async def _read_body_capped(request: Request, limit: int) -> Request:
    """Read the body with a running byte count; 413 once it passes ``limit``.

    The body is cached on the returned request (Starlette's ``request.body()`` / ``stream()``
    then return it), so the handler reads what was counted here. A time deadline
    (:func:`body_read_timeout`, LAB-1566) bounds the whole read as well: past it, 408 and
    nothing is processed."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return request
    chunks: list[bytes] = []
    size = 0
    try:
        async with asyncio.timeout(body_read_timeout(request)):
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise PayloadTooLargeError("request body is too large")
                chunks.append(chunk)
    except TimeoutError:
        raise BodyReadTimeoutError("request body read timed out") from None
    payload = b"".join(chunks)
    consumed = False

    async def replay_receive() -> Message:
        nonlocal consumed
        if not consumed:
            consumed = True
            return {"type": "http.request", "body": payload, "more_body": False}
        return await request.receive()

    buffered = Request(request.scope, replay_receive)
    await buffered.body()
    return buffered


def check_text_size(request: Request, text: str) -> None:
    """Fail with 413 if ``text`` is longer than the configured limit (in code points)."""
    limit = get_max_text_chars(request)
    if len(text) > limit:
        raise PayloadTooLargeError(f"text is longer than {limit} characters")


def owned_session(vault: Vault, session_id: str, request: Request) -> VaultSession:
    """The existing session ``session_id``, if the caller may use it (LAB-1590).

    Unknown, expired or closed: :class:`~pii_guard.vault.SessionNotFoundError` (404). A session
    a gateway request bound to a client identity (LAB-1565/1580) is refused to any other
    identity -- a different ``Authorization`` value, or none for a credentialed owner -- with
    the same 404, as ``/v1/unmask`` does. The check runs before the TTL slides (LAB-1584), so
    a refused caller can't keep the session alive. Unbound and anonymous-owned sessions stay
    open to every caller, and the lookup never claims a session.
    """
    identity = client_identity(request.headers)
    return vault.session(session_id, authorize=lambda s: check_owner(s, identity))


@overload
def ephemeral_session(
    vault: Vault, session_id: str | None, request: Request
) -> AbstractContextManager[VaultSession]: ...


@overload
def ephemeral_session(
    vault: Vault | None, session_id: str | None, request: Request
) -> AbstractContextManager[VaultSession | None]: ...


def ephemeral_session(
    vault: Vault | None, session_id: str | None, request: Request
) -> AbstractContextManager[VaultSession | None]:
    """``with ephemeral_session(vault, session_id, request) as session:`` fails closed.

    On entry, :func:`owned_session`: the existing session (unknown, expired or bound to another
    client identity: 404 ``not_found``, before the block runs) or, for ``None``, a new one.
    Without a vault (``None``, e.g. an opaque image) the session is ``None``.

    If the block raises anything (``BaseException``: cancellation and timeouts too), a
    :class:`~pii_guard.policy.BlockedEntityError` adds ``blocked=<TYPE:count,...>`` to the
    access log line, and a session this request created (no ``session_id``) is dropped, so
    nothing it stored survives. An existing session is left as it is. The error is re-raised.
    """
    return _ephemeral_session(vault, session_id, request)


@contextmanager
def _ephemeral_session(
    vault: Vault | None, session_id: str | None, request: Request
) -> Iterator[VaultSession | None]:
    if vault is None:
        session = None
    elif session_id is None:
        session = vault.session()
    else:
        session = owned_session(vault, session_id, request)
    try:
        yield session
    except BaseException as exc:
        if isinstance(exc, BlockedEntityError):
            log_extra(request, blocked=",".join(f"{t.value}:{n}" for t, n in exc.counts.items()))
            if (metrics := request_metrics(request)) is not None:
                metrics.observe_blocked("inbound", {t.value: n for t, n in exc.counts.items()})
        if session is not None and vault is not None and session_id is None:
            vault.drop(session.session_id)
        raise


def v1_router(route_class: type[LoggedRoute] = LoggedRoute) -> APIRouter:
    return APIRouter(route_class=route_class, tags=["v1"])
