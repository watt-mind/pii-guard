"""Quota tests use synthetic principal IDs and no provider calls."""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from pii_guard.hosted.quotas import (
    DAY_SECONDS,
    QuotaExceededError,
    QuotaLedger,
    QuotaLimits,
    QuotaUnavailableError,
    SponsoredUnavailableError,
    claim_allocation_file,
)


def admit(ledger: QuotaLedger, principal: str = "synthetic-user", **kwargs):
    options = {
        "authenticated": True,
        "input_tokens": 10,
        "output_tokens": 10,
        "sponsored": False,
    }
    options.update(kwargs)
    return ledger.admit(principal, **options)


def sponsored(limits: QuotaLimits | None = None, **kwargs) -> QuotaLedger:
    options = {
        "sponsored_allocation_microdollars": 1000,
        "allocation_expires_at": float(DAY_SECONDS * 3),
        "claim_allocation": lambda: True,
        "clock": lambda: float(DAY_SECONDS),
    }
    options.update(kwargs)
    return QuotaLedger(limits, **options)


def test_guest_budget_is_lower_and_no_refund_on_completion():
    ledger = QuotaLedger(QuotaLimits(guest_requests=1, user_requests=2))
    admit(ledger, "synthetic-guest", authenticated=False).release()
    with pytest.raises(QuotaExceededError) as caught:
        admit(ledger, "synthetic-guest", authenticated=False)
    assert caught.value.resets_at in caught.value.message
    assert ledger.usage("synthetic-guest")["requests_today"] == 1
    with admit(ledger):
        pass
    with admit(ledger):
        pass
    with pytest.raises(QuotaExceededError):
        admit(ledger)


@pytest.mark.parametrize(
    "changes,second_principal",
    [
        ({"guest_tokens": 20}, "synthetic-guest"),
        ({"global_tokens": 20}, "synthetic-other"),
        ({"global_requests": 1}, "synthetic-other"),
    ],
)
def test_daily_caps_are_atomic_without_partial_charge(changes, second_principal):
    ledger = QuotaLedger(replace(QuotaLimits(), **changes))
    admit(ledger, "synthetic-guest", authenticated=False).release()
    before = ledger.usage(second_principal)
    with pytest.raises(QuotaExceededError):
        admit(ledger, second_principal, authenticated=False)
    assert ledger.usage(second_principal) == before


def test_global_concurrency_blocks_other_principals():
    ledger = QuotaLedger(QuotaLimits(global_concurrency=1))
    first = admit(ledger)
    with pytest.raises(QuotaExceededError):
        admit(ledger, "synthetic-other")
    first.release()
    first.release()
    next_reservation = admit(ledger, "synthetic-other")
    with pytest.raises(QuotaExceededError):
        admit(ledger, "synthetic-third")
    next_reservation.release()


def test_simultaneous_admissions_do_not_exceed_cap():
    ledger = QuotaLedger(QuotaLimits(principal_concurrency=3))

    def attempt(_index):
        try:
            return admit(ledger)
        except QuotaExceededError:
            return None

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(attempt, range(32)))
    permitted = [result for result in results if result is not None]
    assert len(permitted) == 3
    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(lambda permit: permit.release(), permitted * 10))
    assert ledger.usage("synthetic-user")["requests_today"] == 3
    admit(ledger).release()


def test_cancelled_stream_releases_concurrency_but_keeps_charge():
    ledger = sponsored(QuotaLimits(principal_concurrency=1))

    async def exercise():
        entered = asyncio.Event()
        wait = asyncio.Event()

        async def stream():
            reservation = admit(ledger, sponsored=True)
            try:
                entered.set()
                await wait.wait()
            finally:
                reservation.release()

        task = asyncio.create_task(stream())
        await entered.wait()
        with pytest.raises(QuotaExceededError):
            admit(ledger)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    admit(ledger, sponsored=True).release()
    # Two reservations cost 700 microdollars; cancelled work still cost 350.
    with pytest.raises(SponsoredUnavailableError):
        admit(ledger, sponsored=True)
    assert ledger.usage("synthetic-user")["requests_today"] == 2


