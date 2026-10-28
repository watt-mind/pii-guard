"""Synthetic networks, clocks and races for secondary hosted admission."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from starlette.datastructures import Headers

from pii_guard.hosted.abuse import (
    IDLE_SECONDS,
    LIFETIME_SECONDS,
    MAX_BUCKETS,
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
    with pytest.raises(AbuseAdmissionError):
        admit(limiter, "2001:db8:ffff::1")
    with pytest.raises(AbuseAdmissionError):
        admit(limiter, "2001:db8::1")
    assert len(limiter._networks) == MAX_BUCKETS
    assert all(isinstance(key, bytes) and len(key) == 32 for key in limiter._networks)
    clock.now += IDLE_SECONDS
    limiter.purge_expired()
    assert not limiter._networks
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
    with pytest.raises(AbuseAdmissionError):
        limiter.admit(
            Headers(),
            principal_id="synthetic-reader-new",
            authenticated=True,
            anonymous_sponsored=False,
            read=True,
        )
    assert len(limiter._reads) == MAX_BUCKETS
