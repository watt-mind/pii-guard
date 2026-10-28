"""Synthetic durable monetary allowance tests; no cloud or provider calls."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from pii_guard.hosted.quotas import SponsoredUnavailableError
from pii_guard.hosted.spend import (
    MAX_ATTEMPTS,
    MAX_BLOB_BYTES,
    MAX_MONEY,
    Approval,
    Conflict,
    DurableSpend,
)

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
ALLOCATION = "synthetic-approved-allowance"
SCHEMA = {
    "version",
    "environment",
    "allocation_id",
    "ceiling_microdollars",
    "expires_at",
    "charged_total",
    "day",
    "daily_charged",
    "enabled",
}


class Clock:
    def __init__(self):
        self.value = NOW.timestamp()

    def __call__(self):
        return self.value


def approval(**updates):
    values = {
        "environment": "dev",
        "allocation_id": ALLOCATION,
        "ceiling_microdollars": 1000,
        "expires_at": int((NOW + timedelta(days=3)).timestamp()),
    }
    values.update(updates)
    return Approval(**values)


def state(**updates):
    values = {
        "version": 1,
        "environment": "dev",
        "allocation_id": ALLOCATION,
        "ceiling_microdollars": 1000,
        "expires_at": int((NOW + timedelta(days=3)).timestamp()),
        "charged_total": 100,
        "day": NOW.date().isoformat(),
        "daily_charged": 100,
        "enabled": True,
    }
    values.update(updates)
    return values


class MemoryStore:
    """Thread-safe versioned blob with controllable synthetic transport outcomes."""

    def __init__(self, value=None):
        self.raw = json.dumps(state() if value is None else value).encode()
        self.version = 0
        self.lock = threading.Lock()
        self.reads = self.attempts = self.conflicts = 0
        self.writes = []
        self.force_conflicts = 0
        self.fail_read = self.fail_write = self.fail_after_commit = False
        self.cancel_after_read = self.cancel_after_conflict = None
        self.first_reads_barrier = None
        self.closed = False
        self.close_calls = 0

    def _etag(self):
        return f'"synthetic-etag-{self.version}"'

    def read(self):
        with self.lock:
            self.reads += 1
            if self.fail_read:
                raise RuntimeError("synthetic private read failure")
            value = self.raw, self._etag()
            wait = self.first_reads_barrier is not None and self.reads <= 2
        if wait:
            self.first_reads_barrier.wait(timeout=5)
        if self.cancel_after_read is not None:
            self.cancel_after_read.set()
        return value

    def compare_and_swap(self, value, etag):
        with self.lock:
            self.attempts += 1
            if self.fail_write:
                raise RuntimeError("synthetic private write failure")
            if self.force_conflicts or etag != self._etag():
                self.force_conflicts = max(0, self.force_conflicts - 1)
                self.conflicts += 1
                if self.cancel_after_conflict is not None:
                    self.cancel_after_conflict.set()
                raise Conflict
            self.raw = bytes(value)
            self.version += 1
            self.writes.append(bytes(value))
            if self.fail_after_commit:
                raise TimeoutError("synthetic private unknown commit outcome")

    def replace(self, value):
        with self.lock:
            self.raw = json.dumps(value).encode()
            self.version += 1

    def document(self):
        with self.lock:
            return json.loads(self.raw)

    def close(self):
        self.close_calls += 1
        self.closed = True


def ledger(store, *, clock=None, daily_ceiling=500, approved=None):
    return DurableSpend(
        store, approved or approval(), daily_ceiling=daily_ceiling, clock=clock or Clock()
    )


def charge(subject, cost):
    subject.charge(cost, threading.Event())


def test_startup_refresh_only_reads_existing_remaining_authority():
    store = MemoryStore(state(charged_total=720, daily_charged=80))
    subject = ledger(store)
    subject.refresh()
    assert subject.available
    assert store.reads == 1
    assert store.attempts == 0
    assert store.document()["charged_total"] == 720
    charge(subject, 200)
    restarted = ledger(store)
    restarted.refresh()
    assert restarted.available
    assert store.attempts == 1
    assert store.document()["charged_total"] == 920
    with pytest.raises(SponsoredUnavailableError):
        charge(restarted, 81)
    assert store.document()["charged_total"] == 920


@pytest.mark.parametrize(
    "updates",
    [
        {"environment": "test"},
        {"allocation_id": ""},
        {"allocation_id": "../synthetic"},
        {"allocation_id": "x" * 129},
        {"ceiling_microdollars": True},
        {"ceiling_microdollars": 1000.0},
        {"ceiling_microdollars": 0},
        {"ceiling_microdollars": MAX_MONEY + 1},
        {"expires_at": True},
        {"expires_at": 1.0},
        {"expires_at": 0},
        {"expires_at": 4_102_444_801},
    ],
)
def test_approval_requires_bounded_exact_authority(updates):
    with pytest.raises(ValueError):
        approval(**updates)


@pytest.mark.parametrize(
    "changes",
    [
        {"version": 2},
        {"version": True},
        {"environment": "prod"},
        {"allocation_id": "synthetic-other-allowance"},
        {"ceiling_microdollars": 1001},
        {"ceiling_microdollars": 1000.0},
        {"expires_at": int(NOW.timestamp())},
        {"expires_at": float((NOW + timedelta(days=3)).timestamp())},
        {"charged_total": True},
        {"charged_total": 100.0},
        {"charged_total": -1},
        {"charged_total": 1001},
        {"daily_charged": True},
        {"daily_charged": 100.0},
        {"daily_charged": -1},
        {"daily_charged": 101},
        {"day": "2026-10-29"},
        {"day": "2026-2-01"},
        {"day": "2026-02-30"},
        {"day": 20261028},
        {"enabled": "true"},
        {"enabled": 1},
        {"unknown_field": "synthetic"},
    ],
)
def test_schema_or_approval_mismatch_never_writes(changes):
    store = MemoryStore(state(**changes))
    subject = ledger(store)
    subject.refresh()
    assert not subject.available
    with pytest.raises(SponsoredUnavailableError):
        charge(subject, 1)
    assert store.attempts == 0


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not-json",
        b"[]",
        b"null",
        b"{}",
        b"\xff",
        b'{"version":1,"version":1}',
        b" " * (MAX_BLOB_BYTES + 1),
    ],
)
def test_malformed_duplicate_missing_or_oversized_state_denies(raw):
    store = MemoryStore()
    store.raw = raw
    subject = ledger(store)
    subject.refresh()
    assert not subject.available
    with pytest.raises(SponsoredUnavailableError):
        charge(subject, 1)
    assert store.attempts == 0


def test_duplicate_known_field_cannot_replace_approved_authority():
    store = MemoryStore()
    original = json.dumps(state()).encode()
    store.raw = original[:-1] + b',"ceiling_microdollars":1000000}'
    with pytest.raises(SponsoredUnavailableError):
        charge(ledger(store), 1)
    assert store.attempts == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("environment", "prod"),
        ("allocation_id", "synthetic-replacement"),
        ("ceiling_microdollars", 1001),
        ("expires_at", int((NOW + timedelta(days=4)).timestamp())),
    ],
)
def test_approval_is_revalidated_after_an_initial_success(field, value):
    store = MemoryStore()
    subject = ledger(store)
    charge(subject, 10)
    changed = store.document()
    changed[field] = value
    store.replace(changed)
    with pytest.raises(SponsoredUnavailableError):
        charge(subject, 10)
    assert store.attempts == 1


def test_daily_rollover_preserves_lifetime_charge_across_restart():
    clock = Clock()
    store = MemoryStore()
    subject = ledger(store, clock=clock, daily_ceiling=200)
    charge(subject, 100)
    assert not subject.available
    with pytest.raises(SponsoredUnavailableError):
        charge(ledger(store, clock=clock, daily_ceiling=200), 1)
    clock.value += 86400
    restarted = ledger(store, clock=clock, daily_ceiling=200)
    restarted.refresh()
    assert restarted.available
    assert store.document()["charged_total"] == 200
    charge(restarted, 200)
    assert store.document()["charged_total"] == 400
    assert store.document()["daily_charged"] == 200
    assert store.document()["day"] == "2026-10-29"
    with pytest.raises(SponsoredUnavailableError):
        charge(restarted, 1)


def test_exhausted_lifetime_allocation_never_refills_on_new_day_or_restart():
    clock = Clock()
    store = MemoryStore()
    subject = ledger(store, clock=clock, daily_ceiling=1000)
    charge(subject, 900)
    assert not subject.available
    clock.value += 86400
    restarted = ledger(store, clock=clock, daily_ceiling=1000)
    restarted.refresh()
    assert not restarted.available
    with pytest.raises(SponsoredUnavailableError):
        charge(restarted, 1)
    assert store.document()["charged_total"] == 1000
    assert store.attempts == 1


@pytest.mark.parametrize("enabled", [False, True])
def test_disabled_or_expired_allowance_denies_without_writing(enabled):
    clock = Clock()
    store = MemoryStore(state(enabled=enabled))
    if enabled:
        clock.value = approval().expires_at
    subject = ledger(store, clock=clock)
    subject.refresh()
    assert not subject.available
    with pytest.raises(SponsoredUnavailableError):
        charge(subject, 1)
    assert store.attempts == 0


@pytest.mark.parametrize("failure", [float("nan"), float("inf"), -1, None])
def test_bad_clock_is_fail_closed(failure):
    clock = Clock()
    store = MemoryStore()
    subject = ledger(store, clock=clock)
    subject.refresh()
    clock.value = failure
    with pytest.raises(SponsoredUnavailableError):
        charge(subject, 1)
    assert not subject.available
    assert store.attempts == 0


def test_backwards_utc_day_cannot_roll_a_daily_charge_back():
    clock = Clock()
    store = MemoryStore()
    subject = ledger(store, clock=clock)
    charge(subject, 10)
    clock.value -= 86400
    with pytest.raises(SponsoredUnavailableError):
        charge(subject, 10)
    assert store.document()["charged_total"] == 110
    assert store.document()["daily_charged"] == 110
    assert store.attempts == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"charged_total": 99, "daily_charged": 99},
        {"charged_total": 100, "daily_charged": 99},
        {"charged_total": 100, "day": "2026-10-27"},
    ],
)
def test_same_process_rejects_total_daily_or_day_rollback(changes):
    store = MemoryStore()
    subject = ledger(store)
    subject.refresh()
    store.replace(state(**changes))
    with pytest.raises(SponsoredUnavailableError):
        charge(subject, 1)
    assert store.attempts == 0


def test_known_conflicts_retry_at_most_three_times_and_charge_once():
    store = MemoryStore()
    store.force_conflicts = MAX_ATTEMPTS - 1
    charge(ledger(store), 30)
    assert store.reads == store.attempts == MAX_ATTEMPTS
    assert len(store.writes) == 1
    assert store.document()["charged_total"] == 130
    assert store.document()["daily_charged"] == 130


def test_known_conflict_retry_bound_never_commits_after_exhaustion():
    store = MemoryStore()
    store.force_conflicts = MAX_ATTEMPTS + 10
    with pytest.raises(SponsoredUnavailableError):
        charge(ledger(store), 30)
    assert store.reads == store.attempts == MAX_ATTEMPTS
    assert not store.writes
    assert store.document()["charged_total"] == 100


@pytest.mark.parametrize("operation", ["read", "write"])
def test_unknown_failure_is_sanitized_and_never_retried(operation):
    store = MemoryStore()
    setattr(store, f"fail_{operation}", True)
    subject = ledger(store)
    with pytest.raises(SponsoredUnavailableError) as caught:
        charge(subject, 10)
    assert caught.value.code == "sponsored_unavailable"
    assert "private" not in str(caught.value) + repr(caught.value)
    assert store.reads == 1
    assert store.attempts == (1 if operation == "write" else 0)
    assert not store.writes
    assert not subject.available


def test_unknown_commit_is_not_retried_or_refunded_and_survives_restart():
    store = MemoryStore()
    store.fail_after_commit = True
    subject = ledger(store, daily_ceiling=1000)
    with pytest.raises(SponsoredUnavailableError) as caught:
        charge(subject, 80)
    assert "unknown" not in str(caught.value)
    assert not subject.available
    assert store.reads == store.attempts == 1
    assert len(store.writes) == 1
    assert store.document()["charged_total"] == 180
    store.fail_after_commit = False
    restarted = ledger(store, daily_ceiling=1000)
    restarted.refresh()
    assert store.attempts == 1
    charge(restarted, 820)
    with pytest.raises(SponsoredUnavailableError):
        charge(restarted, 1)
    assert store.document()["charged_total"] == 1000
    assert len(store.writes) == 2


def test_two_instances_with_stale_etags_cannot_overspend():
    store = MemoryStore(state(charged_total=0, daily_charged=0))
    store.first_reads_barrier = threading.Barrier(2)
    subjects = [ledger(store, daily_ceiling=1000), ledger(store, daily_ceiling=1000)]

    def attempt(subject):
        successes = 0
        for _ in range(5):
            try:
                charge(subject, 110)
                successes += 1
            except SponsoredUnavailableError:
                pass
        return successes

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(attempt, subjects)) == 9
    assert store.conflicts >= 1
    assert store.document()["charged_total"] == 990
    assert store.document()["daily_charged"] == 990
    assert len(store.writes) == 9


def test_cancellation_before_admission_or_after_read_prevents_write():
    cancelled = threading.Event()
    cancelled.set()
    store = MemoryStore()
    with pytest.raises(SponsoredUnavailableError):
        ledger(store).charge(10, cancelled)
    assert store.reads == store.attempts == 0
    cancelled.clear()
    store.cancel_after_read = cancelled
    with pytest.raises(SponsoredUnavailableError):
        ledger(store).charge(10, cancelled)
    assert store.reads == 1
    assert store.attempts == 0


def test_cancellation_after_known_conflict_prevents_another_attempt():
    cancelled = threading.Event()
    store = MemoryStore()
    store.force_conflicts = 1
    store.cancel_after_conflict = cancelled
    with pytest.raises(SponsoredUnavailableError):
        ledger(store).charge(10, cancelled)
    assert store.reads == store.attempts == 1
    assert not store.writes


@pytest.mark.parametrize("cost", [0, -1, True, 1.0, MAX_MONEY + 1])
def test_charge_amount_is_a_positive_bounded_exact_integer(cost):
    store = MemoryStore()
    with pytest.raises(SponsoredUnavailableError):
        charge(ledger(store), cost)
    assert store.reads == store.attempts == 0


def test_encoded_state_contains_only_monetary_metadata_and_close_delegates():
    store = MemoryStore()
    subject = ledger(store)
    charge(subject, 10)
    encoded = json.loads(store.writes[0])
    assert set(encoded) == SCHEMA
    assert encoded["allocation_id"] == ALLOCATION
    assert all(
        type(encoded[name]) is int
        for name in (
            "version",
            "ceiling_microdollars",
            "expires_at",
            "charged_total",
            "daily_charged",
        )
    )
    assert len(store.writes[0]) <= MAX_BLOB_BYTES
    assert b"principal" not in store.writes[0]
    assert b"prompt" not in store.writes[0]
    assert b"response" not in store.writes[0]
    subject.close()
    assert store.closed


def test_absent_store_or_approval_is_unavailable_without_startup_failure():
    for subject in (
        DurableSpend(None, approval(), daily_ceiling=500),
        DurableSpend(MemoryStore(), None, daily_ceiling=500),
    ):
        subject.refresh()
        assert not subject.available
        with pytest.raises(SponsoredUnavailableError):
            charge(subject, 1)


def test_read_that_finishes_after_expiry_cannot_use_its_pre_read_clock():
    clock = Clock()

    class ExpiringReadStore(MemoryStore):
        def read(self):
            result = super().read()
            clock.value = approval().expires_at
            return result

    store = ExpiringReadStore()
    subject = ledger(store, clock=clock)
    with pytest.raises(SponsoredUnavailableError):
        charge(subject, 10)
    assert store.reads == 1
    assert store.attempts == 0
    assert store.document()["charged_total"] == 100
    assert not subject.available


def test_read_crossing_midnight_charges_current_day_and_preserves_total():
    clock = Clock()
    clock.value = datetime(2026, 10, 28, 23, 59, 59, tzinfo=UTC).timestamp()

    class MidnightReadStore(MemoryStore):
        def read(self):
            result = super().read()
            clock.value += 2
            return result

    store = MidnightReadStore()
    subject = ledger(store, clock=clock)
    charge(subject, 10)
    assert store.document()["day"] == "2026-10-29"
    assert store.document()["daily_charged"] == 10
    assert store.document()["charged_total"] == 110
    assert len(store.writes) == 1


@pytest.mark.parametrize("crossing", ["expiry", "midnight"])
def test_write_finishing_after_expiry_or_midnight_denies_without_refund(crossing):
    clock = Clock()

    class ClockChangingWriteStore(MemoryStore):
        def compare_and_swap(self, value, etag):
            super().compare_and_swap(value, etag)
            clock.value = (
                approval().expires_at
                if crossing == "expiry"
                else datetime(2026, 10, 29, tzinfo=UTC).timestamp()
            )

    store = ClockChangingWriteStore()
    subject = ledger(store, clock=clock)
    with pytest.raises(SponsoredUnavailableError):
        charge(subject, 10)
    assert not subject.available
    assert store.reads == store.attempts == 1
    assert len(store.writes) == 1
    assert store.document()["charged_total"] == 110
    assert store.document()["daily_charged"] == 110


def test_wall_clock_rollback_within_same_day_denies_without_writing():
    clock = Clock()
    store = MemoryStore()
    subject = ledger(store, clock=clock)
    subject.refresh()
    clock.value -= 1
    assert datetime.fromtimestamp(clock.value, UTC).date() == NOW.date()
    with pytest.raises(SponsoredUnavailableError):
        charge(subject, 10)
    assert not subject.available
    assert store.attempts == 0
    assert store.document()["charged_total"] == 100


class BlockingWriteStore(MemoryStore):
    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.finish = threading.Event()

    def compare_and_swap(self, value, etag):
        self.entered.set()
        if not self.finish.wait(timeout=5):
            raise TimeoutError("synthetic write test did not finish")
        assert not self.closed, "store must remain open until its active write ends"
        super().compare_and_swap(value, etag)


def test_available_is_nonblocking_while_storage_write_holds_ledger_lock():
    store = BlockingWriteStore()
    subject = ledger(store)
    subject.refresh()
    assert subject.available
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(charge, subject, 10)
        try:
            assert store.entered.wait(timeout=1)
            metadata = pool.submit(lambda: subject.available)
            assert metadata.result(timeout=0.5) is False
        finally:
            store.finish.set()
        pending.result(timeout=1)
    assert store.document()["charged_total"] == 110


def test_close_defers_sdk_close_until_active_worker_finishes_exactly_once():
    store = BlockingWriteStore()
    subject = ledger(store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(charge, subject, 10)
        try:
            assert store.entered.wait(timeout=1)
            cleanup = pool.submit(subject.close)
            cleanup.result(timeout=0.5)
            subject.close()
            assert not store.closed
            assert store.close_calls == 0
        finally:
            store.finish.set()
        pending.result(timeout=1)
    assert store.closed
    assert store.close_calls == 1
    assert store.document()["charged_total"] == 110
    subject.close()
    assert store.close_calls == 1
    assert not subject.available


def test_close_defers_sdk_close_until_active_refresh_finishes_exactly_once():
    class BlockingReadStore(MemoryStore):
        def __init__(self):
            super().__init__()
            self.entered = threading.Event()
            self.finish = threading.Event()

        def read(self):
            self.entered.set()
            if not self.finish.wait(timeout=5):
                raise TimeoutError("synthetic refresh test did not finish")
            assert not self.closed, "store must remain open until its active read ends"
            return super().read()

    store = BlockingReadStore()
    subject = ledger(store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(subject.refresh)
        try:
            assert store.entered.wait(timeout=1)
            cleanup = pool.submit(subject.close)
            cleanup.result(timeout=0.5)
            assert not store.closed
            assert store.close_calls == 0
        finally:
            store.finish.set()
        pending.result(timeout=1)
    assert store.closed
    assert store.close_calls == 1
    assert store.attempts == 0
    subject.close()
    assert store.close_calls == 1
    assert not subject.available
