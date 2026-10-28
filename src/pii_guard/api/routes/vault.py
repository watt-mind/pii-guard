"""The vault inspector (LAB-1328): which sessions the vault holds and what each one maps.

- ``GET /v1/vault/sessions``: every live session, with where it came from, its timings and
  counts. No values.
- ``GET /v1/vault/sessions/{ref}``: one session's placeholders, with a redacted hint of each
  value (``J••• S•••••``, ``•••••••67``); ``?reveal=true`` adds the originals and their forms,
  in ``full`` mode only.
- ``DELETE /v1/vault/sessions/{ref}``: drop a session now.

``PII_GUARD_VAULT_INSPECT`` picks the mode: ``masked`` (default) never returns an original;
``full`` can, and like ``PII_GUARD_TRAFFIC_LOG=full`` it is refused at startup unless the server
binds to a loopback address and answers loopback host names only, and refused per request
(403 ``vault_inspect_not_local``) unless the connection is loopback on both ends. ``off``: the
routes answer 404 ``vault_inspect_disabled``. ``PII_GUARD_API_TOKEN`` and the ``Host`` check
apply as on every route.

Sessions are addressed by their **ref**, the traffic log's
:meth:`~pii_guard.observability.TrafficLog.session_ref` (an HMAC of the session id under a
per-process key), never by the id: a session id is a bearer handle to the vault (``/v1/unmask``
with it restores every value), so it is returned only by a revealed read. The same ref is on
every traffic event, so a Logs row links to its session.

The vault does not record where a session came from. :class:`SessionDirectory` does, from the
gateway's ``X-PII-Guard-Session`` and ``X-PII-Guard-Session-Source`` response headers
(LAB-1286); a session created through the REST API (``/v1/mask``, ``/v1/sessions``) has
source ``api`` and no creation time. Every revealed read is logged with the ref and the entry
count, never a value.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from fastapi import Depends, Path, Query, Request, Response
from pydantic import BaseModel, Field
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from pii_guard.api.deps import get_vault
from pii_guard.api.errors import error_responses
from pii_guard.api.routes._common import v1_router
from pii_guard.api.security import _addr_is_loopback
from pii_guard.gateway.sessions import SESSION_HEADER, SESSION_SOURCE_HEADER, client_identity
from pii_guard.observability import Observability, is_loopback
from pii_guard.types import EntityType, PiiGuardError
from pii_guard.vault import Vault, VaultSession
from pii_guard.vault.inspect import EntryView, KnownView, entries_of, live_sessions, ttl_of, view_of

__all__ = [
    "InspectMode",
    "SessionDirectory",
    "SessionRecorderMiddleware",
    "VaultInspectConfigError",
    "check_inspect_bind",
    "hint",
    "router",
]

logger = logging.getLogger("pii_guard.api.vault")

router = v1_router()
router.tags = ["vault"]

#: How long a client identity is shown: enough to tell two clients apart, not a full hash.
_CLIENT_CHARS = 12
_BULLET = "•"


class InspectMode(StrEnum):
    OFF = "off"
    MASKED = "masked"
    FULL = "full"


class VaultInspectConfigError(ValueError):
    """``PII_GUARD_VAULT_INSPECT=full`` on a server reachable from other machines."""


class VaultInspectDisabledError(PiiGuardError):
    code = "vault_inspect_disabled"
    status_code = 404


class VaultInspectNotLocalError(PiiGuardError):
    code = "vault_inspect_not_local"
    status_code = 403


class VaultRevealDisabledError(PiiGuardError):
    code = "vault_reveal_disabled"
    status_code = 403


class VaultSessionNotFoundError(PiiGuardError):
    code = "not_found"
    status_code = 404


def check_inspect_bind(mode: InspectMode, host: str, hosts: list[str]) -> None:
    """Refuse ``full`` on a non-loopback bind or with non-loopback allowed ``Host`` names."""
    if mode is not InspectMode.FULL:
        return
    if not is_loopback(host):
        raise VaultInspectConfigError(
            "PII_GUARD_VAULT_INSPECT=full is only allowed when the server binds to a loopback "
            f"address (127.0.0.1, ::1, localhost), not {host!r}; use 'masked' or bind locally"
        )
    public = [h for h in hosts if not is_loopback(h)]
    if public:
        raise VaultInspectConfigError(
            "PII_GUARD_VAULT_INSPECT=full is only allowed when the API answers loopback host "
            f"names only; PII_GUARD_ALLOWED_HOSTS also allows {', '.join(public)}"
        )


# --- where sessions came from ----------------------------------------------------------------


@dataclass(slots=True)
class _Record:
    source: str
    client: str
    created: float
    last_used: float


class SessionDirectory:
    """Source, client identity and first/last use of the sessions the gateway resolved.

    The source and client are those of the request that first used the session: a later
    turn that names it in ``X-PII-Guard-Session`` reuses it and only updates ``last_used``.

    Bounded (least recently used out first) and in memory only, like the vault. Holds session
    ids, never values. Thread-safe.
    """

    def __init__(self, size: int = 10_000) -> None:
        self._size = size
        self._records: OrderedDict[str, _Record] = OrderedDict()
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"SessionDirectory(records={len(self._records)})"

    def record(self, session_id: str, source: str, client: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            record = self._records.get(session_id)
            if record is None:
                self._records[session_id] = _Record(source, client, now, now)
                while len(self._records) > self._size:
                    self._records.popitem(last=False)
            else:
                record.last_used = now  # the source and client that created it stay
                self._records.move_to_end(session_id)

    def get(self, session_id: str) -> _Record | None:
        with self._lock:
            return self._records.get(session_id)

    def forget(self, session_id: str) -> None:
        with self._lock:
            self._records.pop(session_id, None)


class SessionRecorderMiddleware:
    """Record each gateway response's session in ``app.state.vault_directory``.

    Reads the response's ``X-PII-Guard-Session`` and ``-Source`` headers and the request's
    client identity (:func:`~pii_guard.gateway.sessions.client_identity`, after the token
    check removed the API token), so the inspector can say where a session came from.
    """

    def __init__(self, app: ASGIApp, directory: SessionDirectory) -> None:
        self.app = app
        self.directory = directory

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        session_header = SESSION_HEADER.lower().encode()
        source_header = SESSION_SOURCE_HEADER.lower().encode()

        async def recording_send(message: Message) -> None:
            if message["type"] == "http.response.start" and message.get("status", 500) < 400:
                found: dict[bytes, str] = {}
                for name, value in message.get("headers") or []:
                    key = name.lower()
                    if key in (session_header, source_header):
                        found[key] = value.decode("latin-1")
                session_id, source = found.get(session_header), found.get(source_header)
                if session_id and source:
                    headers = {
                        k.decode("latin-1").lower(): v.decode("latin-1")
                        for k, v in scope.get("headers") or []
                    }
                    self.directory.record(session_id, source, _client(headers))
            await send(message)

        await self.app(scope, receive, recording_send)


def _client(headers: Mapping[str, str]) -> str:
    identity = client_identity(headers)
    return identity if identity == "anonymous" else identity[:_CLIENT_CHARS]


# --- redacted hints --------------------------------------------------------------------------


def _numeric(value: str) -> bool:
    alnum = [c for c in value if c.isalnum()]
    digits = sum(c.isdigit() for c in alnum)
    return bool(alnum) and digits * 2 >= len(alnum)


def hint(value: str, entity_type: EntityType) -> str:
    """A redacted hint of ``value``: never the value, only its shape.

    Each word keeps its first letter and its length (``J••• S•••••``; words under three
    characters are all bullets); a number keeps its last two digits when it has at least six
    (``+•• •• ••• ••67``); a ``SECRET`` keeps nothing but up to 12 bullets. Separators
    (spaces, ``.``, ``@``, ``-``) stay, so the shape of an e-mail address or IBAN is visible.
    """
    if entity_type is EntityType.SECRET:
        return _BULLET * min(max(len(value), 3), 12)
    if _numeric(value):
        digit_positions = [i for i, c in enumerate(value) if c.isdigit()]
        keep = set(digit_positions[-2:]) if len(digit_positions) >= 6 else set()
        return "".join(c if i in keep or not c.isalnum() else _BULLET for i, c in enumerate(value))
    out: list[str] = []
    word: list[str] = []

    def flush() -> None:
        if word:
            out.append(
                word[0] + _BULLET * (len(word) - 1) if len(word) >= 3 else _BULLET * len(word)
            )
            word.clear()

    for char in value:
        if char.isalnum():
            word.append(char)
        else:
            flush()
            out.append(char)
    flush()
    return "".join(out)


# --- models ---------------------------------------------------------------------------------

Source = Literal["header", "path", "prompt_cache_key", "default", "api"]


class SessionSummary(BaseModel):
    """One live vault session: where it came from, its timings and counts. No values."""

    ref: str = Field(
        description="The session's handle in the inspector and the traffic log (`session_ref`): "
        "an HMAC of the session id under a per-process key. Not the session id, which is a "
        "bearer handle to the vault.",
        examples=["s_3f9a1c0b7d2e4a61"],
    )
    source: Source = Field(
        description="How the gateway chose the session (`header`, `path`, `prompt_cache_key`, "
        "`default`, LAB-1286), or `api` for one created through `/v1/mask` or `/v1/sessions`."
    )
    client: str | None = Field(
        description="The first 12 hex characters of the SHA-256 of the client's "
        "`Authorization` value, `anonymous` without one; `null` for an `api` session."
    )
    created: str | None = Field(
        description="When the gateway first used the session (ISO 8601, UTC); `null` for an "
        "`api` session, whose creation is not recorded."
    )
    last_used: str = Field(description="When the session was last used (ISO 8601, UTC).")
    ttl_left_seconds: float = Field(
        description="Seconds until the session expires unless it is used again (sliding TTL)."
    )
    generation: int = Field(
        description="Grows whenever a placeholder is added or its patterns change."
    )
    entries: int = Field(description="Placeholders the session has issued (variants included).")
    occurrences: int = Field(description="Occurrences masked over all its placeholders so far.")
    known_values: int = Field(description="Values pre-loaded into the session.")
    entity_counts: dict[str, int] = Field(description="Placeholders per entity type.")


class SessionList(BaseModel):
    """Every live vault session, most recently used first."""

    mode: Literal["masked", "full"] = Field(description="`PII_GUARD_VAULT_INSPECT`.")
    ttl_seconds: float = Field(description="The vault's sliding session TTL.")
    sessions: list[SessionSummary] = Field(description="The live sessions.")


class EntryOut(BaseModel):
    """One placeholder of a session. `original` and `forms` only on a revealed read."""

    placeholder: str | None = Field(
        description="The placeholder, or `null` for a known value nothing matched yet."
    )
    entity_type: str = Field(description="The entity type.")
    origin: Literal["detected", "known"] = Field(
        description="`known`: a value pre-loaded with `/v1/sessions` (matched by the `known` "
        "detector); `detected`: found by a detector."
    )
    count: int = Field(description="Occurrences masked with this placeholder so far.")
    forms: int = Field(
        description="Other written forms matched onto this value (inflected stems, split "
        "surfaces), the original excluded."
    )
    variant_of: str | None = Field(
        description="The placeholder this one is a casing or layout variant of, if any."
    )
    hint: str = Field(
        description="A redacted hint of the value: first letter and length of each word, the "
        "last two digits of a number. Never the value.",
        examples=["T•••• E•••"],
    )
    original: str | None = Field(
        default=None,
        description="The value as first written. Revealed reads only (`full` mode, `reveal`).",
    )
    known_forms: list[str] | None = Field(
        default=None,
        description="The other written forms themselves. Revealed reads only.",
    )


class SessionDetail(SessionSummary):
    """One session and its placeholders. Values only on a revealed read."""

    mode: Literal["masked", "full"] = Field(description="`PII_GUARD_VAULT_INSPECT`.")
    revealed: bool = Field(
        description="Whether `original`, `known_forms` and `session_id` are set."
    )
    session_id: str | None = Field(
        default=None,
        description="The session id (a bearer handle to the vault). Revealed reads only.",
    )
    items: list[EntryOut] = Field(
        description="Placeholders, variants after their value, then known values nothing "
        "matched yet."
    )


# --- dependencies ---------------------------------------------------------------------------


def _mode(request: Request) -> InspectMode:
    mode = InspectMode(getattr(request.app.state, "vault_inspect", InspectMode.MASKED))
    if mode is InspectMode.OFF:
        raise VaultInspectDisabledError(
            "the vault inspector is off; set PII_GUARD_VAULT_INSPECT=masked (or full, on localhost)"
        )
    if mode is InspectMode.FULL and not (
        _addr_is_loopback(request.scope.get("server"))
        and _addr_is_loopback(request.scope.get("client"))
    ):
        raise VaultInspectNotLocalError(
            "PII_GUARD_VAULT_INSPECT=full only serves loopback connections; this server is "
            "reachable from other machines. Bind to 127.0.0.1 or use 'masked'"
        )
    return mode


def _observability(request: Request) -> Observability:
    obs = getattr(request.app.state, "observability", None)
    if obs is None:
        obs = Observability()
        request.app.state.observability = obs
    return obs


def _directory(request: Request) -> SessionDirectory:
    directory = getattr(request.app.state, "vault_directory", None)
    if directory is None:
        directory = SessionDirectory()
        request.app.state.vault_directory = directory
    return directory


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds")


def _summary(request: Request, session: VaultSession) -> dict[str, Any] | None:
    view = view_of(session)
    if view is None:
        return None
    record = _directory(request).get(session.session_id)
    now = time.time()
    last_used = now - view.idle_seconds
    if record is not None:
        last_used = max(last_used, record.last_used)
    return {
        "ref": _observability(request).traffic.session_ref(session.session_id),
        "source": record.source if record is not None else "api",
        "client": record.client if record is not None else None,
        "created": _iso(record.created) if record is not None else None,
        "last_used": _iso(last_used),
        "ttl_left_seconds": round(view.ttl_left_seconds, 1),
        "generation": view.generation,
        "entries": view.entries,
        "occurrences": view.occurrences,
        "known_values": view.known_values,
        "entity_counts": view.entity_counts,
    }


def _find(request: Request, vault: Vault, ref: str) -> VaultSession:
    traffic = _observability(request).traffic
    for session in live_sessions(vault):
        if traffic.session_ref(session.session_id) == ref:
            return session
    raise VaultSessionNotFoundError("no live vault session has this ref")


def _entry(item: EntryView, reveal: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "placeholder": item.placeholder,
        "entity_type": item.entity_type.value,
        "origin": item.origin,
        "count": item.count,
        "forms": len(item.forms),
        "variant_of": item.variant_of,
        "hint": hint(item.original, item.entity_type),
    }
    if reveal:
        out["original"] = item.original
        out["known_forms"] = list(item.forms)
    return out


def _pending(item: KnownView, reveal: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "placeholder": None,
        "entity_type": item.entity_type.value,
        "origin": "known",
        "count": 0,
        "forms": 0,
        "variant_of": None,
        "hint": hint(item.value, item.entity_type),
    }
    if reveal:
        out["original"] = item.value
        out["known_forms"] = []
    return out


RefPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=64,
        pattern=r"^s_[0-9a-f]{1,32}$",
        description="The session's `ref` from the list (the traffic log's `session_ref`).",
    ),
]

_ERRORS = (
    "invalid_request",
    "vault_inspect_disabled",
    "vault_inspect_not_local",
    "vault_not_configured",
)


@router.get(
    "/v1/vault/sessions",
    response_model=SessionList,
    summary="Vault sessions: source, timings and counts",
    responses=error_responses(*_ERRORS),
)
def list_sessions(
    request: Request,
    mode: Annotated[InspectMode, Depends(_mode)],
    vault: Annotated[Vault, Depends(get_vault)],
    source: Annotated[Source | None, Query(description="Only sessions with this source.")] = None,
) -> dict[str, Any]:
    """Every live vault session, most recently used first: its `ref`, where it came from,
    the client identity, when it was created and last used, its TTL left and counts per entity
    type. Never a value or a session id. Listing touches no session (no TTL is extended).

    404 `vault_inspect_disabled` while `PII_GUARD_VAULT_INSPECT=off`."""
    summaries = [s for s in (_summary(request, x) for x in live_sessions(vault)) if s is not None]
    if source is not None:
        summaries = [s for s in summaries if s["source"] == source]
    summaries.sort(key=lambda s: s["last_used"], reverse=True)
    return {"mode": mode.value, "ttl_seconds": ttl_of(vault), "sessions": summaries}


@router.get(
    "/v1/vault/sessions/{ref}",
    response_model=SessionDetail,
    summary="One vault session's placeholders (redacted unless revealed)",
    responses=error_responses("not_found", "vault_reveal_disabled", *_ERRORS),
)
def session_detail(
    ref: RefPath,
    request: Request,
    mode: Annotated[InspectMode, Depends(_mode)],
    vault: Annotated[Vault, Depends(get_vault)],
    reveal: Annotated[
        bool,
        Query(
            description="Also return the originals, their forms and the session id. Only in "
            "`full` mode (else 403 `vault_reveal_disabled`); every revealed read is logged."
        ),
    ] = False,
) -> dict[str, Any]:
    """A session's placeholders: type, origin (`detected` or pre-loaded `known`), occurrence
    count, how many other forms matched, and a redacted hint of the value. Known values that
    nothing matched yet are listed last, without a placeholder.

    With `reveal=true` (`full` mode, loopback only) also the original values, their forms and
    the session id. Reading touches no session (no TTL is extended)."""
    if reveal and mode is not InspectMode.FULL:
        raise VaultRevealDisabledError(
            "revealing values needs PII_GUARD_VAULT_INSPECT=full (loopback only); this server "
            "runs the inspector in 'masked' mode"
        )
    session = _find(request, vault, ref)
    summary = _summary(request, session)
    entries, pending = entries_of(session)
    if summary is None:
        raise VaultSessionNotFoundError("no live vault session has this ref")
    if reveal:
        logger.warning(
            "vault inspector: revealed session %s (%d entries, %d pending known values)",
            ref,
            len(entries),
            len(pending),
        )
    return {
        **summary,
        "mode": mode.value,
        "revealed": reveal,
        "session_id": session.session_id if reveal else None,
        "items": [_entry(e, reveal) for e in entries] + [_pending(k, reveal) for k in pending],
    }


@router.delete(
    "/v1/vault/sessions/{ref}",
    status_code=204,
    response_class=Response,
    summary="Drop a vault session",
    responses={
        204: {"description": "The session is gone; its placeholders can't be restored any more."},
        **error_responses("not_found", *_ERRORS),
    },
    dependencies=[Depends(_mode)],
)
def drop_session(
    ref: RefPath,
    request: Request,
    vault: Annotated[Vault, Depends(get_vault)],
) -> Response:
    """Forget a session now, for troubleshooting: its placeholders are no longer restored,
    and a client that names it in `X-PII-Guard-Session` gets 404. A gateway session derived
    from the URL path, `prompt_cache_key` or the client is created again, empty, on its next
    request."""
    session = _find(request, vault, ref)
    vault.drop(session.session_id)
    _directory(request).forget(session.session_id)
    logger.info("vault inspector: dropped session %s", ref)
    return Response(status_code=204)
