"""Detection cache: history messages are detected once per conversation.

Key: (session id, keyed digest of language + detector config + message text). Value: span
offsets, types, scores, detector names and ``forced_by`` -- **never the text or the values**;
spans are
rebuilt from the message text on a hit. The digest is an HMAC under a random per-process key,
so the cache doesn't even hold a plain hash of a short value. Bounded (LRU) with a sliding TTL
equal to the vault session TTL, so an entry never outlives its conversation's mapping by much.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence

from pii_guard.types import EntityType, Span
from pii_guard.vault import DEFAULT_TTL_SECONDS

__all__ = ["CacheKey", "DetectionCache"]

CacheKey = tuple[str, bytes]
_Stored = tuple[tuple[int, int, EntityType, float, str, str | None], ...]


class DetectionCache:
    def __init__(
        self,
        max_entries: int = 4096,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_entries = max_entries
        self._ttl = ttl_seconds
        self._clock = clock
        self._secret = secrets.token_bytes(32)
        self._lock = threading.Lock()
        self._data: OrderedDict[CacheKey, tuple[float, _Stored]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"DetectionCache(entries={len(self._data)}, max_entries={self.max_entries})"

    def key(self, session_id: str, language: str, config_id: str, text: str) -> CacheKey:
        mac = hmac.new(self._secret, digestmod=hashlib.sha256)
        for part in (language, config_id, text):
            mac.update(part.encode("utf-8", "surrogatepass"))
            mac.update(b"\x1f")
        return session_id, mac.digest()

    def get(self, key: CacheKey, text: str) -> list[Span] | None:
        """The cached spans for ``text``, or ``None`` on a miss (or a stale/mismatched entry)."""
        now = self._clock()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expires_at, stored = item
            if now >= expires_at:
                del self._data[key]
                return None
            self._data[key] = (now + self._ttl, stored)
            self._data.move_to_end(key)
        spans: list[Span] = []
        for start, end, entity_type, score, detector, forced_by in stored:
            if end > len(text):
                return None
            spans.append(
                Span(
                    start,
                    end,
                    entity_type,
                    text[start:end],
                    score,
                    detector,
                    forced_by=forced_by,
                )
            )
        return spans

    def put(self, key: CacheKey, spans: Sequence[Span]) -> None:
        if self.max_entries <= 0:
            return
        stored: _Stored = tuple(
            (s.start, s.end, s.entity_type, s.score, s.detector, s.forced_by) for s in spans
        )
        with self._lock:
            self._data[key] = (self._clock() + self._ttl, stored)
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)

    def drop_session(self, session_id: str) -> None:
        with self._lock:
            for key in [k for k in self._data if k[0] == session_id]:
                del self._data[key]
