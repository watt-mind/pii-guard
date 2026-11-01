"""Session assembly, unmasking, and outbound re-check operations for VaultSession."""

from __future__ import annotations

import itertools
import logging
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

from pii_guard.vault.entry import (
    MaskResult,
    RestoreBudget,
    Unmasked,
    UnmaskResult,
    _Entry,
    _placeholder_mask,
    _restored,
    _unmasked_for_entry,
    _unmasked_known,
)
from pii_guard.vault.fold import FoldedText, fold_views
from pii_guard.vault.inflection import following_suffix
from pii_guard.vault.known import KnownValues
from pii_guard.vault.placeholders import PLACEHOLDER_RE

logger = logging.getLogger("pii_guard.vault.session")


def assemble_masked(
    text: str,
    replacements: list[tuple[int, int, _Entry]],
    spans: int,
    generation: int,
    clock: Callable[[], float],
) -> MaskResult:
    """Write the placeholders into ``text``, counting and remembering each occurrence."""
    replacements.sort(key=lambda r: r[0])
    parts: list[str] = []
    cursor = 0
    per_type: Counter[str] = Counter()
    for start, end, entry in replacements:
        parts.append(text[cursor:start])
        parts.append(entry.placeholder)
        entry.remember(following_suffix(text, end), text[start:end])
        entry.count += 1
        now = clock()
        if entry.first_seen is None:
            entry.first_seen = now
        entry.last_seen = now
        per_type[entry.entity_type.value] += 1
        cursor = end
    parts.append(text[cursor:])
    logger.debug(
        "masked %d occurrences (%d from spans): %s",
        len(replacements),
        spans,
        dict(per_type),
    )
    return MaskResult(
        "".join(parts),
        tuple((start, end, entry.placeholder) for start, end, entry in replacements),
        generation,
    )


def unmask_text_locked(
    text: str,
    by_placeholder: dict[str, _Entry],
    budget: RestoreBudget,
) -> UnmaskResult:
    """Restore every known placeholder in ``text``, charging ``budget``; caller holds the lock."""
    unresolved: dict[str, None] = {}
    restored = 0
    parts: list[str] = []
    cursor = 0
    for match in PLACEHOLDER_RE.finditer(text):
        if match.start() < cursor:  # pragma: no cover - a suffix never holds "[["
            continue
        parts.append(text[cursor : match.start()])
        cursor = match.end()
        entry = by_placeholder.get(match.group(0))
        if entry is None:
            unresolved[match.group(0)] = None
            parts.append(match.group(0))
            continue
        restored += 1
        suffix = following_suffix(text, cursor)
        value = _restored(entry, suffix)
        budget.charge(max(0, len(value) - len(suffix)))
        parts.append(value)
        cursor += len(suffix)
    parts.append(text[cursor:])
    result = "".join(parts)
    if unresolved:
        # Unknown tokens are caller/upstream content, not trusted guard-issued ids.
        logger.warning("unmask left %d unresolved placeholders", len(unresolved))
    logger.debug("unmasked %d placeholders", restored)
    return UnmaskResult(result, tuple(unresolved))


def find_unmasked_locked(
    texts: Sequence[str],
    folds: dict[str, tuple[FoldedText, ...]],
    by_key: dict[Any, _Entry],
    known: KnownValues,
    language: str,
) -> list[Unmasked]:
    """Vault values left unmasked in ``texts``, longest first; caller holds the lock."""
    views = [folds.get(text) or fold_views(text) for text in texts]
    # One string with every view: a value none of whose needles is in it can't occur
    # in any text, so most entries are skipped after one substring search each.
    joined = (FoldedText("", "\x00".join(v.text for vs in views for v in vs)),)
    taken = _placeholder_mask(texts)
    found: list[Unmasked] = []
    entries = sorted(by_key.values(), key=lambda e: (-len(e.normalized), e.order))
    candidates = itertools.chain(
        *(_unmasked_for_entry(e, texts, views, joined, language) for e in entries),
        _unmasked_known(known, views, joined[0].text, language),
    )
    for item in candidates:
        if item.end > item.start and not any(taken[item.index][item.start : item.end]):
            taken[item.index][item.start : item.end] = b"\x01" * (item.end - item.start)
            found.append(item)
    found.sort(key=lambda u: (u.index, u.start))
    return found
