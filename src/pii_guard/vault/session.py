"""Per-conversation vault session: placeholder mapping, masking and re-identification.

Nothing in this module logs, reprs or raises with an original value: logs and errors carry
entity types, counts and placeholder ids only (AGENTS.md, ADR 0006).
"""

from __future__ import annotations

import copy
import itertools
import logging
import secrets
import threading
from collections import Counter, OrderedDict
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from pii_guard.detect.ner_context import sweep_vetoed
from pii_guard.types import EntityType, MaskingError, Span
from pii_guard.vault.entry import (
    CASE_SENSITIVE_TYPES,
    DEFAULT_MAX_ENTRIES,
    DEFAULT_MAX_RESTORED_CHARS,
    IDENTIFIER_TYPES,
    MODEL_DETECTORS,
    NEUTRAL_DETECTORS,
    MaskResult,
    PlaceholderInInputError,
    RestoreBudget,
    SessionEntryLimitError,
    SessionNotFoundError,
    Unmasked,
    UnmaskResult,
    _edge_after_placeholder,
    _Entry,
    _folded_index,
    _initial,
    _layout,
    _Masked,
    _placeholder_mask,
    _Plan,
    _recased,
    _relaid,
    _restored,
    _unmasked_for_entry,
    _unmasked_known,
    _validated,
    _value_key,
    _vault_attr,
    plan_spans,
)
from pii_guard.vault.fold import FoldedText, fold_views
from pii_guard.vault.inflection import InflectionMatcher, following_suffix, inflection_for
from pii_guard.vault.known import KnownValue, KnownValues
from pii_guard.vault.placeholders import (
    MAX_ID_LENGTH,
    PLACEHOLDER_RE,
    casing_class,
    derive_id,
    format_placeholder,
)

__all__ = [
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_MAX_RESTORED_CHARS",
    "_COMMITTED_STATE",
    "_FOLD_MEMO_CHARS",
    "_FOLD_MEMO_ENTRIES",
    "_MASK_MEMO",
    "_MASK_MEMO_CHARS",
    "_MASK_MEMO_ENTRIES",
    "_MAX_RESERVED",
    "_MAX_TOUCHED",
    "_REMASK_SINCE",
    "_RESET_CACHES",
    "Authorize",
    "MaskResult",
    "PlaceholderInInputError",
    "RestoreBudget",
    "SessionEntryLimitError",
    "SessionNotFoundError",
    "UnmaskOutputTooLargeError",
    "UnmaskResult",
    "Unmasked",
    "VaultSession",
    "_Masked",
    "_authorized",
]

# Re-exported in __all__ for callers importing from session directly.
from pii_guard.vault.entry import UnmaskOutputTooLargeError

logger = logging.getLogger(__name__)

#: Off only in tests and benchmarks, to check ``since`` remasks change no output (LAB-1278).
_REMASK_SINCE = True
#: Bounds of a session's fold memo: texts, and their characters in all.
_FOLD_MEMO_ENTRIES = 1024
_FOLD_MEMO_CHARS = 512_000
#: Off only in tests and benchmarks, to check the pass-1 memo changes no output (LAB-1315).
_MASK_MEMO = True
#: Bounds of a session's mask memo (:class:`_Masked`): texts, and their characters in all.
_MASK_MEMO_ENTRIES = 1024
_MASK_MEMO_CHARS = 512_000
#: Most foreign placeholder-shaped tokens a session reserves (LAB-1565).
_MAX_RESERVED = DEFAULT_MAX_ENTRIES
#: Most ``_touched`` generations kept (LAB-1565); older ones are forgotten.
_MAX_TOUCHED = 8192

#: The mask state :meth:`VaultSession.commit` replays into a staged copy and publishes (LAB-1584).
_COMMITTED_STATE = (
    "_by_key",
    "_by_placeholder",
    "_identifiers",
    "_reserved",
    "_generation",
    "_touched",
    "_touched_base",
)
_RESET_CACHES = ("_masked", "_masked_chars", "_folds", "_folded_chars", "_initials")

#: A check run on a session before a lookup extends its TTL; raises to refuse the caller.
Authorize = Callable[["VaultSession"], None]


