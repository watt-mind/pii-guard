"""Escalate mode (LAB-1766): fast mode, plus an LLM second look at only what fast was unsure of.

:class:`EscalatingDetector` runs the fast pipeline (rules + NER) unchanged, then:

1. **Selects** uncertain candidates (:func:`select_candidates`):

   - ``low_score``: an NER span with a score under ``low_score`` (already masked);
   - ``name``: a capitalised word no detector covered, right after a form of address
     (``Mr``, ``Frau``, ``Kedves``, before Hungarian ``úr``) or next to a ``PERSON`` span;
   - ``number``: a run of at least six digits no detector covered (rules found no checksum or
     cue); dates and amounts with a currency are left out;
   - ``conflict``: a rules span and an NER span of different types over the same text, unless
     the rules span is checksum- or format-validated (it wins in the resolver anyway).

   Text with no candidate makes no remote call: the result is fast mode's, unchanged.

2. **Windows** (:func:`build_windows`): about ``radius`` characters each side of a candidate,
   snapped to whitespace and widened so no found span is cut, at most ``max_windows`` per
   text. Only the windows are sent, never the whole text, and every span fast mode found is
   replaced by a placeholder (``[[PERSON_1]]``; a conflicting span by a neutral
   ``[[ENTITY_1]]``) in them (:func:`masked_view`): no found value leaves the machine.

3. **Asks** the LLM detector (:mod:`pii_guard.detect.llm`, Muse Spark Open by default) once per
   text with the windows joined, and maps its answer back **verbatim only**
   (:func:`~pii_guard.detect.llm.find_occurrences`, no case- or format-insensitive fallback):
   a value is kept only where it occurs in the window text, never across two windows or
   halfway into a placeholder. A value that includes a placeholder (``Jane [[PERSON_1]]``)
   maps to the original text under it, so the LLM can widen a span or settle its type.

4. **Merges add-only**: the LLM's spans join the fast spans in
   :func:`~pii_guard.detect.pipeline.resolve_spans` with the LLM as the type *adjudicator*
   (as in audit mode). The resolver never drops the characters of a losing span, so the LLM
   can add spans and decide a type conflict, never unmask anything.

**Fail closed.** A timeout (``timeout``, a hard deadline per call) or any error of the LLM call
masks the uncertain candidates that were not masked yet (``name`` as ``PERSON``, ``number`` as
``ID_DOCUMENT``) with ``on_failure="mask"`` (the default); ``on_failure="keep"`` keeps the
rules + NER result. Either way the request goes on, and the failure is counted.

**Cache.** Decisions are cached per session scope (:func:`escalation_request`), keyed by a
hash of the masked window text: the same window in the same session is not sent twice.

Nothing here logs or raises with text: counts, kinds and placeholder numbers only.
"""

from __future__ import annotations

import contextvars
import hashlib
import logging
import re
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pii_guard.detect.ner_orgs import HONORIFICS
from pii_guard.detect.pipeline import DEFAULT_KEEP_TYPES, STRUCTURED_TYPES, resolve_spans
from pii_guard.detect.rules._base import VALIDATED_ID_DOCUMENT
from pii_guard.detect.suffix_trim import trim_name_suffixes
from pii_guard.types import Detector, EntityType, Span

if TYPE_CHECKING:
    from pii_guard.config import Settings

__all__ = [
    "ESCALATE_DETECTOR",
    "Candidate",
    "EscalatingDetector",
    "EscalationRequest",
    "MaskedView",
    "RawRecorder",
    "build_windows",
    "escalation_request",
    "masked_view",
    "select_candidates",
]

logger = logging.getLogger(__name__)

#: ``Span.detector`` of the spans masked because the LLM call failed (fail closed).
ESCALATE_DETECTOR = "escalate"
#: The LLM detector's name, the resolver's adjudicator.
LLM_DETECTOR = "llm"

Kind = Literal["name", "number", "low_score", "conflict"]
#: Selection order when the window cap is reached: unmasked candidates first (a miss leaks).
_PRIORITY: dict[str, int] = {"name": 0, "number": 1, "conflict": 2, "low_score": 3}
#: What a still-unmasked candidate is masked as when the LLM call fails.
_FAIL_TYPES: dict[str, EntityType] = {
    "name": EntityType.PERSON,
    "number": EntityType.ID_DOCUMENT,
}
_SEPARATOR = "\n…\n"
_MIN_DIGITS = 6

