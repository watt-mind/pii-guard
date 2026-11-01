"""Vault entry model, occurrence patterns, inflection planning and span validation.

Nothing in this module logs, reprs or raises with an original value: logs and errors carry
entity types, counts and placeholder ids only (AGENTS.md, ADR 0006).
"""

from __future__ import annotations

import bisect
import itertools
import re
import unicodedata
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

from pii_guard.detect.ner_context import sweep_vetoed
from pii_guard.detect.normalize import INVISIBLE_CHARS, normalize_for_detection
from pii_guard.types import EntityType, MaskingError, PiiGuardError, Span
from pii_guard.vault.fold import FoldedText, dropped, fold_value, spaced
from pii_guard.vault.inflection import (
    InflectionMatcher,
    Split,
    following_suffix,
    inflection_for,
    restore,
    splits,
    variant_stems,
)
from pii_guard.vault.known import KnownValues
from pii_guard.vault.placeholders import PLACEHOLDER_RE, casing_class, normalize_value

__all__ = [
    "CASE_SENSITIVE_TYPES",
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_MAX_RESTORED_CHARS",
    "IDENTIFIER_TYPES",
    "MODEL_DETECTORS",
    "NEUTRAL_DETECTORS",
    "_CASE_AMBIGUOUS",
    "_MIN_ALIAS_LETTERS",
    "_PREFILTER",
    "MaskResult",
    "PlaceholderInInputError",
    "RestoreBudget",
    "SessionEntryLimitError",
    "SessionNotFoundError",
    "UnmaskOutputTooLargeError",
    "UnmaskResult",
    "Unmasked",
    "_Entry",
    "_Masked",
    "_Needles",
    "_Plan",
    "_absent",
    "_body",
    "_compile",
    "_edge_after_placeholder",
    "_exact",
    "_folded_index",
    "_forms",
    "_initial",
    "_is_mark",
    "_is_word_char",
    "_layout",
    "_letters",
    "_literal_forms",
    "_needles",
    "_occurrence",
    "_occurrences",
    "_occurs_alone",
    "_placeholder_mask",
    "_recased",
    "_relaid",
    "_restored",
    "_unmasked_for_entry",
    "_unmasked_known",
    "_validated",
    "_value_key",
    "_value_shape",
    "plan_spans",
]


class PlaceholderInInputError(MaskingError):
    """The text to mask already holds a placeholder this session issued (422).

    Restoring it later would put a value into text the caller never masked. The message
    names a count only, never the token or any value.
    """

    code = "placeholder_in_input"
    status_code = 422


class SessionEntryLimitError(MaskingError):
    """An explicit session holds ``max_entries`` placeholders (409, LAB-1565).

    Nobody can rotate an explicit session for the client, so it fails closed; the client
    recovers by starting a new session.
    """

    code = "session_entry_limit_reached"
    status_code = 409


class SessionNotFoundError(PiiGuardError):
    """The vault session is unknown, expired or closed; its mapping is gone."""

    code = "not_found"
    status_code = 404


class UnmaskOutputTooLargeError(PiiGuardError):
    """Restoring the placeholders would put more than the limit of original characters out (413).

    Fail closed (LAB-1350): nothing is returned, and the output is never built past the limit.
    The message names the limit only.
    """

    code = "unmask_output_too_large"
    status_code = 413


#: Most placeholders a get-or-create session (:meth:`Vault.session_or_create`) collects before
#: its id moves on to a new, empty generation (LAB-1286).
DEFAULT_MAX_ENTRIES = 10_000
#: Most characters of original values one unmask call, or one gateway response, restores: five
#: times the 200,000-character text limit (LAB-1350). A placeholder of a long value repeated in
#: a short text would otherwise expand without bound.
DEFAULT_MAX_RESTORED_CHARS = 1_000_000

#: Entity types keyed and matched by their exact value (LAB-1350). Letter case is part of a
#: credential: ``AbC1`` and ``aBc1`` are two secrets, with two placeholders, and an occurrence in
#: another case is not the confirmed value. Every other type is case-insensitive: names and
#: other natural-language values (and their inflection), and IBANs, plates, ID numbers and
#: e-mail addresses, which are case-insensitive by their own rules.
CASE_SENSITIVE_TYPES: frozenset[EntityType] = frozenset({EntityType.SECRET})

