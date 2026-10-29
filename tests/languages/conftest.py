"""Shared helpers for the language-pack tests. All values are fictional (ADR 0005)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from pii_guard.types import EntityType, Span
from pii_guard.vault import Vault

LeakCheck = Callable[[str, str, str, str], None]


def assert_masked_and_restored(code: str, value: str, form: str, text: str) -> None:
    """``text`` starts with ``value:``; masking that span must also mask ``form`` later on,
    leave the value nowhere in the masked text, and unmask back to ``text``."""
    session = Vault(b"conformance-test-key").session()
    spans = [Span(0, len(value), EntityType.PERSON, value, 1.0, "test")]
    masked = session.mask(text, spans, language=code)
    rest = masked.split(":", 1)[1]
    assert form.casefold() not in rest.casefold(), "an inflected occurrence was left unmasked"
    assert value.casefold() not in masked.casefold(), "the value survives in the masked text"
    assert session.unmask(masked) == text


@pytest.fixture
def leak_check() -> LeakCheck:
    return assert_masked_and_restored
