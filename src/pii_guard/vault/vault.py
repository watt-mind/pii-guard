"""In-memory vault: keyed pseudonyms, the placeholder mapping and re-identification.

The mapping (placeholder -> original value) lives only in this process and expires after a
TTL of inactivity. Nothing in this module logs, reprs or raises with an original value: logs
and errors carry entity types, counts and placeholder ids only (AGENTS.md, ADR 0006).
"""

from __future__ import annotations

import bisect
import copy
import hashlib
import heapq
import hmac
import itertools
import logging
import re
import secrets
import threading
import time
import unicodedata
from collections import Counter, OrderedDict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

from pii_guard.detect.ner_context import sweep_vetoed
from pii_guard.detect.normalize import INVISIBLE_CHARS, normalize_for_detection
from pii_guard.types import EntityType, MaskingError, PiiGuardError, Span
from pii_guard.vault.fold import FoldedText, fold_value, fold_views, spaced
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
from pii_guard.vault.placeholders import (
    DEFAULT_ID_LENGTH,
    MAX_ID_LENGTH,
    MIN_ID_LENGTH,
    PLACEHOLDER_RE,
    casing_class,
    derive_id,
    format_placeholder,
    normalize_value,
)

if TYPE_CHECKING:
    from pii_guard.config import Settings

__all__ = [
    "CASE_SENSITIVE_TYPES",
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_MAX_RESTORED_CHARS",
    "DEFAULT_MAX_SESSIONS",
    "DEFAULT_TTL_SECONDS",
    "MIN_TENANT_KEY_BYTES",
    "MaskResult",
    "PlaceholderInInputError",
    "RestoreBudget",
    "SessionEntryLimitError",
    "SessionNotFoundError",
    "UnmaskOutputTooLargeError",
    "UnmaskResult",
    "Unmasked",
    "Vault",
    "VaultSession",
]

logger = logging.getLogger(__name__)

_SessionMetadata = TypeVar("_SessionMetadata")


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


DEFAULT_TTL_SECONDS = 3600.0
#: Most live sessions a vault holds; a new one beyond it evicts the least recently used.
DEFAULT_MAX_SESSIONS = 10_000
#: Most placeholders a get-or-create session (:meth:`Vault.session_or_create`) collects before
#: its id moves on to a new, empty generation (LAB-1286).
DEFAULT_MAX_ENTRIES = 10_000
MIN_TENANT_KEY_BYTES = 16
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


class SessionNotFoundError(PiiGuardError):
    """The vault session is unknown, expired or closed; its mapping is gone."""

    code = "not_found"
    status_code = 404


class VaultCapacityError(MaskingError):
    """Every capacity slot is pinned by an active request; retry after one finishes."""

    code = "vault_capacity_exhausted"
    status_code = 503


class UnmaskOutputTooLargeError(PiiGuardError):
    """Restoring the placeholders would put more than the limit of original characters out (413).

    Fail closed (LAB-1350): nothing is returned, and the output is never built past the limit.
    The message names the limit only.
    """

    code = "unmask_output_too_large"
    status_code = 413


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
        "entity_type",
        "exact",
        "initials",
        "language",
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
        return _exact(written) in allowed or _exact(spaced(written)) in allowed

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


#: Literal substrings, one of which every match of a pattern contains; ``None``: no filter.
_Needles = tuple[str, ...] | None

#: Characters ``re.IGNORECASE`` matches to another case-folded character: dotted and dotless
#: ``i`` (``re._casefix``). Every other case-folded character matches only itself there, so
#: a needle is cut at these (``test_needle_alphabet_is_closed_under_ignorecase``).
_CASE_AMBIGUOUS = re.compile("[i\u0131]")


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


#: Off only in tests, to check the prefilter changes no output.
_PREFILTER = True

#: Off only in tests and benchmarks, to check ``since`` remasks change no output (LAB-1278).
_REMASK_SINCE = True

#: Bounds of a session's fold memo: texts, and their characters in all. A folded view keeps
#: an offset map per character, so the character bound is what caps the memory.
_FOLD_MEMO_ENTRIES = 1024
_FOLD_MEMO_CHARS = 512_000

#: Off only in tests and benchmarks, to check the pass-1 memo changes no output (LAB-1315).
_MASK_MEMO = True

#: Bounds of a session's mask memo (:class:`_Masked`): texts, and their characters in all.
_MASK_MEMO_ENTRIES = 1024
_MASK_MEMO_CHARS = 512_000

#: Most foreign placeholder-shaped tokens a session reserves (LAB-1565): the oldest are
#: forgotten (a forgotten token could in principle be derived later, as after a restart).
_MAX_RESERVED = DEFAULT_MAX_ENTRIES

#: Most ``_touched`` generations kept (LAB-1565); older ones are forgotten and a memo from
#: before them is re-masked from scratch, which changes cost, never output.
_MAX_TOUCHED = 8192


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


