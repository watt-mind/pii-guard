"""The vault inspector reads entry internals only under the session lock (LAB-1328).

An entry's variants, seen forms, surfaces, aliases and count change while a mask runs, so
:func:`~pii_guard.vault.inspect.entries_of` and :func:`~pii_guard.vault.inspect.view_of`
build their views inside :meth:`VaultSession.peek_entries` / :meth:`peek_summary`, which
hold the lock. All values are fictional (ADR 0005).
"""

from __future__ import annotations

import threading
from collections.abc import Callable

import pytest
from vault_helpers import span_of

import pii_guard.vault.inspect as inspect_module
from pii_guard.types import EntityType
from pii_guard.vault import Vault, VaultSession
from pii_guard.vault.inspect import entries_of, view_of

EMAIL = "teszt.elek@example.com"


def _mask_email(session: VaultSession, index: int) -> None:
    email = f"teszt.elek{index}@example.com"
    session.mask(f"Írj: {email}", [span_of(f"Írj: {email}", email, EntityType.EMAIL)])


def _blocked_while(session: VaultSession) -> Callable[[], bool]:
    """Start a mask on ``session`` in another thread; the result says it is still waiting."""
    done = threading.Event()

    def mask() -> None:
        _mask_email(session, 999)
        done.set()

    thread = threading.Thread(target=mask, daemon=True)
    thread.start()

    def still_blocked() -> bool:
        blocked = not done.wait(0.2)
        return blocked

    return still_blocked


def test_peek_entries_runs_the_builder_under_the_lock(vault: Vault) -> None:
    session = vault.session()
    _mask_email(session, 1)
    seen: list[bool] = []

    def build(by_key: object, known: object) -> int:
        seen.append(_blocked_while(session)())
        return 1

    assert session.peek_entries(build) == 1
    assert seen == [True]  # a concurrent mask waited for the builder to finish


def test_peek_summary_runs_the_builder_under_the_lock(vault: Vault) -> None:
    session = vault.session()
    _mask_email(session, 1)
    seen: list[bool] = []

    def build(*_: object) -> int:
        seen.append(_blocked_while(session)())
        return 1

    assert session.peek_summary(build) == 1
    assert seen == [True]


def test_entries_of_builds_views_under_the_lock(
    vault: Vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = vault.session()
    _mask_email(session, 1)
    real = inspect_module._views
    seen: list[bool] = []

    def spy(*args: object) -> object:
        still_blocked = _blocked_while(session)
        result = real(*args)  # type: ignore[arg-type]
        seen.append(still_blocked())
        return result

    monkeypatch.setattr(inspect_module, "_views", spy)
    views, _ = entries_of(session)
    assert seen == [True]
    assert [v.original for v in views] == ["teszt.elek1@example.com"]


def test_peek_returns_none_once_expired(vault: Vault) -> None:
    session = vault.session()
    session.close()
    assert session.peek_entries(lambda *_: 1) is None
    assert session.peek_summary(lambda *_: 1) is None
    assert entries_of(session) == ([], [])
    assert view_of(session) is None


def test_inspector_reads_consistently_during_concurrent_masks(vault: Vault) -> None:
    session = vault.session()
    stop = threading.Event()
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            for index in range(400):
                if stop.is_set():
                    return
                _mask_email(session, index)
                text = f"TESZT.ELEK{index}@EXAMPLE.COM és teszt.elek{index}@example.com"
                session.mask(text, [], remask=True)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        while thread.is_alive():
            views, _ = entries_of(session)
            summary = view_of(session)
            assert summary is not None
            # Each snapshot is internally consistent: no entry is half-registered.
            assert len({v.placeholder for v in views}) == len(views)
            assert all(v.count >= 1 for v in views if v.variant_of is None)
    finally:
        stop.set()
        thread.join()
    assert not errors
    views, _ = entries_of(session)
    summary = view_of(session)
    assert summary is not None
    assert summary.entries == len(views)
    assert summary.occurrences == sum(v.count for v in views)