#: Number-like identifier types a detector can confuse with each other: the same digits read
#: as a Steuer-ID (``ID_DOCUMENT``) in a Markdown list and as an adóazonosító jel
#: (``NATIONAL_ID_HU_TAX``) in a JSON ``tax_id`` field. A value one of them already holds
#: keeps that placeholder when another type finds it again, so one value is one placeholder
#: per session (LAB-1475: two placeholders for one value sent agents into a "fix the copy"
#: loop). Names, addresses and e-mails keep their own keys.
IDENTIFIER_TYPES: frozenset[EntityType] = frozenset(
    {
        EntityType.PHONE,
        EntityType.DATE_OF_BIRTH,
        EntityType.NATIONAL_ID_HU_TAX,
        EntityType.NATIONAL_ID_HU_TAJ,
        EntityType.ID_DOCUMENT,
        EntityType.BANK_ACCOUNT,
        EntityType.COMPANY_ID_HU,
        EntityType.PARCEL_NUMBER_HU,
        EntityType.VEHICLE_PLATE,
    }
)

#: Learned detectors whose values the sweep checks against the text's structure first
#: (:func:`pii_guard.detect.ner_context.sweep_vetoed`, LAB-1470).
MODEL_DETECTORS: frozenset[str] = frozenset({"ner", "ner_gliner"})
#: Spans that only repeat a value the session already holds (the gateway's restored answer,
#: ``gateway.restore.RESTORED_DETECTOR``): they leave an entry's provenance as it is.
NEUTRAL_DETECTORS: frozenset[str] = frozenset({"gateway"})


class RestoreBudget:
    """The characters of original values one output may still restore (LAB-1350).

    One budget covers one ``/v1/unmask`` text or one gateway response: every choice, field and
    tool-call argument of it, streamed or not. :meth:`VaultSession.unmask_with_report` charges
    each restored value before it writes it; going over raises
    :class:`UnmaskOutputTooLargeError`. Not thread-safe: one response is restored in order.
    """

    __slots__ = ("limit", "spent")

    def __init__(self, limit: int) -> None:
        if limit < 0:
            raise ValueError("the restore limit must not be negative")
        self.limit = limit
        self.spent = 0

    def __repr__(self) -> str:
        return f"RestoreBudget(spent={self.spent}, limit={self.limit})"

    def charge(self, chars: int) -> None:
        """Spend ``chars``; raises :class:`UnmaskOutputTooLargeError` past the limit."""
        if self.spent + chars > self.limit:
            raise UnmaskOutputTooLargeError(
                f"restoring the placeholders would output more than {self.limit} characters "
                "of original values (PII_GUARD_UNMASK_MAX_RESTORED_CHARS)"
            )
        self.spent += chars


@dataclass(frozen=True, slots=True)
class UnmaskResult:
    """Re-identified text plus the placeholder-shaped tokens that could not be resolved.

    ``unresolved`` lists unknown placeholders (invented or mangled by the model) once each,
    in order of first appearance; they are left in ``text`` as is. ``repr()`` omits ``text``
    because it holds original values.
    """

    text: str
    unresolved: tuple[str, ...]

    def __repr__(self) -> str:
        return f"UnmaskResult(text=<redacted>, unresolved={list(self.unresolved)!r})"

    __str__ = __repr__


@dataclass(frozen=True, slots=True)
class MaskResult:
    """Masked text plus where each placeholder went, in offsets of the *input* text.

    ``replacements`` holds ``(start, end, placeholder)`` sorted by ``start``; ``text[start:end]``
    of the input is what the placeholder replaced (the stem, without a detached suffix).
    ``repr()`` omits ``text``.
    """

    text: str
    replacements: tuple[tuple[int, int, str], ...]
    #: The session's entry generation (:attr:`VaultSession.generation`) every entry up to which
    #: this text was scanned with: pass it as ``since`` to a later remask of the output.
    generation: int = 0

    def __repr__(self) -> str:
        return f"MaskResult(text=<redacted>, replacements={len(self.replacements)})"

    __str__ = __repr__


@dataclass(frozen=True, slots=True)
class Unmasked:
    """One occurrence of a session value still written out (:meth:`VaultSession.unmasked`).

    ``index`` is the text it is in, ``start``/``end`` its offsets there. ``chars`` counts the
    letters and digits of the value, ``digits_only`` says it has no letter; ``model_only``:
    only a learned model (the NER) has found the value; ``known``: the operator pre-loaded it.
    Never the value itself.
    """

    index: int
    start: int
    end: int
    entity_type: EntityType
    chars: int
    digits_only: bool
    model_only: bool = False
    known: bool = False


