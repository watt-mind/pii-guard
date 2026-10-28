"""A pre-funded, monetary-only Azure Blob allowance. Never creates or refunds funds.

The operator and every identity allowed to write this blob are trusted budget owners.
ETags prevent concurrent lost updates, not an authorized writer restoring old state.
Unknown write outcomes deny outbound work and remain conservatively charged.
"""

from __future__ import annotations

import hmac
import json
import math
import re
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from importlib import import_module
from typing import Any, Protocol
from urllib.parse import urlsplit

from pii_guard.config import Settings
from pii_guard.hosted.quotas import SponsoredUnavailableError

MAX_BLOB_BYTES = 4096
MAX_MONEY = 10**15
MAX_ATTEMPTS = 3


class Conflict(Exception):
    """A known HTTP412 If-Match failure; no write committed."""


class SpendStore(Protocol):
    def read(self) -> tuple[bytes, str]: ...
    def compare_and_swap(self, value: bytes, etag: str) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Approval:
    environment: str
    allocation_id: str
    ceiling_microdollars: int
    expires_at: int

    def __post_init__(self) -> None:
        if (
            self.environment not in {"dev", "prod"}
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", self.allocation_id)
            or type(self.ceiling_microdollars) is not int
            or not 0 < self.ceiling_microdollars <= MAX_MONEY
            or type(self.expires_at) is not int
            or not 0 < self.expires_at <= 4_102_444_800
        ):
            raise ValueError("Invalid sponsored allowance approval")


@dataclass(frozen=True, slots=True)
class _State:
    version: int
    environment: str
    allocation_id: str
    ceiling_microdollars: int
    expires_at: int
    charged_total: int
    day: str
    daily_charged: int
    enabled: bool

    @classmethod
    def parse(cls, raw: bytes, approval: Approval, today: str) -> _State:
        def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError
                result[key] = value
            return result

        if len(raw) > MAX_BLOB_BYTES:
            raise ValueError
        data = json.loads(raw, object_pairs_hook=object_pairs)
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValueError
        if any(
            type(data[key]) is not int
            for key in (
                "version",
                "ceiling_microdollars",
                "expires_at",
                "charged_total",
                "daily_charged",
            )
        ):
            raise ValueError
        if (
            data["version"] != 1
            or data["environment"] != approval.environment
            or not isinstance(data["allocation_id"], str)
            or not hmac.compare_digest(data["allocation_id"], approval.allocation_id)
            or data["ceiling_microdollars"] != approval.ceiling_microdollars
            or data["expires_at"] != approval.expires_at
            or type(data["enabled"]) is not bool
            or type(data["day"]) is not str
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["day"])
            or datetime.strptime(data["day"], "%Y-%m-%d").date().isoformat() != data["day"]
            or data["day"] > today
            or not 0
            <= data["daily_charged"]
            <= data["charged_total"]
            <= approval.ceiling_microdollars
        ):
            raise ValueError
        return cls(**data)

    def encoded(self) -> bytes:
        return json.dumps(
            {name: getattr(self, name) for name in self.__dataclass_fields__},
            separators=(",", ":"),
        ).encode("ascii")


