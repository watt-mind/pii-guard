"""GLiNER backend for the NER detector: span extraction with label names given at run time.

`GLiNER <https://github.com/urchade/GLiNER>`_ scores text spans against natural-language label
names, so one checkpoint can look for types it was never fine-tuned on. pii-guard compared it
with its fine-tuned XLM-RoBERTa token classifiers (LAB-1150, ``docs/models.md``); this module
is how that comparison runs, and how to use a GLiNER checkpoint anyway:

- :class:`GlinerBackend` implements :class:`~pii_guard.detect.ner.NerBackend`: it asks for
  :data:`GLINER_LABELS` (label name -> pii-guard type) and returns entities labelled with the
  pii-guard type name, so :class:`~pii_guard.detect.ner.NerDetector` maps, thresholds and
  trims them like any other model's. Long texts are cut into overlapping word windows
  (GLiNER reads at most 384 words).
- :class:`GlinerDetector` is that detector under its own registry name, ``ner_gliner``
  (``--detectors rules,ner,ner_gliner`` runs both encoders and lets the resolver take the
  union). ``PII_GUARD_GLINER_MODEL`` picks the checkpoint (default :data:`DEFAULT_MODEL`,
  pinned to :data:`DEFAULT_REVISION`); a local directory with a ``gliner_config.json`` given
  as ``PII_GUARD_NER_MODEL`` makes the plain ``ner`` detector use this backend too.

Needs the ``gliner`` extra, which conflicts with ``ner`` (gliner 0.2.29 pins
``transformers < 5.17``): ``UV_PROJECT_ENVIRONMENT=.venv-gliner uv sync --extra gliner``.
Without it the module imports but defines no ``DETECTOR_CLASS``. Fail closed, as the NER
detector: load and inference errors raise :class:`~pii_guard.types.DetectionError` with the
exception type only. Only ``model.safetensors`` weights are loaded (:func:`safetensors_checkpoint`,
LAB-1304): a pickled ``pytorch_model.bin`` is never downloaded or unpickled.
"""

from __future__ import annotations

import importlib.util
import os
import re
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path

from pii_guard.detect.ner import (
    WARM_UP_TEXT,
    NerDetector,
    RawEntity,
    merge_entities,
    select_device,
)
from pii_guard.types import DetectionError, EntityType

__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_REVISION",
    "GLINER_LABELS",
    "GlinerBackend",
    "GlinerDetector",
    "dependencies_available",
    "is_gliner_checkpoint",
    "safetensors_checkpoint",
    "word_windows",
]

#: GLiNER multi v2.1: mDeBERTa-v3-base span model, multilingual, Apache-2.0.
DEFAULT_MODEL = "urchade/gliner_multi-v2.1"
DEFAULT_REVISION = "443d26d654e0324125a96bebd8e796c14ff2efe6"
MODEL_ENV_VAR = "PII_GUARD_GLINER_MODEL"

#: Label name asked for -> pii-guard type. The fine-tuned checkpoint is trained on the same
#: names, so zero-shot and fine-tuned runs differ only in the weights.
GLINER_LABELS: dict[str, EntityType] = {
    "person": EntityType.PERSON,
    "organization": EntityType.ORGANIZATION,
    "street address": EntityType.ADDRESS,
    "date of birth": EntityType.DATE_OF_BIRTH,
    "email address": EntityType.EMAIL,
    "phone number": EntityType.PHONE,
    "identity document number": EntityType.ID_DOCUMENT,
    "hungarian tax identification number": EntityType.NATIONAL_ID_HU_TAX,
    "hungarian social security number": EntityType.NATIONAL_ID_HU_TAJ,
    "bank account or card number": EntityType.BANK_ACCOUNT,
}

_WORD = re.compile(r"\S+")


def dependencies_available() -> bool:
    """True if the ``gliner`` extra (gliner, torch) is installed."""
    return all(importlib.util.find_spec(m) is not None for m in ("gliner", "torch"))


def is_gliner_checkpoint(model: str) -> bool:
    """A local directory holding a GLiNER checkpoint (``gliner_config.json``)."""
    return (Path(model) / "gliner_config.json").is_file()


#: Weight files that are unpickled on load (code execution from a tampered checkpoint).
PICKLE_PATTERNS = ("*.bin", "*.pt", "*.pth", "*.pkl", "*.pickle", "*.ckpt")


