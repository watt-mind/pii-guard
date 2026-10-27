"""The ``known`` detector: every occurrence of the values pre-loaded into a session.

Deterministic, score ``1.0``, detector name ``known``. Occurrences are matched with the
vault's own rules (case- and whitespace-insensitive; per language, inflected forms: Hungarian
suffixes and stem changes, the English possessive), and a span covers the value's stem only,
so ``Próba Zsuzsannának`` gives the span ``Próba Zsuzsanná`` and the vault keys it on the
lemma ``Próba Zsuzsanna``: a value that is pre-loaded *and* detected by another detector
gets one placeholder.

In the resolver (:func:`~pii_guard.detect.pipeline.resolve_spans`) ``known`` spans win every
conflict; :func:`merge_known` adds them to spans another analyzer already resolved, which is
how ``/v1/mask`` and the gateway use it whenever the session has known values.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from pii_guard.detect.pipeline import DEFAULT_KEEP_TYPES, resolve_spans
from pii_guard.types import EntityType, Span
from pii_guard.vault.known import KnownValue, KnownValues

__all__ = ["KNOWN_DETECTOR", "KnownValuesDetector", "merge_known"]

KNOWN_DETECTOR = "known"


class KnownValuesDetector:
    """Find the occurrences of ``values`` (a session's :class:`KnownValues`, or a list)."""

    name = KNOWN_DETECTOR

    def __init__(self, values: KnownValues | Iterable[KnownValue] = ()) -> None:
        if isinstance(values, KnownValues):
            self._values = values
        else:
            self._values = KnownValues()
            self._values.add(list(values), max_values=10**9)

    def __repr__(self) -> str:
        return f"KnownValuesDetector(values={len(self._values)})"

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        if not self._values:
            return []
        taken = bytearray(len(text))
        spans: list[Span] = []
        # Longest values first, so "Teszt Elek" wins over a separately loaded "Elek".
        for item, start, end in self._values.occurrences(text, language):
            if end <= start or any(taken[start:end]):
                continue
            taken[start:end] = b"\x01" * (end - start)
            spans.append(Span(start, end, item.entity_type, text[start:end], 1.0, KNOWN_DETECTOR))
        spans.sort(key=lambda s: s.start)
        return spans


def merge_known(
    text: str,
    spans: Sequence[Span],
    known: KnownValuesDetector | KnownValues,
    language: str = "hu",
    *,
    keep_types: Iterable[EntityType] = DEFAULT_KEEP_TYPES,
) -> list[Span]:
    """``spans`` (already resolved) plus the known values' spans, resolved again.

    Known spans win their conflicts; the characters of a losing span that no known span
    covers stay a span of the loser's type, except an inflectional suffix that directly
    follows a known stem (it stays outside the placeholder, as in the vault).
    """
    detector = known if isinstance(known, KnownValuesDetector) else KnownValuesDetector(known)
    found = detector.detect(text, language)
    if not found:
        return list(spans)
    return resolve_spans(
        text,
        [*found, *spans],
        detector_order=[KNOWN_DETECTOR],
        keep_types=keep_types,
    )
