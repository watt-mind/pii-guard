"""Rule detector: regular expressions plus validation for structured identifiers.

The first, deterministic detection layer (``docs/architecture.md`` → detect/Rules). Every rule
finds candidates with a regular expression and keeps only those that pass validation
(checksums, known prefixes and area codes, address context), so precision is high and the
output is fully reproducible.

Rules are organised by language pack (ADR 0008, ADR 0010):

- :mod:`.common`: language-independent rules (IBAN, email, international phone numbers,
  payment cards), run for every text;
- each language pack (:mod:`pii_guard.languages`, e.g. ``languages/hu/rules.py``) contributes
  ``everywhere`` rules (identifiers with a checksum or a distinctive validated format, run for
  every language: a Hungarian tax ID in an English e-mail is still personal data) and
  ``rules`` (formats that are only unambiguous in that language's texts, such as postcodes,
  plates and national phone formats, run only when ``language`` matches).

A language without a pack gets the language-independent rules and every pack's
``everywhere`` rules. Add a language with a :class:`~pii_guard.languages.LanguagePack`
(``docs/languages.md``); :func:`register_rule_pack` still overrides the rules of one language.
``pii_guard.detect.rules.hu`` and ``.en`` are aliases of the packs' rule modules, kept for one
release.

Look-alikes are rejected on purpose: wrong check digits, digits that are part of a longer
digit run (``12345678901`` contains no 10-digit tax ID), and dates.

The one exception is a number right after a strong cue word (``TAJ``, ``passport``,
``telefon``): every pack's ``cues.tsv`` lists them, and :mod:`pii_guard.languages.cues` masks
such a number as the cued type even when its checksum fails, at a lower score, unless a
validated rule already covers it (``PII_GUARD_RULES_CUED_NUMBERS``, default on).
"""

from __future__ import annotations

import threading
from bisect import bisect_left
from dataclasses import dataclass

from pii_guard.detect.rules import common
from pii_guard.detect.rules._base import Rule, _Hit
from pii_guard.languages import packs, primary_language
from pii_guard.languages.cues import Cue, CueMatcher, load_cues, matcher_for
from pii_guard.types import DetectionError, Span

__all__ = [
    "DETECTOR_CLASS",
    "Rule",
    "RuleDetector",
    "RulePack",
    "primary_language",
    "register_rule_pack",
    "rule_packs",
]


@dataclass(frozen=True, slots=True)
class RulePack:
    """The rules one language contributes.

    - ``language``: ISO 639-1 code (``"hu"``, ``"en"``).
    - ``everywhere``: validated identifiers of that country, run for every language.
    - ``rules``: run only when the analysed text is in ``language``.
    """

    language: str
    everywhere: tuple[Rule, ...] = ()
    rules: tuple[Rule, ...] = ()


#: Packs registered with :func:`register_rule_pack`; they replace a language pack's rules.
_PACKS: dict[str, RulePack] = {}


def register_rule_pack(pack: RulePack) -> None:
    """Use ``pack`` for ``pack.language``, replacing any existing one.

    Takes effect for :class:`RuleDetector` instances created afterwards.
    """
    _PACKS[primary_language(pack.language)] = pack


def rule_packs() -> dict[str, RulePack]:
    """The rules of every language pack by language, with :func:`register_rule_pack`
    overrides applied (a copy)."""
    found = {
        code: RulePack(code, everywhere=pack.everywhere, rules=pack.rules)
        for code, pack in packs().items()
    }
    return {**found, **_PACKS}


def _drop_contained(hits: list[_Hit]) -> list[_Hit]:
    """Remove hits that lie entirely inside another hit (e.g. digits inside an IBAN).

    Partial overlaps are kept: the resolver decides those. One sweep in start order: every
    kept hit starts at or before the current one, so the current one lies inside a kept hit
    exactly when the kept hits reach (end) at least as far.
    """
    ordered = sorted(set(hits), key=lambda h: (h.start, -(h.end - h.start), -h.score))
    kept: list[_Hit] = []
    reach = -1
    for hit in ordered:
        if hit.end <= reach:
            continue
        kept.append(hit)
        reach = hit.end
    return kept


def _outside_hits(hits: list[_Hit], others: list[_Hit]) -> list[_Hit]:
    """The ``others`` that overlap none of ``hits``, in their order.

    ``hits`` are sorted by start with the running maximum of their ends: a hit starting before
    ``o.end`` overlaps ``o`` exactly when the furthest such end lies after ``o.start``.
    """
    if not hits:
        return list(others)
    ordered = sorted(hits, key=lambda h: h.start)
    starts = [h.start for h in ordered]
    reach: list[int] = []
    furthest = -1
    for h in ordered:
        furthest = max(furthest, h.end)
        reach.append(furthest)
    out: list[_Hit] = []
    for o in others:
        i = bisect_left(starts, o.end)
        if i == 0 or reach[i - 1] <= o.start:
            out.append(o)
    return out


class RuleDetector:
    """Deterministic, checksum-validated detector for structured identifiers.

    Stateless and safe to share between threads. Any unexpected error is raised as
    :class:`DetectionError` without the input text (ADR 0006: fail closed).
    """

    name = "rules"

    def __init__(self, *, cued_numbers: bool | None = None) -> None:
        packs = rule_packs()
        #: Run for every language: language-independent rules + every pack's ``everywhere``.
        self._rules: tuple[Rule, ...] = common.RULES + tuple(
            rule for pack in packs.values() for rule in pack.everywhere
        )
        #: Run only for their language.
        self._language_rules: dict[str, tuple[Rule, ...]] = {
            code: pack.rules for code, pack in packs.items()
        }
        if cued_numbers is None:
            from pii_guard.config import get_settings

            cued_numbers = get_settings().rules_cued_numbers
        #: Every pack's cue words (``cues.tsv``), or empty when cued numbers are off.
        self.cued_numbers = cued_numbers
        self._cues: tuple[tuple[str, tuple[Cue, ...]], ...] = _pack_cues() if cued_numbers else ()
        self._matchers: dict[str, CueMatcher] = {}
        self._lock = threading.Lock()

    def rules_for(self, language: str) -> tuple[Rule, ...]:
        """Every rule that runs for a text in ``language``."""
        return self._rules + self._language_rules.get(primary_language(language), ())

    def cue_matcher(self, language: str) -> CueMatcher | None:
        """The cued-number matcher for a text in ``language`` (its own cues win conflicts)."""
        if not self._cues:
            return None
        code = primary_language(language)
        with self._lock:
            matcher = self._matchers.get(code)
            if matcher is None:
                matcher = self._matchers[code] = matcher_for(code, self._cues)
        return matcher

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        if not isinstance(text, str):
            raise DetectionError(f"rules detector expects str, got {type(text).__name__}")
        try:
            hits = [hit for rule in self.rules_for(language) for hit in rule(text)]
            matcher = self.cue_matcher(language)
            if matcher is not None:
                # A validated hit keeps its span: cued values only fill the gaps.
                hits += _outside_hits(hits, list(matcher.find(text)))
            return [
                Span(h.start, h.end, h.entity_type, text[h.start : h.end], h.score, self.name)
                for h in _drop_contained(hits)
            ]
        except Exception as exc:
            raise DetectionError("rules detector failed") from exc


def _pack_cues() -> tuple[tuple[str, tuple[Cue, ...]], ...]:
    """``(code, cues)`` for every pack with a ``cues.tsv``, in pack order."""
    return tuple((code, load_cues(pack.cues, code)) for code, pack in packs().items() if pack.cues)


DETECTOR_CLASS = RuleDetector