def safetensors_checkpoint(
    model: str, *, revision: str | None = None, local_files_only: bool = False
) -> str:
    """The local directory of GLiNER checkpoint ``model``, refusing pickled weights.

    ``GLiNER.from_pretrained`` has no ``use_safetensors`` switch: it downloads every file of a
    hub repo and, without a ``model.safetensors``, unpickles ``pytorch_model.bin``. So a hub id
    is fetched here at ``revision`` without :data:`PICKLE_PATTERNS`, and the directory (fetched
    or local) must hold ``model.safetensors``; the caller loads that directory. Raises
    :class:`DetectionError` otherwise.
    """
    path = Path(model)
    if not path.exists():
        from huggingface_hub import snapshot_download  # type: ignore[import-not-found]

        path = Path(
            snapshot_download(
                model,
                revision=revision,
                local_files_only=local_files_only,
                ignore_patterns=list(PICKLE_PATTERNS),
            )
        )
    if not (path / "model.safetensors").is_file():
        raise DetectionError("gliner checkpoint has no model.safetensors (pickled weights refused)")
    return str(path)


def word_windows(text: str, size: int = 160, overlap: int = 32) -> list[tuple[int, int]]:
    """Character ranges of overlapping windows of ``size`` whitespace-separated words."""
    if overlap >= size:
        raise ValueError("overlap must be less than size")
    words = [m.span() for m in _WORD.finditer(text)]
    if not words:
        return []
    out: list[tuple[int, int]] = []
    start = 0
    while True:
        end = min(start + size, len(words))
        out.append((words[start][0], words[end - 1][1]))
        if end == len(words):
            return out
        start = end - overlap


class GlinerBackend:
    """A GLiNER checkpoint run with PyTorch; entities come back labelled with pii-guard types."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        revision: str | None = None,
        device: str | None = None,
        labels: Mapping[str, EntityType] | None = None,
        threshold: float = 0.3,
        window_words: int = 160,
        batch_size: int = 8,
        local_files_only: bool = False,
    ) -> None:
        from gliner import GLiNER

        self.device = select_device(device)
        # safetensors only: a local directory, so GLiNER fetches nothing and finds no pickle.
        local = safetensors_checkpoint(model, revision=revision, local_files_only=local_files_only)
        self.model = GLiNER.from_pretrained(local, local_files_only=local_files_only)
        self.model.to(self.device)
        self.model.eval()
        self.labels = dict(labels or GLINER_LABELS)
        self.threshold = threshold
        self.window_words = window_words
        self.batch_size = batch_size
        self._lock = threading.Lock()
        # One forward on the device before the backend is published (LAB-1274).
        self.predict(WARM_UP_TEXT)

    def predict(self, text: str) -> list[RawEntity]:
        windows = word_windows(text, self.window_words, max(self.window_words // 5, 1))
        if not windows:
            return []
        chunks = [text[s:e] for s, e in windows]
        names = list(self.labels)
        with self._lock:
            found = self.model.inference(
                chunks,
                names,
                threshold=self.threshold,
                flat_ner=True,
                batch_size=self.batch_size,
            )
        out: list[RawEntity] = []
        for (offset, _), entities in zip(windows, found, strict=True):
            for e in entities:
                entity_type = self.labels.get(e["label"])
                if entity_type is None:
                    continue
                out.append(
                    RawEntity(
                        entity_type.value,
                        offset + int(e["start"]),
                        offset + int(e["end"]),
                        float(e["score"]),
                    )
                )
        return merge_entities(out)


class GlinerDetector(NerDetector):
    """:class:`NerDetector` with a :class:`GlinerBackend`, registry name ``ner_gliner``."""

    name = "ner_gliner"

    def __init__(
        self,
        *,
        model: str | None = None,
        revision: str | None = None,
        device: str | None = None,
        thresholds: Mapping[str, Mapping[EntityType | str, float]] | None = None,
        entity_types: Sequence[EntityType | str] | None = None,
        labels: Mapping[str, EntityType] | None = None,
        preload: bool = True,
    ) -> None:
        chosen = model or os.environ.get(MODEL_ENV_VAR) or DEFAULT_MODEL
        rev = revision or (DEFAULT_REVISION if chosen == DEFAULT_MODEL else None)

        def factory() -> GlinerBackend:
            if not dependencies_available():
                raise DetectionError("ner_gliner detector needs the 'gliner' extra")
            return GlinerBackend(chosen, revision=rev, device=device, labels=labels)

        super().__init__(
            model=chosen,
            revision=rev,
            device=device,
            thresholds=thresholds,
            entity_types=entity_types,
            backend=factory,
            preload=preload,
        )


if dependencies_available():
    DETECTOR_CLASS = GlinerDetector
