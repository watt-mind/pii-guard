"""Public PII encoders as comparison NER models (LAB-1386, LAB-1391). Evaluation only.

Shared harness for benchmarking a public token classifier against pii-guard's own NER
(``hdkiller/pii-guard-ner-xlmr-base``): nothing outside the evaluation imports this module, and
the gateway's fast mode keeps resolving its NER model through
:mod:`pii_guard.detect.ner_resolve`. Each comparison model is described by an
:class:`EncoderSpec` (the pinned checkpoint, its licence, a :class:`LabelAdapter` and a decoder)
and runs as :class:`ComparisonDetector`, a subclass of pii-guard's
:class:`~pii_guard.detect.ner.NerDetector`. So its output goes through exactly the same
post-processing as ours (thresholds, word and token snapping, number checks, the resolver, the
vault) and is scored like pii-guard's own NER, placeholder consistency included.

Two decoders:

- ``"first"``: pii-guard's own :class:`~pii_guard.detect.ner.TransformersBackend` (each word
  takes its first sub-token's label). Right for XLM-R checkpoints (``eu-pii-safeguard``).
- ``"word"``: :class:`WordLevelBackend`, for the mmBERT / ModernBERT checkpoints. Their
  tokenizer (Gemma-style) attaches the preceding space to a token and splits numbers into single
  digits, often with a bare ``" "`` token first, so a first-sub-token decoder cuts names and
  numbers into fragments (the LAB-1192 sanity check). The word decoder gives each word the mean
  of its sub-tokens' probabilities, with B- and I- mass pooled per type, and merges neighbouring
  words of one type unless the next word looks like a new entity (:func:`decode_words`). It is
  a fresh implementation of the decoding the bardsai v3 card describes; Horizon-Labs and Wismut
  recommend the ``transformers`` pipeline with ``aggregation_strategy="simple"`` plus a merge of
  close pieces, which the same decoder approximates, so every mmBERT model is decoded alike.

The label adapter (:class:`LabelAdapter`, documented in ``docs/evaluation.md``):

- labels map to pii-guard types by a per-model table; every model label has an explicit
  decision, and labels with no pii-guard type (age, URL, IP address, dates, GDPR Art. 9
  categories, …) are dropped before scoring and counted in ``ComparisonDetector.unmapped``;
- per-language overrides (a tax or health-insurance number is the Hungarian tax or TAJ type on
  Hungarian text, as the Ai4Privacy conversion does);
- name and address *parts* of one type separated only by up to three spaces, tabs or commas are
  merged into one span (the gold conversions' rule), so one name is one placeholder;
- a city, state, country or bare location on its own is not an address under pii-guard's
  policy (the datasets mark it as an ignore region), so it is kept only when merged into an
  address.
"""

from __future__ import annotations

import re
import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pii_guard.detect import ner_resolve
from pii_guard.detect.ner import NER_ENTITY_TYPES, NerDetector, RawEntity
from pii_guard.types import DetectionError, EntityType, Span

__all__ = [
    "DECODERS",
    "ComparisonDetector",
    "EncoderSpec",
    "LabelAdapter",
    "WordLevelBackend",
    "decode_words",
    "download",
    "word_spans",
]

DECODERS = ("first", "word")

#: What may separate two parts of one name or address: the gold conversions' merge gap.
_MERGE_GAP_RE = re.compile(r"[ \t,]{0,3}")


