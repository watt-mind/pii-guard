"""Remote traffic telemetry exporter: ship scrubbed gateway events to a remote dashboard.

When ``PII_GUARD_REMOTE_URL`` is set, :class:`~pii_guard.observability.Observability` hands
every recorded gateway event to :class:`RemoteTrafficExporter`. Events are sanitized on the
caller's thread before entering the bounded queue:

- ``level`` is always forced to ``"masked"``;
- ``request.original`` and ``response.unmasked`` are stripped unconditionally, even when the
  local gateway runs with ``PII_GUARD_TRAFFIC_LOG=full`` on loopback;
- at ``PII_GUARD_REMOTE_LEVEL=stats``, ``request`` and ``response`` payloads are omitted
  altogether so only counts, entity types, model, token usage and per-stage timings leave the
  machine.

A slow or unreachable remote dashboard never blocks or fails a local gateway call: when the
queue is full, events are dropped and counted in :attr:`RemoteTrafficExporter.dropped`.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections.abc import Mapping
from contextlib import suppress
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from pii_guard.observability.config import RemoteTrafficLevel, is_loopback
from pii_guard.observability.traffic import scrub

__all__ = [
    "DEFAULT_QUEUE_SIZE",
    "MAX_BATCH_BYTES",
    "MAX_BATCH_SIZE",
    "RemoteTrafficExporter",
    "RemoteTrafficLevel",
    "resolve_ingest_url",
    "sanitize_for_remote",
]

logger = logging.getLogger("pii_guard.observability.remote")

DEFAULT_QUEUE_SIZE = 256
MAX_BATCH_SIZE = 25
# Under the hosted ingest's 32 KiB body limit (``PII_GUARD_HOSTED_MAX_BODY_BYTES``), with room
# for the envelope: a batch is cut at this many serialized bytes, whatever its event count.
MAX_BATCH_BYTES = 24 * 1024
_TIMEOUT = httpx.Timeout(10.0, connect=3.0)


def resolve_ingest_url(remote_url: str) -> str:
    """Turn a dashboard origin, ``/v1`` base URL or ``/e/<id>/v1`` URL into its ingest URL."""
    cleaned = remote_url.strip().rstrip("/")
    if not cleaned:
        raise ValueError("remote_url must not be empty")
    parts = urlsplit(cleaned)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("remote_url must be an http:// or https:// URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError("remote_url must not carry credentials; use PII_GUARD_REMOTE_KEY")
    # The bearer key and masked payloads never cross the network in plaintext.
    if parts.scheme == "http" and not is_loopback(parts.hostname):
        raise ValueError("remote_url must use https:// (http:// only for a loopback host)")
    path = parts.path.rstrip("/")
    if path.endswith("/v1/traffic"):
        target_path = path
    elif path.endswith("/v1"):
        target_path = f"{path}/traffic"
    else:
        target_path = f"{path}/v1/traffic"
    return urlunsplit((parts.scheme, parts.netloc, target_path, "", ""))


def _clean_request_payload(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    out: dict[str, Any] = {}
    if "masked" in raw:
        out["masked"] = raw["masked"]
    if isinstance(raw.get("thumbnails"), list):
        out["thumbnails"] = raw["thumbnails"]
    return out or None


def _clean_response_payload(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    out: dict[str, Any] = {}
    if "masked" in raw:
        out["masked"] = raw["masked"]
    if isinstance(raw.get("chunks"), int) and not isinstance(raw.get("chunks"), bool):
        out["chunks"] = raw["chunks"]
    return out or None


def sanitize_for_remote(
    event: Mapping[str, Any],
    *,
    level: RemoteTrafficLevel = RemoteTrafficLevel.MASKED,
) -> dict[str, Any]:
    """Return a scrubbed copy of ``event`` with ``original`` and ``unmasked`` removed."""
    scrubbed = scrub(dict(event))
    if not isinstance(scrubbed, dict):
        raise ValueError("traffic event must be a mapping")
    scrubbed.pop("seq", None)
    scrubbed.pop("endpoint", None)
    scrubbed["level"] = "masked"
    if level is RemoteTrafficLevel.STATS:
        scrubbed["request"] = None
        scrubbed["response"] = None
    else:
        scrubbed["request"] = _clean_request_payload(scrubbed.get("request"))
        scrubbed["response"] = _clean_response_payload(scrubbed.get("response"))
    return scrubbed


def _size(event: Mapping[str, Any]) -> int:
    return len(json.dumps(event, separators=(",", ":"), default=str))


class RemoteTrafficExporter:
    """Bounded background shipper that POSTs sanitized traffic events to a remote dashboard."""

    def __init__(
        self,
        remote_url: str,
        *,
        api_key: str | None = None,
        level: RemoteTrafficLevel = RemoteTrafficLevel.MASKED,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        batch_size: int = MAX_BATCH_SIZE,
        batch_bytes: int = MAX_BATCH_BYTES,
        client: httpx.Client | None = None,
    ) -> None:
        self.url = resolve_ingest_url(remote_url)
        self.level = RemoteTrafficLevel(level)
        self.batch_size = max(1, min(batch_size, 50))
        self.batch_bytes = max(1024, batch_bytes)
        self._api_key = api_key.strip() if api_key and api_key.strip() else None
        self._own_client = client is None
        self._client = client or httpx.Client(timeout=_TIMEOUT)
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=max(1, queue_size))
        self._closed = False
        self._lock = threading.Lock()
        self.dropped = 0
        self.sent = 0
        self.failed = 0
        self._warned = False
        self._carry: dict[str, Any] | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="pii-guard-remote-traffic",
            daemon=True,
        )
        self._thread.start()

    def __repr__(self) -> str:
        return (
            f"RemoteTrafficExporter(url={self.url!r}, level={self.level.value!r}, "
            f"sent={self.sent}, dropped={self.dropped})"
        )

    def enqueue(self, event: Mapping[str, Any]) -> bool:
        """Sanitize and queue ``event`` without blocking. Returns ``False`` when dropped."""
        with self._lock:
            if self._closed:
                return False
        sanitized = self._fit(sanitize_for_remote(event, level=self.level))
        if sanitized is None:
            self._count("dropped", 1)
            return False
        try:
            self._queue.put_nowait(sanitized)
            return True
        except queue.Full:
            self._count("dropped", 1)
            return False

    def _fit(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """``event``, or its stats-level form when it alone is over the batch byte cap."""
        if _size(event) <= self.batch_bytes:
            return event
        stats = {**event, "request": None, "response": None}
        return stats if _size(stats) <= self.batch_bytes else None

    def _count(self, field: str, n: int) -> None:
        with self._lock:
            setattr(self, field, getattr(self, field) + n)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _send_batch(self, batch: list[dict[str, Any]]) -> None:
        if not batch:
            return
        try:
            response = self._client.post(
                self.url,
                json={"events": batch},
                headers=self._headers(),
            )
            if 200 <= response.status_code < 300:
                self._count("sent", len(batch))
            else:
                self._failed(len(batch), f"HTTP {response.status_code}")
        except Exception as exc:
            self._failed(len(batch), type(exc).__name__)

    def _failed(self, n: int, why: str) -> None:
        self._count("failed", n)
        # The first failure is a warning, so a misconfigured dashboard is noticed; the rest
        # stay at debug so an unreachable one can't flood the log.
        level = logging.DEBUG if self._warned else logging.WARNING
        self._warned = True
        logger.log(level, "remote traffic ingest failed (%s, %d event(s) dropped)", why, n)

    def _drain_batch(self, first: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
        batch = [first]
        size = _size(first)
        stop = False
        while len(batch) < self.batch_size:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                stop = True
                break
            item_size = _size(item)
            if size + item_size > self.batch_bytes:
                # Over the byte cap: this event starts the next batch.
                self._carry = item
                break
            batch.append(item)
            size += item_size
        return batch, stop

    def _run(self) -> None:
        while True:
            item = self._carry if self._carry is not None else self._queue.get()
            self._carry = None
            if item is None:
                self._queue.task_done()
                break
            batch, stop = self._drain_batch(item)
            try:
                self._send_batch(batch)
            finally:
                for _ in batch:
                    self._queue.task_done()
                if stop:
                    self._queue.task_done()
            if stop:
                break

    def flush(self, timeout: float = 5.0) -> None:
        """Wait up to ``timeout`` seconds for queued events to be shipped."""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._queue.all_tasks_done:
            while self._queue.unfinished_tasks:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._queue.all_tasks_done.wait(remaining)

    def close(self, timeout: float = 5.0) -> None:
        """Flush queued events and stop the background worker."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self.flush(timeout=timeout)
        with suppress(queue.Full):
            self._queue.put_nowait(None)
        self._thread.join(timeout=max(0.1, timeout))
        if self._own_client:
            self._client.close()
