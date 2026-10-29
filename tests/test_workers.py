"""BoundedWorkers: a slot stays taken until its thread finishes (LAB-1207)."""

from __future__ import annotations

import asyncio
import contextvars
import threading

import pytest

from pii_guard.workers import BoundedWorkers

_VAR: contextvars.ContextVar[str] = contextvars.ContextVar("test_var", default="unset")


def test_runs_the_call_with_the_callers_context() -> None:
    workers = BoundedWorkers(2, "test")

    async def main() -> str:
        _VAR.set("caller")
        return await workers.run(_VAR.get)

    assert asyncio.run(main()) == "caller"
    workers.close()


def test_a_timed_out_call_keeps_its_slot_until_the_thread_ends() -> None:
    workers = BoundedWorkers(1, "test")
    release = threading.Event()
    started = threading.Event()

    def hang() -> str:
        started.set()
        release.wait(10)
        return "late"

    async def main() -> None:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(workers.run(hang), timeout=0.05)
        assert started.is_set()
        assert workers.running == 1
        # The only slot is still held: a second call can't start, it times out waiting.
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(workers.run(lambda: "next"), timeout=0.05)
        release.set()
        assert await asyncio.wait_for(workers.run(lambda: "next"), timeout=5) == "next"
        assert workers.running == 0

    try:
        asyncio.run(main())
    finally:
        release.set()
        workers.close()


def test_pools_are_independent() -> None:
    """A hung pool (audit mode's) never starves another (fast mode's)."""
    hung, other = BoundedWorkers(1, "hung"), BoundedWorkers(1, "other")
    release = threading.Event()

    async def main() -> str:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(hung.run(release.wait, 10), timeout=0.05)
        return await asyncio.wait_for(other.run(lambda: "ok"), timeout=1)

    try:
        assert asyncio.run(main()) == "ok"
    finally:
        release.set()
        hung.close()
        other.close()


def test_errors_propagate_and_free_the_slot() -> None:
    workers = BoundedWorkers(1, "test")

    def boom() -> None:
        raise RuntimeError("boom")

    async def main() -> str:
        with pytest.raises(RuntimeError, match="boom"):
            await workers.run(boom)
        return await asyncio.wait_for(workers.run(lambda: "ok"), timeout=1)

    assert asyncio.run(main()) == "ok"
    assert workers.running == 0
    workers.close()


def test_one_pool_serves_several_event_loops() -> None:
    workers = BoundedWorkers(1, "test")
    for _ in range(3):
        assert asyncio.run(workers.run(lambda: 42)) == 42
    workers.close()


def test_size_must_be_positive() -> None:
    with pytest.raises(ValueError, match="size"):
        BoundedWorkers(0, "test")