@dataclass(frozen=True)
class LabelAdapter:
    """Model labels (without ``B-`` / ``I-``) to pii-guard types, plus the merge rules."""

    #: label -> type, or ``None``: no pii-guard type, dropped before scoring.
    label_map: Mapping[str, EntityType | None]
    #: language -> {label: type} overrides.
    language_label_map: Mapping[str, Mapping[str, EntityType]] = field(default_factory=dict)
    #: labels that are an address only next to another address part.
    part_only: frozenset[str] = frozenset()
    #: types whose neighbouring parts are merged.
    merged_types: frozenset[EntityType] = frozenset({EntityType.PERSON, EntityType.ADDRESS})

    def type_of(self, label: str, language: str) -> EntityType | None:
        override = self.language_label_map.get(language, {}).get(label)
        return override if override is not None else self.label_map.get(label)

    def adapt(
        self, text: str, raw: Sequence[RawEntity], language: str
    ) -> tuple[list[RawEntity], Counter[str]]:
        """The model's raw entities as pii-guard-typed ones, plus the count of dropped labels.

        Returns entities labelled with :class:`EntityType` values (``"PERSON"``), ready for
        :meth:`NerDetector.to_spans`. A label missing from the table is dropped like a ``None``.
        """
        dropped: Counter[str] = Counter()
        typed: list[tuple[RawEntity, EntityType, bool]] = []  # (entity, type, part-only)
        for e in sorted(raw, key=lambda e: (e.start, e.end)):
            label = e.label.upper()
            entity_type = self.type_of(label, language)
            if entity_type is None:
                dropped[label] += 1
                continue
            typed.append((e, entity_type, label in self.part_only))
        merged: list[tuple[int, int, EntityType, float, bool]] = []  # start, end, type, score, part
        for e, entity_type, part_only in typed:
            if merged:
                start, end, last_type, score, last_part = merged[-1]
                if (
                    last_type is entity_type
                    and entity_type in self.merged_types
                    and e.start >= end
                    and _MERGE_GAP_RE.fullmatch(text, end, e.start)
                ):
                    merged[-1] = (
                        start,
                        e.end,
                        entity_type,
                        max(score, e.score),
                        last_part and part_only,
                    )
                    continue
            merged.append((e.start, e.end, entity_type, e.score, part_only))
        out: list[RawEntity] = []
        for start, end, entity_type, score, part_only in merged:
            if part_only:  # a city, state or country on its own: not an address (policy)
                dropped["ADDRESS_PART_ALONE"] += 1
                continue
            out.append(RawEntity(entity_type.value, start, end, score))
        return out, dropped


@dataclass(frozen=True)
class EncoderSpec:
    """One comparison model: registry name, pinned checkpoint, labels and decoding."""

    #: Registry name (``--detectors rules,<name>``) and the results' config name.
    name: str
    model: ner_resolve.PinnedModel
    adapter: LabelAdapter
    #: ``"first"`` (pii-guard's TransformersBackend) or ``"word"`` (:class:`WordLevelBackend`).
    decoder: str
    #: One line for the run records: architecture, size, label count.
    summary: str
    #: Languages the card lists that matter here (``hu``, ``en``, ``de``), for the README.
    languages: tuple[str, ...] = ("hu", "en", "de")
    #: set name -> contamination note (in the results' contamination column).
    contamination: Mapping[str, str] = field(default_factory=dict)
    #: The window for the word decoder (tokens) and its overlap.
    max_length: int = 512
    stride: int = 128


# -- word-level decoding (mmBERT / ModernBERT checkpoints) --

#: Word characters: split on whitespace and on these separators.
_WORD_RE = re.compile(r"[^\s,;|\"<>()\[\]{}*^]+")
_LEAD_PUNCT = "([{<\"'«„"
_TRAIL_PUNCT = ")]}>\"'».,;:!?"
#: Characters that may separate two words of one entity.
_JOIN_CHARS = " ,-/.()\t\n"


def word_spans(text: str) -> list[tuple[int, int]]:
    """The words of ``text`` as character ranges, edge punctuation trimmed."""
    out: list[tuple[int, int]] = []
    for m in _WORD_RE.finditer(text):
        start, end = m.start(), m.end()
        while start < end and text[start] in _LEAD_PUNCT:
            start += 1
        while end > start and text[end - 1] in _TRAIL_PUNCT:
            end -= 1
        if end > start:
            out.append((start, end))
    return out


