"""Atomic, conservative admission for the single-process hosted deployment.

Reservations are charged in full before work starts. Once the response stream has closed,
a paid reservation may be settled down (never up) to what the request actually used
(LAB-1662): its upstream's reported usage, otherwise a conservative estimate, and nothing
when no upstream call happened. Settlement returns tokens and money, never the request
count, and happens at most once. Concurrency is released after the stream has closed.

The ledger is ephemeral. Sponsored authority therefore requires a one-time external claim
of a reconciled allocation. A successful claim must survive process/container restarts.
The complete allocation is forfeited on restart; neither daily rollover nor a new process
automatically creates spending authority. An ephemeral filesystem claim is NOT sufficient.
"""

from __future__ import annotations

import hashlib
import math
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from types import TracebackType

from pii_guard.types import PiiGuardError

DAY_SECONDS = 86_400
# The one source of the sponsored token rates (integer microdollars per token): QuotaLimits
# and the PII_GUARD_HOSTED_*_MICRODOLLARS_PER_TOKEN settings both default to these.
# Reconciled 2026-10-28 against https://dev.meta.ai/docs/pricing-rate-limits, Standard
# muse-spark-1.3: USD 1.25 input / 4.25 output per million tokens (1.25 / 4.25 µ$ per token);
# reasoning tokens are reported inside completion_tokens, so they are charged as output.
# The defaults stay 4x (input) and about 7x (output) above that, and above Muse Wonder
# (4.00 / 20.00), so a price rise or a second allowlisted model stays covered.
DEFAULT_INPUT_MICRODOLLARS_PER_TOKEN = 5
DEFAULT_OUTPUT_MICRODOLLARS_PER_TOKEN = 30
# The curated demo asks for a short reply; its output reservation is this, not the hosted max.
# muse-spark-1.3 reasons before it answers: on the demo prompts every call at 512 and below
# came back empty, 1024 answered 1 of 4, and 4096 answered all, using at most 2,994 tokens
# (eval/results/2026-10-28-lab-1372-meta-reasoning). A budget too small to answer is still
# charged in full, so the demo reserves enough to answer.
DEMO_MAX_OUTPUT_TOKENS = 4096
# Masking may lengthen a request (a placeholder can be longer than the value it replaces).
# The upstream payload may be at most twice the admitted body plus a fixed allowance; the
# gateway refuses a larger masked payload, so this bound is also the input token charge
# (a byte-level tokenizer never emits more tokens than bytes).
PAYLOAD_EXPANSION = 2
PAYLOAD_ALLOWANCE_BYTES = 4096


def upstream_payload_bound(body_bytes: int) -> int:
    """The largest upstream payload, in bytes and so in input tokens, a body may become."""
    return PAYLOAD_EXPANSION * max(0, body_bytes) + PAYLOAD_ALLOWANCE_BYTES