_WORD_RE = re.compile(r"[^\W\d_][\w'\u2019-]*")
_NUMBER_RE = re.compile(r"(?<!\w)\+?\d(?:[\d \t./-]*\d)?(?!\w)")
_DATE_RE = re.compile(
    r"\d{4}[-./ ]{1,2}\d{1,2}[-./ ]{1,2}\d{1,2}\.?|\d{1,2}[-./ ]{1,2}\d{1,2}[-./ ]{1,2}\d{2,4}\.?"
)
_CURRENCY_RE = re.compile(
    r"(?:[ \t\u00a0]?(?:ft|huf|eur|euro|usd|chf|gbp|pln|zł|zl|€|\$|£)\b|[ \t\u00a0]?[€$£])",
    re.IGNORECASE,
)
_CURRENCY_BEFORE_RE = re.compile(r"(?:[€$£]|\b(?:eur|usd|huf|chf|gbp|pln))[ \t\u00a0]?$", re.I)
#: Hungarian forms of address that follow the name (``Kovács úr``).
_POSTPOSED = frozenset(
    {"úr", "ur", "úrnak", "úrral", "asszony", "asszonynak", "kisasszony", "néni", "bácsi"}
)
_NAME_GAP_RE = re.compile(r"[ \t\u00a0-]{1,2}")
_HONORIFIC_GAP_RE = re.compile(r"\.?,?[ \t\u00a0]{1,3}")


# --- Selection ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Candidate:
    """An uncertain place in a text: ``[start, end)``, why, and its fail-closed type."""

    start: int
    end: int
    kind: Kind

    @property
    def fail_type(self) -> EntityType | None:
        """The type to mask it as when the LLM call fails; ``None``: already masked."""
        return _FAIL_TYPES.get(self.kind)

    def __repr__(self) -> str:  # never the text
        return f"Candidate({self.start}, {self.end}, {self.kind})"


def _covered(spans: Sequence[Span], start: int, end: int) -> bool:
    return any(s.start < end and start < s.end for s in spans)


def _fold(word: str) -> str:
    return word.casefold().rstrip(".")


def _name_candidates(text: str, spans: Sequence[Span]) -> list[Candidate]:
    words = [(m.start(), m.end(), m.group(0)) for m in _WORD_RE.finditer(text)]
    persons = [s for s in spans if s.entity_type is EntityType.PERSON]
    out: list[Candidate] = []
    for i, (start, end, word) in enumerate(words):
        if not word[:1].isupper() or len(word) < 2 or _fold(word) in HONORIFICS:
            continue
        if _covered(spans, start, end) or _in_placeholder(text, start):
            continue
        cue = False
        for j in (i - 1, i - 2):
            if j < 0:
                break
            _, p_end, prev = words[j]
            gap = text[p_end:start] if j == i - 1 else text[p_end : words[j + 1][0]]
            if j == i - 2 and not words[j + 1][2][:1].isupper():
                break
            if _fold(prev) in HONORIFICS and _HONORIFIC_GAP_RE.fullmatch(gap):
                cue = True
                break
        if not cue and i + 1 < len(words):
            n_start, _, nxt = words[i + 1]
            cue = nxt.casefold() in _POSTPOSED and bool(
                _HONORIFIC_GAP_RE.fullmatch(text[end:n_start])
            )
        if not cue:
            # After a name (``Jane [Brightwater]``), or before one unless the word opens a
            # sentence (``Ask Jane`` is a verb, ``[Jane] Brightwater`` a first name).
            opens = _opens_sentence(text, start)
            cue = any(
                (s.end <= start and _NAME_GAP_RE.fullmatch(text[s.end : start]))
                or (not opens and end <= s.start and _NAME_GAP_RE.fullmatch(text[end : s.start]))
                for s in persons
            )
        if cue:
            out.append(Candidate(start, end, "name"))
    return out


def _opens_sentence(text: str, start: int) -> bool:
    before = text[:start].rstrip()
    return not before or before[-1] in ".!?:;\n\"'([{«„“"