def decode_words(
    text: str,
    anchors: Sequence[int],
    type_probs: Sequence[Sequence[float]],
    begin_probs: Sequence[float],
    types: Sequence[str],
) -> list[RawEntity]:
    """Word-level entities from per-token probabilities.

    ``anchors[i]`` is the character token ``i`` starts at (its first non-space character),
    ``type_probs[i]`` its probability per entity type (B- and I- pooled), with ``O`` as the last
    column, and ``begin_probs[i]`` its total B- probability. Each word takes the type with the
    highest mean probability over the tokens anchored in it (``O``: no entity); neighbouring
    words of one type separated only by spaces or ``, - / . ( )`` (no blank line) are merged
    unless the next word's first token is more likely a B- than not. An entity's score is the
    mean of its words' winning probabilities.
    """
    if not len(anchors) == len(type_probs) == len(begin_probs):
        raise ValueError("anchors, type_probs and begin_probs must have the same length")
    n_types = len(types)
    by_char: dict[int, list[int]] = {}
    for i, anchor in enumerate(anchors):
        by_char.setdefault(anchor, []).append(i)
    entities: list[list[Any]] = []  # [label, start, end, [scores]]
    for start, end in word_spans(text):
        tokens = [i for c in range(start, end) for i in by_char.get(c, ())]
        if not tokens:
            continue
        mean = [sum(type_probs[i][k] for i in tokens) / len(tokens) for k in range(n_types + 1)]
        best = max(range(n_types + 1), key=mean.__getitem__)
        if best == n_types:
            continue
        label, score = types[best], mean[best]
        begins = begin_probs[tokens[0]]
        if entities:
            last = entities[-1]
            gap = text[last[2] : start]
            if (
                last[0] == label
                and all(c in _JOIN_CHARS for c in gap)
                and "\n\n" not in gap
                and begins < 0.5
            ):
                last[2] = end
                last[3].append(score)
                continue
        entities.append([label, start, end, [score]])
    return [RawEntity(label, s, e, sum(sc) / len(sc)) for label, s, e, sc in entities]


class WordLevelBackend:
    """A ModernBERT token classifier with :func:`decode_words` (a :class:`NerBackend`).

    Loads from a local directory (safetensors only, no remote code), runs the text in windows
    of ``max_length`` tokens with ``stride`` overlap, averages each token's probabilities over
    the windows it appears in, and decodes words. One forward at a time (a lock), like
    pii-guard's backend.
    """

    def __init__(
        self,
        model: str,
        *,
        device: str | None = None,
        max_length: int = 512,
        stride: int = 128,
    ) -> None:
        import torch
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        from pii_guard.detect.ner import select_device

        self._torch = torch
        self.device = select_device(device)
        self.tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=True)
        if not getattr(self.tokenizer, "is_fast", False):
            raise DetectionError("ner model needs a fast tokenizer (character offsets)")
        self.model = AutoModelForTokenClassification.from_pretrained(
            model, use_safetensors=True, local_files_only=True
        )
        self.model.to(self.device)
        self.model.eval()
        id2label = {int(k): v for k, v in self.model.config.id2label.items()}
        self.types = sorted({label[2:] for label in id2label.values() if label != "O"})
        index = {t: k for k, t in enumerate(self.types)}
        pool = torch.zeros(len(id2label), len(self.types) + 1)
        begin = torch.zeros(len(id2label))
        for i, label in id2label.items():
            pool[i, len(self.types) if label == "O" else index[label[2:]]] = 1.0
            begin[i] = 1.0 if label.startswith(("B-", "S-")) else 0.0
        self._pool, self._begin = pool, begin
        self.max_length, self.stride = max_length, stride
        self._lock = threading.Lock()

    def predict(self, text: str) -> list[RawEntity]:
        torch = self._torch
        with self._lock, torch.inference_mode():
            enc = self.tokenizer(
                text,
                return_offsets_mapping=True,
                return_overflowing_tokens=True,
                truncation=True,
                max_length=self.max_length,
                stride=self.stride,
                padding=True,
                return_tensors="pt",
            )
            offsets = enc.pop("offset_mapping")
            enc.pop("overflow_to_sample_mapping", None)
            mask = enc["attention_mask"]
            logits = self.model(
                input_ids=enc["input_ids"].to(self.device), attention_mask=mask.to(self.device)
            ).logits
            probs = logits.float().softmax(-1).cpu()
        pooled = (probs @ self._pool).tolist()  # windows x tokens x (types + O)
        begins = (probs @ self._begin).tolist()
        offset_rows, mask_rows = offsets.tolist(), mask.tolist()
        # A token seen in two overlapping windows: mean of both (keyed by its character range).
        acc: dict[tuple[int, int], list[Any]] = {}
        for w, row in enumerate(offset_rows):
            for j, (start, end) in enumerate(row):
                if end <= start or not mask_rows[w][j]:
                    continue
                slot = acc.get((start, end))
                if slot is None:
                    acc[(start, end)] = [1, list(pooled[w][j]), begins[w][j]]
                else:
                    slot[0] += 1
                    slot[1] = [a + b for a, b in zip(slot[1], pooled[w][j], strict=True)]
                    slot[2] += begins[w][j]
        anchors: list[int] = []
        type_probs: list[list[float]] = []
        begin_probs: list[float] = []
        for (start, end), (count, total, begin_total) in sorted(acc.items()):
            while start < end - 1 and text[start].isspace():  # the leading space of the token
                start += 1
            anchors.append(start)
            type_probs.append([p / count for p in total])
            begin_probs.append(begin_total / count)
        return decode_words(text, anchors, type_probs, begin_probs, self.types)

    def predict_batch(self, texts: Sequence[str]) -> list[list[RawEntity]]:
        return [self.predict(text) for text in texts]


