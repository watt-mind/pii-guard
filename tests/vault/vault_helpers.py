"""Vault test helpers. All values are fictional (ADR 0005); the key is a fixed test key."""

from __future__ import annotations

from pii_guard.types import EntityType, Span

# Fixed, obviously non-secret test keys. Never use these anywhere else.
TEST_KEY = bytes.fromhex("0f" * 32)
OTHER_TEST_KEY = bytes.fromhex("f0" * 32)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def span_of(text: str, value: str, entity_type: EntityType | str, *, nth: int = 0) -> Span:
    """The ``nth`` occurrence of ``value`` in ``text`` as a span."""
    start = -1
    for _ in range(nth + 1):
        start = text.index(value, start + 1)
    return Span(start, start + len(value), EntityType(entity_type), value, 1.0, "test")