class VaultSession:
    """The placeholder mapping of one conversation. Obtain one from :meth:`Vault.session`.

    Thread-safe. Once the session expires or is closed, every method raises
    :class:`SessionNotFoundError`; the gateway must then fail the request (ADR 0006).
    """

    def __init__(
        self,
        session_id: str,
        tenant_key: bytes,
        *,
        ttl_seconds: float,
        id_length: int,
        clock: Callable[[], float],
        case_sensitive_placeholders: bool = False,
        max_restored_chars: int = DEFAULT_MAX_RESTORED_CHARS,
        entry_limit: int | None = None,
    ) -> None:
        self.session_id = session_id
        #: The gateway client identity this session is bound to (LAB-1565, LAB-1580), set by
        #: :func:`pii_guard.gateway.sessions.check_and_bind`; ``None``: not presented yet.
        #: On the session itself, so the binding lives exactly as long as the session.
        self.owner: str | None = None
        #: Random per session object (LAB-1580): a dropped/expired/rotated id re-created as a
        #: new session gets a new one, so per-session state keyed by it (the gateway's
        #: detection cache) starts clean in every runtime that shares that state.
        self.incarnation = secrets.token_hex(8)
        self._case_sensitive = case_sensitive_placeholders
        self._max_restored = max_restored_chars
        #: Explicit-session placeholder cap enforced at mask time (LAB-1565); ``None``:
        #: a get-or-create session, which the vault rotates instead (:meth:`Vault.session`).
        self._entry_limit = entry_limit
        self._tenant_key = tenant_key
        self._ttl = ttl_seconds
        self._id_length = id_length
        self._clock = clock
        self._lock = threading.RLock()
        self._by_key: dict[tuple[EntityType, str], _Entry] = {}
        self._by_placeholder: dict[str, _Entry] = {}
        # Normalized value -> the first entry of an :data:`IDENTIFIER_TYPES` type holding it.
        self._identifiers: dict[str, _Entry] = {}
        # Placeholder-shaped tokens seen in input that this session did not issue. They are
        # never issued later, so a token the caller wrote can't turn into a masked value.
        # Bounded (LAB-1565): at most _MAX_RESERVED, oldest forgotten first (see above).
        self._reserved: OrderedDict[str, None] = OrderedDict()
        self._closed = False
        self._expires_at = clock() + ttl_seconds
        self._known = KnownValues()
        # A fork (:meth:`fork`) records its successful writes here, for :meth:`commit`.
        self._journal: list[tuple[str, tuple[Span, ...], str, bool, str]] | None = None
        self._parent: VaultSession | None = None
        # fold_views() of recently masked texts: a request re-masks the whole history, so the
        # same texts come back every turn (LAB-1277). Bounded; forgotten with the session.
        self._folds: OrderedDict[str, tuple[FoldedText, ...]] = OrderedDict()
        self._folded_chars = 0
        # Bumped whenever an entry is created or its patterns change (LAB-1278): a remask
        # ``since`` a text's generation scans only the entries changed after it.
        self._generation = 0
        # (generation, language) -> folded initial -> entries (see :meth:`_starting_with`).
        self._initials: tuple[int, str, dict[str, list[_Entry]]] | None = None
        # The entry each generation was touched for: ``_touched[g:]`` changed after ``g``.
        # Bounded (LAB-1565): ``_touched[0]`` is generation ``_touched_base + 1``; generations
        # at or before ``_touched_base`` are forgotten.
        self._touched: list[_Entry] = []
        self._touched_base = 0
        # (text, spans, language) -> its last mask from spans: the next request re-sends the
        # same history, so pass 1 scans only the entries changed since (LAB-1315). Bounded;
        # forgotten with the session; ``None`` in a fork.
        self._masked: OrderedDict[tuple[str, tuple[Span, ...], str], _Masked] | None = OrderedDict()
        self._masked_chars = 0
        #: Entries scanned for occurrences, over every mask call (a cost counter for tests).
        self.entries_scanned = 0

    def __repr__(self) -> str:
        return (
            f"VaultSession(session_id={self.session_id[:6]!r}…, "
            f"placeholders={len(self._by_placeholder)}, closed={self._closed})"
        )

    __str__ = __repr__

    # --- lifecycle -----------------------------------------------------------------------

    @property
    def expired(self) -> bool:
        return self._closed or self._clock() >= self._expires_at

    def close(self) -> None:
        """Forget the mapping now. Later calls raise :class:`SessionNotFoundError`."""
        with self._lock:
            self._closed = True
            self._by_key.clear()
            self._by_placeholder.clear()
            self._identifiers.clear()
            self._reserved.clear()
            self._known.clear()
            self._folds.clear()
            self._folded_chars = 0
            if self._masked is not None:
                self._masked.clear()
            self._masked_chars = 0
            self._touched.clear()
            self._touched_base = self._generation

    @property
    def known_values(self) -> KnownValues:
        """Values pre-loaded into this session (:mod:`pii_guard.vault.known`).

        They expire and are forgotten with the session. Raises :class:`SessionNotFoundError`
        once the session has expired; otherwise extends its TTL like any other use.
        """
        with self._lock:
            self._check_alive()
            return self._known

    def _check_alive(self) -> None:
        """Raise if expired; otherwise extend the TTL (sliding expiry)."""
        if self.expired:
            self.close()
            raise SessionNotFoundError("vault session not found or expired")
        self._expires_at = self._clock() + self._ttl

    # --- staged writes -------------------------------------------------------------------

    def fork(self) -> VaultSession:
        """A private copy to mask in; nothing reaches this session until :meth:`commit`.

        Image work runs in a worker thread that may outlive its request (a timeout): it
        masks into a fork, and only a request that succeeded commits it, so a refused or
        timed-out image registers nothing here (LAB-1207). Known values are shared, read-only.
        """
        with self._lock:
            self._check_alive()
            fork = VaultSession(
                self.session_id,
                self._tenant_key,
                ttl_seconds=self._ttl,
                id_length=self._id_length,
                clock=self._clock,
                case_sensitive_placeholders=self._case_sensitive,
                max_restored_chars=self._max_restored,
                entry_limit=self._entry_limit,
            )
            memo: dict[int, Any] = {}
            fork._by_key = copy.deepcopy(self._by_key, memo)
            fork._by_placeholder = copy.deepcopy(self._by_placeholder, memo)
            fork._identifiers = copy.deepcopy(self._identifiers, memo)
            fork._reserved = OrderedDict(self._reserved)
            fork._generation = self._generation
            fork._masked = None  # its journal is replayed in full anyway
            fork._known = self._known
            fork._journal = []
            fork._parent = self
            fork.owner, fork.incarnation = self.owner, self.incarnation
            return fork

    def commit(self, fork: VaultSession) -> None:
        """Apply a :meth:`fork`'s writes to this session, in order.

        Placeholders are derived from the tenant key, the session id and the value, so the
        replay issues the placeholders the fork printed. If a concurrent request changed
        this session so that the replay comes out differently, raises :class:`MaskingError`
        (fail closed: the caller must not use the fork's output).
        """
        with fork._lock:
            if fork._parent is not self or fork._journal is None:
                raise ValueError("not a fork of this session")
            journal, fork._journal = fork._journal, None
        with self._lock:
            # Copy all mutable mask state together: entries, variants, memo references and
            # generation indexes must continue to refer to the same copied objects.
            excluded = {"_lock", "_clock", "_known", "_parent", "_journal"}
            state = copy.deepcopy({k: v for k, v in vars(self).items() if k not in excluded})
            staged = copy.copy(self)
            staged.__dict__.update(state)
            staged._lock = threading.RLock()
            staged._journal = None
            staged._check_alive()
            for text, spans, language, remask, expected in journal:
                result = staged.mask_with_report(text, spans, language=language, remask=remask)
                if result.text != expected:
                    raise MaskingError("the session changed while an image was masked")
            self.__dict__.update({k: v for k, v in vars(staged).items() if k not in excluded})
            if self._journal is not None:
                self._journal.extend(journal)

    # --- masking -------------------------------------------------------------------------

    def mask(
        self,
        text: str,
        spans: Sequence[Span],
        *,
        language: str = "hu",
        remask: bool = False,
        since: int | None = None,
    ) -> str:
        """Replace each span, and every other occurrence of a confirmed value, by its placeholder.

        Confirmed values are those in ``spans`` plus every value this session masked before.
        Further occurrences are searched in a folded view of ``text`` (:mod:`~pii_guard.vault.fold`:
        case, whitespace, Unicode form, ``ß``/``ss``) and, for ``language``, with inflectional
        suffixes kept outside the placeholder (``[[PERSON_7f3a]]nek``). An occurrence with a
        line break inside it or decomposed accents gets a placeholder of its own, so it
        round-trips as written.

        Every form of one value shares one placeholder keyed on its lemma: a span that ends
        in a suffix is narrowed to the stem (``Próba Zsuzsannának`` -> ``[[PERSON_x]]nak``)
        and stem-changed forms (``Próba Zsuzsannát``, ``Kováccsal``) are found as occurrences.

        Casing: by default every casing of a value shares its placeholder too, and
        :meth:`unmask` restores the value as first written (``TESZT ELEK és Teszt Elek`` with
        a span on ``Teszt Elek`` round-trips to ``Teszt Elek és Teszt Elek``). With
        ``case_sensitive_placeholders`` (``PII_GUARD_VAULT_CASE_SENSITIVE_PLACEHOLDERS``) an
        occurrence written in another casing class (ALL CAPS, lower case, mixed) gets a
        placeholder of its own and round-trips exactly; the upstream model then sees two ids
        for one value. Both modes mask every casing.

        Placeholder-shaped tokens already in ``text``: one equal to a placeholder this session
        issued raises :class:`PlaceholderInInputError` (``placeholder_in_input``, 422), since
        :meth:`unmask` would restore a value into text that was never masked. Any other
        token is reserved: left as it is and never issued as a placeholder later.
        ``remask=True`` is for text this session's own :meth:`mask` produced (a second pass
        that catches values confirmed later): its issued placeholders are expected there.
        ``since`` (with ``remask``, no spans): the :attr:`MaskResult.generation` that text was
        masked at. Only entries created or changed after it are scanned, since every older one
        already scanned the text and its occurrences are placeholders now; with no such entry
        the text is returned as it is (LAB-1278).

        A text masked again from the same spans (the history a request re-sends) is scanned
        only with the entries created or changed since: the session keeps a bounded memo of
        its last result. The output, ``entities()`` counts included, is the same as a mask
        from scratch (LAB-1315).

        Raises :class:`MaskingError` for invalid, out-of-range or overlapping spans, and
        :class:`SessionNotFoundError` once the session has expired. Nothing is recorded when
        it raises.
        """
        return self.mask_with_report(
            text, spans, language=language, remask=remask, since=since
        ).text

    def mask_with_report(
        self,
        text: str,
        spans: Sequence[Span],
        *,
        language: str = "hu",
        remask: bool = False,
        since: int | None = None,
    ) -> MaskResult:
        """Like :meth:`mask`, also returning where each placeholder went."""
        if since is not None and (not remask or spans):
            raise ValueError("since is only for a remask without spans")
        if not _REMASK_SINCE:
            since = None
        with self._lock:
            self._check_alive()
            if self._entry_limit is not None and len(self._by_placeholder) >= self._entry_limit:
                # An explicit session has nobody to rotate it for (LAB-1565): fail closed
                # rather than grow without bound; the client starts a new session.
                raise SessionEntryLimitError(
                    "vault session entry limit reached; start a new session"
                )
            if since is not None and not self._edges_unchanged(text, since, language):
                since = None
            if since is not None and since >= self._generation:
                # Nothing changed since the text was masked: no scan can find anything.
                return MaskResult(text, (), self._generation)
            ordered = _validated(text, spans)
            key = None
            if _MASK_MEMO and self._masked is not None and not remask:
                key = (text, tuple(spans), language)
            foreign = self._foreign_tokens(text, remask)
            added = [token for token in foreign if token not in self._reserved]
            for token in foreign:
                self._reserved[token] = None
                self._reserved.move_to_end(token)
            # Bound _reserved (LAB-1565), but never forget a token of the current text:
            # it must not be issued as a placeholder by this very mask.
            while len(self._reserved) > _MAX_RESERVED:
                oldest = next(iter(self._reserved))
                if oldest in foreign:
                    break
                del self._reserved[oldest]
            try:
                result = self._mask_again(text, key, language) if key is not None else None
                if result is None:
                    result = self._mask_validated(text, ordered, language, since, key)
            except BaseException:
                for token in added:
                    self._reserved.pop(token, None)
                raise
            # A fork's journal is replayed as a full remask: ``since`` is in the fork's
            # numbering, and the replay must come out the same either way (else it fails).
            if self._journal is not None:
                self._journal.append((text, tuple(spans), language, remask, result.text))
            return result

    def _foreign_tokens(self, text: str, remask: bool) -> set[str]:
        """Placeholder-shaped tokens in ``text`` this session didn't issue.

        Raises :class:`PlaceholderInInputError` for one it did, unless ``remask``.
        """
        foreign: set[str] = set()
        issued = 0
        for match in PLACEHOLDER_RE.finditer(text):
            token = match.group(0)
            if token in self._by_placeholder:
                issued += 1
            else:
                foreign.add(token)
        if issued and not remask:
            raise PlaceholderInInputError(
                f"the text contains {issued} placeholder(s) already issued in this session"
            )
        return foreign

    def _edges_unchanged(self, text: str, since: int, language: str) -> bool:
        """Whether no entry changed at or before ``since`` can match ``text`` anywhere new.

        Such an entry scanned the text ``text`` was masked from and its occurrences are
        placeholders now; what is left of that text is unchanged, so it can only match where
        a placeholder put a new boundary next to a word: right before one
        (``…0101[[PERSON_x]]``, the lookahead after the match changed) or right after one
        (``[[PERSON_x]]nak``, the lookbehind before it). The first is rare: then ``False``
        (scan every entry). For the second, every such entry starting with that character
        is tried at that position, which is exact and cheap.
        """
        views: tuple[FoldedText, ...] | None = None
        n = len(text)
        for match in PLACEHOLDER_RE.finditer(text):
            if match.group(0) not in self._by_placeholder:
                continue  # a token from the input itself: its neighbourhood did not change
            before = match.start() - 1
            while before >= 0 and text[before] in INVISIBLE_CHARS:
                before -= 1
            if before >= 0 and (_is_word_char(text[before]) or _is_mark(text[before])):
                return False
            after = match.end()
            while after < n and text[after] in INVISIBLE_CHARS:
                after += 1
            if after >= n or not (_is_word_char(text[after]) or _is_mark(text[after])):
                continue
            if _is_mark(text[after]):
                return False
            if views is None:
                views = self._fold_views(text)
            for view in views:
                index = _folded_index(view, after)
                if index is None:
                    return False
                for entry in self._starting_with(language).get(_initial(view.text[index]), ()):
                    if entry.changed > since:
                        continue  # scanned in full anyway
                    if entry.pattern(language).match(view.text, index):
                        return False
                    for _, alias_pattern, _ in entry.alias_pattern_list(language):
                        if alias_pattern.match(view.text, index):
                            return False
        return True

    def _starting_with(self, language: str) -> dict[str, list[_Entry]]:
        """Entries by the folded characters their matches can start with, for this generation."""
        cached = self._initials
        if cached is not None and cached[0] == self._generation and cached[1] == language:
            return cached[2]
        index: dict[str, list[_Entry]] = {}
        for entry in self._by_key.values():
            for char in entry.initial_chars(language):
                index.setdefault(char, []).append(entry)
        self._initials = (self._generation, language, index)
        return index

    def _mask_validated(
        self,
        text: str,
        ordered: Sequence[Span],
        language: str,
        since: int | None = None,
        key: tuple[str, tuple[Span, ...], str] | None = None,
    ) -> MaskResult:
        matcher = inflection_for(language)
        taken = bytearray(len(text))
        replacements: list[tuple[int, int, _Entry]] = []
        depends: set[tuple[EntityType, str]] | None = set() if key is not None else None
        for plan in self._plans(text, ordered, matcher, depends):
            span, end = plan.span, plan.span.start + plan.stem_length
            entry = self._entry_for(span.entity_type, plan.lemma, language, span.detector)
            if entry.add_surface(span.text):
                self._touch(entry)
            for alias in plan.aliases:
                if entry.add_alias(alias):
                    self._touch(entry)
            replacements.append((span.start, end, self._cased(entry, text[span.start : end])))
            taken[span.start : end] = b"\x01" * (end - span.start)
        folded = self._fold_views(text)
        # Every entry up to here scans this text below; one created during the scan (an
        # alias's own entry) is newer, so a remask since this generation still scans it.
        generation = self._generation
        # Longest values first, so "Teszt Elek" wins over a separately confirmed "Elek".
        pool: Iterable[_Entry] = self._by_key.values()
        if since is not None:
            pool = [e for e in pool if e.changed > since]
        entries = sorted(pool, key=lambda e: len(e.normalized), reverse=True)
        self.entries_scanned += len(entries)
        found = [self._found(entry, language, folded, text) for entry in entries]
        self._take(text, found, language, replacements, taken)
        if depends is not None and key is not None:
            self._remember_masked(key, replacements, generation, depends, len(ordered))
        return self._assemble(text, replacements, len(ordered), generation)

    def _mask_again(
        self, text: str, key: tuple[str, tuple[Span, ...], str], language: str
    ) -> MaskResult | None:
        """Pass 1 of a text masked from the same spans before, from :attr:`_masked`.

        The same as :meth:`_mask_validated`, without planning it again or scanning it with
        the entries that already did (LAB-1315). The plans are the same unless a lemma they
        looked up exists now. Every older entry takes what it took then: an entry changed
        since only adds occurrences that overlap none of those, else from scratch a longer
        value could have won one (``Teszt Elek`` over ``Elek``), so ``None`` (mask from
        scratch). The newer entries scan the input text, as they would from scratch.
        """
        memo = self._masked
        masked = memo.get(key) if memo is not None else None
        if masked is None or any(k in self._by_key for k in masked.depends):
            return None
        generation = self._generation
        if masked.generation < self._touched_base:
            return None  # older changes were forgotten (LAB-1565): mask from scratch
        changed = dict.fromkeys(self._touched[masked.generation - self._touched_base :])
        entries = sorted(changed, key=lambda e: (-len(e.normalized), e.order))
        self.entries_scanned += len(entries)
        replacements = list(masked.replacements)
        if entries:
            taken = bytearray(len(text))
            for start, end, _ in replacements:
                taken[start:end] = b"\x01" * (end - start)
            folded = self._fold_views(text)
            found = [self._found(entry, language, folded, text) for entry in entries]
            for _, occurrences, aliases in found:
                spans = itertools.chain(occurrences, *(o for _, o in aliases))
                if any(any(taken[start:end]) for start, end in spans):
                    return None
            self._take(text, found, language, replacements, taken)
        self._remember_masked(key, replacements, generation, masked.depends, masked.spans)
        return self._assemble(text, replacements, masked.spans, generation)

    @staticmethod
    def _found(
        entry: _Entry, language: str, folded: tuple[FoldedText, ...], text: str
    ) -> tuple[_Entry, list[tuple[int, int]], list[tuple[str, list[tuple[int, int]]]]]:
        """``entry``'s occurrences in ``folded``, and each alias's: ``(entry, own, aliases)``.

        ``text`` is the original the views fold: a case-sensitive entry keeps only the
        occurrences written as its value (:meth:`_Entry.written_as`).
        """
        pattern = entry.pattern(language)
        # Skipping a scan that can find nothing changes no output, only its cost: each
        # request re-masks the whole history against every value of the session (LAB-1277).
        own = [] if _absent(entry.prefilter(language), folded) else _occurrences(pattern, folded)
        aliases = [
            (alias, _occurrences(alias_pattern, folded))
            for alias, alias_pattern, needles in entry.alias_pattern_list(language)
            if not _absent(needles, folded)
        ]
        if entry.entity_type in CASE_SENSITIVE_TYPES:
            own = [(a, b) for a, b in own if entry.written_as(text[a:b])]
            aliases = [
                (alias, [(a, b) for a, b in spans if entry.written_as(text[a:b], alias)])
                for alias, spans in aliases
            ]
        return entry, own, aliases

    def _take(
        self,
        text: str,
        found: list[tuple[_Entry, list[tuple[int, int]], list[tuple[str, list[tuple[int, int]]]]]],
        language: str,
        replacements: list[tuple[int, int, _Entry]],
        taken: bytearray,
    ) -> None:
        """Add each occurrence in ``found`` (in its order) that overlaps nothing taken yet."""
        for entry, own, aliases in found:
            guarded = entry.model_only
            for start, end in own:
                if any(taken[start:end]):
                    continue
                if guarded and sweep_vetoed(text, start, end, entry.entity_type, language):
                    continue
                replacements.append((start, end, self._cased(entry, text[start:end])))
                taken[start:end] = b"\x01" * (end - start)
            # Forms of an alias share the entry's placeholder; with a suffix, unmask restores
            # them from ``seen``. A bare alias ("Minta Kende" after a "Minta Kendét" span) would
            # come back as the span's surface: it gets the alias's own entry instead.
            for alias, occurrences in aliases:
                for start, end in occurrences:
                    if any(taken[start:end]):
                        continue
                    if guarded and sweep_vetoed(text, start, end, entry.entity_type, language):
                        continue
                    written = text[start:end]
                    owner = entry
                    kind = entry.entity_type
                    if not following_suffix(text, end) and _value_key(kind, written) == _value_key(
                        kind, alias
                    ):
                        owner = self._entry_for(
                            entry.entity_type,
                            written,
                            language,
                            "ner" if entry.model_only else None,
                        )
                    replacements.append((start, end, self._cased(owner, written)))
                    taken[start:end] = b"\x01" * (end - start)

    def _remember_masked(
        self,
        key: tuple[str, tuple[Span, ...], str],
        replacements: list[tuple[int, int, _Entry]],
        generation: int,
        depends: Iterable[tuple[EntityType, str]],
        spans: int,
    ) -> None:
        memo = self._masked
        text = key[0]
        if memo is None or len(text) > _MASK_MEMO_CHARS:
            return
        replacements.sort(key=lambda r: r[0])
        if key in memo:
            memo.move_to_end(key)
        else:
            self._masked_chars += len(text)
        memo[key] = _Masked(tuple(replacements), generation, frozenset(depends), spans)
        while len(memo) > _MASK_MEMO_ENTRIES or self._masked_chars > _MASK_MEMO_CHARS:
            evicted, _ = memo.popitem(last=False)
            self._masked_chars -= len(evicted[0])

    def _assemble(
        self,
        text: str,
        replacements: list[tuple[int, int, _Entry]],
        spans: int,
        generation: int,
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

    def _fold_views(self, text: str) -> tuple[FoldedText, ...]:
        """:func:`fold_views` of ``text``, from the session's bounded memo when it has it."""
        views = self._folds.get(text)
        if views is not None:
            self._folds.move_to_end(text)
            return views
        views = fold_views(text)
        if len(text) <= _FOLD_MEMO_CHARS:
            self._folds[text] = views
            self._folded_chars += len(text)
            while len(self._folds) > _FOLD_MEMO_ENTRIES or self._folded_chars > _FOLD_MEMO_CHARS:
                evicted, _ = self._folds.popitem(last=False)
                self._folded_chars -= len(evicted)
        return views

    def _plans(
        self,
        text: str,
        ordered: Sequence[Span],
        matcher: InflectionMatcher,
        depends: set[tuple[EntityType, str]] | None = None,
    ) -> list[_Plan]:
        """The lemma and stem of every span (see :class:`~pii_guard.vault.inflection.Split`).

        - A span that ends inside a word (``Teszt Elek|nek``, ``Próba Zsuzsanná|nak``): the
          detector chose the stem; its lemma comes from the split that agrees with it.
        - A whole-word span with a strong split (``Próba Zsuzsannának``): narrowed to the stem.
        - A weak split (``Próba Zsuzsannát``, ``Teszt Eleknek``) only when the lemma is
          confirmed: it occurs on its own in ``text``, it is another span's value or lemma,
          two spans agree on it, or this session already has it. Otherwise the span is its
          own value, as before, and the candidate lemmas become aliases of it (their forms
          get the same placeholder): recall never depends on a guess.

        ``depends`` collects the weak-split lemmas this session did not have: the only session
        state the plans read, so the same text and spans plan the same until one exists.
        """
        plans: list[_Plan | None] = []
        pending: dict[int, list[Split]] = {}
        confirmed = {key for key in self._by_key}
        # Lemma -> the distinct surface forms that can be read as it ("Eleknek", "Eleket").
        votes: dict[tuple[EntityType, str], set[str]] = {}
        for index, span in enumerate(ordered):
            value, end = span.text, span.end
            if _is_word_char(value[-1]) and end < len(text) and _is_word_char(text[end]):
                run = following_suffix(text, end)
                agree = (
                    next(
                        (
                            c
                            for c in splits(matcher, value + run, span.entity_type)
                            if c.stem == value
                        ),
                        None,
                    )
                    if run
                    else None
                )
                lemma = agree.lemma if agree is not None else value
                plans.append(_Plan(span, lemma, len(value)))
                confirmed.add((span.entity_type, _value_key(span.entity_type, lemma)))
                continue
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
            for c in candidates:
                kind = ordered[index].entity_type
                key = (kind, _value_key(kind, c.lemma))
                candidate_of.setdefault(key, set()).add(index)
                if depends is not None and key not in confirmed:
                    depends.add(key)
        for index, candidates in pending.items():
            span = ordered[index]
            own = (span.entity_type, _value_key(span.entity_type, span.text))
            if candidate_of.get(own, set()) - {index}:
                # Another span reads as an inflected form of this one: it is a lemma itself.
                plans[index] = _Plan(span, span.text, span.length)
                continue
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
                    if len(votes.get((span.entity_type, _value_key(span.entity_type, c.lemma)), ()))
                    >= 2
                ),
                None,
            )
            if choice is None:
                aliases = tuple(
                    dict.fromkeys(
                        c.lemma for c in candidates if _letters(c.lemma) >= _MIN_ALIAS_LETTERS
                    )
                )
                plans[index] = _Plan(span, span.text, span.length, aliases)
            else:
                plans[index] = _Plan(span, choice.lemma, len(choice.stem))
        return [plan for plan in plans if plan is not None]

    def _entry_for(
        self,
        entity_type: EntityType,
        value: str,
        language: str = "hu",
        detector: str | None = None,
    ) -> _Entry:
        """The entry of ``value``, created if new. ``detector`` found it (``None``: unknown,
        which counts as a validated source): see :attr:`_Entry.model_only`."""
        normalized = _value_key(entity_type, value)
        key = (entity_type, normalized)
        entry = self._by_key.get(key)
        if entry is None and entity_type in IDENTIFIER_TYPES:
            entry = self._identifiers.get(normalized)
        if entry is not None:
            if entry.model_only and detector not in MODEL_DETECTORS | NEUTRAL_DETECTORS:
                entry.model_only = False
                self._touch(entry)  # a remask ``since`` now must scan it everywhere
            return entry
        placeholder = self._new_placeholder(entity_type, normalized)
        entry = _Entry(placeholder, entity_type, value, normalized, language)
        entry.model_only = detector in MODEL_DETECTORS
        entry.order = len(self._by_key)
        self._by_key[key] = entry
        self._by_placeholder[placeholder] = entry
        if entity_type in IDENTIFIER_TYPES:
            self._identifiers.setdefault(normalized, entry)
        self._touch(entry)
        return entry

    def _touch(self, entry: _Entry) -> None:
        """A new entry, or new patterns of one: a newer generation (see :attr:`generation`)."""
        self._generation += 1
        entry.changed = self._generation
        if self._masked is not None:
            self._touched.append(entry)
            if len(self._touched) > _MAX_TOUCHED:
                drop = len(self._touched) // 2
                del self._touched[:drop]
                self._touched_base += drop

    def _form(self, value: str, entity_type: EntityType) -> str:
        """The variant key of ``value``: its casing class (case-sensitive mode) and layout.

        A casing-only key is the casing class itself, so those ids are derived as before. A
        case-sensitive type has no casing variants: its occurrences are written as its value.
        """
        casing = ""
        if self._case_sensitive and entity_type not in CASE_SENSITIVE_TYPES:
            casing = casing_class(value)
        layout = _layout(value)
        return f"{casing}|{layout}" if layout else casing

    def _cased(self, entry: _Entry, written: str) -> _Entry:
        """The entry an occurrence written as ``written`` is masked with.

        ``entry`` itself, unless ``written`` is in another form than the entry's value: another
        layout (a line break inside it, decomposed accents) or, with case-sensitive
        placeholders, another casing class. Then that form's variant, created on first use.
        """
        form = self._form(written, entry.entity_type)
        if form == self._form(entry.original, entry.entity_type):
            return entry
        variant = entry.variants.get(form)
        if variant is None:
            placeholder = self._new_placeholder(entry.entity_type, entry.normalized, form)
            # The value in the written form: its casing (case-sensitive mode; the whole
            # value as written, or a changed stem's lemma recased) and its layout.
            original = entry.original
            if self._case_sensitive and entry.entity_type not in CASE_SENSITIVE_TYPES:
                original = _recased(original, written, entry.normalized, casing_class(written))
            original = _relaid(original, written)
            variant = _Entry(
                placeholder, entry.entity_type, original, entry.normalized, entry.language
            )
            entry.variants[form] = variant
            self._by_placeholder[placeholder] = variant
        return variant

    def _new_placeholder(self, entity_type: EntityType, normalized: str, casing: str = "") -> str:
        length = self._id_length
        # The casing class is passed only for a variant: canonical ids are derived as always.
        extra = {"casing": casing} if casing else {}
        while True:
            placeholder_id = derive_id(
                self._tenant_key, self.session_id, entity_type, normalized, length, **extra
            )
            placeholder = format_placeholder(entity_type, placeholder_id)
            if placeholder not in self._by_placeholder and placeholder not in self._reserved:
                return placeholder
            # Collision with a different value: extend the id (ADR 0007).
            if length >= MAX_ID_LENGTH:  # pragma: no cover - a full SHA-256 collision
                raise MaskingError(f"could not derive a unique {entity_type.value} placeholder")
            length = min(length + 2, MAX_ID_LENGTH)

    # --- re-identification ---------------------------------------------------------------

    def restore_budget(self) -> RestoreBudget:
        """A fresh :class:`RestoreBudget` at this session's limit, for one whole output.

        Pass it to every :meth:`unmask_with_report` call that writes into the same response
        (the gateway restores a response placeholder by placeholder, or chunk by chunk).
        """
        return RestoreBudget(self._max_restored)

    def unmask(self, text: str, *, budget: RestoreBudget | None = None) -> str:
        """Replace known placeholders with their original values; unknown ones stay as is."""
        return self.unmask_with_report(text, budget=budget).text

    def unmask_with_report(self, text: str, *, budget: RestoreBudget | None = None) -> UnmaskResult:
        """Like :meth:`unmask`, also listing placeholder-shaped tokens that weren't resolved.

        Restored values are charged to ``budget`` (default: a fresh :meth:`restore_budget` for
        this call alone): past it, raises :class:`UnmaskOutputTooLargeError` before the output
        grows further (LAB-1350).
        """
        if budget is None:
            budget = self.restore_budget()
        with self._lock:
            self._check_alive()
            unresolved: dict[str, None] = {}
            restored = 0
            parts: list[str] = []
            cursor = 0
            for match in PLACEHOLDER_RE.finditer(text):
                if match.start() < cursor:  # pragma: no cover - a suffix never holds "[["
                    continue
                parts.append(text[cursor : match.start()])
                cursor = match.end()
                entry = self._by_placeholder.get(match.group(0))
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
                logger.warning(
                    "unmask left %d unresolved placeholders: %s", len(unresolved), list(unresolved)
                )
            logger.debug("unmasked %d placeholders", restored)
            return UnmaskResult(result, tuple(unresolved))

    @property
    def generation(self) -> int:
        """Grows whenever an entry is created or its patterns change; never goes back."""
        return self._generation

    @property
    def entry_count(self) -> int:
        """How many placeholders this session has issued (casing and layout variants too)."""
        return len(self._by_placeholder)

    def issued_any(self, text: str) -> bool:
        """Whether ``text`` holds a placeholder this session issued (and so can restore)."""
        with self._lock:
            self._check_alive()
            return any(m.group(0) in self._by_placeholder for m in PLACEHOLDER_RE.finditer(text))

    def entities(self) -> list[tuple[str, EntityType, int]]:
        """``(placeholder, entity_type, count)`` for every placeholder this session issued."""
        with self._lock:
            self._check_alive()
            return [(e.placeholder, e.entity_type, e.count) for e in self._by_placeholder.values()]

    def unmasked(self, texts: Sequence[str], language: str = "hu") -> list[Unmasked]:
        """Every occurrence of a value this session holds that is still written out in ``texts``.

        The outbound re-check (LAB-1500): ``texts`` are what is about to leave the guard, and
        any value found here would leave it real. The values are the session's confirmed
        entries (with their surfaces and aliases) and its pre-loaded known values. Each is
        searched with the sweep's own patterns over the sweep's folded views (case,
        whitespace, Unicode form, ``ß``/``ss``, inflection), so a value is found however
        :meth:`mask` would have found it. The sweep's guards apply too: an NER-only value
        where the text's structure rules it out (``sweep_vetoed``) and a case-sensitive value
        in another casing are not occurrences. Neither is anything inside a placeholder
        token. Overlapping occurrences count once, the longest value first.

        Read-only: no entry, count, memo or generation changes. The result holds offsets,
        types and flags, never a value.
        """
        with self._lock:
            self._check_alive()
            views = [self._folds.get(text) or fold_views(text) for text in texts]
            # One string with every view: a value none of whose needles is in it can't occur
            # in any text, so most entries are skipped after one substring search each.
            joined = (FoldedText("", "\x00".join(v.text for vs in views for v in vs)),)
            taken = [bytearray(len(text)) for text in texts]
            for index, text in enumerate(texts):
                for match in PLACEHOLDER_RE.finditer(text):
                    taken[index][match.start() : match.end()] = b"\x01" * (
                        match.end() - match.start()
                    )
            found: list[Unmasked] = []

            def add(index: int, start: int, end: int, unmasked: Unmasked) -> None:
                if end > start and not any(taken[index][start:end]):
                    taken[index][start:end] = b"\x01" * (end - start)
                    found.append(unmasked)

            entries = sorted(self._by_key.values(), key=lambda e: (-len(e.normalized), e.order))
            for entry in entries:
                entry.pattern(language)  # compiles the pattern and its prefilter
                needles = [entry.prefilter(language)]
                needles += [n for _, _, n in entry.alias_pattern_list(language)]
                if all(_absent(n, joined) for n in needles):
                    continue
                chars, digits = _value_shape(entry.normalized)
                for index, text in enumerate(texts):
                    _, own, aliases = self._found(entry, language, views[index], text)
                    for start, end in itertools.chain(own, *(o for _, o in aliases)):
                        if entry.model_only and sweep_vetoed(
                            text, start, end, entry.entity_type, language
                        ):
                            continue
                        add(
                            index,
                            start,
                            end,
                            Unmasked(
                                index,
                                start,
                                end,
                                entry.entity_type,
                                chars,
                                digits,
                                model_only=entry.model_only,
                            ),
                        )
            for item, pattern in self._known.patterns(language):
                if pattern.search(joined[0].text) is None:
                    continue
                chars, digits = _value_shape(normalize_value(item.value))
                for index, view in enumerate(views):
                    for start, end in _occurrences(pattern, view):
                        occurrence = Unmasked(
                            index, start, end, item.entity_type, chars, digits, known=True
                        )
                        add(index, start, end, occurrence)
            found.sort(key=lambda u: (u.index, u.start))
            return found

    def confirmed_values(self, entity_types: Iterable[EntityType]) -> list[str]:
        """The confirmed values of ``entity_types``, as first written, plus pre-loaded ones.

        Personal data: for widening a partly detected span to a value this session already
        has (:func:`~pii_guard.detect.known.widen_to_known`), never for output or logs.
        """
        types = frozenset(entity_types)
        with self._lock:
            self._check_alive()
            found = dict.fromkeys(
                e.original for e in self._by_key.values() if e.entity_type in types
            )
            found.update(
                dict.fromkeys(v.value for v in self._known.values() if v.entity_type in types)
            )
            return list(found)


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