def _in_placeholder(text: str, pos: int) -> bool:
    """``pos`` is inside a ``[[TYPE_id]]`` placeholder from an earlier turn."""
    opened = text.rfind("[[", max(0, pos - 64), pos + 1)
    if opened == -1:
        return False
    closed = text.find("]]", opened)
    return closed != -1 and opened <= pos < closed + 2


def _number_candidates(text: str, spans: Sequence[Span]) -> list[Candidate]:
    out: list[Candidate] = []
    for m in _NUMBER_RE.finditer(text):
        start, end = m.span()
        value = m.group(0)
        if sum(ch.isdigit() for ch in value) < _MIN_DIGITS:
            continue
        if _covered(spans, start, end) or _in_placeholder(text, start):
            continue
        if _DATE_RE.fullmatch(value.strip()):
            continue
        if _CURRENCY_RE.match(text, end) or _CURRENCY_BEFORE_RE.search(
            text[max(0, start - 5) : start]
        ):
            continue
        out.append(Candidate(start, end, "number"))
    return out


def _validated(span: Span) -> bool:
    return span.entity_type in STRUCTURED_TYPES or (
        span.entity_type is EntityType.ID_DOCUMENT and span.subtype == VALIDATED_ID_DOCUMENT
    )


def select_candidates(
    text: str,
    spans: Sequence[Span],
    raw: Sequence[Span] = (),
    *,
    low_score: float = 0.75,
) -> list[Candidate]:
    """The uncertain places in ``text``, given fast mode's resolved ``spans`` and the
    detectors' unresolved ``raw`` spans (for type conflicts). Sorted by position."""
    found: list[Candidate] = []
    found += [
        Candidate(s.start, s.end, "low_score")
        for s in spans
        if s.detector == "ner" and s.score < low_score
    ]
    found += _name_candidates(text, spans)
    found += _number_candidates(text, spans)
    fitting = [
        s for s in raw if 0 <= s.start < s.end <= len(text) and text[s.start : s.end] == s.text
    ]
    # A checksum- or format-validated rules span wins its conflict in the resolver whatever
    # the LLM says, so asking about it would only cost a call.
    rules = [s for s in fitting if s.detector == "rules" and not _validated(s)]
    ner = [s for s in fitting if s.detector == "ner"]
    for r in rules:
        for n in ner:
            if r.start < n.end and n.start < r.end and r.entity_type is not n.entity_type:
                found.append(Candidate(min(r.start, n.start), max(r.end, n.end), "conflict"))
    return sorted(set(found), key=lambda c: (c.start, c.end, c.kind))


# --- Windows -----------------------------------------------------------------------------


def _snap(
    text: str, start: int, end: int, cand: Candidate, spans: Sequence[Span]
) -> tuple[int, int]:
    start, end = max(0, start), min(len(text), end)
    if start > 0:
        ws = re.search(r"\s", text[start : min(cand.start, start + 40)])
        if ws:
            start += ws.end()
    if end < len(text):
        tail = text[max(cand.end, end - 40) : end]
        ws_at = max((m.start() for m in re.finditer(r"\s", tail)), default=None)
        if ws_at is not None:
            end = max(cand.end, end - 40) + ws_at
    for s in spans:  # never cut a found span: widen to include it (it is masked)
        if s.start < start < s.end:
            start = s.start
        if s.start < end < s.end:
            end = s.end
    return start, end


def build_windows(
    text: str,
    candidates: Sequence[Candidate],
    spans: Sequence[Span],
    *,
    radius: int = 200,
    max_windows: int = 4,
) -> tuple[list[tuple[int, int]], list[Candidate]]:
    """Windows around ``candidates`` (merged, sorted) and the candidates they cover.

    Candidates are taken by priority (unmasked ones first); one already inside a window costs
    nothing, and no new window opens once ``max_windows`` are open.
    """
    windows: list[tuple[int, int]] = []
    for cand in sorted(candidates, key=lambda c: (_PRIORITY[c.kind], c.start)):
        if any(ws <= cand.start and cand.end <= we for ws, we in windows):
            continue
        if len(windows) >= max_windows:
            continue
        windows.append(_snap(text, cand.start - radius, cand.end + radius, cand, spans))
    windows.sort()
    merged: list[tuple[int, int]] = []
    for ws, we in windows:
        if merged and ws <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], we))
        else:
            merged.append((ws, we))
    covered = [c for c in candidates if any(ws <= c.start and c.end <= we for ws, we in merged)]
    return merged, covered