class _Entry:
    """One confirmed value, keyed on its lemma. Never repr'd with its value.

    ``original`` is the lemma as first written (``Próba Zsuzsanna``). ``surfaces`` are other
    detected forms that were split onto this lemma (``Próba Zsuzsannának``): they stay
    occurrence patterns, so a split never masks less than the unsplit value did. ``seen`` maps
    the suffix that followed an occurrence, exactly as written, to the stem as it was written
    there, so unmask restores the input exactly (``nek`` -> ``Teszt Elek``, ``NEK`` -> ``TESZT
    ELEK``); ``seen_folded`` is the same keyed on the case-folded suffix, for a suffix the
    model wrote in another casing. ``aliases`` are unconfirmed lemmas of an unsplit span
    (``Minta Kendét`` may be ``Minta Kende`` + ``t``): their forms are masked too, because a
    missed form would leak, with an entry of their own (created on the first match), so
    ``Minta Kende`` is restored as ``Minta Kende`` and not as ``Minta Kendét``.

    ``variants`` holds one entry per other *form* an occurrence was written in: another casing
    class (``TESZT ELEK`` for ``Teszt Elek``, case-sensitive placeholders only) or another
    layout (a line break or tab inside the value, decomposed accents). Each has its own
    placeholder, ``original`` and ``seen``, and shares this entry's patterns, which only it
    holds.
    """

    __slots__ = (
        "alias_patterns",
        "aliases",
        "casing",
        "changed",
        "count",
        "detector",
        "entity_type",
        "exact",
        "first_seen",
        "initials",
        "language",
        "last_seen",
        "model_only",
        "needles",
        "normalized",
        "order",
        "original",
        "patterns",
        "placeholder",
        "seen",
        "seen_folded",
        "surfaces",
        "variants",
    )

    def __init__(
        self,
        placeholder: str,
        entity_type: EntityType,
        original: str,
        normalized: str,
        language: str,
    ) -> None:
        self.placeholder = placeholder
        self.entity_type = entity_type
        self.original = original
        self.normalized = normalized
        self.language = language
        self.count = 0
        # The detector of the first span that created the entry (LAB-1332): provenance for
        # the vault inspector. Never overwritten; a neutral re-mask (``gateway``) leaves it.
        self.detector: str | None = None
        # Vault-clock times of the first and latest masked occurrence (LAB-1332). ``None``
        # until the entry's first occurrence is assembled.
        self.first_seen: float | None = None
        self.last_seen: float | None = None
        # The session generation at which this entry was created or its patterns last
        # changed (a new surface or alias): see :attr:`VaultSession.generation`.
        self.changed = 0
        # Position in the session's entries (insertion order), the tie-break of a scan.
        self.order = 0
        self.patterns: dict[str, re.Pattern[str]] = {}
        # Per language, the literal prefilter of :meth:`pattern` (see :func:`_needles`).
        self.needles: dict[str, tuple[str, ...] | None] = {}
        self.alias_patterns: dict[str, list[tuple[str, re.Pattern[str], _Needles]]] = {}
        # Per language, the folded first characters a match of any pattern can start with.
        self.initials: dict[str, frozenset[str]] = {}
        self.surfaces: dict[str, None] = {}
        self.aliases: dict[str, None] = {}
        self.seen: dict[str, str] = {}
        self.seen_folded: dict[str, str] = {}
        self.casing = casing_class(original)
        self.variants: dict[str, _Entry] = {}
        # Only a learned model (the NER) has found this value so far: the sweep then leaves
        # occurrences that the structure of the text rules out (a file extension, a path
        # segment, a code identifier, a tool name; LAB-1470) alone. Any other detector's span
        # (rules, the LLM, a known value) clears it for good.
        self.model_only = False
        # Case-sensitive types only (:data:`CASE_SENSITIVE_TYPES`): the exact keys
        # (:func:`_exact`) an occurrence of this value or of a surface may be written as.
        self.exact: frozenset[str] | None = None

    def __repr__(self) -> str:
        return f"_Entry(placeholder={self.placeholder!r}, value=<redacted>, count={self.count})"

    def add_surface(self, surface: str) -> bool:
        """Split ``surface`` onto this entry; ``True`` if that changed its pattern."""
        if surface != self.original and surface not in self.surfaces:
            self.surfaces[surface] = None
            self.exact = None
            self.patterns.clear()
            self.needles.clear()
            self.initials.clear()
            return True
        return False

    def add_alias(self, lemma: str) -> bool:
        """Add an unconfirmed lemma; ``True`` if that changed the alias patterns."""
        if lemma != self.original and lemma not in self.aliases:
            self.aliases[lemma] = None
            self.alias_patterns.clear()
            self.initials.clear()
            return True
        return False

    def written_as(self, written: str, alias: str | None = None) -> bool:
        """Whether an occurrence written as ``written`` is this value (or ``alias``).

        Always for a case-insensitive type: its patterns decide. A case-sensitive type's
        patterns match every casing, so the occurrence must also be the value, a surface or
        the alias exactly, up to whitespace, invisible characters and Unicode form
        (:func:`_exact`). Its type has no changed stems (only names, addresses and
        organisations do), so the whole occurrence is one of those.
        """
        if self.entity_type not in CASE_SENSITIVE_TYPES:
            return True
        if alias is not None:
            allowed = frozenset({_exact(alias)})
        else:
            if self.exact is None:
                self.exact = frozenset(_exact(v) for v in (self.original, *self.surfaces))
            allowed = self.exact
        return any(
            _exact(reading) in allowed for reading in (written, spaced(written), dropped(written))
        )

    def remember(self, suffix: str, stem: str) -> None:
        if suffix:
            self.seen.setdefault(suffix, stem)
            self.seen_folded.setdefault(suffix.casefold(), stem)

    def pattern(self, language: str) -> re.Pattern[str]:
        """Pattern for further occurrences of the value, over :func:`fold_views`' folded text.

        Case-, whitespace- and Unicode-form-insensitive (``WEISS`` for ``Weiß``, NFD for NFC).
        A match covers the stem only; an allowed suffix is checked by lookahead and stays
        outside. Alternatives: the lemma, its changed stems (``Zsuzsanná`` before ``-nak``,
        ``Kováccs`` before ``-al``) and the detected surface forms split onto it.
        """
        pattern = self.patterns.get(language)
        if pattern is None:
            matcher = inflection_for(language)
            forms = _literal_forms(matcher, fold_value(self.original), self.entity_type)
            forms += [
                (_occurrence(matcher, folded, self.entity_type), folded)
                for folded in map(fold_value, self.surfaces)
            ]
            pattern = _compile([alternative for alternative, _ in forms])
            self.patterns[language] = pattern
            self.needles[language] = _needles(literal for _, literal in forms)
        return pattern

    def prefilter(self, language: str) -> _Needles:
        """The literal prefilter of :meth:`pattern` (call that first): see :func:`_needles`."""
        return self.needles.get(language)

    def initial_chars(self, language: str) -> frozenset[str]:
        """The folded characters a match of :meth:`pattern` or an alias pattern starts with.

        Each alternative starts with its literal's first character (``i`` standing for both
        case-ambiguous ones, see :func:`_initial`).
        """
        cached = self.initials.get(language)
        if cached is None:
            matcher = inflection_for(language)
            values = [self.original, *self.surfaces, *self.aliases]
            cached = frozenset(
                _initial(literal)
                for value in values
                for _, literal in _literal_forms(matcher, fold_value(value), self.entity_type)
                if literal
            )
            self.initials[language] = cached
        return cached

    def alias_pattern_list(self, language: str) -> list[tuple[str, re.Pattern[str], _Needles]]:
        """``(alias, pattern of its forms, its prefilter)`` per alias, like :meth:`pattern`."""
        cached = self.alias_patterns.get(language)
        if cached is None:
            matcher = inflection_for(language)
            cached = []
            for alias in self.aliases:
                forms = _literal_forms(matcher, fold_value(alias), self.entity_type)
                pattern = _compile([alternative for alternative, _ in forms])
                cached.append((alias, pattern, _needles(literal for _, literal in forms)))
            self.alias_patterns[language] = cached
        return cached

    def matches_at(self, language: str, folded_text: str, index: int) -> bool:
        """Whether :meth:`pattern` or any alias pattern matches ``folded_text`` at ``index``."""
        if self.pattern(language).match(folded_text, index):
            return True
        return any(
            alias_pattern.match(folded_text, index)
            for _, alias_pattern, _ in self.alias_pattern_list(language)
        )

    def find_occurrences(
        self, language: str, folded: tuple[FoldedText, ...], text: str
    ) -> tuple[_Entry, list[tuple[int, int]], list[tuple[str, list[tuple[int, int]]]]]:
        """This entry's occurrences in ``folded``, and each alias's: ``(self, own, aliases)``.

        ``text`` is the original the views fold: a case-sensitive entry keeps only the
        occurrences written as its value (:meth:`written_as`).
        """
        pattern = self.pattern(language)
        # Skipping a scan that can find nothing changes no output, only its cost: each
        # request re-masks the whole history against every value of the session (LAB-1277).
        own = [] if _absent(self.prefilter(language), folded) else _occurrences(pattern, folded)
        aliases = [
            (alias, _occurrences(alias_pattern, folded))
            for alias, alias_pattern, needles in self.alias_pattern_list(language)
            if not _absent(needles, folded)
        ]
        if self.entity_type in CASE_SENSITIVE_TYPES:
            own = [(a, b) for a, b in own if self.written_as(text[a:b])]
            aliases = [
                (alias, [(a, b) for a, b in spans if self.written_as(text[a:b], alias)])
                for alias, spans in aliases
            ]
        return self, own, aliases


