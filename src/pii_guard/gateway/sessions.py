"""Which vault session a gateway request uses (LAB-1286).

Placeholders are stable only within one vault session, so a client that can't send
``X-PII-Guard-Session`` (Muse Code) must still land in the same session every turn. The first
match wins:

1. ``header``: ``X-PII-Guard-Session``. Unknown or expired -> 404 ``session_not_found``, as
   before: the client named a session whose mapping is gone.
2. ``path``: the URL ``/s/<session>/v1/...`` (or ``/s/<session>/muse-code/...``), rewritten by
   :class:`SessionPathMiddleware`. Same grammar as the header; created on first use (the
   client chose the id). ``pii-guard connect`` writes such a base URL.
3. ``prompt_cache_key``: the body's ``prompt_cache_key`` (Muse sends one per conversation):
   the id is ``HMAC(tenant key, "pck:" + client identity + ":" + key)``. Created on first use.
4. ``default``: one session per client identity, ``HMAC(tenant key, "default:" + identity)``.
   Created on first use.

The client identity is the SHA-256 of the request's ``Authorization`` value, or ``anonymous``
without one: two bearer tokens never share a derived session, and every id is keyed with the
tenant key, so ids never collide across deployments. Derived ids leave the process only in
the ``X-PII-Guard-Session`` response header (a client may send it back, step 1);
``X-PII-Guard-Session-Source`` says which step matched. Steps 2-4 use
:meth:`~pii_guard.vault.Vault.session_or_create`, whose entry cap rotates a full session to a
new generation (``PII_GUARD_VAULT_MAX_ENTRIES``).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from enum import StrEnum

from starlette.types import ASGIApp, Receive, Scope, Send

from pii_guard.gateway.request import InvalidChatRequestError
from pii_guard.vault import Vault, VaultSession

__all__ = [
    "PATH_SESSION_KEY",
    "SESSION_HEADER",
    "SESSION_SOURCE_HEADER",
    "SessionPathMiddleware",
    "SessionSource",
    "client_identity",
    "path_session",
    "resolve_session",
]

SESSION_HEADER = "X-PII-Guard-Session"
SESSION_SOURCE_HEADER = "X-PII-Guard-Session-Source"
#: Where :class:`SessionPathMiddleware` leaves the path's session id in the ASGI scope.
PATH_SESSION_KEY = "pii_guard.path_session"

SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_PATH_RE = re.compile(r"^/s/([^/]*)(/(?:v1|muse-code)(?:/.*)?)$")


class SessionSource(StrEnum):
    HEADER = "header"
    PATH = "path"
    PROMPT_CACHE_KEY = "prompt_cache_key"
    DEFAULT = "default"


def client_identity(headers: Mapping[str, str]) -> str:
    """SHA-256 (hex) of the ``Authorization`` value, or ``anonymous`` without one."""
    raw = headers.get("authorization")
    if raw is None or not raw.strip():
        return "anonymous"
    return hashlib.sha256(raw.strip().encode("utf-8")).hexdigest()


def resolve_session(
    vault: Vault,
    headers: Mapping[str, str],
    body: Mapping[str, object],
    path_session: str | None = None,
) -> tuple[VaultSession, bool, SessionSource]:
    """``(session, created, source)`` for one gateway request (the module docstring's order).

    ``body`` is the request before masking (its ``prompt_cache_key`` as the client sent it).
    """
    raw = headers.get(SESSION_HEADER)
    if raw is not None and raw.strip():
        if not SESSION_RE.match(raw.strip()):
            raise InvalidChatRequestError(f"{SESSION_HEADER} is malformed")
        # Unknown or expired -> SessionNotFoundError (404). Start a new conversation without
        # the header; the mapping is gone, so a silent new session would be a different one.
        return vault.session(raw.strip()), False, SessionSource.HEADER
    if path_session is not None:
        if not SESSION_RE.match(path_session):  # the middleware checked it already
            raise InvalidChatRequestError("the session in the URL path is malformed")
        session, created = vault.session_or_create(path_session)
        return session, created, SessionSource.PATH
    identity = client_identity(headers)
    key = body.get("prompt_cache_key")
    if isinstance(key, str) and key:
        derived = vault.derive_session_id(f"pck:{identity}:{key}")
        session, created = vault.session_or_create(derived)
        return session, created, SessionSource.PROMPT_CACHE_KEY
    session, created = vault.session_or_create(vault.derive_session_id(f"default:{identity}"))
    return session, created, SessionSource.DEFAULT


def path_session(scope: Mapping[str, object]) -> str | None:
    """The session id :class:`SessionPathMiddleware` took from the URL, if any."""
    value = scope.get(PATH_SESSION_KEY)
    return value if isinstance(value, str) else None


class SessionPathMiddleware:
    """``/s/<session>/v1/...`` and ``/s/<session>/muse-code/...`` -> the same route, with the
    session id in ``scope[PATH_SESSION_KEY]``. A malformed id is 400 ``invalid_request``."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "") if scope["type"] == "http" else ""
        match = _PATH_RE.match(path) if path.startswith("/s/") else None
        if match is None:
            await self.app(scope, receive, send)
            return
        session_id, rest = match.groups()
        if not SESSION_RE.match(session_id):
            body = json.dumps(
                {
                    "error": {
                        "code": InvalidChatRequestError.code,
                        "message": "the session in the URL path is malformed: use 1-128 of "
                        "A-Z a-z 0-9 _ -",
                    }
                }
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 400,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        scope = dict(scope)
        scope["path"] = rest
        scope["raw_path"] = rest.encode("utf-8")
        scope[PATH_SESSION_KEY] = session_id
        await self.app(scope, receive, send)
