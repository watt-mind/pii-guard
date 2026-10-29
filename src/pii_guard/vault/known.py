"""Known values: sensitive values an application pre-loads into a vault session.

An application often already knows which values are sensitive in a conversation (the
customer record, the case file, a contact list). Pre-loading them makes the ``known``
detector (:mod:`pii_guard.detect.known`) find every occurrence, including inflected forms,
even when statistical detection would miss an unusual name or an internal id format. It is
an extra detector, never a requirement.

Known values live only on their :class:`~pii_guard.vault.VaultSession`: they expire and are
forgotten with it. Nothing here logs, reprs or raises with a value; errors name the index and
entity type of the offending item only.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from pii_guard.types import EntityType, PiiGuardError
from pii_guard.vault.fold import fold_value, fold_views
from pii_guard.vault.inflection import inflection_for
from pii_guard.vault.placeholders import normalize_value

__all__ = [
    "DEFAULT_MAX_KNOWN_VALUES",
    "DEFAULT_MAX_KNOWN_VALUE_LENGTH",
    "MIN_KNOWN_VALUE_LENGTH",
    "KnownValue",
    "KnownValueError",
    "KnownValues",
    "known_values_from",
]

#: Shorter values (after normalization) are refused: "Ann" is fine, "Al" would over-mask.
MIN_KNOWN_VALUE_LENGTH = 3
DEFAULT_MAX_KNOWN_VALUES = 1000
DEFAULT_MAX_KNOWN_VALUE_LENGTH = 256


class KnownValueError(PiiGuardError):
    """A pre-loaded value is invalid or over a limit. Never carries the value itself."""

    code = "invalid_known_value"
    status_code = 422


@dataclass(frozen=True, slots=True)
class KnownValue:
    """One pre-loaded value and its entity type. ``repr()`` omits the value."""

    value: str
    entity_type: EntityType

    def __repr__(self) -> str:
        return f"KnownValue(entity_type={self.entity_type.value}, value=<redacted>)"

    __str__ = __repr__


def known_values_from(
    items: Iterable[object], *, max_length: int = DEFAULT_MAX_KNOWN_VALUE_LENGTH
) -> list[KnownValue]:
    """Validate raw items (``KnownValue`` or ``{"value": ..., "entity_type": ...}``).

    Values are stripped; one with fewer than :data:`MIN_KNOWN_VALUE_LENGTH` non-space
    characters or longer
    than ``max_length`` (after normalization), or of an unknown or visual entity type, raises
    :class:`KnownValueError` naming its index only.
    """
    out: list[KnownValue] = []
    for index, item in enumerate(items):
        if isinstance(item, KnownValue):
            value, raw_type = item.value, item.entity_type
        elif isinstance(item, dict):
            value, raw_type = item.get("value"), item.get("entity_type")
        else:
            raise KnownValueError(f"known value {index} is not an object")
        if not isinstance(value, str):
            raise KnownValueError(f"known value {index} has no string 'value'")
        try:
            entity_type = EntityType(raw_type)
        except ValueError:
            raise KnownValueError(f"known value {index} has an unknown entity_type") from None
        label = f"known value {index} ({entity_type.value})"
        if entity_type.is_visual:
            raise KnownValueError(f"{label} is a visual entity type, not a text value")
        normalized = normalize_value(value)
        if len(normalized.replace(" ", "")) < MIN_KNOWN_VALUE_LENGTH:
            raise KnownValueError(
                f"{label} is shorter than {MIN_KNOWN_VALUE_LENGTH} characters; "
                "it would mask too much"
            )
        if len(normalized) > max_length:
            raise KnownValueError(f"{label} is longer than {max_length} characters")
        out.append(KnownValue(value.strip(), entity_type))
    return out


class KnownValues:
    """The known values of one session, deduplicated on ``(entity_type, normalized value)``.

    Thread-safe. Compiled occurrence patterns are cached per language and rebuilt when values
    are added. ``repr()`` shows the count only.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[tuple[EntityType, str], KnownValue] = {}
        self._patterns: dict[str, list[tuple[KnownValue, re.Pattern[str]]]] = {}

    def __repr__(self) -> str:
        return f"KnownValues(count={len(self._values)})"

    __str__ = __repr__

    def __len__(self) -> int:
        return len(self._values)

    def __bool__(self) -> bool:
        return bool(self._values)

    def values(self) -> list[KnownValue]:
        with self._lock:
            return list(self._values.values())

    def add(
        self, values: Sequence[KnownValue], *, max_values: int = DEFAULT_MAX_KNOWN_VALUES
    ) -> int:
        """Add ``values`` (already validated); returns how many were new.

        All or nothing: if the session would hold more than ``max_values`` values, nothing is
        added and :class:`KnownValueError` (code ``too_many_known_values``) is raised.
        """
        with self._lock:
            new: dict[tuple[EntityType, str], KnownValue] = {}
            for item in values:
                key = (item.entity_type, normalize_value(item.value))
                if key not in self._values:
                    new.setdefault(key, item)
            if len(self._values) + len(new) > max_values:
                raise KnownValueError(
                    f"a session holds at most {max_values} known values",
                    code="too_many_known_values",
                )
            if new:
                self._values.update(new)
                self._patterns.clear()
            return len(new)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
            self._patterns.clear()

    def occurrences(self, text: str, language: str) -> list[tuple[KnownValue, int, int]]:
        """``(value, start, end)`` of every occurrence in ``text``, longest value first.

        Offsets are in ``text``; matches may overlap (the caller picks). The search runs over
        :func:`~pii_guard.vault.fold.fold_views`' folded views, so another casing, Unicode
        form or ``ß``/``ss`` spelling (``WEISS`` for ``Weiß``) is found too.
        """
        patterns = self.patterns(language)
        if not patterns:
            return []
        views = fold_views(text)
        found: list[tuple[KnownValue, int, int]] = []
        for item, pattern in patterns:
            seen: set[tuple[int, int]] = set()
            for folded in views:
                for match in pattern.finditer(folded.text):
                    if match.end() > match.start():
                        span = folded.to_original(*match.span())
                        if span not in seen:
                            seen.add(span)
                            found.append((item, *span))
        return found

    def patterns(self, language: str) -> list[tuple[KnownValue, re.Pattern[str]]]:
        """``(value, pattern)`` per value, longest value first, for ``language``.

        A pattern runs over folded text (:func:`~pii_guard.vault.fold.fold_text`; use
        :meth:`occurrences` for offsets in the original) and matches an occurrence case-,
        whitespace- and Unicode-form-insensitively; with the language's inflection matcher it
        also matches changed stems (``Próba Zsuzsanná`` before ``-nak``) and allows a suffix
        after the value, which stays outside the match: the same occurrence rules the vault
        applies to values it has confirmed.
        """
        with self._lock:
            cached = self._patterns.get(language)
            if cached is None:
                from pii_guard.vault.vault import _compile, _forms  # the vault's own rules

                matcher = inflection_for(language)
                ordered = sorted(
                    self._values.values(), key=lambda v: len(normalize_value(v.value)), reverse=True
                )
                cached = [
                    (item, _compile(_forms(matcher, fold_value(item.value), item.entity_type)))
                    for item in ordered
                ]
                self._patterns[language] = cached
            return cached
