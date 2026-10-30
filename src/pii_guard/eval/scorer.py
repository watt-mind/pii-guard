"""Scoring: span precision/recall/F1, leak rate, over-masking, round trip and latency.

Pure functions on gold and predicted spans (:func:`match_counts`, :func:`prf`,
:func:`leak_report`, :func:`over_masked`) plus :func:`run_documents`, which runs an analyzer
and the vault over fixture documents, and :func:`summarize`, which turns the results into
one score block (per entity type, micro and macro).

Definitions (``docs/evaluation.md``):

- **exact** match: same ``start``, ``end`` and ``entity_type``.
- **overlap** match: same ``entity_type`` and at least one shared character. Precision
  counts predictions that overlap some gold span, recall counts gold spans that overlap some
  prediction (not one-to-one: one long prediction can cover two gold spans).
- Undefined ratios (no predictions, no gold spans) are ``None``; F1 is 0 when either side
  is 0. Macro averages run over every type with gold or predicted spans, undefined as 0.
- **Leak rate**: distinct labelled values (per document, entity type and normalized value)
  of a ``mask``-policy type for which any surface form
  (:func:`pii_guard.eval.forms.find_surface_forms`) survives in the masked text.
  **Partial leak**: not fully leaked, but an identifying token of the value survives (a
  token of 3+ letters or 4+ digits that is not a language stopword and doesn't also occur in
  the original text outside the gold spans), or, when the vault's replacements are known,
  digits of an occurrence are left right next to its placeholder: a digit run the placeholder
  edge cuts (``[[ID_DOCUMENT_x]]010``, ``8[[NATIONAL_ID_HU_TAX_x]]``) or one joined to it by
  ``.``, ``-`` or ``/`` (``[[ID_DOCUMENT_x]].91``). These are a few digits of an identifier,
  too short to count as a token on their own (LAB-1367).
- **Over-masking rate**: masked predicted spans that overlap no gold span of any type (a share
  of spans, not of characters).
- **Unscored predictions**: a prediction that overlaps one of the document's *ignore regions*
  (``meta.ignore``: text the source labelled but pii-guard's policy doesn't score, such as any
  date in a public dataset) and matches no gold span is left out of precision and
  over-masking: it is neither credited nor charged. Recall and leak rate don't change.
  Documents of a kind in :data:`LEGACY_UNSCORED_TYPES` that carry no ignore regions (a sample
  converted before they existed) apply the same rule per type instead.
- **Round trip**: documents where ``unmask(mask(text)) == text``.
- **Placeholder consistency**: gold entities (per document, of a ``mask``-policy type) whose
  occurrences are all masked by one and the same placeholder. An entity groups the gold spans
  of one type that are surface forms of each other (``Minta Anna``, ``Minta Annának``,
  ``TESZT ELEK``; :func:`pii_guard.eval.forms.surface_pattern`). An occurrence counts only if
  it is fully covered: every letter and digit of the gold span lies inside the placeholder,
  except a trailing case ending or possessive the language's inflection matcher reads as a
  suffix (the vault keeps it outside: ``[[PERSON_x]]nak``) and whole words that identify no
  one by the partial-leak rule (``Ms``, ``Frau``, ``MD``). An occurrence left unmasked
  or masked only in part (``[[PERSON_x]]inta Anna``, ``Próba [[PERSON_x]]``, digits left next
  to the placeholder as in the partial-leak rule: ``[[ID_x]].91``) makes its entity
  inconsistent (LAB-1355, LAB-1367).
  ``multi_rate`` counts only entities with 2+ occurrences.
- **Number validity** (public sets only): recall and leak split by whether a structured
  identifier passes the language packs' validators, plus the leak of every other value
  (:mod:`pii_guard.eval.validity`). The headline counts are not changed by it.
"""

from __future__ import annotations

import re
import statistics
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from pii_guard.detect.normalize import normalize_for_detection
from pii_guard.detect.pipeline import DetectionPipeline
from pii_guard.eval.fixtures import Document, GoldSpan, ignore_regions
from pii_guard.eval.forms import find_surface_forms, language_forms, surface_pattern
from pii_guard.eval.stats import percentile
from pii_guard.policy import DEFAULT_POLICIES, PolicySet
from pii_guard.registry import create_detector
from pii_guard.types import TEXT_ENTITY_TYPES, DetectionError, Detector, EntityType, Span
from pii_guard.vault import CASE_SENSITIVE_TYPES, PLACEHOLDER_RE, Vault, normalize_value
from pii_guard.vault.inflection import inflection_for, splits

