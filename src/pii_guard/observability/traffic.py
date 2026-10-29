"""The traffic log: one structured event per gateway call, kept in memory only.

- A bounded ring buffer (``PII_GUARD_TRAFFIC_LOG_SIZE``, default 200). Nothing is ever written
  to disk or to the application log; a restart forgets everything.
- Live subscribers (``GET /v1/traffic/stream``) get each new event; a slow subscriber loses
  events rather than slowing the gateway down.
- Sessions appear only as :meth:`TrafficLog.session_ref`: an HMAC of the session id under a
  random per-process key. The ref groups one conversation's calls, cannot be turned back into
  the session id (which is a bearer handle to the vault) and changes on restart.
- Every payload goes through :func:`scrub` before it is stored: credential-looking fields are
  replaced, secrets the server knows (the upstream key) are cut out of any string, inline
  images are summarised and long strings are truncated.

What goes into an event is decided by the gateway (:mod:`pii_guard.gateway.service`) and the
level: ``masked`` keeps what was sent upstream and what the upstream answered (placeholders
only); ``full`` also keeps the original request and the restored answer, and is only allowed
on a loopback bind (:func:`pii_guard.observability.config.check_bind`).

Several logs can share one :class:`TrafficFeed` (hosted mode: one per owner, LAB-1492). They
then number their events from one sequence under one lock, so a reader that merges them by
``seq`` gets a single cursor with no duplicates and no gaps, whatever log an event went to.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import itertools
import re
import secrets
import threading
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from contextlib import asynccontextmanager
from typing import Any

from pii_guard.observability.config import TrafficLevel

__all__ = ["REDACTED", "TrafficFeed", "TrafficFeedView", "TrafficLog", "scrub"]

REDACTED = "[redacted]"
#: Longest string kept in an event (code points); longer ones are cut with a marker.
MAX_STRING = 20_000
#: Field names whose values are never kept (compared lower-case, ``-`` as ``_``).
SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "proxy_authorization",
        "api_key",
        "apikey",
        "x_api_key",
        "access_token",
        "refresh_token",
        "id_token",
        "client_secret",
        "secret",
        "password",
        "cookie",
        "set_cookie",
    }
)
_CREDENTIAL_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
_SUBSCRIBER_QUEUE = 256

#: Words (splitting a key on separators and camelCase) that make it a credential by meaning
#: (LAB-1565): ``auth_token``, ``accessToken`` and ``x-auth`` are credentials whatever their
#: spelling. Plurals stay out on purpose: ``max_tokens`` / ``prompt_tokens`` are counts.
_SENSITIVE_WORDS = frozenset(
    {
        "auth",
        "authorization",
        "bearer",
        "cookie",
        "cookies",
        "credential",
        "credentials",
        "passwd",
        "password",
        "passphrase",
        "pwd",
        "secret",
        "token",
    }
)
#: Separator-free key fragments that are credential-shaped even as one word.
_SENSITIVE_FRAGMENTS = (
    "apikey",
    "authorization",
    "credential",
    "passwd",
    "passphrase",
    "password",
    "privatekey",
    "secret",
)
#: A ``key`` word is a credential only next to one of these (``prompt_cache_key`` is not).
_KEY_QUALIFIERS = frozenset(
    {"access", "api", "auth", "encryption", "master", "private", "secret", "session", "signing"}
)


def _sensitive(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    if normalized in SENSITIVE_KEYS:
        return True
    # Split camelCase, then on any separator, e.g. ``accessToken`` / ``X-Api-Key``.
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", key)
    words = [w for w in re.split(r"[^a-z0-9]+", spaced.lower()) if w]
    if any(w in _SENSITIVE_WORDS for w in words):
        return True
    if "key" in words and any(w in _KEY_QUALIFIERS for w in words):
        return True
    flat = "".join(words)
    if any(fragment in flat for fragment in _SENSITIVE_FRAGMENTS):
        return True
    # ``authtoken`` / ``refreshtoken`` written as one word; ``tokenizer``/counts stay visible.
    return flat.endswith("token") and flat != "tokenizer"


def scrub(value: Any, secrets_: Iterable[str] = (), *, max_string: int = MAX_STRING) -> Any:
    """A JSON-safe copy of ``value`` with credentials, known secrets and images taken out."""
    known = [s for s in secrets_ if s and len(s) >= 3]

    def clean_str(text: str) -> str:
        if text.startswith("data:") and len(text) > 64:
            kind = text[5 : text.find(";")] if ";" in text[:64] else "data"
            return f"[inline {kind or 'data'}, {len(text)} chars]"
        for secret in known:
            if secret in text:
                text = text.replace(secret, REDACTED)
        text = _CREDENTIAL_RE.sub(lambda m: f"{m.group(1)} {REDACTED}", text)
        if len(text) > max_string:
            text = text[:max_string] + f"... [truncated, {len(text)} chars]"
        return text

    def walk(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {str(k): (REDACTED if _sensitive(str(k)) else walk(v)) for k, v in item.items()}
        if isinstance(item, list | tuple):
            return [walk(v) for v in item]
        if isinstance(item, str):
            return clean_str(item)
        if item is None or isinstance(item, bool | int | float):
            return item
        return clean_str(str(item))

    return walk(value)


Source = Callable[[str], bool]


class TrafficFeed:
    """One sequence, boot id and lock shared by several traffic logs, each named by a source.

    Every member log takes ``seq`` from the shared counter and appends under the shared lock,
    and :meth:`recent` reads all of them under that same lock. A merged page is therefore a
    consistent snapshot: an event with a smaller ``seq`` can never appear after a reader has
    moved its cursor past it. Subscribers pick their sources with a predicate."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.seq = itertools.count(1)
        self.boot = "b_" + secrets.token_hex(8)
        self._logs: dict[str, TrafficLog] = {}
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[Any], Source]] = set()
        self.dropped = 0

    def __repr__(self) -> str:
        return f"TrafficFeed(logs={len(self._logs)})"

    def attach(self, source: str, log: TrafficLog) -> None:
        with self.lock:
            self._logs[source] = log

    def detach(self, source: str) -> None:
        with self.lock:
            self._logs.pop(source, None)

    def sources(self) -> list[str]:
        with self.lock:
            return list(self._logs)

    def logs(self, include: Source) -> list[TrafficLog]:
        with self.lock:
            return [log for source, log in self._logs.items() if include(source)]

    def recent(
        self, include: Source, limit: int | None = None, *, after: int | None = None
    ) -> list[dict[str, Any]]:
        """The stored events of the included logs, merged by ``seq``, oldest first."""
        with self.lock:
            events = [
                event
                for source, log in self._logs.items()
                if include(source)
                for event in log._events
                if after is None or event["seq"] > after
            ]
        events.sort(key=lambda event: event["seq"])
        if limit is not None:
            events = events[-limit:] if limit > 0 else []
        return events

    def _matching(self, source: str) -> list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[Any]]]:
        return [(loop, queue) for loop, queue, include in self._subscribers if include(source)]

    def _discard(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[Any]) -> None:
        with self.lock:
            self._subscribers = {s for s in self._subscribers if s[:2] != (loop, queue)}

    @asynccontextmanager
    async def subscribe(self, include: Source) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        """A queue that receives every event an included log publishes while it is open."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE)
        entry = (loop, queue, include)
        with self.lock:
            self._subscribers.add(entry)
        try:
            yield queue
        finally:
            with self.lock:
                self._subscribers.discard(entry)

    @property
    def subscribers(self) -> int:
        with self.lock:
            return len(self._subscribers)


class TrafficFeedView:
    """Some sources of a feed, read like one :class:`TrafficLog` (``/v1/traffic`` uses it)."""

    def __init__(self, feed: TrafficFeed, include: Source, level: TrafficLevel) -> None:
        self.feed, self.include, self.level = feed, include, TrafficLevel(level)
        self.boot = feed.boot

    @property
    def enabled(self) -> bool:
        return self.level is not TrafficLevel.OFF

    @property
    def size(self) -> int:
        return sum(log.size for log in self.feed.logs(self.include))

    def recent(self, limit: int | None = None, *, after: int | None = None) -> list[dict[str, Any]]:
        return self.feed.recent(self.include, limit, after=after)

    def subscribe(self) -> Any:
        return self.feed.subscribe(self.include)


class TrafficLog:
    """In-memory ring buffer of traffic events with live subscribers. Thread-safe."""

    def __init__(
        self,
        level: TrafficLevel = TrafficLevel.OFF,
        size: int = 200,
        *,
        feed: TrafficFeed | None = None,
        source: str = "",
    ) -> None:
        self.level = TrafficLevel(level)
        self.size = size
        self._events: deque[dict[str, Any]] = deque(maxlen=size)
        self._key = secrets.token_bytes(32)  # per process: refs change on restart
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[Any]]] = set()
        self.dropped = 0
        #: Fields added to every event this log stores (hosted: the endpoint it serves).
        self.labels: Mapping[str, Any] = {}
        self.feed, self.source = feed, source
        self._lock: threading.Lock | threading.RLock
        if feed is None:
            self._lock = threading.Lock()
            self._seq = itertools.count(1)
            # Per process too: ``seq`` restarts at 1 with a new boot id, so a client polling
            # with ``after=<seq>`` can tell its cursor is from an earlier run (LAB-1357).
            self.boot = "b_" + secrets.token_hex(8)
        else:
            self._lock, self._seq, self.boot = feed.lock, feed.seq, feed.boot
            feed.attach(source, self)

    def __repr__(self) -> str:
        return f"TrafficLog(level={self.level.value}, events={len(self._events)}/{self.size})"

    @property
    def enabled(self) -> bool:
        return self.level is not TrafficLevel.OFF

    @property
    def full(self) -> bool:
        return self.level is TrafficLevel.FULL

    def session_ref(self, session_id: str) -> str:
        """A stable, non-reversible handle for a session within this process."""
        digest = hmac.new(self._key, session_id.encode("utf-8"), hashlib.sha256).hexdigest()
        return "s_" + digest[:16]

    def publish(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Store an event (it gets ``seq``) and hand it to the subscribers. No-op when off."""
        if not self.enabled:
            return None
        for name, value in self.labels.items():
            event[name] = dict(value) if isinstance(value, Mapping) else value
        with self._lock:
            event["seq"] = next(self._seq)
            self._events.append(event)
            subscribers = list(self._subscribers)
            shared = self.feed._matching(self.source) if self.feed is not None else []
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(self._offer, queue, event)
            except RuntimeError:  # the subscriber's loop is closed
                with self._lock:
                    self._subscribers.discard((loop, queue))
        for loop, queue in shared:
            try:
                loop.call_soon_threadsafe(self._offer, queue, event)
            except RuntimeError:
                if self.feed is not None:
                    self.feed._discard(loop, queue)
        return event

    def _offer(self, queue: asyncio.Queue[Any], event: dict[str, Any]) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            self.dropped += 1
            if self.feed is not None:
                self.feed.dropped += 1

    def recent(self, limit: int | None = None, *, after: int | None = None) -> list[dict[str, Any]]:
        """Stored events, oldest first; ``after`` keeps those with a larger ``seq``."""
        with self._lock:
            events = list(self._events)
        if after is not None:
            events = [e for e in events if e["seq"] > after]
        if limit is not None:
            events = events[-limit:] if limit > 0 else []
        return events

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        """A queue that receives every event published while the context is open."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE)
        entry = (loop, queue)
        with self._lock:
            self._subscribers.add(entry)
        try:
            yield queue
        finally:
            with self._lock:
                self._subscribers.discard(entry)

    @property
    def subscribers(self) -> int:
        with self._lock:
            return len(self._subscribers)