def test_exception_context_keeps_reservation_charge():
    ledger = QuotaLedger(QuotaLimits(user_requests=1))
    with pytest.raises(RuntimeError), admit(ledger):
        raise RuntimeError("synthetic upstream failure")
    with pytest.raises(QuotaExceededError):
        admit(ledger)
    admit(ledger, "synthetic-other").release()


def test_daily_rollover_preserves_active_permits_and_allocation_total():
    now = [float(DAY_SECONDS)]
    ledger = sponsored(
        QuotaLimits(principal_concurrency=1, global_daily_microdollars=350),
        clock=lambda: now[0],
    )
    active = admit(ledger, sponsored=True)
    now[0] += DAY_SECONDS
    with pytest.raises(QuotaExceededError):
        admit(ledger)
    assert ledger.usage("synthetic-user")["requests_today"] == 0
    active.release()
    admit(ledger, sponsored=True).release()
    with pytest.raises(SponsoredUnavailableError):
        admit(ledger, sponsored=True)


def test_daily_money_cap_resets_without_increasing_allocation():
    now = [float(DAY_SECONDS)]
    ledger = sponsored(QuotaLimits(global_daily_microdollars=350), clock=lambda: now[0])
    admit(ledger, sponsored=True).release()
    with pytest.raises(QuotaExceededError):
        admit(ledger, sponsored=True)
    now[0] += DAY_SECONDS
    admit(ledger, sponsored=True).release()
    with pytest.raises(SponsoredUnavailableError):
        admit(ledger, sponsored=True)


def test_capacity_never_evicts_a_daily_quota_and_cleans_next_day():
    now = [float(DAY_SECONDS)]
    ledger = QuotaLedger(QuotaLimits(max_principals=1), clock=lambda: now[0])
    admit(ledger).release()
    assert ledger.usage("synthetic-other")["requests_today"] == 0
    with pytest.raises(QuotaUnavailableError):
        admit(ledger, "synthetic-other")
    now[0] += DAY_SECONDS
    admit(ledger, "synthetic-other").release()


def test_missing_allocation_and_kill_switch_deny_sponsored_only():
    ledger = QuotaLedger()
    assert not ledger.sponsored_enabled
    with pytest.raises(SponsoredUnavailableError):
        admit(ledger, sponsored=True)
    admit(ledger).release()
    ledger = sponsored()
    assert ledger.sponsored_enabled
    ledger.disable_sponsored()
    assert not ledger.sponsored_enabled
    with pytest.raises(SponsoredUnavailableError):
        admit(ledger, sponsored=True)


def test_allocation_expiry_does_not_release_an_active_stream():
    now = [float(DAY_SECONDS)]
    ledger = sponsored(
        QuotaLimits(global_concurrency=1),
        clock=lambda: now[0],
        allocation_expires_at=now[0] + 1,
    )
    permit = admit(ledger, sponsored=True)
    now[0] += 2
    assert not ledger.sponsored_enabled
    with pytest.raises(SponsoredUnavailableError):
        admit(ledger, sponsored=True)
    with pytest.raises(QuotaExceededError):
        admit(ledger, "synthetic-other")
    permit.release()
    admit(ledger, "synthetic-other").release()


def test_spent_allocation_disables_sponsored_status():
    ledger = sponsored(sponsored_allocation_microdollars=350)
    admit(ledger, sponsored=True).release()
    assert not ledger.sponsored_enabled


@pytest.mark.parametrize("result", [False, None, 1])
def test_claim_requires_exact_true(result):
    ledger = sponsored(claim_allocation=lambda: result)
    assert not ledger.sponsored_enabled


def test_claim_error_is_closed_and_does_not_expose_detail():
    calls = []

    def fail():
        calls.append(True)
        raise RuntimeError("synthetic provider secret")

    ledger = sponsored(claim_allocation=fail)
    with pytest.raises(SponsoredUnavailableError) as caught:
        admit(ledger, sponsored=True)
    assert "synthetic provider secret" not in str(caught.value)
    assert calls == [True]


def test_durable_claim_prevents_restart_replenishment(tmp_path):
    args = {
        "allocation_id": "synthetic-allocation-001",
        "allocation_directory": tmp_path,
        "claim_allocation": None,
    }
    first = sponsored(**args)
    assert first.sponsored_enabled
    admit(first, sponsored=True).release()
    assert not sponsored(**args).sponsored_enabled
    assert len(list(tmp_path.glob("*.claimed"))) == 1