@dataclass(frozen=True, slots=True)
class _Masked:
    """A text's last :meth:`VaultSession.mask` from spans, kept for the next request (LAB-1315).

    ``replacements`` are ``(start, end, entry)`` sorted by ``start``, as of ``generation``:
    every entry up to it scanned the text. ``depends`` are the lemma keys a weak split looked
    up and the session did not have: once one exists, the plans may come out differently.
    """

    replacements: tuple[tuple[int, int, _Entry], ...]
    generation: int
    depends: frozenset[tuple[EntityType, str]]
    spans: int


#: Literal substrings, one of which every match of a pattern contains; ``None``: no filter.
_Needles = tuple[str, ...] | None

#: Characters ``re.IGNORECASE`` matches to another case-folded character: dotted and dotless
#: ``i`` (``re._casefix``). Every other case-folded character matches only itself there, so
#: a needle is cut at these (``test_needle_alphabet_is_closed_under_ignorecase``).
_CASE_AMBIGUOUS = re.compile("[i\u0131]")

#: Off only in tests, to check the prefilter changes no output.
_PREFILTER = True


def _needles(literals: Iterable[str]) -> _Needles:
    """The prefilter of a pattern compiled from the folded ``literals``, one per alternative.

    An alternative is its literal's whitespace-separated tokens joined by ``\\s+`` (lookarounds
    aside; an inflectional suffix is a lookahead and never part of the match), so every token,
    and every substring of one, is in any text it matches. The needle of an alternative is
    its longest such substring free of :data:`_CASE_AMBIGUOUS`: it is case-folded and the text
    searched is too, so ``needle in view.text`` holds wherever the alternative matches. A text
    holding none of the needles has no match and need not be scanned. ``None`` (always scan)
    if an alternative has no such substring.
    """
    found: dict[str, None] = {}
    for literal in literals:
        pieces = [p for token in literal.split() for p in _CASE_AMBIGUOUS.split(token)]
        needle = max(pieces, key=len, default="")
        if not needle:
            return None
        found[needle] = None
    return tuple(found)


