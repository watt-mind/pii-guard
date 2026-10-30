"""Which vault session a gateway request uses (LAB-1286).

Placeholders are stable only within one vault session, so a client that can't send
``X-PII-Guard-Session`` (Muse Code) must still land in the same session every turn. The first
match wins:

1. ``header``: ``X-PII-Guard-Session``. Unknown or expired -> 404 ``session_not_found``, as
   before: the client named a session whose mapping is gone.
2. ``path``: the URL ``/s/<session>/v1/...`` (or ``/s/<session>/muse-code/...``), rewritten by
   :class:`SessionPathMiddleware`. Same grammar as the header; created on first use (the
   client chose the id). ``pii-guard connect`` writes such a base URL.
3. ``prompt_cache_key``: the body's ``prompt_cache_key``: the id is
   ``HMAC(tenant key, "pck:" + client identity + ":" + key)``. Created on first use. Muse Code
   sends ``tbh:main:<conversation uuid>`` for its main agent and
   ``tbh:<kind>-reminder:<uuid[:8]>:...`` for each reminder observer; an observer key uses the
   session of the newest main key of the same client identity with that 8-hex prefix
   (LAB-1300), so one task stays in one session. Muse sends its first main turn and its first
   observer at the same time, so either can be resolved first (LAB-1341): an observer whose
   main key this process hasn't seen leaves its session under the prefix, and the first main
   key with that prefix takes that session over instead of starting its own.
4. ``default``: one session per client identity, ``HMAC(tenant key, "default:" + identity)``.
   Created on first use.

The client identity is the SHA-256 of the request's ``Authorization`` value (else of its
``x-api-key``, as Anthropic clients send it), or ``anonymous`` without either: two bearer
tokens never share a derived session, and every id is keyed with the tenant key, so ids never
collide across deployments. Derived ids leave the process only in the
``X-PII-Guard-Session`` response header (a client may send it back, step 1);
``X-PII-Guard-Session-Source`` says which step matched. Steps 2-4 use
:meth:`~pii_guard.vault.Vault.session_or_create`, whose entry cap rotates a full session to a
new generation (``PII_GUARD_VAULT_MAX_ENTRIES``).

Explicit sessions (steps 1-2) are bound to the credentialed client identity that first
presents them through the gateway (LAB-1565): a *different credentialed* identity presenting
an existing explicit id gets ``session_not_found`` (fail closed, no distinction from a
missing session), never the mapping. The credential-less ``anonymous`` identity is a
*single* principal by construction: in the documented local (loopback) deployment every
local client without ``Authorization`` is the same user, so they share the anonymous derived
session (multi-turn restore needs that) and anonymous presenters never refuse each other;
a credentialed identity takes an anonymous binding over. An anonymous presenter is refused
by a *credentialed* binding: dropping ``Authorization`` is the caller's choice, so it must
not unlock a session another credential owns. Distinct ``Authorization`` values always
derive distinct sessions.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import weakref
from collections import OrderedDict
from collections.abc import Mapping
from enum import StrEnum

from starlette.types import ASGIApp, Receive, Scope, Send

from pii_guard.gateway.request import InvalidChatRequestError
from pii_guard.vault import SessionNotFoundError, Vault, VaultSession

__all__ = [
    "PATH_SESSION_KEY",
    "SESSION_HEADER",
    "SESSION_SOURCE_HEADER",
    "SessionPathMiddleware",
    "SessionSource",
    "check_and_bind",
    "check_owner",
    "client_identity",
    "path_session",
    "resolve_session",
]

SESSION_HEADER = "X-PII-Guard-Session"
SESSION_SOURCE_HEADER = "X-PII-Guard-Session-Source"
#: Where :class:`SessionPathMiddleware` leaves the path's session id in the ASGI scope.
PATH_SESSION_KEY = "pii_guard.path_session"

#: At least 3 characters: 1-2 character client-chosen ids are refused (LAB-1565). Generated
#: ids (``s_``/``c_``/``d_`` + 32 hex) are 34 chars; short human-chosen path ids (``box``)
#: stay legal, so the floor stays low and identity binding is the access control.
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{3,128}$")
_PATH_RE = re.compile(r"^/s/([^/]*)(/(?:v1|muse-code)(?:/.*)?)$")
# Muse Code's prompt_cache_key grammar (1.4.13, 1.4.14): the main agent's key carries the
# conversation's UUID, each reminder observer's key the UUID's first 8 hex digits.
_MUSE_MAIN_RE = re.compile(
    r"^tbh:main:([0-9a-f]{8})-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_MUSE_OBSERVER_RE = re.compile(r"^tbh:[a-z]+-reminder:([0-9a-f]{8}):")
#: Main conversations remembered per vault for their observers (oldest forgotten first).
MAX_CONVERSATIONS = 4096


class SessionSource(StrEnum):
    HEADER = "header"
    PATH = "path"
    PROMPT_CACHE_KEY = "prompt_cache_key"
    DEFAULT = "default"


def _credential(headers: Mapping[str, str]) -> str | None:
    """The client's credential header, as one value: ``Authorization``, else ``x-api-key``
    (Anthropic clients, LAB-1605) marked with a NUL, which no ``Authorization`` value carries,
    so the same value in the two headers never gives the same identity."""
    raw = headers.get("authorization")
    if raw is not None and raw.strip():
        return raw.strip()
    raw = headers.get("x-api-key")
    if raw is not None and raw.strip():
        return "x-api-key\x00" + raw.strip()
    return None


def client_identity(headers: Mapping[str, str]) -> str:
    """SHA-256 (hex) of the ``Authorization`` value; without one, of the ``x-api-key`` value
    (Anthropic clients, LAB-1605), so two keys never share a derived session; ``anonymous``
    without either."""
    credential = _credential(headers)
    if credential is None:
        return "anonymous"
    return hashlib.sha256(credential.encode("utf-8")).hexdigest()


class _Conversations:
    """Muse conversations per vault. Lives as long as its vault (sessions are in memory); each
    index keeps :data:`MAX_CONVERSATIONS` entries (oldest forgotten first).

    - ``_by_prefix``: ``(client identity, 8-hex prefix) -> session id`` of the newest main key.
    - ``_mains``: ``(client identity, main key) -> session id``, so a main key that took an
      observer's session over keeps it.
    - ``_pending``: ``(client identity, 8-hex prefix) -> session id`` of an observer that came
      before any main key with its prefix, until that main key takes it over.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_prefix: OrderedDict[tuple[str, str], str] = OrderedDict()
        self._mains: OrderedDict[tuple[str, str], str] = OrderedDict()
        self._pending: OrderedDict[tuple[str, str], str] = OrderedDict()

    def main(self, identity: str, prefix: str, key: str, derived: str) -> str:
        """The session id for main key ``key`` (``derived``: the key's own derived id)."""
        with self._lock:
            found = self._mains.get((identity, key))
            if found is None:
                # An observer of this conversation came first: take its session over.
                found = self._pending.pop((identity, prefix), derived)
            _put(self._mains, (identity, key), found)
            _put(self._by_prefix, (identity, prefix), found)
            return found

    def observer(self, identity: str, prefix: str, derived: str) -> str:
        """The session id for an observer key with ``prefix`` (``derived``: its own id)."""
        with self._lock:
            found = self._by_prefix.get((identity, prefix))
            if found is None:
                found = self._pending.get((identity, prefix))
            if found is None:
                found = derived
                _put(self._pending, (identity, prefix), found)
            return found