def claim_allocation_file(directory: str | Path, allocation_id: str) -> bool:
    """Consume an allocation once using an operator-provided durable filesystem.

    The directory must already exist, be absolute and be on storage surviving container
    replacement. Deployment must ensure exactly one replica and never remove claim files.
    This helper cannot establish the durability of an arbitrary mount. An ID is only a
    one-time claim identifier, not an authorization secret; hash it to avoid path traversal.
    A partially written claim is still consumed. All failures disable sponsored work.
    """
    if not allocation_id or len(allocation_id) > 256 or not Path(directory).is_absolute():
        return False
    directory_fd: int | None = None
    marker_fd: int | None = None
    try:
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        filename = hashlib.sha256(allocation_id.encode("utf-8")).hexdigest() + ".claimed"
        marker_fd = os.open(
            filename,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        os.write(marker_fd, b"allocation consumed; do not remove\n")
        os.fsync(marker_fd)
        os.fsync(directory_fd)
        return True
    except (OSError, ValueError):
        return False
    finally:
        if marker_fd is not None:
            os.close(marker_fd)
        if directory_fd is not None:
            os.close(directory_fd)


class QuotaExceededError(PiiGuardError):
    code = "quota_exceeded"
    status_code = 429

    def __init__(self, *, resets_at: str) -> None:
        self.resets_at = resets_at
        super().__init__(f"Hosted budget exhausted; resets at {resets_at}")


class QuotaUnavailableError(PiiGuardError):
    code = "quota_unavailable"
    status_code = 503

    def __init__(self) -> None:
        super().__init__("Hosted admission is unavailable")


class SponsoredUnavailableError(PiiGuardError):
    code = "sponsored_unavailable"
    status_code = 503

    def __init__(self) -> None:
        super().__init__("Sponsored budget is unavailable; use an owned connection")


@dataclass(frozen=True, slots=True)
class QuotaLimits:
    guest_requests: int = 5
    user_requests: int = 100
    guest_tokens: int = 100_000
    user_tokens: int = 1_000_000
    global_requests: int = 10_000
    global_tokens: int = 10_000_000
    principal_concurrency: int = 2
    global_concurrency: int = 8
    max_principals: int = 10_000
    # Integer microdollars per token, including reasoning/output. Operators must set
    # upper bounds covering every permitted model and provider billing component.
    input_microdollars_per_token: int = DEFAULT_INPUT_MICRODOLLARS_PER_TOKEN
    output_microdollars_per_token: int = DEFAULT_OUTPUT_MICRODOLLARS_PER_TOKEN
    global_daily_microdollars: int = 10_000_000
    # Images (LAB-1390): a separate daily count, never covered by the token allowance.
    # Guests get none; there is no remote image cost, only replica CPU.
    user_images: int = 20
    global_images: int = 500

    def __post_init__(self) -> None:
        if any(
            type(getattr(self, f.name)) is not int or getattr(self, f.name) <= 0
            for f in fields(self)
        ):
            raise ValueError("quota limits must be positive integers")


@dataclass(slots=True)
class _Usage:
    day: int
    requests: int = 0
    tokens: int = 0
    images: int = 0
    active: int = 0


class Reservation:
    """One admitted operation, retained until streaming and cleanup are complete."""

    def __init__(
        self,
        ledger: QuotaLedger,
        usage: _Usage,
        *,
        day: int = 0,
        tokens: int = 0,
        spend: int = 0,
    ) -> None:
        self._ledger = ledger
        self._usage = usage
        self._released = False
        self._settled = False
        self._day, self.tokens, self.spend = day, tokens, spend

    def settle(self, tokens: int, spend: int) -> tuple[int, int]:
        """Lower this reservation to ``tokens`` and ``spend`` (microdollars), at most once.

        Returns the (tokens, spend) refunded. Never raises the charge: values above the
        reservation, or that are not nonnegative integers, refund nothing. A reservation
        from a previous day refunds only the allocation, never today's fresh counters.
        """
        ledger = self._ledger
        with ledger._lock:
            if self._settled:
                return 0, 0
            self._settled = True
            if type(tokens) is not int or type(spend) is not int or tokens < 0 or spend < 0:
                return 0, 0
            refund_tokens = self.tokens - min(tokens, self.tokens)
            refund_spend = self.spend - min(spend, self.spend)
            try:
                same_day = ledger._rollover() == self._day
            except QuotaUnavailableError:
                same_day = False
            if same_day:
                usage = self._usage
                usage.tokens -= min(refund_tokens, usage.tokens)
                ledger._tokens -= min(refund_tokens, ledger._tokens)
                ledger._spent_today -= min(refund_spend, ledger._spent_today)
            else:
                refund_tokens = 0
            ledger._spent_allocation -= min(refund_spend, ledger._spent_allocation)
            return refund_tokens, refund_spend

    def release(self) -> None:
        """Idempotent, thread-safe concurrency release; never refunds budget."""
        with self._ledger._lock:
            if not self._released:
                self._usage.active -= 1
                self._ledger._active -= 1
                self._released = True

    def __enter__(self) -> Reservation:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


class QuotaLedger:
    """Bounded owner accounting, shared by all runtimes in exactly one process.

    ``claim_allocation`` atomically consumes an external, durable one-time allocation.
    It must return exactly ``True`` once, never merely confirm that configuration exists.
    The callback is invoked at construction before any sponsored work is admitted.
    Failed or missing claims leave sponsored work disabled, while BYOK compute remains
    subject to the same request/token/concurrency budgets. No automatic retries exist.
    """

    def __init__(
        self,
        limits: QuotaLimits | None = None,
        *,
        sponsored_allocation_microdollars: int = 0,
        allocation_expires_at: float | None = None,
        claim_allocation: Callable[[], bool] | None = None,
        allocation_id: str | None = None,
        allocation_directory: str | Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.limits = limits or QuotaLimits()
        self._clock = clock
        self._lock = threading.Lock()
        self._users: dict[str, _Usage] = {}
        self._active = 0
        self._day = self._read_day()
        self._requests = self._tokens = self._spent_today = self._spent_allocation = 0
        self._images = 0
        if (
            type(sponsored_allocation_microdollars) is not int
            or sponsored_allocation_microdollars < 0
        ):
            raise ValueError("sponsored allocation must be a nonnegative integer")
        self._allocation = sponsored_allocation_microdollars
        self._allocation_expires_at = allocation_expires_at
        self._sponsored_enabled = False
        self._sponsored_killed = False
        if allocation_id is not None and allocation_directory is not None:
            if claim_allocation is not None:
                raise ValueError("supply only one allocation claim mechanism")
            claim_allocation = partial(claim_allocation_file, allocation_directory, allocation_id)
        if self._allocation and claim_allocation is not None:
            if allocation_expires_at is None or not math.isfinite(allocation_expires_at):
                raise ValueError("sponsored allocation requires a finite expiry")
            if self._now() < allocation_expires_at:
                try:
                    self._sponsored_enabled = claim_allocation() is True
                except Exception:
                    # The claim may have committed before an error. Never retry or expose
                    # store errors, which can contain credentials or deployment metadata.
                    self._sponsored_enabled = False

    @property
    def sponsored_enabled(self) -> bool:
        with self._lock:
            return (
                self._sponsored_enabled
                and self._allocation_expires_at is not None
                and self._now() < self._allocation_expires_at
                and self._spent_allocation < self._allocation
            )

    def _now(self) -> float:
        try:
            now = self._clock()
            if not math.isfinite(now) or now < 0:
                raise ValueError
            return now
        except Exception:
            raise QuotaUnavailableError from None

    def _read_day(self) -> int:
        return int(self._now() // DAY_SECONDS)

    def _rollover(self) -> int:
        day = self._read_day()
        if day < self._day:
            raise QuotaUnavailableError
        if day > self._day:
            self._day = day
            self._requests = self._tokens = self._spent_today = self._images = 0
            # Never discard a live stream's permit. Idle previous-day identities can
            # be removed, but eviction within a day must not replenish quotas.
            self._users = {key: usage for key, usage in self._users.items() if usage.active}
            for usage in self._users.values():
                usage.day, usage.requests, usage.tokens, usage.images = day, 0, 0, 0
        return day

    def _reset_at(self) -> str:
        return datetime.fromtimestamp((self._day + 1) * DAY_SECONDS, UTC).isoformat()

    def disable_sponsored(self) -> None:
        """Operator kill switch for future sponsored admissions, irreversible this process."""
        with self._lock:
            self._sponsored_enabled = False
            self._sponsored_killed = True

    @property
    def sponsored_killed(self) -> bool:
        with self._lock:
            return self._sponsored_killed

    def admit(
        self,
        principal: str,
        *,
        authenticated: bool,
        input_tokens: int,
        output_tokens: int,
        sponsored: bool,
        images: int = 0,
    ) -> Reservation:
        """Reserve once before detection/upstream work, or raise without mutating budgets.

        Token bounds MUST cover the eventual outbound payload and maximum generated tokens,
        including reasoning; caller controls model allowlists and payload/output limits.
        Each retry needs a new admission. Guarded detector work uses ``sponsored=False``
        but still consumes request/token/compute budgets. A downstream call in the same
        operation must be included here, not admitted after detector work has started.
        ``images`` counts against the separate daily image allowance; guests have none.
        """
        if not principal or len(principal) > 256:
            raise QuotaUnavailableError
        if any(type(n) is not int or n < 0 for n in (input_tokens, output_tokens, images)):
            raise QuotaUnavailableError
        if images and (not authenticated or sponsored):
            raise QuotaUnavailableError
        tokens = input_tokens + output_tokens
        limits = self.limits
        spend = (
            input_tokens * limits.input_microdollars_per_token
            + output_tokens * limits.output_microdollars_per_token
        )
        with self._lock:
            day = self._rollover()
            if sponsored and (
                not self._sponsored_enabled
                or self._allocation_expires_at is None
                or self._now() >= self._allocation_expires_at
                or self._spent_allocation + spend > self._allocation
            ):
                raise SponsoredUnavailableError
            usage = self._users.get(principal)
            if usage is None:
                if len(self._users) >= limits.max_principals:
                    raise QuotaUnavailableError
                usage = _Usage(day)
            request_limit = limits.user_requests if authenticated else limits.guest_requests
            token_limit = limits.user_tokens if authenticated else limits.guest_tokens
            if (
                usage.requests >= request_limit
                or usage.tokens + tokens > token_limit
                or usage.active >= limits.principal_concurrency
                or self._requests >= limits.global_requests
                or self._tokens + tokens > limits.global_tokens
                or self._active >= limits.global_concurrency
                or (images and usage.images + images > limits.user_images)
                or (images and self._images + images > limits.global_images)
                or (sponsored and self._spent_today + spend > limits.global_daily_microdollars)
            ):
                raise QuotaExceededError(resets_at=self._reset_at())
            # Construct the permit before committing, so allocation failure cannot consume
            # capacity without giving the caller its corresponding release handle.
            reservation = Reservation(
                self, usage, day=day, tokens=tokens, spend=spend if sponsored else 0
            )
            self._users[principal] = usage
            usage.requests += 1
            usage.tokens += tokens
            usage.images += images
            usage.active += 1
            self._requests += 1
            self._tokens += tokens
            self._images += images
            self._active += 1
            if sponsored:
                self._spent_today += spend
                self._spent_allocation += spend
            return reservation

    def usage(self, principal: str) -> dict[str, int | str]:
        """Safe account metadata without creating entries or exposing global usage."""
        with self._lock:
            self._rollover()
            usage = self._users.get(principal)
            return {
                "requests_today": usage.requests if usage else 0,
                "tokens_today": usage.tokens if usage else 0,
                "images_today": usage.images if usage else 0,
                "resets_at": self._reset_at(),
            }
