"""Bounded secondary admission; network signals never establish an identity.

Only direct, verified ACA ingress may supply the rightmost X-Forwarded-For hop.
Raw addresses are normalized and HMACed inside admission, never retained. This
ephemeral limiter supplements, and cannot replenish, the sponsored spend ledger.
"""

from __future__ import annotations

import hmac
import ipaddress
import math
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from starlette.datastructures import Headers

from pii_guard.types import PiiGuardError

ClientIPSource = Literal["off", "aca_xff_rightmost"]
MAX_HEADER_BYTES = 2048
MAX_HOPS = 32
MAX_BUCKETS = 4096
IDLE_SECONDS = 3600
LIFETIME_SECONDS = 86400
# A full table may evict its least recently used bucket once it has been idle this long:
# long enough to refill any burst, so eviction forgets no short-term allowance.
EVICT_IDLE_SECONDS = 300
HOUR_SECONDS = 3600
# (burst, refill per second) for each table.
NETWORK_RATE = (30, 0.5)
NETWORK_HOURLY = 120
# Each network (IPv4 address or IPv6 /64) also charges its aggregate (IPv4 /24 or IPv6
# /48), so one large allocation cannot multiply its allowance or fill the network table.
AGGREGATE_RATE = (120, 1.0)
AGGREGATE_HOURLY = 480
MAX_NETWORKS_PER_AGGREGATE = 64
PRINCIPAL_RATE = (10, 0.5)
# Signed-in console reads (GET/HEAD): one console load fans out to more than ten owner-scoped
# reads (ADR 0013), so they draw on their own, larger bucket instead of the work bucket.
PRINCIPAL_READ_RATE = (120, 10.0)


class AbuseAdmissionError(PiiGuardError):
    status_code = 429
    code = "abuse_throttled"

    def __init__(self, retry_after: int, *, sign_in: bool = False) -> None:
        self.retry_after = max(1, retry_after)
        if sign_in:
            self.code = "sign_in_required"
        super().__init__(
            "Anonymous network allowance exhausted; sign in with Google to continue, "
            "or use the free walkthrough"
            if sign_in
            else f"Request allowance reached; try again in {self.retry_after} seconds"
        )


class AbuseSignalError(PiiGuardError):
    status_code = 503
    code = "abuse_signal_unavailable"

    def __init__(self) -> None:
        super().__init__(
            "Anonymous demo admission is unavailable; sign in with Google "
            "or use the free walkthrough"
        )


class AbuseUnavailableError(PiiGuardError):
    status_code = 503
    code = "abuse_unavailable"

    def __init__(self) -> None:
        super().__init__("Request admission is unavailable; retry later")


@dataclass(slots=True, repr=False)
class _Bucket:
    created: float
    touched: float
    tokens: float
    hour_start: float
    requests: int = 0
    parent: bytes | None = None