__all__ = [
    "DEFAULT_POLICY",
    "EVAL_TENANT_KEY",
    "LEGACY_UNSCORED_TYPES",
    "Analyzer",
    "DetectorAnalyzer",
    "DocumentResult",
    "EntityConsistency",
    "MatchMode",
    "TypeCounts",
    "ValueLeak",
    "consistency_report",
    "leak_report",
    "match_counts",
    "over_masked",
    "prf",
    "run_documents",
    "summarize",
    "unscored",
]

MatchMode = Literal["exact", "overlap"]

#: Default text-type policies (:data:`pii_guard.policy.DEFAULT_POLICIES`, from
#: ``docs/entities.md``): everything is masked except organisations and company identifiers,
#: which the model needs to reason and which aren't personal data. Values are
#: :class:`~pii_guard.policy.Policy` members, which compare equal to ``"mask"``/``"keep"``.
DEFAULT_POLICY: Mapping[EntityType, str] = {t: DEFAULT_POLICIES[t] for t in TEXT_ENTITY_TYPES}

#: Per ``meta.kind``: predicted types that can't be scored on documents without ignore regions.
#: Ai4Privacy labels every date ``DATE``, which pii-guard's policy excludes, so a
#: ``DATE_OF_BIRTH`` prediction there can be neither confirmed nor refuted.
LEGACY_UNSCORED_TYPES: Mapping[str, frozenset[EntityType]] = {
    "public-ai4privacy": frozenset(
        {
            EntityType.DATE_OF_BIRTH,
            EntityType.ORGANIZATION,
            EntityType.VEHICLE_PLATE,
            EntityType.PARCEL_NUMBER_HU,
            EntityType.COMPANY_ID_HU,
        }
    ),
}

#: Fixed, public key for evaluation runs only, so placeholders are reproducible.
EVAL_TENANT_KEY = b"pii-guard-evaluation-only-key-v1"


class _SpanLike(Protocol):
    @property
    def start(self) -> int: ...
    @property
    def end(self) -> int: ...
    @property
    def entity_type(self) -> EntityType: ...


# --- Detection metrics -------------------------------------------------------------------


@dataclass(slots=True)
class TypeCounts:
    """Counts for one entity type. ``tp_pred``/``tp_gold`` differ only in overlap mode."""

    gold: int = 0
    pred: int = 0
    tp_pred: int = 0
    tp_gold: int = 0

    def __iadd__(self, other: TypeCounts) -> TypeCounts:
        self.gold += other.gold
        self.pred += other.pred
        self.tp_pred += other.tp_pred
        self.tp_gold += other.tp_gold
        return self

    @property
    def precision(self) -> float | None:
        return self.tp_pred / self.pred if self.pred else None

    @property
    def recall(self) -> float | None:
        return self.tp_gold / self.gold if self.gold else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None and r is None:
            return None
        if not p or not r:
            return 0.0
        return 2 * p * r / (p + r)

    def to_dict(self) -> dict[str, object]:
        return {
            "gold": self.gold,
            "pred": self.pred,
            "tp_pred": self.tp_pred,
            "tp_gold": self.tp_gold,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
        }


def _matches(gold: _SpanLike, pred: _SpanLike, mode: MatchMode) -> bool:
    if gold.entity_type != pred.entity_type:
        return False
    if mode == "exact":
        return gold.start == pred.start and gold.end == pred.end
    return gold.start < pred.end and pred.start < gold.end


def match_counts(
    gold: Iterable[_SpanLike], pred: Iterable[_SpanLike], mode: MatchMode
) -> dict[EntityType, TypeCounts]:
    """Per-type counts for one document."""
    gold, pred = list(gold), list(pred)
    counts: dict[EntityType, TypeCounts] = defaultdict(TypeCounts)
    for g in gold:
        counts[g.entity_type].gold += 1
        if any(_matches(g, p, mode) for p in pred):
            counts[g.entity_type].tp_gold += 1
    for p in pred:
        counts[p.entity_type].pred += 1
        if any(_matches(g, p, mode) for g in gold):
            counts[p.entity_type].tp_pred += 1
    return dict(counts)