# -- the detector --


def download(spec: EncoderSpec) -> str:
    """The verified local directory of ``spec.model``, fetched first if it isn't cached."""
    choice = ner_resolve.NerChoice(
        source="configured",
        model=spec.model.repo_id,
        revision=spec.model.revision,
        pinned=spec.model,
        ready=False,  # let ensure() check the cache marker (weights SHA-256) or download
        may_download=True,
    )
    return ner_resolve.ensure(choice)


class ComparisonDetector(NerDetector):
    """pii-guard's NER detector running a comparison model through its :class:`LabelAdapter`.

    Subclasses set :attr:`spec`. ``name`` stays ``ner``: it takes the NER detector's place in
    the pipeline, and its spans are resolved exactly like ours. The pinned checkpoint is fetched
    into the model cache on first use and verified. ``unmapped`` counts the labels dropped so
    far.
    """

    spec: ClassVar[EncoderSpec]

    def __init__(
        self,
        *,
        device: str | None = None,
        preload: bool = True,
        backend: Any = None,
        **kwargs: Any,
    ) -> None:
        spec = self.spec
        if backend is None and spec.decoder == "word":
            path = download(spec)
            backend = lambda: WordLevelBackend(  # noqa: E731 - a deferred factory
                path, device=device, max_length=spec.max_length, stride=spec.stride
            )
            model = spec.model.repo_id
        else:
            # Always the verified copy in the model cache, never a hub id (no unpinned load).
            model = spec.model.repo_id if backend is not None else download(spec)
        super().__init__(model=model, device=device, backend=backend, preload=False, **kwargs)
        self.revision = None  # a local directory, already at the pinned revision
        self.entity_types = NER_ENTITY_TYPES | {EntityType.SECRET}
        self.label_map = {t.value: t for t in EntityType}
        self.unmapped: Counter[str] = Counter()
        if preload:
            self.load()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(revision={self.spec.model.revision[:12]!r})"

    def to_spans(self, text: str, raw: Sequence[RawEntity], language: str = "hu") -> list[Span]:
        adapted, dropped = self.spec.adapter.adapt(text, raw, language)
        self.unmapped.update(dropped)
        return super().to_spans(text, adapted, language)