class AbuseAdmission:
    """One lock covers expiry, capacity and charging; denials never refund tokens.

    Network buckets have 30 burst tokens, refilling at 0.5/s, and 120 requests
    per fixed hour starting with their creation. Each network request also charges
    its aggregate (IPv4 /24, IPv6 /48: 120 burst, 1/s, 480/hour), and an aggregate
    tracks at most 64 networks, so one /48 cannot fill the 4096-entry network table.
    Authenticated principals have independent 10-token work bursts at the same refill
    rate, without a network cap, plus a separate read bucket (120 burst, 10/s) for
    GET/HEAD requests. A full table evicts its least recently used bucket once that
    bucket has been idle for ``EVICT_IDLE_SECONDS``; otherwise it refuses, with
    ``Retry-After`` set to when a slot can free up.
    """

    def __init__(
        self,
        source: ClientIPSource = "off",
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if source not in {"off", "aca_xff_rightmost"}:
            raise ValueError("Unknown hosted client IP source")
        self.source = source
        self._clock = clock
        self._key = secrets.token_bytes(32)
        self._lock = threading.Lock()
        self._networks: dict[bytes, _Bucket] = {}
        self._aggregates: dict[bytes, _Bucket] = {}
        self._principals: dict[bytes, _Bucket] = {}
        self._reads: dict[bytes, _Bucket] = {}
        self._last_now = 0.0

    def _now(self) -> float:
        try:
            now = self._clock()
            if not math.isfinite(now) or now < self._last_now:
                raise ValueError
            self._last_now = now
            return now
        except Exception:
            raise AbuseUnavailableError from None

    def _network_keys(self, headers: Headers) -> tuple[bytes, bytes]:
        """Return the (network, aggregate) digests for the rightmost hop."""
        values = headers.getlist("x-forwarded-for")
        if len(values) != 1:
            raise AbuseSignalError
        raw = values[0]
        if not raw or len(raw) > MAX_HEADER_BYTES or not raw.isascii():
            raise AbuseSignalError
        hops = raw.split(",")
        if len(hops) > MAX_HOPS:
            raise AbuseSignalError
        address = None
        for hop in hops:
            value = hop.strip(" \t")
            if not value or "%" in value:
                raise AbuseSignalError
            try:
                # Validate every hop, but use only the ACA-appended rightmost one.
                address = ipaddress.ip_address(value)
            except ValueError:
                raise AbuseSignalError from None
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        if isinstance(address, ipaddress.IPv4Address):
            network = b"v4\0" + address.packed
            aggregate = b"v4/24\0" + address.packed[:3]
        elif isinstance(address, ipaddress.IPv6Address):
            network = b"v6/64\0" + address.packed[:8]
            aggregate = b"v6/48\0" + address.packed[:6]
        else:
            raise AbuseSignalError
        return (
            hmac.digest(self._key, b"network\0" + network, "sha256"),
            hmac.digest(self._key, b"aggregate\0" + aggregate, "sha256"),
        )

    def _network_digest(self, headers: Headers) -> bytes:
        return self._network_keys(headers)[0]

    @staticmethod
    def _purge(table: dict[bytes, _Bucket], now: float) -> None:
        for key, bucket in list(table.items()):
            if now - bucket.touched >= IDLE_SECONDS or now - bucket.created >= LIFETIME_SECONDS:
                del table[key]

    def purge_expired(self) -> None:
        with self._lock:
            now = self._now()
            for table in (self._networks, self._aggregates, self._principals, self._reads):
                self._purge(table, now)

    @staticmethod
    def _victim(candidates: list[tuple[bytes, _Bucket]], now: float) -> bytes:
        """Pick the least recently used idle bucket, or refuse with the real wait.

        The wait is when the first candidate becomes evictable or expires, assuming
        its owner sends nothing more; it never understates that point.
        """
        key, bucket = min(candidates, key=lambda item: item[1].touched)
        if now - bucket.touched >= EVICT_IDLE_SECONDS:
            return key
        free_at = min(
            min(b.touched + EVICT_IDLE_SECONDS, b.created + LIFETIME_SECONDS) for _, b in candidates
        )
        raise AbuseAdmissionError(math.ceil(free_at - now))

    @staticmethod
    def _charge_wait(
        bucket: _Bucket, now: float, burst: int, rate: float, hourly: int | None
    ) -> tuple[int, bool]:
        """Refill ``bucket``; return (seconds until it admits, hourly cap reached)."""
        bucket.tokens = min(float(burst), bucket.tokens + (now - bucket.touched) * rate)
        bucket.touched = now
        if now - bucket.hour_start >= HOUR_SECONDS:
            bucket.hour_start, bucket.requests = now, 0
        if hourly is not None and bucket.requests >= hourly:
            return math.ceil(HOUR_SECONDS - (now - bucket.hour_start)), True
        if bucket.tokens < 1:
            return math.ceil((1 - bucket.tokens) / rate), False
        return 0, False

    def admit(
        self,
        headers: Headers,
        *,
        principal_id: str,
        authenticated: bool,
        anonymous_sponsored: bool,
        read: bool = False,
    ) -> None:
        """Charge before reading a body. Free account inspection bypasses this call.

        With source off, anonymous behavior is unchanged. Missing/invalid signals
        refuse anonymous sponsored work only; sign-in is always independent.
        ``read`` marks a GET/HEAD request: an authenticated principal is charged to
        its read bucket instead of its work bucket (a long-lived SSE stream costs
        one read, at open). It does not change anonymous admission.
        """
        if authenticated:
            if not principal_id or len(principal_id) > 256:
                raise AbuseUnavailableError
            digest = hmac.digest(self._key, b"principal\0" + principal_id.encode(), "sha256")
            if read:
                table, (burst, rate) = self._reads, PRINCIPAL_READ_RATE
            else:
                table, (burst, rate) = self._principals, PRINCIPAL_RATE
            with self._lock:
                self._charge(((table, digest, burst, rate, None, None),))
        elif anonymous_sponsored and self.source != "off":
            network, aggregate = self._network_keys(headers)
            with self._lock:
                self._charge(
                    (
                        (self._aggregates, aggregate, *AGGREGATE_RATE, AGGREGATE_HOURLY, None),
                        (self._networks, network, *NETWORK_RATE, NETWORK_HOURLY, aggregate),
                    )
                )

    def check_anonymous(self, headers: Headers) -> None:
        """Refuse, without charging, when this network's anonymous allowance is spent.

        For a route that should only pay for failures (``GET /metrics``: a good scrape token
        costs nothing, a bad guess is charged with :meth:`admit`). No-op with source off.
        """
        if self.source == "off":
            return
        network, aggregate = self._network_keys(headers)
        levels = (
            (self._aggregates, aggregate, *AGGREGATE_RATE, AGGREGATE_HOURLY),
            (self._networks, network, *NETWORK_RATE, NETWORK_HOURLY),
        )
        with self._lock:
            now = self._now()
            wait, sign_in = 0, False
            for table, key, burst, rate, hourly in levels:
                bucket = table.get(key)
                if bucket is None:
                    continue
                level_wait, level_sign_in = self._charge_wait(bucket, now, burst, rate, hourly)
                wait, sign_in = max(wait, level_wait), sign_in or level_sign_in
        if wait:
            raise AbuseAdmissionError(wait, sign_in=sign_in)

    def _charge(
        self,
        levels: tuple[
            tuple[dict[bytes, _Bucket], bytes, int, float, int | None, bytes | None], ...
        ],
    ) -> None:
        """Admit only if every level admits; charge all of them or none. Lock held."""
        now = self._now()
        evict: list[tuple[dict[bytes, _Bucket], bytes]] = []
        buckets: list[tuple[dict[bytes, _Bucket], bytes, _Bucket, bool]] = []
        for table, key, burst, _rate, _hourly, parent in levels:
            self._purge(table, now)
            bucket = table.get(key)
            if bucket is not None:
                buckets.append((table, key, bucket, False))
                continue
            victim = None
            if parent is not None:
                siblings = [(k, b) for k, b in table.items() if b.parent == parent]
                if len(siblings) >= MAX_NETWORKS_PER_AGGREGATE:
                    # Only the aggregate's own networks compete for its slots.
                    victim = self._victim(siblings, now)
            if victim is None and len(table) >= MAX_BUCKETS:
                victim = self._victim(list(table.items()), now)
            if victim is not None:
                evict.append((table, victim))
            buckets.append((table, key, _Bucket(now, now, float(burst), now, parent=parent), True))
        wait, sign_in = 0, False
        for (_t, _k, burst, rate, hourly, _p), (_, _, bucket, _new) in zip(
            levels, buckets, strict=True
        ):
            level_wait, level_sign_in = self._charge_wait(bucket, now, burst, rate, hourly)
            # The request waits for the slowest refusing level, not the first.
            wait, sign_in = max(wait, level_wait), sign_in or level_sign_in
        if wait:
            raise AbuseAdmissionError(wait, sign_in=sign_in)
        for table, key in evict:
            del table[key]
        for table, key, bucket, new in buckets:
            if new:
                table[key] = bucket
            bucket.tokens -= 1
            bucket.requests += 1
