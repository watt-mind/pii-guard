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
# (burst, refill per second) for each table.
NETWORK_RATE = (30, 0.5)
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


class AbuseAdmission:
    """One lock covers expiry, capacity and charging; denials never refund tokens.

    Network buckets have 30 burst tokens, refilling at 0.5/s, and 120 requests
    per fixed hour starting with their creation. Authenticated principals have
    independent 10-token work bursts at the same refill rate, without a network
    cap, plus a separate read bucket (120 burst, 10/s) for GET/HEAD requests.
    Every table refuses new entries at capacity instead of forgetting allowances.
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

    def _network_digest(self, headers: Headers) -> bytes:
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
            normalized = b"v4\0" + address.packed
        elif isinstance(address, ipaddress.IPv6Address):
            normalized = b"v6/64\0" + address.packed[:8]
        else:
            raise AbuseSignalError
        return hmac.digest(self._key, b"network\0" + normalized, "sha256")

    @staticmethod
    def _purge(table: dict[bytes, _Bucket], now: float) -> None:
        for key, bucket in list(table.items()):
            if now - bucket.touched >= IDLE_SECONDS or now - bucket.created >= LIFETIME_SECONDS:
                del table[key]

    def purge_expired(self) -> None:
        with self._lock:
            now = self._now()
            self._purge(self._networks, now)
            self._purge(self._principals, now)
            self._purge(self._reads, now)

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
        elif anonymous_sponsored and self.source != "off":
            digest = self._network_digest(headers)
            table, (burst, rate) = self._networks, NETWORK_RATE
        else:
            return
        with self._lock:
            now = self._now()
            self._purge(table, now)
            bucket = table.get(digest)
            if bucket is None:
                if len(table) >= MAX_BUCKETS:
                    raise AbuseAdmissionError(60)
                bucket = _Bucket(now, now, float(burst), now)
                table[digest] = bucket
            bucket.tokens = min(float(burst), bucket.tokens + (now - bucket.touched) * rate)
            bucket.touched = now
            if now - bucket.hour_start >= 3600:
                bucket.hour_start, bucket.requests = now, 0
            if not authenticated and bucket.requests >= 120:
                raise AbuseAdmissionError(math.ceil(3600 - (now - bucket.hour_start)), sign_in=True)
            if bucket.tokens < 1:
                raise AbuseAdmissionError(math.ceil((1 - bucket.tokens) / rate))
            bucket.tokens -= 1
            bucket.requests += 1
