"""In-memory vault: keyed pseudonyms, the placeholder mapping and re-identification.

The mapping (placeholder -> original value) lives only in this process and expires after a
TTL of inactivity. Nothing in this module logs, reprs or raises with an original value: logs
and errors carry entity types, counts and placeholder ids only (AGENTS.md, ADR 0006).
"""

from __future__ import annotations

import copy
import heapq
import itertools
import logging
import re
import secrets
import threading
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pii_guard.types import EntityType, MaskingError, PiiGuardError, Span
from pii_guard.vault.fold import FoldedText, fold_text, fold_value
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
    "DEFAULT_MAX_SESSIONS",
    "DEFAULT_TTL_SECONDS",
    "MIN_TENANT_KEY_BYTES",
    "MaskResult",
    "PlaceholderInInputError",
    "SessionNotFoundError",
    "UnmaskResult",
    "Vault",
    "VaultSession",
]

logger = logging.getLogger(__name__)


class PlaceholderInInputError(MaskingError):
    """The text to mask already holds a placeholder this session issued (422).

    Restoring it later would put a value into text the caller never masked. The message
    names a count only, never the token or any value.
    """

    code = "placeholder_in_input"
    status_code = 422


DEFAULT_TTL_SECONDS = 3600.0
#: Most live sessions a vault holds; a new one beyond it evicts the least recently used.
DEFAULT_MAX_SESSIONS = 10_000
MIN_TENANT_KEY_BYTES = 16


