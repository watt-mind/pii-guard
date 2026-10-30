"""LLM detector: reported values are not kept after alignment (LAB-1353).

The alignment patterns embed the value the model reported. They used to sit in two unbounded
``functools.cache``s for the life of the process, untouched by session delete or TTL. No HTTP:
``align`` is called directly. All values are fictional.
"""

from __future__ import annotations

import gc
import re
from collections.abc import Iterator

import pytest

from pii_guard.config import Settings
from pii_guard.detect import llm
from pii_guard.detect.llm import LlmDetector, LlmEntity, clear_alignment_caches
from pii_guard.types import EntityType

N_VALUES = 1000


@pytest.fixture
def detector() -> LlmDetector:
    return LlmDetector(api_key="test-key", base_url="https://llm.test/v1", settings=Settings())


@pytest.fixture(autouse=True)
def isolated_re_cache() -> Iterator[None]:
    """LAB-1406: these tests assert on the global ``re`` cache, so run hermetic.

    A full-suite worker compiles patterns in earlier modules; the starting fill of
    ``re._cache`` then decides which of this file's value-embedding patterns survive its
    whole-cache evictions, so the live-pattern scan below saw other runs' leftovers.
    Snapshot the cache, start empty, and restore it afterwards."""
    saved = dict(re._cache)
    re._cache.clear()
    try:
        yield
    finally:
        re._cache.clear()
        re._cache.update(saved)


def _name(i: int) -> str:
    return f"Szintetikus Ember{i:04d}"


def _align_many(detector: LlmDetector) -> None:
    for i in range(N_VALUES):
        name = _name(i)
        entities = [
            LlmEntity(EntityType.PERSON, name),  # verbatim match
            LlmEntity(EntityType.PERSON, name.upper()),  # loose (case-insensitive) match
        ]
        spans = detector.align(f"Kedves {name}, üdv.", entities, "hu")
        assert [s.text for s in spans] == [name]


def _live_patterns_with(marker: str) -> list[re.Pattern[str]]:
    gc.collect()
    return [
        obj
        for obj in gc.get_objects()
        if type(obj) is re.Pattern
        and isinstance(obj.pattern, str)
        and marker.lower() in obj.pattern.lower()
    ]


def test_no_module_cache_keeps_reported_values(detector: LlmDetector) -> None:
    _align_many(detector)
    for name in ("_pattern", "_loose_pattern"):
        assert not hasattr(getattr(llm, name), "cache_info"), f"{name} is cached again"


def test_re_cache_stays_bounded_and_clear_drops_every_value(detector: LlmDetector) -> None:
    clear_alignment_caches()
    _align_many(detector)
    assert len(re._cache) <= re._MAXCACHE  # type: ignore[attr-defined]
    # Older values were evicted by the bound; the most recent ones may still be in re's cache.
    assert _live_patterns_with("Szintetikus Ember0000") == []
    clear_alignment_caches()
    assert _live_patterns_with("Szintetikus Ember") == []


def test_alignment_unchanged_after_clear(detector: LlmDetector) -> None:
    clear_alignment_caches()
    text = "Kedves Szintetikus Ember0001 és SZINTETIKUS EMBER0002."
    spans = detector.align(
        text,
        [LlmEntity(EntityType.PERSON, _name(1)), LlmEntity(EntityType.PERSON, _name(2))],
        "hu",
    )
    assert [s.text for s in spans] == [_name(1), "SZINTETIKUS EMBER0002"]