def prf(counts: Mapping[EntityType, TypeCounts]) -> dict[str, object]:
    """Per-type, micro and macro precision/recall/F1 for accumulated counts."""
    micro = TypeCounts()
    for c in counts.values():
        micro += c
    present = [c for c in counts.values() if c.gold or c.pred]

    def macro(attr: str) -> float | None:
        if not present:
            return None
        return statistics.fmean(getattr(c, attr) or 0.0 for c in present)

    return {
        "per_type": {t.value: counts[t].to_dict() for t in sorted(counts, key=_type_order)},
        "micro": micro.to_dict(),
        "macro": {"precision": macro("precision"), "recall": macro("recall"), "f1": macro("f1")},
    }


_TYPE_ORDER = {t: i for i, t in enumerate(EntityType)}


def _type_order(t: EntityType) -> int:
    return _TYPE_ORDER[t]


# --- Leak rate ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[^\W_]+")
_OBJECT = "￼"  # stands in for a placeholder: not a word character, so boundaries hold


@dataclass(frozen=True, slots=True)
class ValueLeak:
    """Leak result for one distinct labelled value. Never repr'd with the value."""

    entity_type: EntityType
    occurrences: int
    leaked: bool
    partial: bool
    #: The labelled value (first occurrence), for in-process breakdowns only: never in
    #: ``repr`` or :meth:`to_dict`.
    value: str = field(default="", repr=False, compare=False)

    def to_dict(self) -> dict[str, object]:
        return {
            "entity_type": self.entity_type.value,
            "occurrences": self.occurrences,
            "leaked": self.leaked,
            "partial": self.partial,
        }


def _strip_placeholders(masked_text: str) -> str:
    return PLACEHOLDER_RE.sub(_OBJECT, masked_text)


def _identifying_tokens(value: str, entity_type: EntityType, stopwords: frozenset[str]) -> set[str]:
    if entity_type is EntityType.EMAIL and "@" in value:
        value = value.split("@", 1)[0]  # the domain is usually shared and not identifying
    tokens: set[str] = set()
    for token in _TOKEN_RE.findall(value):
        folded = token.casefold()
        if folded in stopwords:
            continue
        if (token.isdigit() and len(token) >= 4) or (not token.isdigit() and len(token) >= 3):
            tokens.add(folded)
    return tokens


#: Characters that join digit groups inside one identifier (``812.754.113.91``, ``06-20``).
_DIGIT_JOINERS = ".-/"


def _digits_at_edge(text: str, covered: Sequence[bool], i: int, j: int) -> bool:
    """True if the uncovered ``text[i:j]`` leaves digits right next to a covered neighbour.

    ``covered[k]`` says whether ``text[k]`` lies inside a placeholder. Digits count when the
    edge cuts their run (``[[ID_x]]010``: a covered alphanumeric next to a digit) or when one
    joiner (:data:`_DIGIT_JOINERS`) stands between a covered digit and them (``[[ID_x]].91``).
    """
    gap = text[i:j]
    if i > 0 and covered[i - 1]:
        before = text[i - 1]
        if gap[0].isdigit() and before.isalnum():
            return True
        if len(gap) > 1 and gap[0] in _DIGIT_JOINERS and gap[1].isdigit() and before.isdigit():
            return True
    if j < len(text) and covered[j]:
        after = text[j]
        if gap[-1].isdigit() and after.isalnum():
            return True
        if len(gap) > 1 and gap[-1] in _DIGIT_JOINERS and gap[-2].isdigit() and after.isdigit():
            return True
    return False


def _gaps(text: str, covered: Sequence[bool]) -> Iterator[tuple[int, int]]:
    """The maximal uncovered runs ``[i, j)`` of ``text``."""
    i = 0
    while i < len(text):
        if covered[i]:
            i += 1
            continue
        j = i
        while j < len(text) and not covered[j]:
            j += 1
        yield i, j
        i = j


def _coverage(span: GoldSpan, replacements: Sequence[tuple[int, int, str]]) -> list[bool]:
    hits = [(s, e) for s, e, _ in replacements if s < span.end and span.start < e]
    return [any(s <= i < e for s, e in hits) for i in range(span.start, span.end)]


def _digits_left(span: GoldSpan, replacements: Sequence[tuple[int, int, str]]) -> bool:
    """True if a placeholder covers part of ``span`` and leaves digits of it at its edge."""
    covered = _coverage(span, replacements)
    if not any(covered):
        return False
    return any(_digits_at_edge(span.text, covered, i, j) for i, j in _gaps(span.text, covered))