class SessionNotFoundError(PiiGuardError):
    """The vault session is unknown, expired or closed; its mapping is gone."""

    code = "not_found"
    status_code = 404


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
        "count",
        "entity_type",
        "language",
        "normalized",
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
        self.patterns: dict[str, re.Pattern[str]] = {}
        self.alias_patterns: dict[str, list[tuple[str, re.Pattern[str]]]] = {}
        self.surfaces: dict[str, None] = {}
        self.aliases: dict[str, None] = {}
        self.seen: dict[str, str] = {}
        self.seen_folded: dict[str, str] = {}
        self.casing = casing_class(original)
        self.variants: dict[str, _Entry] = {}

    def __repr__(self) -> str:
        return f"_Entry(placeholder={self.placeholder!r}, value=<redacted>, count={self.count})"

    def add_surface(self, surface: str) -> None:
        if surface != self.original and surface not in self.surfaces:
            self.surfaces[surface] = None
            self.patterns.clear()

    def add_alias(self, lemma: str) -> None:
        if lemma != self.original and lemma not in self.aliases:
            self.aliases[lemma] = None
            self.alias_patterns.clear()

    def remember(self, suffix: str, stem: str) -> None:
        if suffix:
            self.seen.setdefault(suffix, stem)
            self.seen_folded.setdefault(suffix.casefold(), stem)

    def pattern(self, language: str) -> re.Pattern[str]:
        """Pattern for further occurrences of the value, over :func:`fold_text`'s folded text.

        Case-, whitespace- and Unicode-form-insensitive (``WEISS`` for ``Weiß``, NFD for NFC).
        A match covers the stem only; an allowed suffix is checked by lookahead and stays
        outside. Alternatives: the lemma, its changed stems (``Zsuzsanná`` before ``-nak``,
        ``Kováccs`` before ``-al``) and the detected surface forms split onto it.
        """
        pattern = self.patterns.get(language)
        if pattern is None:
            matcher = inflection_for(language)
            alternatives = _forms(matcher, fold_value(self.original), self.entity_type)
            alternatives += [
                _occurrence(matcher, fold_value(s), self.entity_type) for s in self.surfaces
            ]
            pattern = _compile(alternatives)
            self.patterns[language] = pattern
        return pattern

    def alias_pattern_list(self, language: str) -> list[tuple[str, re.Pattern[str]]]:
        """``(alias, pattern of its forms)`` per alias, like :meth:`pattern`."""
        cached = self.alias_patterns.get(language)
        if cached is None:
            matcher = inflection_for(language)
            cached = [
                (alias, _compile(_forms(matcher, fold_value(alias), self.entity_type)))
                for alias in self.aliases
            ]
            self.alias_patterns[language] = cached
        return cached


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
    forms = [_occurrence(matcher, value, entity_type)]
    for stem, suffix in variant_stems(matcher, value, entity_type):
        left = r"(?<!\w)" if _is_word_char(stem[0]) else ""
        forms.append(f"{left}{_body(stem)}(?=(?:{suffix})(?!\\w))")
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
    ) -> None:
        self.session_id = session_id
        self._case_sensitive = case_sensitive_placeholders
        self._tenant_key = tenant_key
        self._ttl = ttl_seconds
        self._id_length = id_length
        self._clock = clock
        self._lock = threading.RLock()
        self._by_key: dict[tuple[EntityType, str], _Entry] = {}
        self._by_placeholder: dict[str, _Entry] = {}
        # Placeholder-shaped tokens seen in input that this session did not issue. They are
        # never issued later, so a token the caller wrote can't turn into a masked value.
        self._reserved: set[str] = set()
        self._closed = False
        self._expires_at = clock() + ttl_seconds
        self._known = KnownValues()
        # A fork (:meth:`fork`) records its successful writes here, for :meth:`commit`.
        self._journal: list[tuple[str, tuple[Span, ...], str, bool, str]] | None = None
        self._parent: VaultSession | None = None

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
            self._reserved.clear()
            self._known.clear()

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
            )
            memo: dict[int, Any] = {}
            fork._by_key = copy.deepcopy(self._by_key, memo)
            fork._by_placeholder = copy.deepcopy(self._by_placeholder, memo)
            fork._reserved = set(self._reserved)
            fork._known = self._known
            fork._journal = []
            fork._parent = self
            return fork

    def commit(self, fork: VaultSession) -> None:
        """Apply a :meth:`fork`'s writes to this session, in order.

        Placeholders are derived from the tenant key, the session id and the value, so the
        replay issues the placeholders the fork printed. If a concurrent request changed
        this session so that the replay comes out differently, raises :class:`MaskingError`
        (fail closed: the caller must not use the fork's output).
        """
        if fork._parent is not self or fork._journal is None:
            raise ValueError("not a fork of this session")
        journal, fork._journal = fork._journal, None
        with self._lock:
            for text, spans, language, remask, expected in journal:
                result = self.mask_with_report(text, spans, language=language, remask=remask)
                if result.text != expected:
                    raise MaskingError("the session changed while an image was masked")

    # --- masking -------------------------------------------------------------------------

    def mask(
        self,
        text: str,
        spans: Sequence[Span],
        *,
        language: str = "hu",
        remask: bool = False,
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

        Raises :class:`MaskingError` for invalid, out-of-range or overlapping spans, and
        :class:`SessionNotFoundError` once the session has expired. Nothing is recorded when
        it raises.
        """
        return self.mask_with_report(text, spans, language=language, remask=remask).text

    def mask_with_report(
        self,
        text: str,
        spans: Sequence[Span],
        *,
        language: str = "hu",
        remask: bool = False,
    ) -> MaskResult:
        """Like :meth:`mask`, also returning where each placeholder went."""
        with self._lock:
            self._check_alive()
            ordered = _validated(text, spans)
            foreign = self._foreign_tokens(text, remask)
            added = foreign - self._reserved
            self._reserved |= added
            try:
                result = self._mask_validated(text, ordered, language)
            except BaseException:
                self._reserved -= added
                raise
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

    def _mask_validated(self, text: str, ordered: Sequence[Span], language: str) -> MaskResult:
        matcher = inflection_for(language)
        taken = bytearray(len(text))
        replacements: list[tuple[int, int, _Entry]] = []
        for plan in self._plans(text, ordered, matcher):
            span, end = plan.span, plan.span.start + plan.stem_length
            entry = self._entry_for(span.entity_type, plan.lemma, language)
            entry.add_surface(span.text)
            for alias in plan.aliases:
                entry.add_alias(alias)
            replacements.append((span.start, end, self._cased(entry, text[span.start : end])))
            taken[span.start : end] = b"\x01" * (end - span.start)
        folded = fold_text(text)
        # Longest values first, so "Teszt Elek" wins over a separately confirmed "Elek".
        entries = sorted(self._by_key.values(), key=lambda e: len(e.normalized), reverse=True)
        for entry in entries:
            for start, end in _occurrences(entry.pattern(language), folded):
                if any(taken[start:end]):
                    continue
                replacements.append((start, end, self._cased(entry, text[start:end])))
                taken[start:end] = b"\x01" * (end - start)
            # Forms of an alias share the entry's placeholder; with a suffix, unmask restores
            # them from ``seen``. A bare alias ("Minta Kende" after a "Minta Kendét" span) would
            # come back as the span's surface: it gets the alias's own entry instead.
            for alias, pattern in entry.alias_pattern_list(language):
                for start, end in _occurrences(pattern, folded):
                    if any(taken[start:end]):
                        continue
                    written = text[start:end]
                    owner = entry
                    if not following_suffix(text, end) and normalize_value(
                        written
                    ) == normalize_value(alias):
                        owner = self._entry_for(entry.entity_type, written, language)
                    replacements.append((start, end, self._cased(owner, written)))
                    taken[start:end] = b"\x01" * (end - start)
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
            len(ordered),
            dict(per_type),
        )
        return MaskResult(
            "".join(parts),
            tuple((start, end, entry.placeholder) for start, end, entry in replacements),
        )

    def _plans(self, text: str, ordered: Sequence[Span], matcher: InflectionMatcher) -> list[_Plan]:
        """The lemma and stem of every span (see :class:`~pii_guard.vault.inflection.Split`).

        - A span that ends inside a word (``Teszt Elek|nek``, ``Próba Zsuzsanná|nak``): the
          detector chose the stem; its lemma comes from the split that agrees with it.
        - A whole-word span with a strong split (``Próba Zsuzsannának``): narrowed to the stem.
        - A weak split (``Próba Zsuzsannát``, ``Teszt Eleknek``) only when the lemma is
          confirmed: it occurs on its own in ``text``, it is another span's value or lemma,
          two spans agree on it, or this session already has it. Otherwise the span is its
          own value, as before, and the candidate lemmas become aliases of it (their forms
          get the same placeholder): recall never depends on a guess.
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
                confirmed.add((span.entity_type, normalize_value(lemma)))
                continue
            candidates = splits(matcher, value, span.entity_type)
            strong = next((c for c in candidates if c.strong), None)
            if strong is not None:
                plans.append(_Plan(span, strong.lemma, len(strong.stem)))
                confirmed.add((span.entity_type, normalize_value(strong.lemma)))
            elif candidates:
                plans.append(None)
                pending[index] = candidates
                for lemma in {normalize_value(c.lemma) for c in candidates}:
                    votes.setdefault((span.entity_type, lemma), set()).add(normalize_value(value))
            else:
                plans.append(_Plan(span, value, len(value)))
            # A span's own value is a confirmed lemma for the others ("Zoltán" for "Zoltánt").
            confirmed.add((span.entity_type, normalize_value(value)))
        # Lemmas other spans may be inflected forms of ("Varga Bernadett" for "...Bernadettel").
        candidate_of: dict[tuple[EntityType, str], set[int]] = {}
        for index, candidates in pending.items():
            for c in candidates:
                key = (ordered[index].entity_type, normalize_value(c.lemma))
                candidate_of.setdefault(key, set()).add(index)
        for index, candidates in pending.items():
            span = ordered[index]
            own = (span.entity_type, normalize_value(span.text))
            if candidate_of.get(own, set()) - {index}:
                # Another span reads as an inflected form of this one: it is a lemma itself.
                plans[index] = _Plan(span, span.text, span.length)
                continue
            # A confirmed lemma beats one that only two surfaces agree on.
            choice = next(
                (
                    c
                    for c in candidates
                    if (span.entity_type, normalize_value(c.lemma)) in confirmed
                    or _occurs_alone(text, c.lemma, span)
                ),
                None,
            ) or next(
                (
                    c
                    for c in candidates
                    if len(votes.get((span.entity_type, normalize_value(c.lemma)), ())) >= 2
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

    def _entry_for(self, entity_type: EntityType, value: str, language: str = "hu") -> _Entry:
        normalized = normalize_value(value)
        key = (entity_type, normalized)
        entry = self._by_key.get(key)
        if entry is not None:
            return entry
        placeholder = self._new_placeholder(entity_type, normalized)
        entry = _Entry(placeholder, entity_type, value, normalized, language)
        self._by_key[key] = entry
        self._by_placeholder[placeholder] = entry
        return entry

    def _form(self, value: str) -> str:
        """The variant key of ``value``: its casing class (case-sensitive mode) and layout.

        A casing-only key is the casing class itself, so those ids are derived as before.
        """
        casing = casing_class(value) if self._case_sensitive else ""
        layout = _layout(value)
        return f"{casing}|{layout}" if layout else casing

    def _cased(self, entry: _Entry, written: str) -> _Entry:
        """The entry an occurrence written as ``written`` is masked with.

        ``entry`` itself, unless ``written`` is in another form than the entry's value: another
        layout (a line break inside it, decomposed accents) or, with case-sensitive
        placeholders, another casing class. Then that form's variant, created on first use.
        """
        form = self._form(written)
        if form == self._form(entry.original):
            return entry
        variant = entry.variants.get(form)
        if variant is None:
            placeholder = self._new_placeholder(entry.entity_type, entry.normalized, form)
            # The value in the written form: its casing (case-sensitive mode; the whole
            # value as written, or a changed stem's lemma recased) and its layout.
            original = entry.original
            if self._case_sensitive:
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

    def unmask(self, text: str) -> str:
        """Replace known placeholders with their original values; unknown ones stay as is."""
        return self.unmask_with_report(text).text

    def unmask_with_report(self, text: str) -> UnmaskResult:
        """Like :meth:`unmask`, also listing placeholder-shaped tokens that weren't resolved."""
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
                parts.append(_restored(entry, suffix))
                cursor += len(suffix)
            parts.append(text[cursor:])
            result = "".join(parts)
            if unresolved:
                logger.warning(
                    "unmask left %d unresolved placeholders: %s", len(unresolved), list(unresolved)
                )
            logger.debug("unmasked %d placeholders", restored)
            return UnmaskResult(result, tuple(unresolved))

    def entities(self) -> list[tuple[str, EntityType, int]]:
        """``(placeholder, entity_type, count)`` for every placeholder this session issued."""
        with self._lock:
            self._check_alive()
            return [(e.placeholder, e.entity_type, e.count) for e in self._by_placeholder.values()]


def _occurrences(pattern: re.Pattern[str], folded: FoldedText) -> list[tuple[int, int]]:
    """Original ``(start, end)`` of every non-empty match of ``pattern`` in the folded text."""
    return [
        folded.to_original(*match.span())
        for match in pattern.finditer(folded.text)
        if match.end() > match.start()
    ]


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
    whose sliding TTL ends first), which is closed like an expired one, so its later use is
    ``404 session_not_found``. Eviction rather than 429 keeps the service up under a flood;
    a client whose idle session was evicted starts a new one.
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
        self._max_sessions = max_sessions
        self._tenant_key = bytes(tenant_key)
        self._ttl = ttl_seconds
        self._id_length = id_length
        self._clock = clock
        self._case_sensitive = case_sensitive_placeholders
        self._lock = threading.Lock()
        self._sessions: dict[str, VaultSession] = {}

    @classmethod
    def from_settings(cls, settings: Settings, **kwargs: Any) -> Vault:
        """A vault keyed by ``PII_GUARD_TENANT_KEY``. Fails closed if the key is unset.

        ``PII_GUARD_VAULT_CASE_SENSITIVE_PLACEHOLDERS`` sets ``case_sensitive_placeholders``
        and ``PII_GUARD_VAULT_MAX_SESSIONS`` sets ``max_sessions``, unless ``kwargs`` does.
        """
        key = settings.tenant_key_bytes()
        if key is None:
            raise MaskingError("PII_GUARD_TENANT_KEY is not set", code="vault_not_configured")
        kwargs.setdefault("case_sensitive_placeholders", settings.vault_case_sensitive_placeholders)
        kwargs.setdefault("max_sessions", settings.vault_max_sessions)
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
                self._evict_locked(self._max_sessions - 1)
                session_id = f"s_{secrets.token_hex(16)}"
                session = VaultSession(
                    session_id,
                    self._tenant_key,
                    ttl_seconds=self._ttl,
                    id_length=self._id_length,
                    clock=self._clock,
                    case_sensitive_placeholders=self._case_sensitive,
                )
                self._sessions[session_id] = session
                return session
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError("vault session not found or expired")
            session._check_alive()
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
            excess, self._sessions.items(), key=lambda item: item[1]._expires_at
        )
        for sid, session in oldest:
            del self._sessions[sid]
            session.close()
        logger.info("vault: evicted %d least recently used session(s)", len(oldest))

    def _purge_locked(self) -> int:
        stale = [sid for sid, session in self._sessions.items() if session.expired]
        for sid in stale:
            self._sessions.pop(sid).close()
        return len(stale)