class DurableSpend:
    """Serial local access and ETag CAS across instances, with bounded conflict retries.

    Config pins the exact operator-approved authority on every read. The local high-water
    mark only detects within-process rollback; storage writers must never reset/restore
    the same allocation, including while applications are stopped.
    """

    def __init__(
        self,
        store: SpendStore | None,
        approval: Approval | None,
        *,
        daily_ceiling: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store, self._approval = store, approval
        self._daily_ceiling, self._clock = daily_ceiling, clock
        self._lock = threading.Lock()
        self._closing = threading.Event()
        self._last: _State | None = None
        self._available = False
        self._last_now = 0.0

    def _now(self) -> tuple[float, str]:
        now = self._clock()
        if not math.isfinite(now) or now < self._last_now:
            raise SponsoredUnavailableError
        self._last_now = now
        return now, datetime.fromtimestamp(now, UTC).date().isoformat()

    def _read(self) -> tuple[_State, str, float, str]:
        if self._store is None or self._approval is None:
            raise SponsoredUnavailableError
        raw, etag = self._store.read()
        now, today = self._now()
        if (
            not isinstance(etag, str)
            or not etag.isascii()
            or not re.fullmatch(r'"[^"\x00-\x20\x7f]{1,254}"', etag)
        ):
            raise SponsoredUnavailableError
        state = _State.parse(raw, self._approval, today)
        last = self._last
        if last is not None and (
            state.charged_total < last.charged_total
            or state.day < last.day
            or (state.day == last.day and state.daily_charged < last.daily_charged)
        ):
            raise SponsoredUnavailableError
        self._last = state
        return state, etag, now, today

    @property
    def available(self) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        try:
            try:
                return (
                    self._available
                    and self._last is not None
                    and self._last_now <= self._clock() < self._last.expires_at
                )
            except Exception:
                return False
        finally:
            self._lock.release()

    def refresh(self) -> None:
        """Startup reads remaining allowance only. Failure leaves BYOK operational."""
        with self._lock:
            try:
                state, _, now, today = self._read()
                self._available = (
                    state.enabled
                    and now < state.expires_at
                    and state.charged_total < state.ceiling_microdollars
                    and (state.day != today or state.daily_charged < self._daily_ceiling)
                )
            except Exception:
                self._available = False
            finally:
                if self._closing.is_set():
                    self._close_locked()

    def charge(self, cost: int, cancelled: threading.Event) -> None:
        """Full conservative charge, never refund or reconcile on completion."""
        with self._lock:
            self._available = False
            try:
                if type(cost) is not int or not 0 < cost <= MAX_MONEY:
                    raise SponsoredUnavailableError
                for attempt in range(MAX_ATTEMPTS):
                    if cancelled.is_set():
                        raise SponsoredUnavailableError
                    state, etag, now, today = self._read()
                    now, today = self._now()
                    daily = state.daily_charged if state.day == today else 0
                    if (
                        not state.enabled
                        or now >= state.expires_at
                        or state.charged_total + cost > state.ceiling_microdollars
                        or daily + cost > self._daily_ceiling
                        or cancelled.is_set()
                    ):
                        raise SponsoredUnavailableError
                    updated = replace(
                        state,
                        charged_total=state.charged_total + cost,
                        day=today,
                        daily_charged=daily + cost,
                    )
                    try:
                        if self._store is None:
                            raise SponsoredUnavailableError
                        before_write, before_day = self._now()
                        if before_write >= state.expires_at or before_day != today:
                            raise SponsoredUnavailableError
                        self._store.compare_and_swap(updated.encoded(), etag)
                    except Conflict:
                        if attempt + 1 == MAX_ATTEMPTS:
                            raise SponsoredUnavailableError from None
                        continue
                    self._last = updated
                    after_write, after_day = self._now()
                    if after_write >= state.expires_at or after_day != today or cancelled.is_set():
                        raise SponsoredUnavailableError
                    self._available = (
                        updated.charged_total < updated.ceiling_microdollars
                        and updated.daily_charged < self._daily_ceiling
                    )
                    return
                raise SponsoredUnavailableError
            except Exception:
                # SDK/validation exceptions can carry account URLs, credentials or data.
                self._available = False
                raise SponsoredUnavailableError from None
            finally:
                if self._closing.is_set():
                    self._close_locked()

    def close(self) -> None:
        self._closing.set()
        if self._lock.acquire(blocking=False):
            try:
                self._close_locked()
            finally:
                self._lock.release()

    def _close_locked(self) -> None:
        store, self._store = self._store, None
        self._available = False
        if store is not None:
            with suppress(Exception):
                store.close()


class AzureBlobStore:
    """Managed identity only, bounded single-GET/single-PUT operations, SDK retries off."""

    def __init__(self, settings: Settings) -> None:
        url = urlsplit(settings.hosted_spend_account_url or "")
        if (
            url.scheme != "https"
            or not re.fullmatch(r"[a-z0-9]{3,24}\.blob\.core\.windows\.net", url.netloc)
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
            or not re.fullmatch(
                r"[a-z0-9](?:[a-z0-9-]{1,61})[a-z0-9]", settings.hosted_spend_container
            )
            or "--" in settings.hosted_spend_container
        ):
            raise ValueError("Invalid sponsored allowance storage configuration")
        identity = import_module("azure.identity")
        blob = import_module("azure.storage.blob")
        self._match = import_module("azure.core").MatchConditions.IfNotModified
        self._credential = identity.ManagedIdentityCredential(
            client_id=settings.hosted_spend_managed_identity_client_id,
            retry_total=0,
            connection_timeout=3,
            read_timeout=5,
        )
        self._client = blob.BlobClient(
            account_url=f"https://{url.netloc}",
            container_name=settings.hosted_spend_container,
            blob_name=f"{settings.hosted_spend_environment}.json",
            credential=self._credential,
            retry_total=0,
            retry_connect=0,
            retry_read=0,
            retry_status=0,
            connection_timeout=3,
            read_timeout=5,
            logging_enable=False,
            max_single_get_size=MAX_BLOB_BYTES + 1,
            max_single_put_size=MAX_BLOB_BYTES,
        )

    def read(self) -> tuple[bytes, str]:
        download = self._client.download_blob(
            offset=0,
            length=MAX_BLOB_BYTES + 1,
            max_concurrency=1,
            timeout=5,
            logging_enable=False,
        )
        raw = download.readall()
        if not isinstance(raw, bytes) or len(raw) > MAX_BLOB_BYTES:
            raise SponsoredUnavailableError
        return raw, download.properties.etag

    def compare_and_swap(self, value: bytes, etag: str) -> None:
        if len(value) > MAX_BLOB_BYTES:
            raise SponsoredUnavailableError
        try:
            self._client.upload_blob(
                value,
                overwrite=True,
                etag=etag,
                match_condition=self._match,
                max_concurrency=1,
                timeout=5,
                logging_enable=False,
            )
        except Exception as exc:
            if getattr(exc, "status_code", None) == 412:
                raise Conflict from None
            raise SponsoredUnavailableError from None

    def close(self) -> None:
        try:
            self._client.close()
        finally:
            self._credential.close()


def azure_spend(settings: Settings, *, daily_ceiling: int) -> DurableSpend:
    """An invalid/missing/unavailable store disables sponsorship, never BYOK startup."""
    store = None
    approval = None
    try:
        expiry = settings.hosted_allocation_expires_at
        if expiry is None or not math.isfinite(expiry) or expiry != int(expiry):
            raise ValueError
        approval = Approval(
            settings.hosted_spend_environment,
            settings.hosted_sponsored_allocation_id or "",
            settings.hosted_sponsored_microdollars,
            int(expiry),
        )
        store = AzureBlobStore(settings)
    except Exception:
        store = None
    ledger = DurableSpend(store, approval, daily_ceiling=daily_ceiling)
    ledger.refresh()
    return ledger
