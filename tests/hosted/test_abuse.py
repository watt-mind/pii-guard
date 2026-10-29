"""Synthetic networks, clocks and races for secondary hosted admission."""

import math
from concurrent.futures import ThreadPoolExecutor

import pytest
from starlette.datastructures import Headers

from pii_guard.hosted.abuse import (
    AGGREGATE_HOURLY,
    AGGREGATE_RATE,
    EVICT_IDLE_SECONDS,
    IDLE_SECONDS,
    LIFETIME_SECONDS,
    MAX_BUCKETS,
    MAX_NETWORKS_PER_AGGREGATE,
    AbuseAdmission,
    AbuseAdmissionError,
    AbuseSignalError,
    AbuseUnavailableError,
)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def headers(value="192.0.2.1"):
    return Headers({"x-forwarded-for": value})


def admit(limiter, value="192.0.2.1", *, owner="synthetic-guest", authenticated=False):
    limiter.admit(
        headers(value),
        principal_id=owner,
        authenticated=authenticated,
        anonymous_sponsored=True,
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        "unknown",
        "192.0.2.1,",
        ",192.0.2.1",
        "invalid, 192.0.2.1",
        "192.0.2.1:443",
        "[2001:db8::1]",
        "2001:db8::1%eth0",
        "192.0.002.1",
        "192.0.2.1\r\n",
        "192.0.2.1\x00",
        "é,192.0.2.1",
        "1" * 2049,
        ",".join(["192.0.2.1"] * 33),
    ],
)
def test_malformed_signal_never_echoes_header(value):
    limiter = AbuseAdmission("aca_xff_rightmost")
    with pytest.raises(AbuseSignalError) as error:
        admit(limiter, value)
    assert error.value.code == "abuse_signal_unavailable"
    assert not limiter._networks
    assert "192.0.2" not in str(error.value)
    assert value not in str(error.value) if value else True


@pytest.mark.parametrize(
    "raw",
    [
        [],
        [(b"x-forwarded-for", b"192.0.2.1"), (b"x-forwarded-for", b"192.0.2.2")],
        [(b"forwarded", b"for=192.0.2.1"), (b"x-real-ip", b"192.0.2.1")],
    ],
)
def test_no_duplicate_or_alternative_signal_fallback(raw):
    limiter = AbuseAdmission("aca_xff_rightmost")
    with pytest.raises(AbuseSignalError):
        limiter.admit(
            Headers(raw=raw), principal_id="guest", authenticated=False, anonymous_sponsored=True
        )


def test_forged_prefixes_and_ipv4_mapped_addresses_share_only_rightmost_bucket():
    limiter = AbuseAdmission("aca_xff_rightmost")
    digest = limiter._network_digest(headers("192.0.2.2"))
    for prefix in ("192.0.2.3", "2001:db8::1", "198.51.100.1,203.0.113.2"):
        assert limiter._network_digest(headers(f"{prefix}, 192.0.2.2")) == digest
    assert limiter._network_digest(headers("::ffff:192.0.2.2")) == digest
    assert limiter._network_digest(headers("192.0.2.3")) != digest
    assert len(digest) == 32
    assert AbuseAdmission("aca_xff_rightmost")._network_digest(headers("192.0.2.2")) != digest


def test_ipv6_privacy_addresses_share_64_bit_network():
    limiter = AbuseAdmission("aca_xff_rightmost")
    digest = limiter._network_digest(headers("2001:db8:1:2::1"))
    assert limiter._network_digest(headers("2001:0db8:0001:0002:abcd::1234")) == digest
    assert limiter._network_digest(headers("2001:db8:1:3::1")) != digest


def test_network_burst_refill_and_denials_do_not_refund():
    clock = Clock()
    limiter = AbuseAdmission("aca_xff_rightmost", clock=clock)
    for _ in range(30):
        admit(limiter)
    with pytest.raises(AbuseAdmissionError) as error:
        admit(limiter)
    assert error.value.retry_after == 2
    clock.now += 1
    with pytest.raises(AbuseAdmissionError) as error:
        admit(limiter)
    assert error.value.retry_after == 1
    clock.now += 1
    admit(limiter)
    assert next(iter(limiter._networks.values())).requests == 31