_WHITESPACE_RUN = re.compile(r"\s+")


def _value_key(entity_type: EntityType, value: str) -> str:
    """The key a gold value is grouped by, as the vault keys it (LAB-1350, LAB-1382).

    :func:`normalize_value` (case-folded) for most types. :data:`CASE_SENSITIVE_TYPES`
    (``SECRET``) keep their case: ``AbC1`` and ``aBc1`` are two credentials with two
    placeholders, so they are two values here too. Only the detection fold (invisible
    characters, Unicode form, spaces and dashes) and whitespace runs are normalized.
    """
    if entity_type in CASE_SENSITIVE_TYPES:
        return _WHITESPACE_RUN.sub(" ", normalize_for_detection(value).text).strip()
    return normalize_value(value)


def _same_value(entity_type: EntityType, value: str, written: str) -> bool:
    """Whether ``written`` (a case-insensitive surface match) is ``value`` for its type."""
    if entity_type not in CASE_SENSITIVE_TYPES:
        return True
    return _value_key(entity_type, written) == _value_key(entity_type, value)


def leak_report(
    doc: Document,
    masked_text: str,
    *,
    policy: Mapping[EntityType, str] = DEFAULT_POLICY,
    replacements: Sequence[tuple[int, int, str]] | None = None,
) -> list[ValueLeak]:
    """Which labelled values of ``doc`` survive in ``masked_text`` (the text sent upstream).

    Only ``mask``-policy types are checked. Placeholders are removed before searching, so a
    hex placeholder id never counts as a surviving value. With ``replacements`` (the vault's
    ``(start, end, placeholder)``), digits of an occurrence left at its placeholder's edge
    also make the value partially leaked (see the module docstring).
    """
    clean = _strip_placeholders(masked_text)
    forms = language_forms(doc.language)
    groups: dict[tuple[EntityType, str], list[GoldSpan]] = defaultdict(list)
    for span in doc.spans:
        if policy.get(span.entity_type, "mask") == "mask":
            groups[(span.entity_type, _value_key(span.entity_type, span.text))].append(span)

    # Tokens that also occur outside every gold span don't prove anything when they survive.
    outside = list(doc.text)
    for span in doc.spans:
        outside[span.start : span.end] = " " * (span.end - span.start)
    outside_text = "".join(outside)

    report: list[ValueLeak] = []
    for (entity_type, _), spans in groups.items():
        value = spans[0].text
        leaked = any(
            _same_value(entity_type, value, clean[a:b])
            for a, b in find_surface_forms(clean, value, entity_type, doc.language)
        )
        partial = False
        if not leaked:
            for token in _identifying_tokens(value, entity_type, forms.stopwords):
                if find_surface_forms(outside_text, token, EntityType.PERSON, doc.language):
                    continue
                if find_surface_forms(clean, token, EntityType.PERSON, doc.language):
                    partial = True
                    break
            if not partial and replacements:
                partial = any(_digits_left(span, replacements) for span in spans)
        report.append(ValueLeak(entity_type, len(spans), leaked, partial, value))
    return report


# --- Placeholder consistency -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EntityConsistency:
    """Consistency of one gold entity. Never repr'd with its value."""

    entity_type: EntityType
    occurrences: int
    consistent: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "entity_type": self.entity_type.value,
            "occurrences": self.occurrences,
            "consistent": self.consistent,
        }


def _gold_entities(doc: Document, policy: Mapping[EntityType, str]) -> list[list[GoldSpan]]:
    """Gold spans grouped into entities: same type, surface forms of the shortest value."""
    groups: list[tuple[GoldSpan, list[GoldSpan]]] = []
    candidates = [s for s in doc.spans if policy.get(s.entity_type, "mask") == "mask"]
    for span in sorted(candidates, key=lambda s: (len(s.text), s.start)):
        for head, members in groups:
            if head.entity_type is not span.entity_type:
                continue
            if _value_key(head.entity_type, head.text) == _value_key(
                span.entity_type, span.text
            ) or (
                _same_value(head.entity_type, head.text, span.text)
                and surface_pattern(head.text, head.entity_type, doc.language).fullmatch(span.text)
            ):
                members.append(span)
                break
        else:
            groups.append((span, [span]))
    return [members for _, members in groups]