@dataclass
class MaskedView:
    """The windows as sent: found spans replaced by placeholders, and where each character
    came from. ``origin[i]`` is the original ``(start, end)`` of character ``i`` (a
    placeholder's characters all map to its whole span), ``None`` for a separator.
    ``token[i]`` is the placeholder's ``(start, end)`` in the view for its characters."""

    text: str
    origin: list[tuple[int, int] | None]
    token: list[tuple[int, int] | None]
    placeholders: int = 0

    def __repr__(self) -> str:  # never the text
        return f"MaskedView(chars={len(self.text)}, placeholders={self.placeholders})"

    def to_original(self, start: int, end: int) -> tuple[int, int] | None:
        """The original range under view ``[start, end)``, or ``None`` when it crosses a
        window separator or starts or ends inside a placeholder."""
        if not 0 <= start < end <= len(self.text):
            return None
        if any(self.origin[i] is None for i in range(start, end)):
            return None
        first, last = self.token[start], self.token[end - 1]
        if (first is not None and first[0] != start) or (last is not None and last[1] != end):
            return None
        a, b = self.origin[start], self.origin[end - 1]
        if a is None or b is None:  # pragma: no cover - excluded above
            return None
        return a[0], b[1]


def masked_view(
    text: str,
    windows: Sequence[tuple[int, int]],
    spans: Sequence[Span],
    neutral: Sequence[Candidate] = (),
) -> MaskedView:
    """``windows`` of ``text`` joined by a separator, every span in ``spans`` masked."""
    parts: list[str] = []
    origin: list[tuple[int, int] | None] = []
    token: list[tuple[int, int] | None] = []
    number = 0
    length = 0

    def add(chunk: str, src: tuple[int, int] | None, tok: bool) -> None:
        nonlocal length
        parts.append(chunk)
        bounds = (length, length + len(chunk)) if tok else None
        for i, _ in enumerate(chunk):
            origin.append(src if tok or src is None else (src[0] + i, src[0] + i + 1))
            token.append(bounds)
        length += len(chunk)

    ordered = sorted(spans, key=lambda s: s.start)
    for w, (ws, we) in enumerate(windows):
        if w:
            add(_SEPARATOR, None, False)
        pos = ws
        for s in ordered:
            if s.end <= ws or s.start >= we:
                continue
            if s.start > pos:
                add(text[pos : s.start], (pos, s.start), False)
            number += 1
            label = (
                "ENTITY"
                if any(c.start < s.end and s.start < c.end for c in neutral)
                else s.entity_type.value
            )
            add(f"[[{label}_{number}]]", (s.start, s.end), True)
            pos = max(pos, s.end)
        if pos < we:
            add(text[pos:we], (pos, we), False)
    return MaskedView("".join(parts), origin, token, number)


# --- Per-request state -------------------------------------------------------------------


@dataclass
class EscalationRequest:
    """One gateway request's escalation scope and counts (no text)."""

    #: The cache scope: the vault session (and its incarnation). ``None``: no cache.
    scope: str | None = None
    #: Texts escalated at most, per request.
    max_texts: int | None = None
    escalations: int = 0
    cache_hits: int = 0
    failures: int = 0
    capped: int = 0
    llm_ms: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def take(self) -> bool:
        """Reserve one escalation; ``False`` when the request's cap is reached."""
        with self._lock:
            if self.max_texts is not None and self.escalations >= self.max_texts:
                self.capped += 1
                return False
            self.escalations += 1
            return True

    def add(self, **deltas: float) -> None:
        with self._lock:
            for key, delta in deltas.items():
                setattr(self, key, getattr(self, key) + delta)


_REQUEST: contextvars.ContextVar[EscalationRequest | None] = contextvars.ContextVar(
    "pii_guard_escalation_request", default=None
)
_RAW: contextvars.ContextVar[dict[str, list[Span]] | None] = contextvars.ContextVar(
    "pii_guard_escalation_raw", default=None
)


@contextmanager
def escalation_request(
    scope: str | None = None, *, max_texts: int | None = None
) -> Iterator[EscalationRequest]:
    """Scope the detections run inside (worker threads included, which copy the context) to
    one request: its cache scope, its escalation cap, and the counts it reports."""
    request = EscalationRequest(scope=scope, max_texts=max_texts)
    token = _REQUEST.set(request)
    try:
        yield request
    finally:
        _REQUEST.reset(token)