def _initial(literal: str) -> str:
    """The index key of ``literal``'s first character: ``i`` for either case-ambiguous one."""
    char = literal[0]
    return "i" if _CASE_AMBIGUOUS.match(char) else char


def _absent(needles: _Needles, views: tuple[FoldedText, ...]) -> bool:
    """No needle is in any view, so the pattern they filter cannot match there."""
    if needles is None or not _PREFILTER:
        return False
    return not any(needle in view.text for view in views for needle in needles)


def _compile(alternatives: list[str]) -> re.Pattern[str]:
    # The text is case-folded already; IGNORECASE covers a custom matcher's upper-case suffix.
    return re.compile("|".join(f"(?:{a})" for a in alternatives), re.IGNORECASE)


def _body(value: str) -> str:
    return r"\s+".join(re.escape(token) for token in value.split())


def _forms(matcher: InflectionMatcher, value: str, entity_type: EntityType) -> list[str]:
    """``value`` with its allowed suffixes, then its changed stems before theirs.

    ``value`` is folded (:func:`~pii_guard.vault.fold.fold_value`) and the patterns run over
    folded text.
    """
    return [alternative for alternative, _ in _literal_forms(matcher, value, entity_type)]


def _literal_forms(
    matcher: InflectionMatcher, value: str, entity_type: EntityType
) -> list[tuple[str, str]]:
    """:func:`_forms` as ``(pattern, literal)``: the pattern matches the literal's tokens."""
    forms = [(_occurrence(matcher, value, entity_type), value)]
    for stem, suffix in variant_stems(matcher, value, entity_type):
        left = r"(?<!\w)" if _is_word_char(stem[0]) else ""
        forms.append((f"{left}{_body(stem)}(?=(?:{suffix})(?!\\w))", stem))
    return forms


def _occurrence(matcher: InflectionMatcher, value: str, entity_type: EntityType) -> str:
    """``value`` between word boundaries, optionally followed by an allowed suffix."""
    left = r"(?<!\w)" if _is_word_char(value[0]) else ""
    right = ""
    if _is_word_char(value[-1]):
        suffix = matcher.suffix_pattern(value, entity_type)
        right = f"(?=(?:{suffix})?(?!\\w))" if suffix else r"(?!\w)"
    return left + _body(value) + right


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char == "_"


@dataclass(slots=True)
class _Plan:
    """How one detected span is masked: the lemma it is keyed on and the stem it covers."""

    span: Span
    lemma: str
    stem_length: int
    aliases: tuple[str, ...] = ()