def _authorized(session: VaultSession, authorize: Authorize | None) -> None:
    if authorize is not None:
        authorize(session)


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
        #: Gateway client identity bound by :func:`pii_guard.gateway.sessions.check_and_bind`.
        self.owner: str | None = None
        #: Random per session object (LAB-1580) for per-session external cache invalidation.
        self.incarnation = secrets.token_hex(8)
        self._case_sensitive = case_sensitive_placeholders
        self._max_restored = max_restored_chars
        self._entry_limit = entry_limit
        self._tenant_key = tenant_key
        self._ttl = ttl_seconds
        self._id_length = id_length
        self._clock = clock
        self._lock = threading.RLock()
        self._by_key: dict[tuple[EntityType, str], _Entry] = {}
        self._by_placeholder: dict[str, _Entry] = {}
        self._identifiers: dict[str, _Entry] = {}
        self._reserved: OrderedDict[str, None] = OrderedDict()
        self._json_numbers: dict[str, tuple[str, str] | None] = {}
        self._closed = False
        self._expires_at = clock() + ttl_seconds
        self._known = KnownValues()
        self._journal: list[tuple[str, tuple[Span, ...], str, bool, str]] | None = None
        self._parent: VaultSession | None = None
        self._folds: OrderedDict[str, tuple[FoldedText, ...]] = OrderedDict()
        self._folded_chars = 0
        self._generation = 0
        self._initials: tuple[int, str, dict[str, list[_Entry]]] | None = None
        self._touched: list[_Entry] = []
        self._touched_base = 0
        self._masked: OrderedDict[tuple[str, tuple[Span, ...], str], _Masked] | None = OrderedDict()
        self._masked_chars = 0
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

    @property
    def expires_at(self) -> float:
        """Vault-clock timestamp when this session's sliding TTL ends."""
        return self._expires_at

    def touch(
        self,
        *,
        authorize: Authorize | None = None,
        below_entries: int | None = None,
    ) -> bool:
        """Authorize and, if below ``below_entries`` (when set), verify alive and extend TTL."""
        with self._lock:
            _authorized(self, authorize)
            if below_entries is not None and len(self._by_placeholder) >= below_entries:
                return False
            self._check_alive()
            return True

    def touch_explicit(self, max_entries: int, *, authorize: Authorize | None = None) -> None:
        """Authorize, verify alive and extend TTL, and cap at ``max_entries`` if uncapped."""
        with self._lock:
            _authorized(self, authorize)
            self._check_alive()
            if self._entry_limit is None:
                self._entry_limit = max_entries

    def peek_summary(self) -> tuple[list[_Entry], int, float, float, int] | None:
        """Read-only inspector snapshot without extending TTL; ``None`` once expired."""
        with self._lock:
            if self.expired:
                return None
            ttl_left = max(0.0, self._expires_at - self._clock())
            idle = max(0.0, self._ttl - ttl_left)
            return (
                list(self._by_placeholder.values()),
                len(self._known),
                idle,
                ttl_left,
                self._generation,
            )

    def peek_entries(
        self,
    ) -> tuple[list[tuple[tuple[EntityType, str], _Entry]], list[KnownValue]] | None:
        """Read-only entries and known values without extending TTL; ``None`` once expired."""
        with self._lock:
            if self.expired:
                return None
            return list(self._by_key.items()), self._known.values()

    def close(self) -> None:
        """Forget the mapping now. Later calls raise :class:`SessionNotFoundError`."""
        with self._lock:
            self._closed = True
            self._by_key.clear()
            self._by_placeholder.clear()
            self._identifiers.clear()
            self._reserved.clear()
            self._json_numbers.clear()
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
        """Values pre-loaded into this session (:mod:`pii_guard.vault.known`)."""
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
        """A private copy to mask in; nothing reaches this session until :meth:`commit`."""
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
            fork._json_numbers = dict(self._json_numbers)
            fork._generation = self._generation
            fork._masked = None  # its journal is replayed in full anyway
            fork._known = self._known
            fork._journal = []
            fork._parent = self
            fork.owner, fork.incarnation = self.owner, self.incarnation
            return fork

    def commit(self, fork: VaultSession) -> None:
        """Apply a :meth:`fork`'s writes to this session, in order (fail closed on conflict)."""
        with fork._lock:
            if fork._parent is not self or fork._journal is None:
                raise ValueError("not a fork of this session")
            journal, fork._journal = fork._journal, None
        with self._lock:
            if self.expired:
                self.close()
                raise SessionNotFoundError("vault session not found or expired")
            state = copy.deepcopy({name: getattr(self, name) for name in _COMMITTED_STATE})
            staged = copy.copy(self)
            staged.__dict__.update(state)
            staged.__dict__.update(
                _masked=None if self._masked is None else OrderedDict(),
                _masked_chars=0,
                _folds=OrderedDict(),
                _folded_chars=0,
                _initials=None,
                _lock=threading.RLock(),
                _journal=None,
            )
            scanned = staged.entries_scanned
            for text, spans, language, remask, expected in journal:
                result = staged.mask_with_report(text, spans, language=language, remask=remask)
                if result.text != expected:
                    raise MaskingError("the session changed while an image was masked")
            for name in (*_COMMITTED_STATE, *_RESET_CACHES):
                setattr(self, name, getattr(staged, name))
            self.entries_scanned += staged.entries_scanned - scanned
            self._check_alive()  # extend the TTL only once the commit succeeded
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
        suffixes kept outside the placeholder (``[[PERSON_7f3a]]nek``).

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
        if not _vault_attr("_REMASK_SINCE", _REMASK_SINCE):
            since = None
        with self._lock:
            self._check_alive()
            self._check_entry_limit()
            if since is not None and not self._edges_unchanged(text, since, language):
                since = None
            if since is not None and since >= self._generation:
                return MaskResult(text, (), self._generation)
            ordered = _validated(text, spans)
            key = self._memo_key(text, spans, language, remask)
            added = self._reserve_foreign(text, remask)
            try:
                result = self._mask_again(text, key, language) if key is not None else None
                if result is None:
                    result = self._mask_validated(text, ordered, language, since, key)
            except BaseException:
                for token in added:
                    self._reserved.pop(token, None)
                raise
            if self._journal is not None:
                self._journal.append((text, tuple(spans), language, remask, result.text))
            return result

    def _check_entry_limit(self) -> None:
        if self._entry_limit is not None and len(self._by_placeholder) >= self._entry_limit:
            raise SessionEntryLimitError("vault session entry limit reached; start a new session")

    def _memo_key(
        self, text: str, spans: Sequence[Span], language: str, remask: bool
    ) -> tuple[str, tuple[Span, ...], str] | None:
        if _vault_attr("_MASK_MEMO", _MASK_MEMO) and self._masked is not None and not remask:
            return (text, tuple(spans), language)
        return None

    def _reserve_foreign(self, text: str, remask: bool) -> list[str]:
        """Reserve foreign placeholder-shaped tokens in ``text``; returns newly added tokens."""
        foreign = self._foreign_tokens(text, remask)
        added = [token for token in foreign if token not in self._reserved]
        for token in foreign:
            self._reserved[token] = None
            self._reserved.move_to_end(token)
        max_reserved = _vault_attr("_MAX_RESERVED", _MAX_RESERVED)
        while len(self._reserved) > max_reserved:
            oldest = next(iter(self._reserved))
            if oldest in foreign:
                break
            del self._reserved[oldest]
        return added

    def _foreign_tokens(self, text: str, remask: bool) -> set[str]:
        """Placeholder-shaped tokens in ``text`` this session didn't issue."""
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
        """Whether no entry changed at or before ``since`` can match ``text`` anywhere new."""
        views: tuple[FoldedText, ...] | None = None
        for match in PLACEHOLDER_RE.finditer(text):
            if match.group(0) not in self._by_placeholder:
                continue
            ok, after = _edge_after_placeholder(text, match)
            if not ok:
                return False
            if after is None:
                continue
            if views is None:
                views = self._fold_views(text)
            if self._matches_at_edge(views, after, since, language):
                return False
        return True

    def _matches_at_edge(
        self, views: tuple[FoldedText, ...], after: int, since: int, language: str
    ) -> bool:
        by_initial = self._starting_with(language)
        for view in views:
            index = _folded_index(view, after)
            if index is None:
                return True
            entries = by_initial.get(_initial(view.text[index]), ())
            if any(
                entry.changed <= since and entry.matches_at(language, view.text, index)
                for entry in entries
            ):
                return True
        return False

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
        generation = self._generation
        pool: Iterable[_Entry] = self._by_key.values()
        if since is not None:
            pool = [e for e in pool if e.changed > since]
        entries = sorted(pool, key=lambda e: len(e.normalized), reverse=True)
        self.entries_scanned += len(entries)
        found = [entry.find_occurrences(language, folded, text) for entry in entries]
        self._take(text, found, language, replacements, taken)
        if depends is not None and key is not None:
            self._remember_masked(key, replacements, generation, depends, len(ordered))
        return self._assemble(text, replacements, len(ordered), generation)

    def _mask_again(
        self, text: str, key: tuple[str, tuple[Span, ...], str], language: str
    ) -> MaskResult | None:
        """Pass 1 of a text masked from the same spans before, from :attr:`_masked`."""
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
            found = [entry.find_occurrences(language, folded, text) for entry in entries]
            for _, occurrences, aliases in found:
                spans = itertools.chain(occurrences, *(o for _, o in aliases))
                if any(any(taken[start:end]) for start, end in spans):
                    return None
            self._take(text, found, language, replacements, taken)
        self._remember_masked(key, replacements, generation, masked.depends, masked.spans)
        return self._assemble(text, replacements, masked.spans, generation)

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
        max_chars = _vault_attr("_MASK_MEMO_CHARS", _MASK_MEMO_CHARS)
        max_entries = _vault_attr("_MASK_MEMO_ENTRIES", _MASK_MEMO_ENTRIES)
        if memo is None or len(text) > max_chars:
            return
        replacements.sort(key=lambda r: r[0])
        if key in memo:
            memo.move_to_end(key)
        else:
            self._masked_chars += len(text)
        memo[key] = _Masked(tuple(replacements), generation, frozenset(depends), spans)
        while len(memo) > max_entries or self._masked_chars > max_chars:
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
            now = self._clock()
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

    def _fold_views(self, text: str) -> tuple[FoldedText, ...]:
        """:func:`fold_views` of ``text``, from the session's bounded memo when it has it."""
        views = self._folds.get(text)
        if views is not None:
            self._folds.move_to_end(text)
            return views
        views = fold_views(text)
        max_chars = _vault_attr("_FOLD_MEMO_CHARS", _FOLD_MEMO_CHARS)
        max_entries = _vault_attr("_FOLD_MEMO_ENTRIES", _FOLD_MEMO_ENTRIES)
        if len(text) <= max_chars:
            self._folds[text] = views
            self._folded_chars += len(text)
            while len(self._folds) > max_entries or self._folded_chars > max_chars:
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
        """The lemma and stem of every span (see :func:`~pii_guard.vault.entry.plan_spans`)."""
        return plan_spans(text, ordered, matcher, self._by_key, depends)

    def _entry_for(
        self,
        entity_type: EntityType,
        value: str,
        language: str = "hu",
        detector: str | None = None,
    ) -> _Entry:
        """The entry of ``value``, created if new."""
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
        if detector not in NEUTRAL_DETECTORS:
            entry.detector = detector
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
            max_touched = _vault_attr("_MAX_TOUCHED", _MAX_TOUCHED)
            if len(self._touched) > max_touched:
                drop = len(self._touched) // 2
                del self._touched[:drop]
                self._touched_base += drop

    def _form(self, value: str, entity_type: EntityType) -> str:
        """The variant key of ``value``: its casing class (case-sensitive mode) and layout."""
        casing = ""
        if self._case_sensitive and entity_type not in CASE_SENSITIVE_TYPES:
            casing = casing_class(value)
        layout = _layout(value)
        return f"{casing}|{layout}" if layout else casing

    def _cased(self, entry: _Entry, written: str) -> _Entry:
        """The entry an occurrence written as ``written`` is masked with."""
        form = self._form(written, entry.entity_type)
        if form == self._form(entry.original, entry.entity_type):
            return entry
        variant = entry.variants.get(form)
        if variant is None:
            placeholder = self._new_placeholder(entry.entity_type, entry.normalized, form)
            original = entry.original
            if self._case_sensitive and entry.entity_type not in CASE_SENSITIVE_TYPES:
                original = _recased(original, written, entry.normalized, casing_class(written))
            original = _relaid(original, written)
            variant = _Entry(
                placeholder, entry.entity_type, original, entry.normalized, entry.language
            )
            variant.detector = entry.detector
            entry.variants[form] = variant
            self._by_placeholder[placeholder] = variant
        return variant

    def _new_placeholder(self, entity_type: EntityType, normalized: str, casing: str = "") -> str:
        length = self._id_length
        extra = {"casing": casing} if casing else {}
        derive = _vault_attr("derive_id", derive_id)
        while True:
            placeholder_id = derive(
                self._tenant_key, self.session_id, entity_type, normalized, length, **extra
            )
            placeholder = format_placeholder(entity_type, placeholder_id)
            if placeholder not in self._by_placeholder and placeholder not in self._reserved:
                return placeholder
            if length >= MAX_ID_LENGTH:  # pragma: no cover - a full SHA-256 collision
                raise MaskingError(f"could not derive a unique {entity_type.value} placeholder")
            length = min(length + 2, MAX_ID_LENGTH)

    # --- JSON leaf types (LAB-1361) ------------------------------------------------------

    def note_json_leaf(self, placeholder: str, number: tuple[str, str] | None) -> None:
        """Record that ``placeholder`` replaced a whole JSON number or string leaf."""
        with self._lock:
            self._check_alive()
            if placeholder not in self._by_placeholder:
                return
            if placeholder not in self._json_numbers:
                self._json_numbers[placeholder] = number
            elif self._json_numbers[placeholder] != number:
                self._json_numbers[placeholder] = None

    def json_number(self, placeholder: str) -> tuple[str, str] | None:
        """``(value text, JSON literal)`` if ``placeholder`` only ever replaced that number."""
        with self._lock:
            self._check_alive()
            return self._json_numbers.get(placeholder)

    # --- re-identification ---------------------------------------------------------------

    def restore_budget(self) -> RestoreBudget:
        """A fresh :class:`RestoreBudget` at this session's limit, for one whole output."""
        return RestoreBudget(self._max_restored)

    def unmask(self, text: str, *, budget: RestoreBudget | None = None) -> str:
        """Replace known placeholders with their original values; unknown ones stay as is."""
        return self.unmask_with_report(text, budget=budget).text

    def unmask_with_report(self, text: str, *, budget: RestoreBudget | None = None) -> UnmaskResult:
        """Like :meth:`unmask`, also listing placeholder-shaped tokens that weren't resolved."""
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
        """Every occurrence of a value this session holds that is still written out in ``texts``."""
        with self._lock:
            self._check_alive()
            views = [self._folds.get(text) or fold_views(text) for text in texts]
            joined = (FoldedText("", "\x00".join(v.text for vs in views for v in vs)),)
            taken = _placeholder_mask(texts)
            found: list[Unmasked] = []
            entries = sorted(self._by_key.values(), key=lambda e: (-len(e.normalized), e.order))
            candidates = itertools.chain(
                *(_unmasked_for_entry(e, texts, views, joined, language) for e in entries),
                _unmasked_known(self._known, views, joined[0].text, language),
            )
            for item in candidates:
                if item.end > item.start and not any(taken[item.index][item.start : item.end]):
                    taken[item.index][item.start : item.end] = b"\x01" * (item.end - item.start)
                    found.append(item)
            found.sort(key=lambda u: (u.index, u.start))
            return found

    def confirmed_values(self, entity_types: Iterable[EntityType]) -> list[str]:
        """The confirmed values of ``entity_types``, as first written, plus pre-loaded ones."""
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