class RawRecorder:
    """Passes a detector through and keeps its unresolved spans per text, for conflict
    candidates (only inside :meth:`EscalatingDetector.detect_many`)."""

    def __init__(self, inner: Detector) -> None:
        self.inner = inner
        self.name = inner.name

    def __repr__(self) -> str:
        return f"RawRecorder({self.inner!r})"

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        found = self.inner.detect(text, language)
        self._keep(text, found)
        return found

    def detect_batch(self, texts: Sequence[str], language: str = "hu") -> list[list[Span]]:
        batch = getattr(self.inner, "detect_batch", None)
        found = (
            batch(texts, language)
            if batch is not None
            else [self.inner.detect(t, language) for t in texts]
        )
        if isinstance(found, list) and len(found) == len(texts):
            for text, spans in zip(texts, found, strict=True):
                self._keep(text, spans)
        return found

    @staticmethod
    def _keep(text: str, found: object) -> None:
        store = _RAW.get()
        if store is not None and isinstance(found, list):
            store.setdefault(text, []).extend(s for s in found if isinstance(s, Span))


class _DecisionCache:
    """LLM answers per (scope, language, masked view), LRU-bounded."""

    def __init__(self, size: int) -> None:
        self.size = size
        self._items: OrderedDict[bytes, tuple[tuple[EntityType, str], ...]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def key(scope: str, language: str, model: str, view: str) -> bytes:
        h = hashlib.sha256()
        for part in (scope, language, model, view):
            h.update(part.encode("utf-8", "surrogatepass"))
            h.update(b"\0")
        return h.digest()

    def get(self, key: bytes) -> tuple[tuple[EntityType, str], ...] | None:
        with self._lock:
            found = self._items.get(key)
            if found is not None:
                self._items.move_to_end(key)
            return found

    def put(self, key: bytes, value: tuple[tuple[EntityType, str], ...]) -> None:
        if self.size <= 0:
            return
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)


# --- The detector ------------------------------------------------------------------------

#: Counters in :attr:`EscalatingDetector.usage` (counts only).
USAGE_KEYS = (
    "texts",
    "escalated_texts",
    "windows",
    "window_chars",
    "candidates",
    "cache_hits",
    "failures",
    "capped",
    "added_spans",
)


@dataclass
class _Plan:
    index: int
    view: MaskedView
    candidates: list[Candidate]
    windows: int