def _plan_in_word(
    text: str,
    span: Span,
    matcher: InflectionMatcher,
    confirmed: set[tuple[EntityType, str]],
    next_start: int,
) -> _Plan | None:
    """Plan a span that ends inside a word (``Teszt Elek|nek``), or ``None`` if whole-word."""
    value, end = span.text, span.end
    if not (_is_word_char(value[-1]) and end < len(text) and _is_word_char(text[end])):
        return None
    run = following_suffix(text, end)
    candidates = splits(matcher, value + run, span.entity_type) if run else []
    # A subword NER span may stop one consonant short of a doubled-consonant lemma at a
    # simplified triple-consonant boundary (Erika Musterman|nak for Erika Mustermann + -nak);
    # widen the stem when the longer lemma is confirmed or occurs standalone in the text.
    wider = next(
        (
            c
            for c in candidates
            if len(value) < len(c.stem) <= next_start - span.start
            and (
                (span.entity_type, _value_key(span.entity_type, c.lemma)) in confirmed
                or _occurs_alone(text, c.lemma, span)
            )
        ),
        None,
    )
    if wider is not None:
        widened = Span(
            start=span.start,
            end=span.start + len(wider.stem),
            entity_type=span.entity_type,
            text=wider.stem,
            score=span.score,
            detector=span.detector,
        )
        return _Plan(widened, wider.lemma, len(wider.stem))
    agree = next((c for c in candidates if c.stem == value), None)
    lemma = agree.lemma if agree is not None else value
    return _Plan(span, lemma, len(value))


def _resolve_weak_plan(
    text: str,
    span: Span,
    index: int,
    candidates: list[Split],
    confirmed: set[tuple[EntityType, str]],
    votes: dict[tuple[EntityType, str], set[str]],
    candidate_of: dict[tuple[EntityType, str], set[int]],
) -> _Plan:
    """Resolve a pending weak-split span once all spans' confirmed lemmas and votes are known."""
    own = (span.entity_type, _value_key(span.entity_type, span.text))
    if candidate_of.get(own, set()) - {index}:
        # Another span reads as an inflected form of this one: it is a lemma itself.
        return _Plan(span, span.text, span.length)
    # A confirmed lemma beats one that only two surfaces agree on.
    choice = next(
        (
            c
            for c in candidates
            if (span.entity_type, _value_key(span.entity_type, c.lemma)) in confirmed
            or _occurs_alone(text, c.lemma, span)
        ),
        None,
    ) or next(
        (
            c
            for c in candidates
            if len(votes.get((span.entity_type, _value_key(span.entity_type, c.lemma)), ())) >= 2
        ),
        None,
    )
    if choice is not None:
        return _Plan(span, choice.lemma, len(choice.stem))
    aliases = tuple(
        dict.fromkeys(c.lemma for c in candidates if _letters(c.lemma) >= _MIN_ALIAS_LETTERS)
    )
    return _Plan(span, span.text, span.length, aliases)


def plan_spans(
    text: str,
    ordered: Sequence[Span],
    matcher: InflectionMatcher,
    confirmed_keys: Iterable[tuple[EntityType, str]],
    depends: set[tuple[EntityType, str]] | None = None,
) -> list[_Plan]:
    """The lemma and stem of every span (see :class:`~pii_guard.vault.inflection.Split`)."""
    plans: list[_Plan | None] = []
    pending: dict[int, list[Split]] = {}
    confirmed = set(confirmed_keys)
    # Lemma -> the distinct surface forms that can be read as it ("Eleknek", "Eleket").
    votes: dict[tuple[EntityType, str], set[str]] = {}
    for index, span in enumerate(ordered):
        next_start = ordered[index + 1].start if index + 1 < len(ordered) else len(text)
        in_word = _plan_in_word(text, span, matcher, confirmed, next_start)
        if in_word is not None:
            plans.append(in_word)
            confirmed.add((span.entity_type, _value_key(span.entity_type, in_word.lemma)))
            continue
        value = span.text
        candidates = splits(matcher, value, span.entity_type)
        strong = next((c for c in candidates if c.strong), None)
        if strong is not None:
            plans.append(_Plan(span, strong.lemma, len(strong.stem)))
            confirmed.add((span.entity_type, _value_key(span.entity_type, strong.lemma)))
        elif candidates:
            plans.append(None)
            pending[index] = candidates
            for lemma in {_value_key(span.entity_type, c.lemma) for c in candidates}:
                votes.setdefault((span.entity_type, lemma), set()).add(
                    _value_key(span.entity_type, value)
                )
        else:
            plans.append(_Plan(span, value, len(value)))
        # A span's own value is a confirmed lemma for the others ("Zoltán" for "Zoltánt").
        confirmed.add((span.entity_type, _value_key(span.entity_type, value)))
    # Lemmas other spans may be inflected forms of ("Varga Bernadett" for "...Bernadettel").
    candidate_of: dict[tuple[EntityType, str], set[int]] = {}
    for index, candidates in pending.items():
        kind = ordered[index].entity_type
        for c in candidates:
            key = (kind, _value_key(kind, c.lemma))
            candidate_of.setdefault(key, set()).add(index)
            if depends is not None and key not in confirmed:
                depends.add(key)
    for index, candidates in pending.items():
        plans[index] = _resolve_weak_plan(
            text, ordered[index], index, candidates, confirmed, votes, candidate_of
        )
    return [plan for plan in plans if plan is not None]


