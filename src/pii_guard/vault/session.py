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
from collections import OrderedDict
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
    _Plan,
    _recased,
    _relaid,
    _validated,
    _value_key,
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
from pii_guard.vault.session_ops import assemble_masked, find_unmasked_locked, unmask_text_locked

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

#: The mask state :meth:`VaultSession.commit` replays into a staged copy and publishes
#: (LAB-1584). An allow-list: every other attribute (identity, lifecycle, limits, the lock) is
#: left as it is, so a write to one of them during a commit is never reverted. The memo
#: caches (``_masked``, ``_folds``, ``_initials``) are not copied: the staged copy starts them
#: empty, so a commit never deep-copies up to 512k characters of memo under the lock.
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

#: A check run on a session before a lookup extends its TTL; raises to refuse the caller
#: (:func:`pii_guard.gateway.sessions.check_and_bind`).
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
        # Placeholder -> (value text, JSON number literal) when it has only ever replaced a
        # whole JSON number leaf; ``None`` once it also replaced a whole string (LAB-1361).
        # Bounded: issued placeholders only.
        self._json_numbers: dict[str, tuple[str, str] | None] = {}
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

    def peek_summary[T](
        self, build: Callable[[Sequence[_Entry], int, float, float, int], T]
    ) -> T | None:
        """Read-only inspector snapshot without extending TTL; ``None`` once expired.

        ``build`` gets the entries, the known-value count, the idle and remaining TTL seconds
        and the generation, and runs while this session's lock is held: entries are mutable,
        so every field the inspector reads is read under the lock.
        """
        with self._lock:
            if self.expired:
                return None
            ttl_left = max(0.0, self._expires_at - self._clock())
            idle = max(0.0, self._ttl - ttl_left)
            return build(
                list(self._by_placeholder.values()),
                len(self._known),
                idle,
                ttl_left,
                self._generation,
            )

    def peek_entries[T](
        self,
        build: Callable[[Sequence[tuple[tuple[EntityType, str], _Entry]], list[KnownValue]], T],
    ) -> T | None:
        """Read-only entries and known values without extending TTL; ``None`` once expired.

        ``build`` runs while this session's lock is held, so it may read entry internals
        (variants, seen, surfaces, aliases, count) without racing a concurrent mask.
        """
        with self._lock:
            if self.expired:
                return None
            return build(list(self._by_key.items()), self._known.values())

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
            fork._json_numbers = dict(self._json_numbers)
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
            if self.expired:
                self.close()
                raise SessionNotFoundError("vault session not found or expired")
            # Copy the mask state together (one memo): entries, variants and generation
            # indexes must continue to refer to the same copied objects. Only the
            # :data:`_COMMITTED_STATE` allow-list is copied and published (LAB-1584).
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
        suffixes kept outside the placeholder (``[[PERSON_7f3a]]nek``). An occurrence with a
        line break inside it or decomposed accents gets a placeholder of its own, so it
        round-trips as written.

        Every form of one value shares one placeholder keyed on its lemma: a span that ends
        in a suffix is narrowed to the stem (``Próba Zsuzsannának`` -> ``[[PERSON_x]]nak``)
        and stem-changed forms (``Próba Zsuzsannát``, ``Kováccsal``) are found as occurrences.
        A single-word value that is also a common word (``Bor``/``bor``) masks that word's
        inflected forms too (``bort``): accepted over-masking (LAB-1343). Telling the surname
        from the common word would need a capitalisation or lexicon gate, and either would
        leak a lower-case name in chat text; the guard stays biased toward masking.

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
            self._check_entry_limit()
            if since is not None and not self._edges_unchanged(text, since, language):
                since = None
            if since is not None and since >= self._generation:
                # Nothing changed since the text was masked: no scan can find anything.
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
            # A fork's journal is replayed as a full remask: ``since`` is in the fork's
            # numbering, and the replay must come out the same either way (else it fails).
            if self._journal is not None:
                self._journal.append((text, tuple(spans), language, remask, result.text))
            return result

    def _check_entry_limit(self) -> None:
        # An explicit session has nobody to rotate it for (LAB-1565): fail closed rather than
        # grow without bound; the client starts a new session.
        if self._entry_limit is not None and len(self._by_placeholder) >= self._entry_limit:
            raise SessionEntryLimitError("vault session entry limit reached; start a new session")

    def _memo_key(
        self, text: str, spans: Sequence[Span], language: str, remask: bool
    ) -> tuple[str, tuple[Span, ...], str] | None:
        if _MASK_MEMO and self._masked is not None and not remask:
            return (text, tuple(spans), language)
        return None

    def _reserve_foreign(self, text: str, remask: bool) -> list[str]:
        """Reserve foreign placeholder-shaped tokens in ``text``; returns newly added tokens."""
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
        return added

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
        for match in PLACEHOLDER_RE.finditer(text):
            if match.group(0) not in self._by_placeholder:
                continue  # a token from the input itself: its neighbourhood did not change
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
            # An entry changed after ``since`` is scanned in full anyway.
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
        # Every entry up to here scans this text below; one created during the scan (an
        # alias's own entry) is newer, so a remask since this generation still scans it.
        generation = self._generation
        # Longest values first, so "Teszt Elek" wins over a separately confirmed "Elek".
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
        return assemble_masked(text, replacements, spans, generation, self._clock)

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
        The work is done by :func:`~pii_guard.vault.entry.plan_spans`.
        """
        return plan_spans(text, ordered, matcher, self._by_key, depends)

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
            variant.detector = entry.detector
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

    # --- JSON leaf types (LAB-1361) ------------------------------------------------------

    def note_json_leaf(self, placeholder: str, number: tuple[str, str] | None) -> None:
        """Record that ``placeholder`` replaced a whole JSON leaf: a number (``number`` is
        its value text and JSON literal, ``("<NUMBER>", "<NUMBER>.0")``) or a string
        (``None``). A placeholder of a session-issued value only; any mix of the two, or of
        two literals, makes it a string for good (fail closed)."""
        with self._lock:
            self._check_alive()
            if placeholder not in self._by_placeholder:
                return
            if placeholder not in self._json_numbers:
                self._json_numbers[placeholder] = number
            elif self._json_numbers[placeholder] != number:
                self._json_numbers[placeholder] = None

    def json_number(self, placeholder: str) -> tuple[str, str] | None:
        """``(value text, JSON literal)`` if ``placeholder`` only ever replaced whole JSON
        number leaves of that one literal; else ``None`` (restore it as a string)."""
        with self._lock:
            self._check_alive()
            return self._json_numbers.get(placeholder)

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
            return unmask_text_locked(text, self._by_placeholder, budget)

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
            return find_unmasked_locked(texts, self._folds, self._by_key, self._known, language)

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