def test_cookie_rotation_cannot_replenish_hourly_network_allowance():
    clock = Clock()
    limiter = AbuseAdmission("aca_xff_rightmost", clock=clock)
    for index in range(120):
        admit(limiter, owner=f"synthetic-rotating-guest-{index}")
        clock.now += 2
    with pytest.raises(AbuseAdmissionError) as error:
        admit(limiter, owner="new-guest")
    assert error.value.code == "sign_in_required"
    assert error.value.retry_after == 3360
    assert "sign in with Google" in error.value.message
    assert len(limiter._networks) == 1
    clock.now = 3700
    admit(limiter)
    assert next(iter(limiter._networks.values())).requests == 1


def test_shared_network_sign_in_has_separate_principal_allowances_without_signal():
    limiter = AbuseAdmission("aca_xff_rightmost", clock=Clock())
    for _ in range(30):
        admit(limiter)
    with pytest.raises(AbuseAdmissionError):
        admit(limiter)
    for owner in ("synthetic-judge-one", "synthetic-judge-two"):
        for _ in range(10):
            limiter.admit(
                Headers(), principal_id=owner, authenticated=True, anonymous_sponsored=True
            )
        with pytest.raises(AbuseAdmissionError) as error:
            admit(limiter, owner=owner, authenticated=True)
        assert error.value.code == "abuse_throttled"
        assert error.value.retry_after == 2
    assert len(limiter._principals) == 2
    assert len(limiter._networks) == 1


def test_disabled_source_never_requires_signal_for_guests():
    limiter = AbuseAdmission()
    for _ in range(200):
        limiter.admit(
            Headers(), principal_id="guest", authenticated=False, anonymous_sponsored=True
        )
    assert not limiter._networks
    assert not limiter._principals


def test_capacity_refuses_new_network_without_resetting_existing_allowance():
    clock = Clock()
    limiter = AbuseAdmission("aca_xff_rightmost", clock=clock)
    for index in range(MAX_BUCKETS):
        admit(limiter, f"2001:db8:{index:x}::1")
    for _ in range(29):
        admit(limiter, "2001:db8::1")
    with pytest.raises(AbuseAdmissionError) as error:
        admit(limiter, "2001:db8:ffff::1")
    # Every bucket is live, so nothing is evicted; the wait is until one goes idle.
    assert error.value.retry_after == EVICT_IDLE_SECONDS
    with pytest.raises(AbuseAdmissionError):
        admit(limiter, "2001:db8::1")
    assert len(limiter._networks) == MAX_BUCKETS
    assert all(isinstance(key, bytes) and len(key) == 32 for key in limiter._networks)
    assert all(isinstance(key, bytes) and len(key) == 32 for key in limiter._aggregates)
    clock.now += IDLE_SECONDS
    limiter.purge_expired()
    assert not limiter._networks
    assert not limiter._aggregates
    admit(limiter, "2001:db8:ffff::1")


def test_absolute_expiry_forgets_active_network_and_principal_metadata():
    clock = Clock()
    limiter = AbuseAdmission("aca_xff_rightmost", clock=clock)
    for _ in range(48):
        admit(limiter)
        admit(limiter, owner="signed-in", authenticated=True)
        clock.now += 1800
    limiter.purge_expired()
    assert not limiter._networks
    assert not limiter._principals
    assert clock.now == 100 + LIFETIME_SECONDS


@pytest.mark.parametrize("failure", [-1, float("nan"), float("inf"), None])
def test_bad_or_backwards_clock_fails_closed_without_reset(failure):
    clock = Clock()
    limiter = AbuseAdmission("aca_xff_rightmost", clock=clock)
    admit(limiter)
    clock.now = failure
    with pytest.raises(AbuseUnavailableError):
        admit(limiter)
    assert next(iter(limiter._networks.values())).requests == 1


def test_clock_exception_is_sanitized():
    def broken():
        raise RuntimeError("synthetic secret clock failure")

    limiter = AbuseAdmission("aca_xff_rightmost", clock=broken)
    with pytest.raises(AbuseUnavailableError) as error:
        admit(limiter)
    assert "secret" not in str(error.value)