def _fully_covered(span: GoldSpan, hits: Sequence[tuple[int, int, str]], language: str) -> bool:
    """True if ``hits`` leave nothing identifying of ``span`` outside a placeholder.

    Text of the span outside the placeholder is allowed only as

    - whole words that identify no one, by the partial-leak rule (:func:`_identifying_tokens`):
      a title or short particle (``Ms [[PERSON_x]]``, ``Frau [[PERSON_x]]``, ``, MD``);
    - a case ending or possessive right after the placeholder at the end of the span, which
      the language's inflection matcher reads as a suffix of it and the vault keeps outside
      on purpose (``[[PERSON_x]]nak``, ``[[PERSON_x]]'s``).

    ``[[PERSON_x]]inta Anna``, ``Minta [[PERSON_x]]``, ``[[ID_x]]010`` and ``[[ID_x]].91``
    are not covered.
    """
    if not hits:
        return False
    text = span.text
    covered = [any(s <= i < e for s, e, _ in hits) for i in range(span.start, span.end)]
    if not any(covered):
        return False
    stopwords = language_forms(language).stopwords
    for i, j in _gaps(text, covered):
        gap = text[i:j]
        cut_left = i > 0 and gap[0].isalnum() and text[i - 1].isalnum()
        cut_right = j < len(text) and gap[-1].isalnum() and text[j].isalnum()
        suffix = cut_left and j == len(text) and _is_suffix(span, i, language)
        if not suffix and (
            cut_left
            or cut_right
            or _digits_at_edge(text, covered, i, j)
            or _identifying_tokens(gap, span.entity_type, stopwords)
        ):
            return False
    return True


def _is_suffix(span: GoldSpan, at: int, language: str) -> bool:
    """True if ``span.text[at:]`` (bar trailing punctuation) is a suffix of ``span.text[:at]``."""
    tail = _TRAILING_PUNCT_RE.sub("", span.text[at:])
    if not tail or any(ch.isspace() for ch in tail):
        return False
    matcher = inflection_for(language)
    if any(split.suffix == tail for split in splits(matcher, span.text, span.entity_type)):
        return True
    pattern = matcher.suffix_pattern(span.text[:at], span.entity_type)
    return re.fullmatch(pattern, tail) is not None


_TRAILING_PUNCT_RE = re.compile(r"[^\w'\u2019-]+$")


def consistency_report(
    doc: Document,
    replacements: Sequence[tuple[int, int, str]],
    *,
    policy: Mapping[EntityType, str] = DEFAULT_POLICY,
) -> list[EntityConsistency]:
    """Per gold entity: is every occurrence fully masked, all by a single placeholder?

    ``replacements`` are the vault's ``(start, end, placeholder)`` in input offsets
    (:meth:`pii_guard.vault.VaultSession.mask_with_report`).
    """
    report: list[EntityConsistency] = []
    for members in _gold_entities(doc, policy):
        placeholders: set[str] = set()
        covered = True
        for span in members:
            hits = [(s, e, p) for s, e, p in replacements if s < span.end and span.start < e]
            covered &= _fully_covered(span, hits, doc.language)
            placeholders |= {p for _, _, p in hits}
        report.append(
            EntityConsistency(
                members[0].entity_type, len(members), covered and len(placeholders) == 1
            )
        )
    return report


def unscored(doc: Document, span: _SpanLike) -> bool:
    """True if ``span`` is left out of precision and over-masking (see the module docstring)."""
    if any(_matches(g, span, "overlap") for g in doc.spans):
        return False
    if "ignore" in doc.meta:
        return any(span.start < end and start < span.end for start, end in ignore_regions(doc))
    return span.entity_type in LEGACY_UNSCORED_TYPES.get(str(doc.meta.get("kind")), ())


def over_masked(doc: Document, masked_spans: Sequence[_SpanLike]) -> list[_SpanLike]:
    """Masked spans that overlap no gold span of any type (not personal data)."""
    return [
        s for s in masked_spans if not any(s.start < g.end and g.start < s.end for g in doc.spans)
    ]


# --- Running detectors and the vault -----------------------------------------------------


class Analyzer(Protocol):
    """Detection as the gateway sees it: non-overlapping spans sorted by ``start``."""

    def analyze(self, text: str, language: str) -> list[Span]: ...