def _put(index: OrderedDict[tuple[str, str], str], at: tuple[str, str], value: str) -> None:
    index[at] = value
    index.move_to_end(at)
    while len(index) > MAX_CONVERSATIONS:
        index.popitem(last=False)


_CONVERSATIONS: weakref.WeakKeyDictionary[Vault, _Conversations] = weakref.WeakKeyDictionary()
_CONVERSATIONS_LOCK = threading.Lock()


def _conversations(vault: Vault) -> _Conversations:
    with _CONVERSATIONS_LOCK:
        found = _CONVERSATIONS.get(vault)
        if found is None:
            found = _CONVERSATIONS[vault] = _Conversations()
        return found


_OWNER_LOCK = threading.Lock()


def _owner_refuses(owner: str | None, identity: str) -> bool:
    """Whether a session recorded for ``owner`` must refuse ``identity`` (LAB-1565).

    The credential-less ``anonymous`` identity is the one local principal (see the module
    docstring): it matches an anonymous owner, and a credentialed identity may use an
    anonymous-owned (or unowned) session. Any other mismatch is refused, including
    ``anonymous`` presenting a credentialed owner: leaving ``Authorization`` out is the
    caller's choice and must not bypass the binding.
    """
    if owner is None or owner == "anonymous":
        return False
    # Constant time: ``identity`` is derived from the caller's ``Authorization`` value.
    return not hmac.compare_digest(owner.encode(), identity.encode())