def test_concurrent_cookie_rotation_cannot_exceed_atomic_burst():
    limiter = AbuseAdmission("aca_xff_rightmost", clock=Clock())

    def attempt(index):
        try:
            admit(limiter, owner=f"synthetic-guest-{index}")
            return True
        except AbuseAdmissionError:
            return False

    with ThreadPoolExecutor(max_workers=32) as pool:
        assert sum(pool.map(attempt, range(128))) == 30
    assert next(iter(limiter._networks.values())).requests == 30


def test_signed_in_reads_use_a_separate_generous_bucket():
    clock = Clock()
    limiter = AbuseAdmission(clock=clock)

    def signed_in(*, read):
        limiter.admit(
            Headers(),
            principal_id="synthetic-console-owner",
            authenticated=True,
            anonymous_sponsored=False,
            read=read,
        )

    for _ in range(120):
        signed_in(read=True)
    with pytest.raises(AbuseAdmissionError) as error:
        signed_in(read=True)
    assert error.value.retry_after == 1
    # Reads never drained the work bucket, and work never drains the read bucket.
    for _ in range(10):
        signed_in(read=False)
    with pytest.raises(AbuseAdmissionError) as error:
        signed_in(read=False)
    assert error.value.retry_after == 2
    clock.now += 1
    for _ in range(10):
        signed_in(read=True)
    with pytest.raises(AbuseAdmissionError):
        signed_in(read=True)
    assert len(limiter._reads) == len(limiter._principals) == 1
    assert all(len(key) == 32 for key in limiter._reads)
    clock.now += IDLE_SECONDS
    limiter.purge_expired()
    assert not limiter._reads


def test_read_flag_leaves_anonymous_network_admission_unchanged():
    limiter = AbuseAdmission("aca_xff_rightmost", clock=Clock())
    for _ in range(30):
        limiter.admit(
            headers(),
            principal_id="guest",
            authenticated=False,
            anonymous_sponsored=True,
            read=True,
        )
    with pytest.raises(AbuseAdmissionError):
        admit(limiter)
    assert not limiter._reads
    assert not limiter._principals


def test_read_bucket_table_is_bounded():
    limiter = AbuseAdmission(clock=Clock())
    for index in range(MAX_BUCKETS):
        limiter.admit(
            Headers(),
            principal_id=f"synthetic-reader-{index}",
            authenticated=True,
            anonymous_sponsored=False,
            read=True,
        )
    with pytest.raises(AbuseAdmissionError) as error:
        limiter.admit(
            Headers(),
            principal_id="synthetic-reader-new",
            authenticated=True,
            anonymous_sponsored=False,
            read=True,
        )
    assert error.value.retry_after == EVICT_IDLE_SECONDS
    assert len(limiter._reads) == MAX_BUCKETS


# LAB-1443: one IPv6 /48 holds 65,536 /64s. Before aggregate buckets, one demo from each of
# 4096 of them filled the network table and locked every other client out for up to an hour
# behind `Retry-After: 60`.


def test_ipv6_48_and_ipv4_24_share_an_aggregate_digest():
    limiter = AbuseAdmission("aca_xff_rightmost")
    network, aggregate = limiter._network_keys(headers("2001:db8:1:2::1"))
    other_network, same_aggregate = limiter._network_keys(headers("2001:db8:1:ffff::1"))
    assert other_network != network and same_aggregate == aggregate
    assert limiter._network_keys(headers("2001:db8:2::1"))[1] != aggregate
    v4, v4_aggregate = limiter._network_keys(headers("192.0.2.1"))
    assert limiter._network_keys(headers("192.0.2.200"))[1] == v4_aggregate
    assert limiter._network_keys(headers("::ffff:192.0.2.9"))[1] == v4_aggregate
    assert limiter._network_keys(headers("192.0.3.1"))[1] != v4_aggregate
    assert len({network, aggregate, v4, v4_aggregate}) == 4
    assert all(len(key) == 32 for key in (network, aggregate, v4, v4_aggregate))