class DetectorAnalyzer:
    """Runs registry detectors by name through :class:`DetectionPipeline` (the resolver the
    API and the gateway use), with the policies' ``keep`` types losing overlaps.

    Names that can't be resolved or instantiated are skipped and listed in ``skipped``
    (``(name, reason)``), so ``--detectors rules,llm`` still runs when the LLM detector
    isn't installed yet. A detector that fails *during* detection fails the run.
    """

    def __init__(self, names: Sequence[str], *, policies: PolicySet | None = None) -> None:
        self.policies = policies or PolicySet()
        self.detectors: list[Detector] = []
        self.loaded: list[str] = []
        self.skipped: list[tuple[str, str]] = []
        for name in names:
            try:
                detector = create_detector(name)
            except DetectionError as exc:
                self.skipped.append((name, exc.message))
                continue
            except Exception as exc:
                self.skipped.append((name, f"could not be created ({type(exc).__name__})"))
                continue
            self.detectors.append(detector)
            self.loaded.append(name)

        self.pipeline: DetectionPipeline | None = (
            DetectionPipeline(self.detectors, keep_types=self.policies.keep_types)
            if self.detectors
            else None
        )

    def analyze(self, text: str, language: str) -> list[Span]:
        if self.pipeline is None:
            raise DetectionError("no detector could be loaded")
        return self.pipeline.detect(text, language)


@dataclass(frozen=True, slots=True)
class DocumentResult:
    """Everything measured on one document."""

    document: Document
    predicted: tuple[Span, ...]
    masked_spans: tuple[Span, ...]
    masked_text: str
    roundtrip: bool
    detect_ms: float
    mask_ms: float
    #: The vault's ``(start, end, placeholder)``; ``None`` when the system doesn't report its
    #: replacements (a comparison tool), which makes placeholder consistency ``None``.
    replacements: tuple[tuple[int, int, str], ...] | None = None

    def __repr__(self) -> str:
        return (
            f"DocumentResult(id={self.document.id!r}, predicted={len(self.predicted)}, "
            f"roundtrip={self.roundtrip})"
        )


def run_documents(
    documents: Iterable[Document],
    analyzer: Analyzer,
    *,
    policy: Mapping[EntityType, str] = DEFAULT_POLICY,
    tenant_key: bytes = EVAL_TENANT_KEY,
    known_values: bool = False,
) -> list[DocumentResult]:
    """Detect, mask (every prediction not of a ``keep``-policy type) and unmask every document.

    A ``block`` type would refuse the request; here it is masked like ``mask`` so its values
    never count as leaked.

    With ``known_values``, a document's ``meta.known_values`` (``[{"value", "entity_type"}]``)
    is pre-loaded into its session and found by the ``known`` detector, as
    ``POST /v1/sessions/{id}/known-values`` would; this measures the uplift of pre-loading.

    Each document gets a fresh vault session, as one request would. Errors propagate
    (fail closed): a run with a failing detector produces no scorecard.
    """
    vault = Vault(tenant_key)
    results: list[DocumentResult] = []
    for doc in documents:
        started = time.perf_counter()
        predicted = analyzer.analyze(doc.text, doc.language)
        if known_values and doc.meta.get("known_values"):
            from pii_guard.detect.known import KnownValuesDetector, merge_known
            from pii_guard.vault.known import KnownValueError, known_values_from

            try:
                items = known_values_from(doc.meta["known_values"])
            except KnownValueError as exc:
                raise KnownValueError(f"document {doc.id!r}: {exc.message}") from None
            predicted = merge_known(
                doc.text, predicted, KnownValuesDetector(items), doc.language, keep_types=()
            )
        detected = time.perf_counter()
        to_mask = [s for s in predicted if policy.get(s.entity_type, "mask") != "keep"]
        session = vault.session()
        mask_result = session.mask_with_report(doc.text, to_mask, language=doc.language)
        masked_text = mask_result.text
        masked = time.perf_counter()
        roundtrip = session.unmask(masked_text) == doc.text
        vault.drop(session.session_id)
        results.append(
            DocumentResult(
                document=doc,
                predicted=tuple(predicted),
                masked_spans=tuple(to_mask),
                masked_text=masked_text,
                roundtrip=roundtrip,
                detect_ms=(detected - started) * 1000,
                mask_ms=(masked - detected) * 1000,
                replacements=mask_result.replacements,
            )
        )
    return results