def check_and_bind(session: VaultSession, identity: str) -> None:
    """Record ``identity`` as ``session``'s owner; refuse a different credentialed identity.

    The owner lives on the :class:`VaultSession` itself (LAB-1580), so the binding lasts
    exactly as long as the session: no index to evict, and a dropped/expired/rotated id
    that is re-created as a new session object starts unowned. A credentialed identity
    takes an anonymous owner over.
    """
    with _OWNER_LOCK:
        if _owner_refuses(session.owner, identity):
            raise SessionNotFoundError("vault session not found or expired")
        if session.owner != identity:
            session.owner = identity


def check_owner(session: VaultSession, identity: str) -> None:
    """Refuse ``identity`` like :func:`check_and_bind`, without recording it (``/v1/unmask``).

    A session no gateway request presented yet has no owner and stays open to every caller,
    as before (``/v1/mask`` sessions); reading never claims one.
    """
    with _OWNER_LOCK:
        if _owner_refuses(session.owner, identity):
            raise SessionNotFoundError("vault session not found or expired")


def _cache_key_session_id(vault: Vault, identity: str, key: str) -> str:
    """The derived id for ``key`` (step 3); Muse's main and observer keys of one conversation
    share one, whichever is resolved first."""
    derived = vault.derive_session_id(f"pck:{identity}:{key}")
    if (main := _MUSE_MAIN_RE.match(key)) is not None:
        return _conversations(vault).main(identity, main.group(1), key, derived)
    if (observer := _MUSE_OBSERVER_RE.match(key)) is not None:
        return _conversations(vault).observer(identity, observer.group(1), derived)
    return derived


def resolve_session(
    vault: Vault,
    headers: Mapping[str, str],
    body: Mapping[str, object],
    path_session: str | None = None,
) -> tuple[VaultSession, bool, SessionSource]:
    """``(session, created, source)`` for one gateway request (the module docstring's order).

    ``body`` is the request before masking (its ``prompt_cache_key`` as the client sent it).
    """
    identity = client_identity(headers)

    def bind(session: VaultSession) -> None:
        # Runs inside the vault lookup, before the TTL is extended (LAB-1584): a refused
        # identity can't keep another identity's session alive by presenting its id.
        check_and_bind(session, identity)

    raw = headers.get(SESSION_HEADER)
    if raw is not None and raw.strip():
        if not SESSION_RE.match(raw.strip()):
            raise InvalidChatRequestError(f"{SESSION_HEADER} is malformed")
        # Unknown or expired -> SessionNotFoundError (404). Start a new conversation without
        # the header; the mapping is gone, so a silent new session would be a different one.
        # LAB-1565: a different identity than the recorded creator gets the same 404.
        session = vault.session(raw.strip(), authorize=bind)
        return session, False, SessionSource.HEADER
    if path_session is not None:
        if not SESSION_RE.match(path_session):  # the middleware checked it already
            raise InvalidChatRequestError("the session in the URL path is malformed")
        session, created = vault.session_or_create(path_session, authorize=bind)
        return session, created, SessionSource.PATH
    key = body.get("prompt_cache_key")
    if isinstance(key, str) and key:
        session, created = vault.session_or_create(
            _cache_key_session_id(vault, identity, key), authorize=bind
        )
        return session, created, SessionSource.PROMPT_CACHE_KEY
    session, created = vault.session_or_create(
        vault.derive_session_id(f"default:{identity}"), authorize=bind
    )
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
                        "message": "the session in the URL path is malformed: use 3-128 of "
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
