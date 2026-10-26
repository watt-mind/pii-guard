"""NER detector: an open multilingual token-classification encoder for names, addresses and orgs.

The fast-mode complement to the rules: rules find structured identifiers (checksums, formats),
this detector finds ``PERSON``, ``ADDRESS``, ``ORGANIZATION`` and, with a model trained for it,
``DATE_OF_BIRTH``, in any language the encoder covers. It runs in-process (CPU, Apple MPS or
CUDA), so the text never leaves the guard. See ``docs/models.md``.

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

from pii_guard.types import DetectionError, EntityType, Span

__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_REVISION",
    "DEFAULT_THRESHOLDS",
    "DEVICE_ENV_VAR",
    "LABEL_MAP",
    "MODEL_ENV_VAR",
    "NER_ENTITY_TYPES",
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

#: Zero-shot default: XLM-RoBERTa-base fine-tuned for PER/ORG/LOC/DATE NER on ten high-resource
#: languages (AFL-3.0). Hungarian is not among them; it works cross-lingually. Point
#: ``PII_GUARD_NER_MODEL`` at the fine-tuned model (``training/ner/``) for better results.
DEFAULT_MODEL = "Davlan/xlm-roberta-base-ner-hrl"
#: Pinned hub revision of :data:`DEFAULT_MODEL` (used only when the default model is used).
DEFAULT_REVISION = "253f557bd8249b8515114cfd7f71974fe5fa4d2f"
MODEL_ENV_VAR = "PII_GUARD_NER_MODEL"
REVISION_ENV_VAR = "PII_GUARD_NER_REVISION"
DEVICE_ENV_VAR = "PII_GUARD_NER_DEVICE"

#: The types this detector reports. Structured identifiers are left to the rules.
NER_ENTITY_TYPES: frozenset[EntityType] = frozenset(
    {EntityType.PERSON, EntityType.ADDRESS, EntityType.ORGANIZATION, EntityType.DATE_OF_BIRTH}
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
}

#: Minimum span score per language and type. ``"default"`` applies to every other language.
DEFAULT_THRESHOLDS: dict[str, dict[EntityType, float]] = {
    "default": {
        EntityType.PERSON: 0.5,
        EntityType.ADDRESS: 0.5,
        EntityType.ORGANIZATION: 0.5,
        EntityType.DATE_OF_BIRTH: 0.5,
    },
}

# Trimmed off span ends. Dots are kept: they belong to "Kft.", "Ltd." and Hungarian dates and
# house numbers ("1982.06.26.", "utca 12."); a PERSON span loses a trailing dot.
_TRIM = " \t\r\n,;:!?()[]{}\"'\u00ab\u00bb\u201e\u201c\u201d\u2018\u2019\u2013\u2014-/"
_REQUIRED_MODULES = ("torch", "transformers")


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
    """Runs the model: text in, raw entities with character offsets into that text out."""

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


class TransformersBackend:
    """A Hugging Face token-classification model run with PyTorch.

    ``max_length`` and ``stride`` (tokens) set the window and overlap for long inputs.
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
    ) -> None:
        if stride >= max_length // 2:
            raise ValueError("stride must be less than half of max_length")
        import torch
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        self._torch = torch
        self.device = select_device(device)
        kwargs: dict[str, Any] = {"revision": revision, "local_files_only": local_files_only}
        self.tokenizer = AutoTokenizer.from_pretrained(model, use_fast=True, **kwargs)
        if not getattr(self.tokenizer, "is_fast", False):
            raise DetectionError("ner model needs a fast tokenizer (character offsets)")
        self.model = AutoModelForTokenClassification.from_pretrained(model, **kwargs)
        self.model.to(self.device)
        self.model.eval()
        config = self.model.config
        self.id2label: dict[int, str] = {int(k): v for k, v in config.id2label.items()}
        self.aggregation = aggregation or getattr(config, "pii_guard_aggregation", None) or "first"
        model_max = getattr(self.tokenizer, "model_max_length", max_length) or max_length
        self.max_length = min(max_length, model_max if model_max < 100_000 else max_length)
        self.stride = stride
        self._lock = threading.Lock()  # fast tokenizers are not safe for concurrent calls

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
            offsets = enc.pop("offset_mapping").tolist()
            enc.pop("overflow_to_sample_mapping", None)
            word_ids = [enc.word_ids(i) for i in range(len(offsets))]
            inputs = {k: v.to(self.device) for k, v in enc.items()}
            probs = torch.softmax(self.model(**inputs).logits.float(), dim=-1)
            best, ids = probs.max(dim=-1)
            best, ids = best.cpu().tolist(), ids.cpu().tolist()
        entities: list[RawEntity] = []
        for window in range(len(offsets)):
            entities.extend(
                decode_tokens(
                    [tuple(o) for o in offsets[window]],
                    word_ids[window],
                    [self.id2label[i] for i in ids[window]],
                    best[window],
                    aggregation=self.aggregation,
                )
            )
        return merge_entities(entities)


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

    - ``model`` / ``revision``: hub id or local directory, default ``PII_GUARD_NER_MODEL`` then
      :data:`DEFAULT_MODEL` (pinned to :data:`DEFAULT_REVISION`), and ``PII_GUARD_NER_REVISION``.
    - ``device``: ``auto`` (default, ``PII_GUARD_NER_DEVICE``), ``cpu``, ``mps``, ``cuda``.
    - ``thresholds``: ``{language: {entity_type: min_score}}``, merged over
      :data:`DEFAULT_THRESHOLDS`.
    - ``entity_types``: which of :data:`NER_ENTITY_TYPES` to report (default all).
    - ``label_map``: extra model-label → type mappings.
    - ``backend``: a :class:`NerBackend` to use instead of loading a model (tests), or a
      zero-argument factory for one.
    - ``preload``: load the model in the constructor (default), so a missing or broken model
      fails when the detector is built; ``False`` defers it to the first call.

    The model is loaded once, thread-safely; a load failure raises :class:`DetectionError`
    (and a deferred load is retried on the next call).
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
    ) -> None:
        env_model = os.environ.get(MODEL_ENV_VAR)
        self.model = model or env_model or DEFAULT_MODEL
        self.revision = (
            revision
            or os.environ.get(REVISION_ENV_VAR)
            or (DEFAULT_REVISION if self.model == DEFAULT_MODEL else None)
        )
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
        self._lock = threading.Lock()
        if preload:
            self.load()

    def __repr__(self) -> str:
        return f"NerDetector(model={self.model!r}, device={self.device or 'auto'!r})"

    # -- loading --

    def load(self) -> NerBackend:
        """Load the model (once). Raises :class:`DetectionError` if it can't be loaded."""
        if self._backend is not None:
            return self._backend
        with self._lock:
            if self._backend is None:
                try:
                    if self._factory is not None:
                        backend = self._factory()
                    else:
                        if not dependencies_available():
                            raise DetectionError(
                                "ner detector needs the 'ner' extra (torch, transformers)"
                            )
                        backend = TransformersBackend(
                            self.model,
                            revision=self.revision,
                            device=self.device,
                            max_length=self.max_length,
                            stride=self.stride,
                            aggregation=self.aggregation,
                        )
                except DetectionError:
                    raise
                except Exception as exc:
                    raise DetectionError(
                        f"ner model could not be loaded ({type(exc).__name__})"
                    ) from exc
                logger.info("ner model loaded: %s", self.model)
                self._backend = backend
        return self._backend

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
        return sorted(spans, key=lambda s: (s.start, s.end, s.entity_type.value))


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