def _placeholder_mask(texts: Sequence[str]) -> list[bytearray]:
    """Per-text byte mask marking issued or foreign placeholder tokens."""
    taken = [bytearray(len(text)) for text in texts]
    for index, text in enumerate(texts):
        for match in PLACEHOLDER_RE.finditer(text):
            taken[index][match.start() : match.end()] = b"\x01" * (match.end() - match.start())
    return taken


def _unmasked_for_entry(
    entry: _Entry,
    texts: Sequence[str],
    views: Sequence[tuple[FoldedText, ...]],
    joined: tuple[FoldedText, ...],
    language: str,
) -> Iterator[Unmasked]:
    """Yield every unmasked occurrence of ``entry`` across ``texts``."""
    entry.pattern(language)  # compiles the pattern and its prefilter
    needles = [
        entry.prefilter(language),
        *(n for _, _, n in entry.alias_pattern_list(language)),
    ]
    if all(_absent(n, joined) for n in needles):
        return
    chars, digits = _value_shape(entry.normalized)
    for index, text in enumerate(texts):
        _, own, aliases = entry.find_occurrences(language, views[index], text)
        for start, end in itertools.chain(own, *(o for _, o in aliases)):
            if entry.model_only and sweep_vetoed(text, start, end, entry.entity_type, language):
                continue
            yield Unmasked(
                index,
                start,
                end,
                entry.entity_type,
                chars,
                digits,
                model_only=entry.model_only,
            )


def _unmasked_known(
    known: KnownValues,
    views: Sequence[tuple[FoldedText, ...]],
    joined_text: str,
    language: str,
) -> Iterator[Unmasked]:
    """Yield every unmasked occurrence of pre-loaded ``known`` values across ``views``."""
    for item, pattern in known.patterns(language):
        if pattern.search(joined_text) is None:
            continue
        chars, digits = _value_shape(normalize_value(item.value))
        for index, view in enumerate(views):
            for start, end in _occurrences(pattern, view):
                yield Unmasked(index, start, end, item.entity_type, chars, digits, known=True)


def _value_shape(normalized: str) -> tuple[int, bool]:
    """Letters and digits in a value, and whether all of them are digits."""
    alnum = [c for c in normalized if c.isalnum()]
    return len(alnum), bool(alnum) and all(c.isdigit() for c in alnum)


_WHITESPACE_RUN = re.compile(r"\s+")


def _exact(value: str) -> str:
    """``value`` as a case-sensitive type is keyed (LAB-1350): the detection fold (invisible
    characters dropped, accents composed, Unicode spaces and dashes folded) and its whitespace
    collapsed, without the case fold."""
    return _WHITESPACE_RUN.sub(" ", normalize_for_detection(value).text).strip()


def _value_key(entity_type: EntityType, value: str) -> str:
    """The key ``value`` is confirmed and stored under: :func:`normalize_value` (case-folded),
    or :func:`_exact` for :data:`CASE_SENSITIVE_TYPES`."""
    if entity_type in CASE_SENSITIVE_TYPES:
        return _exact(value)
    return normalize_value(value)


def _folded_index(view: FoldedText, position: int) -> int | None:
    """The first index in ``view.text`` folded from original character ``position``; ``None``
    if it has none of its own (dropped, or composed with the character before it)."""
    if not view.starts:
        return position if position < len(view.text) else None
    index = bisect.bisect_left(view.starts, position)
    if index < len(view.starts) and view.starts[index] == position:
        return index
    return None


def _is_mark(char: str) -> bool:
    return unicodedata.category(char) in ("Mn", "Mc", "Me")


def _word_or_mark(char: str) -> bool:
    return _is_word_char(char) or _is_mark(char)


def _edge_after_placeholder(text: str, match: re.Match[str]) -> tuple[bool, int | None]:
    """Inspect the text edges around an issued placeholder ``match``.

    Returns ``(ok, after)``: ``ok`` is ``False`` when a word character or mark sits at a
    boundary that forces a full rescan; otherwise ``after`` is the index of a following word
    character to check against entry initials (or ``None`` when no word character follows).
    """
    before = match.start() - 1
    while before >= 0 and text[before] in INVISIBLE_CHARS:
        before -= 1
    if before >= 0 and _word_or_mark(text[before]):
        return False, None
    n = len(text)
    after = match.end()
    while after < n and text[after] in INVISIBLE_CHARS:
        after += 1
    if after >= n or not _word_or_mark(text[after]):
        return True, None
    if _is_mark(text[after]):
        return False, None
    return True, after


def _occurrences(pattern: re.Pattern[str], views: tuple[FoldedText, ...]) -> list[tuple[int, int]]:
    """Original ``(start, end)`` of every non-empty match of ``pattern`` in the folded views.

    The views are :func:`~pii_guard.vault.fold.fold_views`'s; a span found in both is listed once.
    """
    found: dict[tuple[int, int], None] = {}
    for folded in views:
        for match in pattern.finditer(folded.text):
            if match.end() > match.start():
                found.setdefault(folded.to_original(*match.span()))
    return list(found)