class Vault:
    """Per-tenant store of :class:`VaultSession` mappings, held in memory with a TTL.

    ``tenant_key`` keys every placeholder id (at least 16 bytes; ``openssl rand -hex 32``
    decoded). ``ttl_seconds`` is sliding: each use of a session extends it. ``id_length`` is
    the initial hex length of placeholder ids (collisions extend it).
    ``case_sensitive_placeholders`` gives each casing class of a value its own placeholder
    (see :meth:`VaultSession.mask`). ``clock`` is injectable for tests.

    ``max_sessions`` caps the live sessions (every ``/v1/mask`` without a ``session_id``
    creates one): creating one more **evicts the least recently used** session (the one
    whose sliding TTL ends first) among unleased sessions. It is closed like an expired
    one, so its later use is ``404 session_not_found``. When every session is leased,
    creation fails with ``503 vault_capacity_exhausted`` without evicting an active session.

    ``max_entries`` caps a **get-or-create** session (:meth:`session_or_create`: the gateway's
    path, ``prompt_cache_key`` and default sessions, which can live as long as a client keeps
    using them). Once a session holds that many placeholders, the next lookup of its id starts
    a new, empty **generation** under a new derived id (logged once per rotation); the full
    generation is no longer handed out and expires with its TTL. A conversation that crosses
    a rotation is re-masked from its re-sent history under the new generation; only a
    placeholder it kept from before the rotation (and no longer sends the value of) stays
    unrestored. Explicit sessions (:meth:`session`) cannot rotate (the client addresses them
    by id), so the same ``max_entries`` is enforced at mask time instead: a full explicit
    session fails closed and its client starts a new one (LAB-1565).

    ``max_restored_chars`` caps the characters of original values one unmask call (or one
    :meth:`VaultSession.restore_budget`, a gateway response) restores: see
    :class:`RestoreBudget` (LAB-1350).
    """

    def __init__(
        self,
        tenant_key: bytes,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        id_length: int = DEFAULT_ID_LENGTH,
        clock: Callable[[], float] = time.monotonic,
        case_sensitive_placeholders: bool = False,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_restored_chars: int = DEFAULT_MAX_RESTORED_CHARS,
    ) -> None:
        if not isinstance(tenant_key, bytes | bytearray):
            raise TypeError("tenant_key must be bytes")
        if len(tenant_key) < MIN_TENANT_KEY_BYTES:
            raise ValueError(f"tenant_key must be at least {MIN_TENANT_KEY_BYTES} bytes")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if not MIN_ID_LENGTH <= id_length <= MAX_ID_LENGTH:
            raise ValueError(f"id_length must be in [{MIN_ID_LENGTH}, {MAX_ID_LENGTH}]")
        if max_sessions < 1:
            raise ValueError("max_sessions must be at least 1")
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        if max_restored_chars < 1:
            raise ValueError("max_restored_chars must be at least 1")
        self._max_restored = max_restored_chars
        self._max_sessions = max_sessions
        self._max_entries = max_entries
        # base id -> current generation, only for ids that rotated at least once.
        self._generations: dict[str, int] = {}
        self._tenant_key = bytes(tenant_key)
        self._ttl = ttl_seconds
        self._id_length = id_length
        self._clock = clock
        self._case_sensitive = case_sensitive_placeholders
        self._lock = threading.RLock()
        self._leases: Counter[VaultSession] = Counter()
        self._sessions: dict[str, VaultSession] = {}

    @classmethod
    def from_settings(cls, settings: Settings, **kwargs: Any) -> Vault:
        """A vault keyed by ``PII_GUARD_TENANT_KEY``. Fails closed if the key is unset.

        ``PII_GUARD_VAULT_CASE_SENSITIVE_PLACEHOLDERS`` sets ``case_sensitive_placeholders``
        ``PII_GUARD_VAULT_MAX_SESSIONS`` sets ``max_sessions``, ``PII_GUARD_VAULT_MAX_ENTRIES``
        sets ``max_entries`` and ``PII_GUARD_UNMASK_MAX_RESTORED_CHARS`` sets
        ``max_restored_chars``, unless ``kwargs`` does.
        """
        key = settings.tenant_key_bytes()
        if key is None:
            raise MaskingError("PII_GUARD_TENANT_KEY is not set", code="vault_not_configured")
        kwargs.setdefault("case_sensitive_placeholders", settings.vault_case_sensitive_placeholders)
        kwargs.setdefault("max_sessions", settings.vault_max_sessions)
        kwargs.setdefault("max_entries", settings.vault_max_entries)
        kwargs.setdefault("max_restored_chars", settings.unmask_max_restored_chars)
        return cls(key, **kwargs)

    def __repr__(self) -> str:
        return f"Vault(sessions={len(self._sessions)}, ttl_seconds={self._ttl})"

    __str__ = __repr__

    def __len__(self) -> int:
        """Number of live sessions."""
        with self._lock:
            self._purge_locked()
            return len(self._sessions)

    def session(self, session_id: str | None = None) -> VaultSession:
        """``None`` -> a new session with a fresh random id; an existing id -> that session.

        Raises :class:`SessionNotFoundError` for an unknown, expired or closed id.
        """
        with self._lock:
            self._purge_locked()
            if session_id is None:
                created = self._create_locked(f"s_{secrets.token_hex(16)}")
                created._entry_limit = self._max_entries  # explicit: capped, not rotated
                return created
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError("vault session not found or expired")
            with session._lock:
                session._check_alive()
                if session._entry_limit is None:
                    session._entry_limit = self._max_entries  # addressed explicitly now
            return session

    def session_or_create(self, session_id: str) -> tuple[VaultSession, bool]:
        """The live session for ``session_id``, created when there is none: ``(session, new)``.

        For ids the caller chose or derived (:meth:`derive_session_id`), never 404. The
        returned session's id differs from ``session_id`` once that id rotated to a later
        generation (``max_entries``); send the returned id back to address it directly.
        """
        if not session_id:
            raise ValueError("session_id must not be empty")
        with self._lock:
            self._purge_locked()
            generation = self._generations.get(session_id, 0)
            current = self._generation_id(session_id, generation)
            session = self._sessions.get(current)
            if session is not None and not session.expired:
                if session.entry_count < self._max_entries:
                    with session._lock:
                        session._check_alive()
                    return session, False
                generation += 1
                current = self._generation_id(session_id, generation)
                logger.info(
                    "vault: a session reached %d placeholders; starting generation %d",
                    self._max_entries,
                    generation,
                )
                existing = self._sessions.get(current)
                if existing is not None and not existing.expired:  # pragma: no cover - race
                    existing._check_alive()
                    return existing, False
            session = self._create_locked(current)
            if generation:
                self._generations[session_id] = generation
            return session, True

    def acquire_session(
        self, resolve: Callable[[], tuple[VaultSession, bool, _SessionMetadata]]
    ) -> tuple[VaultSession, bool, _SessionMetadata]:
        """Resolve and pin a session atomically against LRU eviction.

        ``resolve`` must use this vault's session lookup methods. Each successful acquire
        requires one :meth:`release_session`, including on failure or cancellation. Pins
        protect against capacity eviction only; explicit deletion and TTL still apply.
        """
        with self._lock:
            result = resolve()
            session = result[0]
            if self._sessions.get(session.session_id) is not session:
                raise SessionNotFoundError("vault session not found or expired")
            with session._lock:
                session._check_alive()
            self._leases[session] += 1
            return result

    def release_session(self, session: VaultSession) -> None:
        """Release one pin, even if TTL or explicit deletion already removed the session."""
        with self._lock:
            if self._leases[session] <= 0:
                raise ValueError("session has no lease")
            self._leases[session] -= 1
            if not self._leases[session]:
                del self._leases[session]

    def derive_session_id(self, material: str) -> str:
        """A stable session id for ``material``, keyed with the tenant key: ``d_`` + 32 hex.

        The same material gives the same id in this deployment and different ids under
        another tenant key; the id reveals nothing about the material.
        """
        digest = hmac.new(
            self._tenant_key, b"pii-guard-session\x00" + material.encode("utf-8"), hashlib.sha256
        )
        return "d_" + digest.hexdigest()[:32]

    def _generation_id(self, base: str, generation: int) -> str:
        if generation == 0:
            return base
        return self.derive_session_id(f"generation:{generation}:{base}")

    def _create_locked(self, session_id: str) -> VaultSession:
        self._evict_locked(self._max_sessions - 1)
        session = VaultSession(
            session_id,
            self._tenant_key,
            ttl_seconds=self._ttl,
            id_length=self._id_length,
            clock=self._clock,
            case_sensitive_placeholders=self._case_sensitive,
            max_restored_chars=self._max_restored,
        )
        self._sessions[session_id] = session
        return session

    def drop(self, session_id: str) -> None:
        """Close and forget a session now (no error if it is already gone)."""
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            session.close()

    def purge_expired(self) -> int:
        """Drop every expired session; returns how many were dropped."""
        with self._lock:
            return self._purge_locked()

    def _evict_locked(self, keep: int) -> None:
        """Close the least recently used sessions until at most ``keep`` are left."""
        excess = len(self._sessions) - keep
        if excess <= 0:
            return
        oldest = heapq.nsmallest(
            excess,
            (
                (sid, session)
                for sid, session in self._sessions.items()
                if not self._leases[session]
            ),
            key=lambda item: item[1]._expires_at,
        )
        if len(oldest) < excess:
            raise VaultCapacityError("vault session capacity is occupied by active requests")
        for sid, session in oldest:
            del self._sessions[sid]
            session.close()
        logger.info("vault: evicted %d least recently used session(s)", len(oldest))

    def _purge_locked(self) -> int:
        stale = [sid for sid, session in self._sessions.items() if session.expired]
        for sid in stale:
            self._sessions.pop(sid).close()
        if self._generations:  # a rotated id whose current generation is gone starts over
            gone = [
                base
                for base, generation in self._generations.items()
                if self._generation_id(base, generation) not in self._sessions
            ]
            for base in gone:
                del self._generations[base]
        return len(stale)
