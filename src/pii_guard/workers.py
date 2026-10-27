"""Bounded worker pools for blocking detection and image work (LAB-1207).

``asyncio.to_thread`` runs on the loop's shared default executor, and ``asyncio.wait_for``
only cancels the awaiting coroutine: a timed-out detection keeps its thread, and a semaphore
around the ``await`` is released while that thread still runs. A hung detector then fills
the shared executor and starves every other caller, including another mode's.

:class:`BoundedWorkers` is a private pool of ``size`` threads plus a slot counter of the same
size that is released only when the thread has actually finished (or never started). So at
most ``size`` calls of one pool run at once, timed-out ones included; once they are all
stuck, callers wait for a free slot inside their own timeout (and fail with it) instead of
piling more threads up, and other pools are not affected.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, TypeVar

__all__ = ["BoundedWorkers"]

T = TypeVar("T")


class BoundedWorkers:
    """``size`` worker threads; a slot is held until its thread finishes.

    Safe to share across event loops (one app served by several test clients): the slot
    semaphore is bound to the running loop and recreated for a new one.
    """

    def __init__(self, size: int, name: str) -> None:
        if size < 1:
            raise ValueError("size must be at least 1")
        self.size = size
        self.name = name
        self._executor = ThreadPoolExecutor(max_workers=size, thread_name_prefix=name)
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._slots: asyncio.Semaphore | None = None
        self._running = 0

    def __repr__(self) -> str:
        return f"BoundedWorkers({self.name!r}, size={self.size}, running={self._running})"

    @property
    def running(self) -> int:
        """Calls whose thread has not finished yet (timed-out ones included)."""
        return self._running

    def _semaphore(self) -> tuple[asyncio.AbstractEventLoop, asyncio.Semaphore]:
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._loop is not loop or self._slots is None:
                # A new loop: calls still running from an old one release on that loop's
                # semaphore, so start full. The pool still has ``size`` threads, so at most
                # ``size`` more calls queue behind them.
                self._loop = loop
                self._slots = asyncio.Semaphore(self.size)
            return loop, self._slots

    async def run(self, fn: Callable[..., T], /, *args: Any) -> T:
        """Run ``fn(*args)`` on a worker (with the caller's context variables).

        Cancelling the caller (``asyncio.wait_for`` timing out) does not free the slot
        while the thread runs; a call that has not started yet is dropped.
        """
        loop, slots = self._semaphore()
        await slots.acquire()
        context = contextvars.copy_context()
        with self._lock:
            self._running += 1
        try:
            future: Future[T] = self._executor.submit(context.run, fn, *args)
        except BaseException:
            with self._lock:
                self._running -= 1
            slots.release()
            raise

        def finished(_: Future[T]) -> None:
            with self._lock:
                self._running -= 1
            # A closed loop raises RuntimeError: its semaphore is gone with it.
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(slots.release)

        future.add_done_callback(finished)
        return await asyncio.wrap_future(future, loop=loop)

    def close(self) -> None:
        """Stop accepting work; queued calls are dropped, running threads finish alone."""
        self._executor.shutdown(wait=False, cancel_futures=True)