class EscalatingDetector:
    """Fast mode's pipeline plus an LLM look at only its uncertain spans. A :class:`Detector`.

    ``fast`` is the fast pipeline (a :class:`~pii_guard.detect.pipeline.DetectionPipeline`
    whose detectors are wrapped in :class:`RawRecorder` to report type conflicts); ``llm``
    is the LLM detector (:class:`~pii_guard.detect.llm.LlmDetector`; any detector with
    ``detect`` works, for tests). ``on_llm_ms`` receives the escalation wall time per call,
    in the calling thread (the gateway adds it to the request's detector timings).
    """

    name = "escalate"

    def __init__(
        self,
        fast: Detector,
        llm: Detector,
        *,
        radius: int = 200,
        max_windows: int = 4,
        low_score: float = 0.75,
        timeout: float = 10.0,
        on_failure: Literal["mask", "keep"] = "mask",
        cache_size: int = 2048,
        workers: int = 8,
        settings: Settings | None = None,
        on_llm_ms: Callable[[float], None] | None = None,
    ) -> None:
        if on_failure not in ("mask", "keep"):
            raise ValueError("on_failure must be 'mask' or 'keep'")
        if timeout <= 0 or radius < 1 or max_windows < 1:
            raise ValueError("timeout, radius and max_windows must be positive")
        self._settings = settings
        self._refuse()
        self.fast = fast
        self.llm = llm
        self.inner = llm  # unavailable_reason() looks through ``inner`` for the LLM's key
        self.radius = radius
        self.max_windows = max_windows
        self.low_score = low_score
        self.timeout = timeout
        self.on_failure = on_failure
        self.on_llm_ms = on_llm_ms
        self.model = str(getattr(llm, "model", "") or "")
        self._cache = _DecisionCache(cache_size)
        self._pool = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="pii-guard-escalate"
        )
        self.usage: dict[str, int] = dict.fromkeys(USAGE_KEYS, 0)
        #: Wall time (ms) of each escalation call, newest last, for latency percentiles.
        self.latencies_ms: deque[float] = deque(maxlen=10_000)
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"EscalatingDetector(model={self.model!r}, radius={self.radius})"

    @property
    def detectors(self) -> list[Detector]:
        return [*getattr(self.fast, "detectors", [self.fast]), self.llm]

    @property
    def unavailable_reason(self) -> str | None:
        reason = getattr(self.llm, "unavailable_reason", None)
        if isinstance(reason, str) and reason:
            return reason.replace("audit mode", "escalate mode", 1)
        return None

    def _refuse(self) -> None:
        if self._settings is not None:
            from pii_guard.detection_profile import refuse_remote

            refuse_remote(self._settings, "escalate detection (LLM escalation)")

    def _count(self, **deltas: int) -> None:
        with self._lock:
            for key, delta in deltas.items():
                self.usage[key] += delta

    # -- Detector --

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        return self.detect_many([text], language)[0]

    def detect_many(self, texts: Sequence[str], language: str = "hu") -> list[list[Span]]:
        """Fast mode's spans for every text, then one escalation per text that has
        uncertain candidates (run in parallel, each under ``timeout``)."""
        self._refuse()
        texts = list(texts)
        raw: dict[str, list[Span]] = {}
        token = _RAW.set(raw)
        try:
            many = getattr(self.fast, "detect_many", None)
            fast = (
                many(texts, language)
                if many is not None
                else [self.fast.detect(t, language) for t in texts]
            )
        finally:
            _RAW.reset(token)
        self._count(texts=len(texts))
        plans: list[_Plan] = []
        for i, text in enumerate(texts):
            spans = fast[i]
            candidates = select_candidates(text, spans, raw.get(text, ()), low_score=self.low_score)
            if not candidates:
                continue
            windows, covered = build_windows(
                text, candidates, spans, radius=self.radius, max_windows=self.max_windows
            )
            neutral = [c for c in covered if c.kind == "conflict"]
            view = masked_view(text, windows, spans, neutral)
            plans.append(_Plan(i, view, covered, len(windows)))
        if not plans:
            return [list(spans) for spans in fast]
        request = _REQUEST.get()
        started = time.perf_counter()
        answers = self._ask_all(plans, language, request)
        elapsed = (time.perf_counter() - started) * 1000
        if self.on_llm_ms is not None:
            self.on_llm_ms(elapsed)
        if request is not None:
            request.add(llm_ms=elapsed)
        out = [list(spans) for spans in fast]
        for plan in plans:
            answer = answers.get(plan.index)
            if answer is _SKIPPED:
                continue
            out[plan.index] = self._merge(
                texts[plan.index], fast[plan.index], plan, answer, language
            )
        return out

    # -- LLM --

    def _ask_all(
        self, plans: list[_Plan], language: str, request: EscalationRequest | None
    ) -> dict[int, Any]:
        """``{text index: entities | None (failed) | _SKIPPED}``."""
        answers: dict[int, Any] = {}
        futures: dict[int, tuple[Future[list[tuple[EntityType, str]]], bytes | None, float]] = {}
        for plan in plans:
            key = None
            if request is not None and request.scope is not None:
                key = self._cache.key(request.scope, language, self.model, plan.view.text)
                cached = self._cache.get(key)
                if cached is not None:
                    answers[plan.index] = list(cached)
                    self._count(cache_hits=1)
                    request.add(cache_hits=1)
                    continue
            if request is not None and not request.take():
                answers[plan.index] = _SKIPPED
                self._count(capped=1)
                continue
            self._count(
                escalated_texts=1,
                windows=plan.windows,
                window_chars=len(plan.view.text),
                candidates=len(plan.candidates),
            )
            context = contextvars.copy_context()
            future = self._pool.submit(context.run, self._ask, plan.view.text, language)
            futures[plan.index] = (future, key, time.perf_counter())
        deadline = time.monotonic() + self.timeout
        for index, (future, key, submitted) in futures.items():
            try:
                found = future.result(timeout=max(0.0, deadline - time.monotonic()))
            except FutureTimeout:
                future.cancel()
                logger.warning("escalation timed out after %gs; failing closed", self.timeout)
                answers[index] = None
            except Exception as exc:
                # Never str(exc): it may quote the input.
                logger.warning("escalation failed (%s); failing closed", type(exc).__name__)
                answers[index] = None
            else:
                answers[index] = found
                if key is not None:
                    self._cache.put(key, tuple(found))
            finally:
                with self._lock:
                    self.latencies_ms.append((time.perf_counter() - submitted) * 1000)
            if answers[index] is None:
                self._count(failures=1)
                if request is not None:
                    request.add(failures=1)
        return answers

    def _ask(self, view: str, language: str) -> list[tuple[EntityType, str]]:
        """The LLM's ``(type, surface text)`` answers for ``view``. Raises on failure."""
        from pii_guard.detect.llm import LlmDetector, chunk_text

        self._refuse()
        llm = self.llm
        if isinstance(llm, LlmDetector):
            llm.require_available()
            entities = []
            # The detector's own client and chunk call (key check, retries, JSON parsing).
            with llm._client() as client:  # noqa: SLF001
                for _, chunk in chunk_text(view, llm.chunk_size, llm.chunk_overlap):
                    entities.extend(llm._detect_chunk(client, chunk, language))  # noqa: SLF001
            return [(e.entity_type, e.text) for e in entities]
        return [(s.entity_type, s.text) for s in llm.detect(view, language)]

    # -- Merge --

    def _merge(
        self,
        text: str,
        spans: list[Span],
        plan: _Plan,
        answer: list[tuple[EntityType, str]] | None,
        language: str,
    ) -> list[Span]:
        if answer is None:  # the call failed: fail closed
            if self.on_failure == "keep":
                return list(spans)
            added = [
                Span(c.start, c.end, t, text[c.start : c.end], 0.5, ESCALATE_DETECTOR)
                for c in plan.candidates
                if (t := c.fail_type) is not None and not _covered(spans, c.start, c.end)
            ]
        else:
            added = trim_name_suffixes(text, align(text, plan.view, answer, language), language)
            added = [
                s
                for s in added
                if not any(
                    (f.start, f.end, f.entity_type) == (s.start, s.end, s.entity_type)
                    for f in spans
                )
            ]
        if not added:
            return list(spans)
        self._count(added_spans=len(added))
        fast = self.fast
        order = [getattr(d, "name", "") for d in getattr(fast, "detectors", [])]
        return resolve_spans(
            text,
            [*spans, *added],
            detector_order=[*order, LLM_DETECTOR, ESCALATE_DETECTOR],
            authoritative=getattr(fast, "authoritative", ("rules",)),
            adjudicator=LLM_DETECTOR,
            keep_types=getattr(fast, "keep_types", DEFAULT_KEEP_TYPES),
            overriding=getattr(fast, "overriding", ("known",)),
        )