def _layout(value: str) -> str:
    """How ``value`` is laid out, beyond casing: ``""`` for spaces and composed accents.

    Otherwise the whitespace between its words (``"\\n"`` for ``Teszt\\nElek``; a run of plain
    spaces counts as one space) and ``nfd`` for decomposed accents. An occurrence in another
    layout than its entry's value gets a variant of its own, so unmask gives back the line
    break or the decomposed accents as written.
    """
    runs = [" " if not run.strip(" ") else run for run in re.findall(r"\s+", value.strip())]
    composed = unicodedata.is_normalized("NFC", value)
    if all(run == " " for run in runs) and composed:
        return ""
    return "".join(runs).encode("unicode_escape").decode("ascii") + ("" if composed else "|nfd")


def _relaid(value: str, written: str) -> str:
    """``value`` with the whitespace and Unicode form of ``written`` (same number of words)."""
    words = value.split()
    runs = re.findall(r"\s+", written.strip())
    if len(runs) == len(words) - 1:
        value = words[0] + "".join(run + word for run, word in zip(runs, words[1:], strict=True))
    if not unicodedata.is_normalized("NFC", written):
        value = unicodedata.normalize("NFD", value)
    return value


def _recased(original: str, written: str, normalized: str, casing: str) -> str:
    """The value a casing variant restores: as written if ``written`` is the whole value,
    otherwise (a changed stem such as ``ZSUZSANNÁ``) ``original`` in that casing class.
    """
    if normalize_value(written) == normalized:
        return written
    if casing == "upper":
        return original.upper()
    if casing == "lower":
        return original.lower()
    return re.sub(r"\w+", lambda m: m.group(0).capitalize(), original)


def _restored(entry: _Entry, suffix: str) -> str:
    """The entry's value inflected for the ``suffix`` that follows its placeholder.

    Without case-sensitive placeholders that is the value as first written, whatever the
    casing of the occurrence was (a documented limitation, see :meth:`VaultSession.mask`).

    A suffix seen after this value in the input restores the stem as written there (exact
    round trip); any other suffix, such as one the upstream model added, is re-inflected by
    the language's matcher (``[[PERSON_x]]nak`` -> ``Próba Zsuzsannának``).
    """
    if not suffix:
        return entry.original
    stem = entry.seen.get(suffix)
    if stem is None:
        stem = entry.seen_folded.get(suffix.casefold())
    if stem is not None:
        return stem + suffix
    return restore(inflection_for(entry.language), entry.original, suffix, entry.entity_type)


# An alias's last word needs this many letters: "Kornél" is not read as "Kor" + "nél" ("kor"
# is a common word), but "Minta Kendét" is also matched as "Minta Kende".
_MIN_ALIAS_LETTERS = 4


def _letters(value: str) -> int:
    words = value.split()
    return sum(ch.isalpha() for ch in words[-1]) if words else 0


def _occurs_alone(text: str, lemma: str, span: Span) -> bool:
    """``lemma`` stands on its own (no suffix) somewhere in ``text`` outside ``span``.

    Case-sensitive, so ``Kornél`` is not read as ``Kor`` + ``nél`` because ``kor`` (a common
    word) occurs in the text.
    """
    left = r"(?<!\w)" if _is_word_char(lemma[0]) else ""
    pattern = re.compile(f"{left}{_body(lemma)}(?!\\w)")
    return any(m.end() <= span.start or m.start() >= span.end for m in pattern.finditer(text))


def _validated(text: str, spans: Sequence[Span]) -> list[Span]:
    """Spans sorted by start; raises :class:`MaskingError` (no values in the message)."""
    for index, span in enumerate(spans):
        if not isinstance(span, Span):
            raise MaskingError(f"span {index} is not a Span")
        label = f"span {index} ({span.entity_type.value})"
        if span.end > len(text):
            raise MaskingError(f"{label} is out of range [{span.start}, {span.end})")
        if text[span.start : span.end] != span.text:
            raise MaskingError(f"{label} does not match the text at [{span.start}, {span.end})")
        if span.entity_type.is_visual:
            raise MaskingError(f"{label} is a visual entity type, not a text span")
        if not normalize_value(span.text):
            raise MaskingError(f"{label} is blank")
    ordered = sorted(spans, key=lambda s: (s.start, s.end))
    for previous, current in itertools.pairwise(ordered):
        if previous.overlaps(current):
            raise MaskingError(
                f"overlapping spans {previous.entity_type.value} [{previous.start}, "
                f"{previous.end}) and {current.entity_type.value} [{current.start}, "
                f"{current.end})"
            )
    return ordered