def test_one_ipv6_48_cannot_fill_the_network_table_or_lock_out_others():
    clock = Clock()
    limiter = AbuseAdmission("aca_xff_rightmost", clock=clock)
    admitted = 0
    for index in range(MAX_BUCKETS):
        try:
            admit(limiter, f"2001:db8:1:{index:x}::1")
            admitted += 1
        except AbuseAdmissionError as error:
            # The /48 waits until its own oldest network goes idle: the real wait.
            assert error.retry_after == EVICT_IDLE_SECONDS
    assert admitted == MAX_NETWORKS_PER_AGGREGATE
    assert len(limiter._networks) == MAX_NETWORKS_PER_AGGREGATE
    assert len(limiter._aggregates) == 1
    # Clients on other networks are unaffected.
    admit(limiter, "2001:db8:2::1")
    admit(limiter, "192.0.2.1")
    # The quoted Retry-After is honest: one second early is still refused, then it admits.
    clock.now += EVICT_IDLE_SECONDS - 1
    with pytest.raises(AbuseAdmissionError) as error:
        admit(limiter, "2001:db8:1:ffff::1")
    assert error.value.retry_after == 1
    clock.now += 1
    admit(limiter, "2001:db8:1:ffff::1")
    assert len(limiter._networks) == MAX_NETWORKS_PER_AGGREGATE + 2


def test_full_table_evicts_least_recently_used_idle_bucket_and_quotes_real_wait():
    clock = Clock()
    limiter = AbuseAdmission("aca_xff_rightmost", clock=clock)
    # Fill every slot from distinct /48s, one second apart for the first few.
    for index in range(MAX_BUCKETS):
        admit(limiter, f"2001:db8:{index:x}::1")
        if index < 3:
            clock.now += 1
    assert len(limiter._networks) == MAX_BUCKETS
    # The oldest bucket was touched 3 s ago, so it becomes evictable in 297 s, not 60 s.
    with pytest.raises(AbuseAdmissionError) as error:
        admit(limiter, "192.0.2.1")
    assert error.value.code == "abuse_throttled"
    assert error.value.retry_after == EVICT_IDLE_SECONDS - 3
    # A live bucket that keeps sending is never evicted in favour of a newcomer: the oldest
    # one sends again a second early, so the next-oldest (touched at +1 s) is the candidate.
    clock.now += error.value.retry_after - 1
    admit(limiter, "2001:db8::1")
    clock.now += 1
    with pytest.raises(AbuseAdmissionError) as error:
        admit(limiter, "192.0.2.1")
    assert error.value.retry_after == 1
    clock.now += 1
    admit(limiter, "192.0.2.1")
    # The newcomer replaced the least recently used idle bucket (the second one).
    assert len(limiter._networks) == MAX_BUCKETS
    assert limiter._network_digest(headers("2001:db8:1::1")) not in limiter._networks
    assert limiter._network_digest(headers("2001:db8::1")) in limiter._networks


def test_one_aggregate_cannot_multiply_the_network_burst():
    clock = Clock()
    limiter = AbuseAdmission("aca_xff_rightmost", clock=clock)
    burst, rate = AGGREGATE_RATE
    for index in range(burst):
        admit(limiter, f"2001:db8:1:{index % 8:x}::1")
    with pytest.raises(AbuseAdmissionError) as error:
        admit(limiter, "2001:db8:1:ff::1")
    assert error.value.code == "abuse_throttled"
    assert error.value.retry_after == math.ceil(1 / rate)
    # The refusal charged neither level, and created no network bucket.
    assert limiter._network_digest(headers("2001:db8:1:ff::1")) not in limiter._networks
    assert sum(bucket.requests for bucket in limiter._networks.values()) == burst
    admit(limiter, "2001:db8:2::1")


def test_retry_after_reports_the_slowest_refusing_level():
    clock = Clock()
    limiter = AbuseAdmission("aca_xff_rightmost", clock=clock)
    # Exhaust the aggregate's hourly allowance from many networks, at its refill rate.
    for index in range(AGGREGATE_HOURLY):
        admit(limiter, f"2001:db8:1:{index % 60:x}::1")
        clock.now += 1
    with pytest.raises(AbuseAdmissionError) as error:
        admit(limiter, "2001:db8:1:fff::1")
    # The fresh /64 would admit at once; the aggregate's hour is what the client waits for.
    assert error.value.code == "sign_in_required"
    assert error.value.retry_after == 3600 - AGGREGATE_HOURLY
    admit(limiter, "2001:db8:2::1")