def test_claim_is_exclusive_and_filename_cannot_traverse(tmp_path):
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(
            pool.map(lambda _: claim_allocation_file(tmp_path, "../synthetic"), range(16))
        )
    assert sum(claims) == 1
    assert len(list(tmp_path.glob("*.claimed"))) == 1


@pytest.mark.parametrize("allocation_id", ["", "x" * 257])
def test_invalid_claim_id_fails_closed(tmp_path, allocation_id):
    assert not claim_allocation_file(tmp_path, allocation_id)


def test_claim_requires_existing_absolute_nonsymlink_directory(tmp_path):
    assert not claim_allocation_file(Path("relative"), "synthetic")
    assert not claim_allocation_file(tmp_path / "absent", "synthetic")
    link = tmp_path / "symlink"
    link.symlink_to(tmp_path, target_is_directory=True)
    assert not claim_allocation_file(link, "synthetic")


def test_partial_claim_is_consumed_on_fsync_failure(tmp_path, monkeypatch):
    def fail(_fd):
        raise OSError("synthetic disk failure")

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fail)
        assert not claim_allocation_file(tmp_path, "synthetic")
    assert not claim_allocation_file(tmp_path, "synthetic")


@pytest.mark.parametrize("now", [float("nan"), float("inf"), -1])
def test_invalid_clock_fails_closed(now):
    with pytest.raises(QuotaUnavailableError):
        QuotaLedger(clock=lambda: now)


def test_clock_exception_and_backwards_day_do_not_reset_quotas():
    now = [float(DAY_SECONDS)]
    ledger = QuotaLedger(clock=lambda: now[0])
    admit(ledger).release()
    now[0] = 0
    with pytest.raises(QuotaUnavailableError):
        admit(ledger)
    now[0] = float(DAY_SECONDS)
    assert ledger.usage("synthetic-user")["requests_today"] == 1


@pytest.mark.parametrize("value", [-1, True, 1.5])
def test_invalid_token_bound_fails_closed(value):
    ledger = QuotaLedger()
    with pytest.raises(QuotaUnavailableError):
        admit(ledger, input_tokens=value)
    assert ledger.usage("synthetic-user")["requests_today"] == 0


@pytest.mark.parametrize("principal", ["", "x" * 257])
def test_invalid_principal_fails_closed(principal):
    with pytest.raises(QuotaUnavailableError):
        admit(QuotaLedger(), principal)


def test_invalid_settings_rejected(tmp_path):
    with pytest.raises(ValueError):
        QuotaLimits(user_requests=0)
    with pytest.raises(ValueError):
        sponsored(sponsored_allocation_microdollars=-1)
    with pytest.raises(ValueError):
        sponsored(allocation_expires_at=None)
    with pytest.raises(ValueError):
        sponsored(allocation_id="synthetic", allocation_directory=tmp_path)
    assert not sponsored(allocation_expires_at=0).sponsored_enabled


def test_images_have_a_separate_daily_count_guests_none_and_rollover_resets_it():
    now = [float(DAY_SECONDS)]
    ledger = QuotaLedger(QuotaLimits(user_images=2, global_images=3), clock=lambda: now[0])
    with pytest.raises(QuotaUnavailableError):
        admit(ledger, "synthetic-guest", authenticated=False, images=1)
    with pytest.raises(QuotaUnavailableError):
        admit(ledger, images=1, sponsored=True)
    with pytest.raises(QuotaUnavailableError):
        admit(ledger, images=-1)
    admit(ledger, images=1).release()
    admit(ledger, images=1).release()
    with pytest.raises(QuotaExceededError):
        admit(ledger, images=1)
    # Text is still admitted, and a refused image consumed nothing.
    admit(ledger).release()
    assert ledger.usage("synthetic-user")["images_today"] == 2
    admit(ledger, "synthetic-other", images=1).release()
    with pytest.raises(QuotaExceededError):
        admit(ledger, "synthetic-third", images=1)
    now[0] += DAY_SECONDS
    admit(ledger, images=1).release()
    assert ledger.usage("synthetic-user")["images_today"] == 1