# --- Summaries ---------------------------------------------------------------------------


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def summarize(results: Sequence[DocumentResult]) -> dict[str, object]:
    """One score block for ``results`` (all documents, or one language)."""
    scored = [[p for p in r.predicted if not unscored(r.document, p)] for r in results]
    detection: dict[str, object] = {}
    for mode in ("exact", "overlap"):
        total: dict[EntityType, TypeCounts] = defaultdict(TypeCounts)
        for r, preds in zip(results, scored, strict=True):
            for t, c in match_counts(r.document.spans, preds, mode).items():
                total[t] += c
        detection[mode] = prf(total)

    leak_total: Counter[str] = Counter()
    leak_by_type: dict[str, Counter[str]] = defaultdict(Counter)
    over_total: Counter[str] = Counter()
    over_by_type: dict[str, Counter[str]] = defaultdict(Counter)
    consistency_total: Counter[str] = Counter()
    consistency_by_type: dict[str, Counter[str]] = defaultdict(Counter)
    for r in results:
        for entity in consistency_report(r.document, r.replacements or ()):
            for bucket in (consistency_total, consistency_by_type[entity.entity_type.value]):
                bucket["entities"] += 1
                bucket["consistent"] += entity.consistent
                if entity.occurrences > 1:
                    bucket["multi_occurrence"] += 1
                    bucket["multi_consistent"] += entity.consistent
        for leak in leak_report(r.document, r.masked_text, replacements=r.replacements):
            for bucket in (leak_total, leak_by_type[leak.entity_type.value]):
                bucket["values"] += 1
                bucket["leaked"] += leak.leaked
                bucket["partial"] += leak.partial
        masked = [s for s in r.masked_spans if not unscored(r.document, s)]
        over = {id(s) for s in over_masked(r.document, masked)}
        for span in masked:
            for bucket in (over_total, over_by_type[span.entity_type.value]):
                bucket["masked"] += 1
                bucket["over_masked"] += id(span) in over

    def leak_block(c: Counter[str]) -> dict[str, object]:
        return {
            "values": c["values"],
            "leaked": c["leaked"],
            "partial": c["partial"],
            "rate": _ratio(c["leaked"], c["values"]),
            "partial_rate": _ratio(c["partial"], c["values"]),
        }

    def over_block(c: Counter[str]) -> dict[str, object]:
        return {
            "masked": c["masked"],
            "over_masked": c["over_masked"],
            "rate": _ratio(c["over_masked"], c["masked"]),
        }

    def consistency_block(c: Counter[str]) -> dict[str, object]:
        return {
            "entities": c["entities"],
            "consistent": c["consistent"],
            "rate": _ratio(c["consistent"], c["entities"]),
            "multi_occurrence": c["multi_occurrence"],
            "multi_consistent": c["multi_consistent"],
            "multi_rate": _ratio(c["multi_consistent"], c["multi_occurrence"]),
        }

    detect_ms = [r.detect_ms for r in results]
    mask_ms = [r.mask_ms for r in results]
    from pii_guard.eval.validity import is_public, validity_block

    extra: dict[str, object] = {"validity": validity_block(results)} if is_public(results) else {}
    return {
        "documents": len(results),
        "gold_spans": sum(len(r.document.spans) for r in results),
        "predicted_spans": sum(len(r.predicted) for r in results),
        "unscored_predictions": sum(
            len(r.predicted) - len(p) for r, p in zip(results, scored, strict=True)
        ),
        "detection": detection,
        "leak": {
            **leak_block(leak_total),
            "per_type": {t: leak_block(leak_by_type[t]) for t in _ordered_names(leak_by_type)},
        },
        "over_masking": {
            **over_block(over_total),
            "per_type": {t: over_block(over_by_type[t]) for t in _ordered_names(over_by_type)},
        },
        "consistency": None
        if any(r.replacements is None for r in results)
        else {
            **consistency_block(consistency_total),
            "per_type": {
                t: consistency_block(consistency_by_type[t])
                for t in _ordered_names(consistency_by_type)
            },
        },
        "roundtrip": {
            "documents": len(results),
            "exact": sum(r.roundtrip for r in results),
            "rate": _ratio(sum(r.roundtrip for r in results), len(results)),
        },
        "latency_ms": {
            "detect": {"p50": percentile(detect_ms, 0.5), "p95": percentile(detect_ms, 0.95)},
            "mask": {"p50": percentile(mask_ms, 0.5), "p95": percentile(mask_ms, 0.95)},
        },
        **extra,
    }


def _ordered_names(names: Iterable[str]) -> list[str]:
    return sorted(names, key=lambda n: _TYPE_ORDER[EntityType(n)])
