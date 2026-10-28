"""NER detector: an open multilingual token-classification encoder for names, addresses and orgs.

The fast-mode complement to the rules: rules find structured identifiers (checksums, formats),
this detector finds ``PERSON``, ``ADDRESS``, ``ORGANIZATION`` and, with a model trained for it,
``DATE_OF_BIRTH``, in any language the encoder covers. A v2 checkpoint (LAB-1150) also
proposes ``EMAIL``, ``PHONE``, ``ID_DOCUMENT``, the Hungarian tax and TAJ numbers and
``BANK_ACCOUNT``, so a number whose checksum fails or whose format no rule knows is still
masked; validated rule spans keep their boundaries and win in the resolver. It runs
in-process (CPU, Apple MPS or CUDA), so the text never leaves the guard. See ``docs/models.md``.

- **Model.** Any Hugging Face token-classification checkpoint (BIO labels): a hub id or a local
  directory, from ``model=`` or ``PII_GUARD_NER_MODEL`` (default :data:`DEFAULT_MODEL`). The
  fine-tuned pii-guard model (``training/ner/``) uses the entity type names as labels
  (``B-PERSON``, ``I-ADDRESS``, …); generic NER labels are mapped by :data:`LABEL_MAP`
  (``PER`` → ``PERSON``, ``ORG`` → ``ORGANIZATION``, ``LOC`` → ``ADDRESS``).
  ``trust_remote_code`` is never enabled.
- **Offsets.** Character offsets come from the fast tokenizer's offset mapping, which is in
  code points of the Python string, so spans are exact for any Unicode input. Inputs longer
  than the model window are split into overlapping token windows; overlapping same-type spans
  are merged.
- **Aggregation.** ``"first"``: every word takes the label of its first sub-token (what generic
  NER checkpoints are trained for). ``"token"``: labels per sub-token, so a span can end inside
  a word (a Hungarian case suffix such as ``Pétert`` stays outside ``Péter``); the fine-tuned
  model records this in its config (``pii_guard_aggregation``).
- **Thresholds** per language and entity type (:data:`DEFAULT_THRESHOLDS`, ``thresholds=``);
  an unknown language uses ``"default"``.
- **Fail closed** (ADR 0006): a missing dependency, a model that can't be loaded and any
  inference error raise :class:`~pii_guard.types.DetectionError`. Messages carry exception
  types only, never text.

The optional dependencies are the ``ner`` extra (``uv sync --extra ner``). Without them the
module still imports (the classes are testable with an injected backend) but defines no
``DETECTOR_CLASS``, so the registry reports ``ner`` as unavailable and the gateway's fast mode
stays rules-only.

Download / warm the model cache (Hugging Face cache, ``HF_HOME``)::

    uv run --extra ner python -m pii_guard.detect.ner download [--model ID_OR_PATH]
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pii_guard.detect import ner_resolve
from pii_guard.detect.ner_context import guard_spans
from pii_guard.detect.ner_numbers import check_numbers
from pii_guard.detect.ner_orgs import relabel_brands
from pii_guard.detect.ner_words import snap_to_tokens, snap_to_words
from pii_guard.types import DetectionError, EntityType, Span

__all__ = [
    "BACKEND_ENV_VAR",
    "DEFAULT_MODEL",
    "DEFAULT_REVISION",
    "DEFAULT_THRESHOLDS",
    "DEVICE_ENV_VAR",
    "LABEL_MAP",
    "MODEL_ENV_VAR",
    "NER_ENTITY_TYPES",
    "NER_V1_ENTITY_TYPES",
    "NerBackend",
    "NerDetector",
    "RawEntity",
    "TransformersBackend",
    "decode_tokens",
    "dependencies_available",
    "merge_entities",
    "select_device",
]

logger = logging.getLogger(__name__)

#: Default without ``PII_GUARD_NER_MODEL``: the public fallback of
#: :mod:`pii_guard.detect.ner_resolve` (an Apache-2.0 multilingual PII token classifier,
#: LAB-1192), loaded from the pii-guard model cache and downloaded there on first use. Point
#: ``PII_GUARD_NER_MODEL`` at the fine-tuned model (``training/ner/``) for better results.
DEFAULT_MODEL = ner_resolve.PUBLIC_FALLBACK.repo_id
#: Pinned hub revision of :data:`DEFAULT_MODEL` (used only when the default model is used).
DEFAULT_REVISION = ner_resolve.PUBLIC_FALLBACK.revision
#: The previous zero-shot default (LAB-1106 to LAB-1150): XLM-RoBERTa base NER on ten
#: high-resource languages, AFL-3.0. Still loads with ``PII_GUARD_NER_MODEL``.
DAVLAN_MODEL = "Davlan/xlm-roberta-base-ner-hrl"
MODEL_ENV_VAR = "PII_GUARD_NER_MODEL"
REVISION_ENV_VAR = "PII_GUARD_NER_REVISION"
DEVICE_ENV_VAR = "PII_GUARD_NER_DEVICE"
#: ``transformers`` (default) or ``gliner`` (:mod:`pii_guard.detect.ner_gliner`; the default
#: model is then the public zero-shot GLiNER multi checkpoint).
BACKEND_ENV_VAR = "PII_GUARD_NER_BACKEND"
BACKENDS = ("transformers", "gliner")

#: The v1 types (names, addresses, organisations, dates of birth): what a generic NER
#: checkpoint or a pii-guard v1 checkpoint (LAB-1106, LAB-1128) reports.
NER_V1_ENTITY_TYPES: frozenset[EntityType] = frozenset(
    {EntityType.PERSON, EntityType.ADDRESS, EntityType.ORGANIZATION, EntityType.DATE_OF_BIRTH}
)
#: The types this detector can report. A v2 checkpoint (LAB-1150) also proposes identifiers
#: (emails, phones, ID and tax numbers, bank accounts and cards); the rules still validate
#: those and keep their own scores and boundaries, and the resolver and policy decide
#: (``docs/entities.md``, "NER label set").
NER_ENTITY_TYPES: frozenset[EntityType] = NER_V1_ENTITY_TYPES | frozenset(
    {
        EntityType.EMAIL,
        EntityType.PHONE,
        EntityType.ID_DOCUMENT,
        EntityType.NATIONAL_ID_HU_TAX,
        EntityType.NATIONAL_ID_HU_TAJ,
        EntityType.BANK_ACCOUNT,
    }
)

#: Model label (without ``B-``/``I-``) → entity type. Labels not listed are ignored (for
#: example ``DATE`` and ``MISC``: a date is only personal data in a birth-date context).
LABEL_MAP: dict[str, EntityType] = {
    "PER": EntityType.PERSON,
    "PERSON": EntityType.PERSON,
    "ORG": EntityType.ORGANIZATION,
    "ORGANIZATION": EntityType.ORGANIZATION,
    "LOC": EntityType.ADDRESS,
    "ADDRESS": EntityType.ADDRESS,
    "DATE_OF_BIRTH": EntityType.DATE_OF_BIRTH,
    "EMAIL": EntityType.EMAIL,
    "PHONE": EntityType.PHONE,
    "ID_DOCUMENT": EntityType.ID_DOCUMENT,
    "NATIONAL_ID_HU_TAX": EntityType.NATIONAL_ID_HU_TAX,
    "NATIONAL_ID_HU_TAJ": EntityType.NATIONAL_ID_HU_TAJ,
    "BANK_ACCOUNT": EntityType.BANK_ACCOUNT,
    # The public fallback's labels (bardsai/eu-pii-anonimization-multilang, LAB-1192).
    "PERSON_NAME": EntityType.PERSON,
    "ORGANIZATION_NAME": EntityType.ORGANIZATION,
    "POSTAL_ADDRESS": EntityType.ADDRESS,
    "LOCATION": EntityType.ADDRESS,
    "EMAIL_ADDRESS": EntityType.EMAIL,
    "PHONE_NUMBER": EntityType.PHONE,
    "DOCUMENT_IDENTIFIER": EntityType.ID_DOCUMENT,
    "PERSON_IDENTIFIER": EntityType.ID_DOCUMENT,
    "BANK_ACCOUNT_IDENTIFIER": EntityType.BANK_ACCOUNT,
    "PAYMENT_CARD": EntityType.BANK_ACCOUNT,
}

#: Minimum span score per language and type. ``"default"`` applies to every other language.
DEFAULT_THRESHOLDS: dict[str, dict[EntityType, float]] = {
    "default": {t: 0.5 for t in sorted(NER_ENTITY_TYPES)},
}

# Trimmed off span ends. Dots are kept: they belong to "Kft.", "Ltd." and Hungarian dates and
# house numbers ("1982.06.26.", "utca 12."); a PERSON span loses a trailing dot.
_TRIM = " \t\r\n,;:!?()[]{}\"'\u00ab\u00bb\u201e\u201c\u201d\u2018\u2019\u2013\u2014-/"
_REQUIRED_MODULES = ("torch", "transformers")
#: Windows per forward pass in :meth:`TransformersBackend.predict_batch` (LAB-1279), the cap
#: on padded tokens per pass (8 full 512-token windows), and on padded / real tokens.
DEFAULT_BATCH_SIZE = 8
DEFAULT_MAX_BATCH_TOKENS = 4096
DEFAULT_MAX_PADDING = 2.0
#: Texts that :meth:`TransformersBackend.predict_batch` runs together from concurrent callers
#: (LAB-1177). A caller's own texts are never split, so one large request may exceed it.
DEFAULT_MAX_COMBINED_TEXTS = 64
#: What a backend runs once on its device before it is published (fictional, no PII).
WARM_UP_TEXT = "Warm-up sentence for the model."

# Model loading is process-wide (LAB-1274): the REST API and the gateway each build a
# NerDetector, and two loads (or first forwards) at once on Apple MPS crashed the process with
# signal 11. One lock serialises every load and its warm-up forward, and detectors with the same
# configuration share the loaded backend, so a model is in memory once and its inference lock
# serialises all callers.
_load_lock = threading.Lock()
_shared_backends: dict[tuple[object, ...], NerBackend] = {}


def dependencies_available() -> bool:
    """True if the ``ner`` extra (torch, transformers) is installed."""
    return all(importlib.util.find_spec(m) is not None for m in _REQUIRED_MODULES)


@dataclass(frozen=True, slots=True)
class RawEntity:
    """A model prediction before thresholds: a label (``PER``, ``ADDRESS``…) over ``[start, end)``.

    ``repr()`` carries no text, only offsets.
    """

    label: str
    start: int
    end: int
    score: float


class NerBackend(Protocol):
    """Runs the model: text in, raw entities with character offsets into that text out.

    A backend may also offer ``predict_batch(texts) -> list[list[RawEntity]]`` (one result per
    text, in order); :meth:`NerDetector.detect_batch` uses it when present and loops
    ``predict`` otherwise.
    """

    def predict(self, text: str) -> list[RawEntity]: ...


def _split_label(label: str) -> tuple[str, str]:
    """``"B-PER"`` → ``("B", "PER")``; ``"O"`` → ``("O", "")``; a bare ``"PER"`` → ``("I", …)``."""
    if label == "O" or not label:
        return "O", ""
    if len(label) > 2 and label[1] in "-_" and label[0] in "BIESLU":
        prefix = {"E": "I", "L": "I", "S": "B", "U": "B"}.get(label[0], label[0])
        return prefix, label[2:]
    return "I", label


def decode_tokens(
    offsets: Sequence[tuple[int, int]],
    word_ids: Sequence[int | None],
    labels: Sequence[str],
    scores: Sequence[float],
    *,
    aggregation: str = "first",
) -> list[RawEntity]:
    """Turn per-token BIO predictions into entities with character offsets.

    ``offsets`` are the tokenizer's ``(start, end)`` character offsets, ``word_ids`` its word
    index per token (``None`` for special tokens), ``labels`` the argmax label per token and
    ``scores`` its probability. With ``aggregation="first"`` each word takes its first
    sub-token's label and the entity spans whole words; with ``"token"`` every sub-token
    counts on its own. An entity's score is the mean of its units' scores.
    """
    if not len(offsets) == len(word_ids) == len(labels) == len(scores):
        raise ValueError("offsets, word_ids, labels and scores must have the same length")
    if aggregation not in ("first", "token"):
        raise ValueError(f"unknown aggregation {aggregation!r}")

    # Units: (start, end, prefix, entity, score, word_start). Words for "first", tokens otherwise.
    units: list[tuple[int, int, str, str, float, bool]] = []
    previous_word: int | None = None
    for (start, end), word, label, score in zip(offsets, word_ids, labels, scores, strict=True):
        if word is None or end <= start:
            previous_word = None if word is None else previous_word
            continue
        new_word = word != previous_word
        previous_word = word
        prefix, entity = _split_label(label)
        if aggregation == "first":
            if new_word:
                units.append((start, end, prefix, entity, float(score), True))
            else:
                s, _, p, e, sc, _ = units[-1]
                units[-1] = (s, end, p, e, sc, True)
        else:
            units.append((start, end, prefix, entity, float(score), new_word))

    entities: list[RawEntity] = []
    current: list[Any] | None = None  # [label, start, end, [scores]]

    def close() -> None:
        nonlocal current
        if current is not None:
            label, start, end, unit_scores = current
            entities.append(RawEntity(label, start, end, sum(unit_scores) / len(unit_scores)))
            current = None

    for start, end, prefix, entity, score, word_start in units:
        if prefix == "O":
            close()
            continue
        continues = (
            current is not None
            and current[0] == entity
            and (prefix == "I" or (aggregation == "token" and not word_start))
        )
        if continues:
            current[2] = end  # type: ignore[index]
            current[3].append(score)  # type: ignore[index]
        else:
            close()
            current = [entity, start, end, [score]]
    close()
    return entities


def merge_entities(entities: Sequence[RawEntity]) -> list[RawEntity]:
    """Union overlapping or touching entities of the same label (from overlapping windows)."""
    out: list[RawEntity] = []
    for e in sorted(entities, key=lambda e: (e.label, e.start, -e.end)):
        if out and out[-1].label == e.label and e.start <= out[-1].end:
            last = out[-1]
            out[-1] = RawEntity(e.label, last.start, max(last.end, e.end), max(last.score, e.score))
        else:
            out.append(e)
    return sorted(out, key=lambda e: (e.start, e.end, e.label))


def select_device(requested: str | None = None) -> str:
    """``cpu``, ``mps``, ``cuda`` or ``cuda:N``; ``auto`` (default) prefers CUDA, then MPS."""
    import torch

    device = (requested or os.environ.get(DEVICE_ENV_VAR) or "auto").strip().lower()
    if device == "auto":
        if torch.cuda.is_available():
            return "cuda"
        return "mps" if torch.backends.mps.is_available() else "cpu"
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise DetectionError("ner device 'cuda' requested but CUDA is not available")
    if device == "mps" and not torch.backends.mps.is_available():
        raise DetectionError("ner device 'mps' requested but MPS is not available")
    return device


class _Call:
    """One :meth:`TransformersBackend.predict_batch` call waiting in the queue (LAB-1177).

    ``event`` is set when the call is done or when its thread is promoted to run the queue.
    """

    __slots__ = ("done", "error", "event", "result", "texts")

    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self.result: list[list[RawEntity]] | None = None
        self.error: BaseException | None = None
        self.done = False
        self.event = threading.Event()

    def finish(
        self, result: list[list[RawEntity]] | None = None, error: BaseException | None = None
    ) -> None:
        self.result, self.error, self.done = result, error, True
        self.event.set()


class TransformersBackend:
    """A Hugging Face token-classification model run with PyTorch.

    ``max_length`` and ``stride`` (tokens) set the window and overlap for long inputs.
    :meth:`predict_batch` runs the windows of several texts in length-sorted micro-batches of
    at most ``batch_size`` windows, ``max_batch_tokens`` padded tokens and ``max_padding``
    times their real tokens (LAB-1279).

    Concurrent callers share forward passes (LAB-1177): the tokenizer and the model are used by
    one thread at a time, and callers that arrive while a run is in progress queue up; the next
    run takes every queued caller's texts (up to ``max_combined_texts``, never splitting one
    caller) as one batch. A caller that finds the model idle runs at once, so there is no wait
    window and nothing is added at concurrency 1. Several forwards at once are not used: two at
    once on Apple MPS crashed the process (LAB-1274).
    """

    def __init__(
        self,
        model: str,
        *,
        revision: str | None = None,
        device: str | None = None,
        max_length: int = 512,
        stride: int = 64,
        aggregation: str | None = None,
        local_files_only: bool = False,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_batch_tokens: int = DEFAULT_MAX_BATCH_TOKENS,
        max_padding: float = DEFAULT_MAX_PADDING,
        max_combined_texts: int = DEFAULT_MAX_COMBINED_TEXTS,
    ) -> None:
        if stride >= max_length // 2:
            raise ValueError("stride must be less than half of max_length")
        if batch_size < 1 or max_batch_tokens < 1 or max_padding < 1 or max_combined_texts < 1:
            raise ValueError(
                "batch_size, max_batch_tokens, max_padding and max_combined_texts must be positive"
            )
        import torch
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        self._torch = torch
        self.device = select_device(device)
        kwargs: dict[str, Any] = {"revision": revision, "local_files_only": local_files_only}
        self.tokenizer = AutoTokenizer.from_pretrained(model, use_fast=True, **kwargs)
        if not getattr(self.tokenizer, "is_fast", False):
            raise DetectionError("ner model needs a fast tokenizer (character offsets)")
        # safetensors only: never unpickle a pytorch_model.bin from the hub (code execution).
        self.model = AutoModelForTokenClassification.from_pretrained(
            model, use_safetensors=True, **kwargs
        )
        self.model.to(self.device)
        self.model.eval()
        config = self.model.config
        self.id2label: dict[int, str] = {int(k): v for k, v in config.id2label.items()}
        self.aggregation = aggregation or getattr(config, "pii_guard_aggregation", None) or "first"
        model_max = getattr(self.tokenizer, "model_max_length", max_length) or max_length
        self.max_length = min(max_length, model_max if model_max < 100_000 else max_length)
        self.stride = stride
        self.batch_size = batch_size
        self.max_batch_tokens = max_batch_tokens
        self.max_padding = max_padding
        self.max_combined_texts = max_combined_texts
        self._lock = threading.Lock()  # fast tokenizers are not safe for concurrent calls
        # Callers waiting for a run, oldest first, and whether a run is in progress (LAB-1177).
        # While ``_running`` is set, exactly one thread runs or is about to run the queue.
        self._queue_lock = threading.Lock()
        self._queue: list[_Call] = []
        self._running = False
        # One forward on the device before anyone else can see this backend (LAB-1274).
        self.predict(WARM_UP_TEXT)

    def predict(self, text: str) -> list[RawEntity]:
        return self.predict_batch([text])[0]

    def predict_batch(self, texts: Sequence[str]) -> list[list[RawEntity]]:
        """Raw entities for each of ``texts``, in order, from batched forward passes.

        Concurrent calls are combined into shared runs of :meth:`_predict_now` (see the class
        docstring); each caller gets exactly its own results. When a combined run fails, its
        callers are run one at a time, so only the caller whose texts fail gets the error.
        """
        if not texts:
            return []
        call = _Call(list(texts))
        with self._queue_lock:
            self._queue.append(call)
            # Invariant: a non-empty queue has a runner. If none is running, this call is
            # alone in the queue and runs now; otherwise it waits to be served or promoted.
            lead = not self._running
            self._running = True
        if not lead:
            call.event.wait()
        if not call.done:  # this thread runs the queue (first in line, or promoted)
            self._run_queue()
        if call.error is not None:
            raise call.error
        return call.result or []

    def _run_queue(self) -> None:
        """Run the oldest queued calls as one batch, then hand the queue to the next caller.

        Called by the thread whose call is first in the queue. The next run is done by the
        next waiting caller's own thread, so a caller is never kept busy serving later ones.
        """
        with self._queue_lock:
            taken = [self._queue.pop(0)]
            size = len(taken[0].texts)
            while self._queue and size + len(self._queue[0].texts) <= self.max_combined_texts:
                size += len(self._queue[0].texts)
                taken.append(self._queue.pop(0))
        try:
            self._serve(taken)
        finally:
            for call in taken:
                if not call.done:  # BaseException from the run: never leave a caller hanging
                    call.finish(error=DetectionError("ner batch was interrupted"))
            with self._queue_lock:
                if self._queue:
                    self._queue[0].event.set()  # promoted: its thread runs the next batch
                else:
                    self._running = False

    def _serve(self, calls: list[_Call]) -> None:
        if len(calls) == 1:
            call = calls[0]
            try:
                call.finish(result=self._predict_now(call.texts))
            except Exception as exc:
                call.finish(error=exc)
            return
        try:
            results = self._predict_now([t for call in calls for t in call.texts])
        except Exception:
            for call in calls:  # isolate the failure: only the failing caller gets an error
                self._serve([call])
            return
        start = 0
        for call in calls:
            call.finish(result=results[start : start + len(call.texts)])
            start += len(call.texts)

    def _predict_now(self, texts: Sequence[str]) -> list[list[RawEntity]]:
        """:meth:`predict_batch` for ``texts`` in this thread, without combining callers.

        All texts are tokenized together into windows (``overflow_to_sample_mapping`` maps a
        window back to its text). The windows run longest first in micro-batches, each padded
        on the right to its own longest window, under one acquisition of the inference lock.
        Logits go to the CPU once per micro-batch; softmax and argmax run there (on MPS that is
        faster than two device syncs). Every window is decoded on its own and a text's entities
        are merged across its windows, as for one text. Any error fails the whole batch.
        """
        if not texts:
            return []
        torch = self._torch
        with self._lock, torch.inference_mode():
            enc = self.tokenizer(
                list(texts),
                return_offsets_mapping=True,
                return_overflowing_tokens=True,
                truncation=True,
                max_length=self.max_length,
                stride=self.stride,
            )
            offsets = enc.pop("offset_mapping")
            samples = enc.pop("overflow_to_sample_mapping", None)
            if samples is None:
                samples = list(range(len(offsets)))
            word_ids = [enc.word_ids(i) for i in range(len(offsets))]
            features = {key: enc[key] for key in enc}
            lengths = [len(ids) for ids in features["input_ids"]]
            pad_values = {
                "input_ids": self.tokenizer.pad_token_id,
                "token_type_ids": getattr(self.tokenizer, "pad_token_type_id", 0),
            }
            best: list[list[float]] = [[] for _ in lengths]
            label_ids: list[list[int]] = [[] for _ in lengths]
            for chunk in self._micro_batches(lengths):
                width = lengths[chunk[0]]  # longest first
                inputs = {
                    key: torch.tensor(
                        [
                            [*values[w], *[pad_values.get(key, 0)] * (width - lengths[w])]
                            for w in chunk
                        ]
                    ).to(self.device)
                    for key, values in features.items()
                }
                logits = self.model(**inputs).logits.float().cpu()
                scores, ids = torch.softmax(logits, dim=-1).max(dim=-1)
                for row, window in enumerate(chunk):
                    n = lengths[window]  # padded on the right
                    best[window] = scores[row, :n].tolist()
                    label_ids[window] = ids[row, :n].tolist()
        per_text: list[list[RawEntity]] = [[] for _ in texts]
        for window, sample in enumerate(samples):
            per_text[sample].extend(
                decode_tokens(
                    [tuple(o) for o in offsets[window]],
                    word_ids[window],
                    [self.id2label[i] for i in label_ids[window]],
                    best[window],
                    aggregation=self.aggregation,
                )
            )
        return [merge_entities(entities) for entities in per_text]

    def _micro_batches(self, lengths: Sequence[int]) -> list[list[int]]:
        """Window indices, longest first, cut into batches for :meth:`predict_batch`.

        A window joins the current batch while the batch stays within ``batch_size`` windows
        and ``max_batch_tokens`` padded tokens, and padding stays at most
        ``max_padding`` x its real tokens (a long system prompt does not pad seven short tool
        descriptions to its length).
        """
        order = sorted(range(len(lengths)), key=lambda w: (-lengths[w], w))
        batches: list[list[int]] = []
        real = 0
        for window in order:
            current = batches[-1] if batches else None
            if current is not None:
                # Sorted longest first, so the first window of a batch sets its padded length.
                padded = (len(current) + 1) * lengths[current[0]]
                if (
                    len(current) < self.batch_size
                    and padded <= self.max_batch_tokens
                    and padded <= self.max_padding * (real + lengths[window])
                ):
                    current.append(window)
                    real += lengths[window]
                    continue
            batches.append([window])
            real = lengths[window]
        return batches


def _normalize_thresholds(
    raw: Mapping[str, Mapping[EntityType | str, float]] | None,
) -> dict[str, dict[EntityType, float]]:
    merged: dict[str, dict[EntityType, float]] = {
        lang: dict(values) for lang, values in DEFAULT_THRESHOLDS.items()
    }
    for lang, values in (raw or {}).items():
        target = merged.setdefault(lang.lower(), dict(merged["default"]))
        for key, value in values.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError("thresholds must be in [0, 1]")
            target[EntityType(key)] = float(value)
    return merged


class NerDetector:
    """Detect names, addresses, organisations (and dates of birth) with an NER encoder.

    Every argument is optional:

    - ``model`` / ``revision``: hub id or local directory, default ``PII_GUARD_NER_MODEL``, then
      the published checkpoint, then the public fallback :data:`DEFAULT_MODEL` from the model
      cache (:mod:`pii_guard.detect.ner_resolve`; downloaded on first load), and
      ``PII_GUARD_NER_REVISION``.
    - ``published`` / ``fallback``: ``PII_GUARD_NER_PUBLISHED_MODEL`` and
      ``PII_GUARD_NER_FALLBACK`` (``download`` | ``cached`` | ``off``) for that resolution.
    - ``device``: ``auto`` (default, ``PII_GUARD_NER_DEVICE``), ``cpu``, ``mps``, ``cuda``.
    - ``backend_kind``: ``transformers`` (default) or ``gliner`` (``PII_GUARD_NER_BACKEND``):
      a GLiNER checkpoint, by default the public zero-shot
      :data:`pii_guard.detect.ner_gliner.DEFAULT_MODEL`. A local directory with a
      ``gliner_config.json`` uses the GLiNER backend whatever this says.
    - ``thresholds``: ``{language: {entity_type: min_score}}``, merged over
      :data:`DEFAULT_THRESHOLDS`.
    - ``entity_types``: which of :data:`NER_ENTITY_TYPES` to report (default all).
    - ``label_map``: extra model-label → type mappings.
    - ``backend``: a :class:`NerBackend` to use instead of loading a model (tests), or a
      zero-argument factory for one.
    - ``preload``: load the model in the constructor (default), so a missing or broken model
      fails when the detector is built; ``False`` defers it to the first call.
    - ``number_checks``: drop the proposed ``ID_DOCUMENT``, ``BANK_ACCOUNT``, tax and TAJ
      numbers that a negative cue or their shape rules out
      (:mod:`pii_guard.detect.ner_numbers`, LAB-1293); default on.

    The model is loaded once per process, under a process-wide lock, and detectors with the
    same model, revision, device and window settings share it (LAB-1274). A load failure raises
    :class:`DetectionError` (and a deferred load is retried on the next call).
    """

    name = "ner"

    def __init__(
        self,
        *,
        model: str | None = None,
        revision: str | None = None,
        device: str | None = None,
        thresholds: Mapping[str, Mapping[EntityType | str, float]] | None = None,
        entity_types: Sequence[EntityType | str] | None = None,
        label_map: Mapping[str, EntityType | str] | None = None,
        max_length: int = 512,
        stride: int = 64,
        aggregation: str | None = None,
        backend: NerBackend | Callable[[], NerBackend] | None = None,
        preload: bool = True,
        backend_kind: str | None = None,
        published: str | None = None,
        fallback: str | None = None,
        number_checks: bool = True,
        local_files_only: bool = False,
    ) -> None:
        self.number_checks = number_checks
        from pii_guard.config import get_settings
        from pii_guard.detection_profile import is_local_only

        local_files_only = local_files_only or is_local_only(get_settings())
        self.local_files_only = local_files_only
        kind = (backend_kind or os.environ.get(BACKEND_ENV_VAR) or "transformers").strip().lower()
        if kind not in BACKENDS:
            raise ValueError(f"ner backend must be one of {BACKENDS}")
        self.backend_kind = kind
        self._published, self._fallback = published, fallback
        env_model = os.environ.get(MODEL_ENV_VAR)
        default_revision: str | None
        #: How the model was picked (:func:`pii_guard.detect.ner_resolve.resolve`); ``None``
        #: for an explicit or GLiNER model.
        self.choice: ner_resolve.NerChoice | None = None
        if kind == "gliner":
            from pii_guard.detect import ner_gliner

            default_model, default_revision = ner_gliner.DEFAULT_MODEL, ner_gliner.DEFAULT_REVISION
            self.model = model or env_model or default_model
        elif model or env_model:
            default_model, default_revision = DEFAULT_MODEL, DEFAULT_REVISION
            self.model = model or env_model or default_model
        else:
            # Published pii-guard checkpoint, else the public fallback (LAB-1192).
            # Nothing resolved: load() refuses (an injected backend still works).
            choice = ner_resolve.resolve(published=published, fallback=fallback)
            self.choice = choice
            self.model = choice.model or DEFAULT_MODEL
            default_model, default_revision = self.model, choice.revision
        self.revision = (
            revision
            or os.environ.get(REVISION_ENV_VAR)
            or (default_revision if self.model == default_model else None)
        )
        if local_files_only:
            from pii_guard.detection_profile import require_local_model

            require_local_model(model or env_model, self.backend_kind)
        self.device = device
        self.thresholds = _normalize_thresholds(thresholds)
        types = frozenset(EntityType(t) for t in (entity_types or NER_ENTITY_TYPES))
        if not types <= NER_ENTITY_TYPES:
            raise ValueError("entity_types must be a subset of NER_ENTITY_TYPES")
        self.entity_types = types
        self.label_map = dict(LABEL_MAP)
        self.label_map.update({k: EntityType(v) for k, v in (label_map or {}).items()})
        self.max_length = max_length
        self.stride = stride
        self.aggregation = aggregation
        self._backend: NerBackend | None = None
        self._factory: Callable[[], NerBackend] | None = None
        if backend is not None and hasattr(backend, "predict"):
            self._backend = backend  # type: ignore[assignment]
        elif backend is not None:
            self._factory = backend  # type: ignore[assignment]
        if preload:
            self.load()

    def __repr__(self) -> str:
        return f"NerDetector(model={self.model!r}, device={self.device or 'auto'!r})"

    # -- loading --

    def load(self) -> NerBackend:
        """Load the model (once per process and configuration). Raises :class:`DetectionError`.

        Double-checked under the process-wide load lock: the backend is published only after it
        is fully built (on its device, in eval mode, one warm-up forward done).
        """
        backend = self._backend
        if backend is not None:
            return backend
        with _load_lock:
            if self._backend is None:
                try:
                    self._backend = self._build_backend()
                except DetectionError:
                    raise
                except Exception as exc:
                    raise DetectionError(
                        f"ner model could not be loaded ({type(exc).__name__})"
                    ) from exc
        return self._backend

    def _shared_key(self) -> tuple[object, ...]:
        device = (self.device or os.environ.get(DEVICE_ENV_VAR) or "auto").strip().lower()
        return (
            self.backend_kind,
            self.model,
            self.revision,
            device,
            self.max_length,
            self.stride,
            self.aggregation,
            self.local_files_only,
        )

    def _build_backend(self) -> NerBackend:
        """Called with ``_load_lock`` held."""
        if self._factory is not None:
            return self._factory()
        key = self._shared_key()
        shared = _shared_backends.get(key)
        if shared is not None:
            return shared
        backend: NerBackend
        if self.backend_kind == "gliner" or os.path.isfile(
            os.path.join(self.model, "gliner_config.json")
        ):
            from pii_guard.detect import ner_gliner

            if not ner_gliner.dependencies_available():
                raise DetectionError("ner gliner backend needs the 'gliner' extra")
            backend = ner_gliner.GlinerBackend(
                self.model, revision=self.revision, device=self.device
            )
        else:
            if not dependencies_available():
                raise DetectionError("ner detector needs the 'ner' extra (torch, transformers)")
            if self.choice is not None and self.choice.model is None:
                raise DetectionError(f"no ner model: {self.choice.reason}")
            if self.choice is not None and not self.choice.ready:
                # The published checkpoint or the public fallback, first use: fetch it (LAB-1192).
                self.model = ner_resolve.ensure(self.choice)
                self.choice = ner_resolve.resolve(
                    published=self._published, fallback=self._fallback
                )
            backend = TransformersBackend(
                self.model,
                revision=self.revision,
                device=self.device,
                max_length=self.max_length,
                stride=self.stride,
                aggregation=self.aggregation,
                local_files_only=self.local_files_only,
            )
        logger.info("ner model loaded: %s", self.model)
        _shared_backends[key] = backend
        return backend

    # -- detection --

    def threshold(self, language: str, entity_type: EntityType) -> float:
        primary = (language or "").replace("_", "-").split("-")[0].lower()
        table = self.thresholds.get(primary) or self.thresholds["default"]
        return table.get(entity_type, self.thresholds["default"].get(entity_type, 0.5))

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        if not text.strip():
            return []
        backend = self.load()
        try:
            raw = backend.predict(text)
        except DetectionError:
            raise
        except Exception as exc:
            raise DetectionError(f"ner inference failed ({type(exc).__name__})") from exc
        return self.to_spans(text, raw, language)

    def detect_batch(self, texts: Sequence[str], language: str = "hu") -> list[list[Span]]:
        """``[detect(t, language) for t in texts]``, with the model run on all texts at once.

        Uses the backend's ``predict_batch`` when it has one (one lock acquisition, batched
        forwards), else calls ``predict`` per text. Fail closed: any error raises
        :class:`DetectionError` for the whole batch and no spans are returned.
        """
        out: list[list[Span]] = [[] for _ in texts]
        todo = [i for i, text in enumerate(texts) if text.strip()]
        if not todo:
            return out
        backend = self.load()
        batch = getattr(backend, "predict_batch", None)
        try:
            if batch is not None:
                raws = batch([texts[i] for i in todo])
            else:
                raws = [backend.predict(texts[i]) for i in todo]
        except DetectionError:
            raise
        except Exception as exc:
            raise DetectionError(f"ner inference failed ({type(exc).__name__})") from exc
        if not isinstance(raws, list) or len(raws) != len(todo):
            raise DetectionError("ner backend returned the wrong number of batch results")
        for i, raw in zip(todo, raws, strict=True):
            out[i] = self.to_spans(texts[i], raw, language)
        return out

    def to_spans(self, text: str, raw: Sequence[RawEntity], language: str = "hu") -> list[Span]:
        """Map labels, apply thresholds, trim span ends and build :class:`Span` objects."""
        spans: set[Span] = set()
        for entity in raw:
            entity_type = self.label_map.get(entity.label.upper())
            if entity_type is None or entity_type not in self.entity_types:
                continue
            if not 0 <= entity.start < entity.end <= len(text):
                raise DetectionError("ner model returned offsets outside the input")
            score = min(max(float(entity.score), 0.0), 1.0)
            if score < self.threshold(language, entity_type):
                continue
            trimmed = _trim(text, entity.start, entity.end, entity_type)
            if trimmed is None:
                continue
            start, end = trimmed
            spans.add(Span(start, end, entity_type, text[start:end], score, self.name))
        # Names, organisations and addresses start and end on word boundaries (LAB-1338).
        found = snap_to_words(text, list(spans), language)
        # Numbers and phones cover whole tokens, so no digits stay next to the mask (LAB-1367).
        found = snap_to_tokens(text, found)
        if self.number_checks:
            # Format, checksum and cue checks for the numbers the model proposes (LAB-1293).
            found = sorted(
                set(check_numbers(text, found)),
                key=lambda s: (s.start, s.end, s.entity_type.value),
            )
        found = relabel_brands(text, found, language)  # brand names as PERSON (LAB-1336)
        # File names, paths, code and tool names in agent text are not personal data (LAB-1470).
        return guard_spans(text, found, language)


def _trim(text: str, start: int, end: int, entity_type: EntityType) -> tuple[int, int] | None:
    trim = _TRIM + "." if entity_type is EntityType.PERSON else _TRIM
    while start < end and text[start] in trim:
        start += 1
    while end > start and text[end - 1] in trim:
        end -= 1
    if start >= end or not any(ch.isalnum() for ch in text[start:end]):
        return None
    return start, end


if dependencies_available():
    DETECTOR_CLASS = NerDetector


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m pii_guard.detect.ner download``: fetch the model into the local cache."""
    parser = argparse.ArgumentParser(prog="python -m pii_guard.detect.ner")
    sub = parser.add_subparsers(dest="command", required=True)
    download = sub.add_parser("download", help="download the model into the Hugging Face cache")
    download.add_argument("--model", help=f"hub id or path (default: {MODEL_ENV_VAR} or default)")
    download.add_argument("--revision")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not dependencies_available():
        print("install the 'ner' extra first: uv sync --extra ner", file=sys.stderr)
        return 2
    detector = NerDetector(model=args.model, revision=args.revision, device="cpu")
    try:
        detector.load()
    except DetectionError as exc:
        print(f"ner: {exc.message}", file=sys.stderr)
        return 1
    print(f"ner: model ready: {detector.model}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