_SKIPPED: Any = object()


def align(
    text: str, view: MaskedView, answer: Sequence[tuple[EntityType, str]], language: str
) -> list[Span]:
    """The LLM's answer as spans over ``text``: each value found **verbatim** in the view
    (:func:`~pii_guard.detect.llm.find_occurrences`) and mapped back through it. Values that
    are not in the view, cross a separator or cut a placeholder are dropped."""
    from pii_guard.detect.llm import find_occurrences, language_profile

    profile = language_profile(language)
    out: set[Span] = set()
    dropped = 0
    for entity_type, value in dict.fromkeys(answer):
        if entity_type.is_visual:
            continue
        hits = find_occurrences(
            view.text,
            value,
            word_boundary=profile.word_boundary,
            allow_suffix=profile.allow_suffix,
        )
        mapped = [r for a, b in hits if (r := view.to_original(a, b)) is not None]
        if not mapped:
            dropped += 1
        for start, end in mapped:
            if any(ch.isalnum() for ch in text[start:end]):
                out.add(Span(start, end, entity_type, text[start:end], 0.85, LLM_DETECTOR))
    if dropped:
        logger.info("escalation dropped %d values not found verbatim in the windows", dropped)
    return sorted(out, key=lambda s: (s.start, s.end, s.entity_type.value))
