"""Which NER model fast mode runs, and fetching it once into the pii-guard model cache.

Resolution order (LAB-1192, ``docs/models.md``), first match wins:

1. **Configured**: ``PII_GUARD_NER_MODEL``, a local directory or a Hugging Face hub id (with
   ``PII_GUARD_NER_REVISION``). A configured model that can't load stops startup (ADR 0006).
2. **Published**: the published pii-guard checkpoint, ``PII_GUARD_NER_PUBLISHED_MODEL``
   (``repo`` or ``repo@revision``, default :data:`PUBLISHED_REPO`). It is used only once it is
   pinned: a ``@revision`` in the setting, or :data:`PUBLISHED`'s revision, which LAB-1306 fills
   in with the weights' SHA-256 when it publishes. Until then this step is skipped.
3. **Public fallback**: :data:`PUBLIC_FALLBACK`, a public multilingual PII token classifier
   (Apache-2.0), pinned to a hub revision. A stop-gap until the published checkpoint exists:
   it leaks little but over-masks (about 23 % on en-smoke). ``PII_GUARD_NER_FALLBACK`` decides
   what happens when it is not in the cache yet: ``download`` (default) fetches it on first
   use, ``cached`` uses it only if it is already there, ``off`` never uses it (fast mode is
   then rules only). Only ``download`` fetches anything, a pinned published model included.

Pinned models are fetched with ``huggingface_hub.snapshot_download`` at their revision, only the
files the detector reads, into ``$PII_GUARD_MODELS_DIR/ner/<repo>-<revision>`` (default
``~/.cache/pii-guard/models``, the cache LAB-1249 uses for huSpaCy), and loaded from that
directory, so a second run is offline. Nothing here goes through a ``uv`` source.

::

    uv run --extra ner python -m pii_guard.detect.ner_resolve status   # what would run
    uv run --extra ner python -m pii_guard.detect.ner_resolve fetch    # download it now
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pii_guard.types import DetectionError

__all__ = [
    "FALLBACK_ENV_VAR",
    "PUBLIC_FALLBACK",
    "PUBLISHED",
    "PUBLISHED_ENV_VAR",
    "PUBLISHED_REPO",
    "NerChoice",
    "PinnedModel",
    "describe",
    "ensure",
    "models_dir",
    "resolve",
]

MODEL_ENV_VAR = "PII_GUARD_NER_MODEL"
REVISION_ENV_VAR = "PII_GUARD_NER_REVISION"
PUBLISHED_ENV_VAR = "PII_GUARD_NER_PUBLISHED_MODEL"
FALLBACK_ENV_VAR = "PII_GUARD_NER_FALLBACK"
FALLBACK_MODES = ("download", "cached", "off")

Source = Literal["configured", "published", "fallback", "none"]


@dataclass(frozen=True, slots=True)
class PinnedModel:
    """A hub checkpoint pinned to a revision, cached as plain files in the model cache."""

    repo_id: str
    revision: str
    licence: str
    #: Approximate download size, for the progress message.
    size_mb: int
    #: SHA-256 of ``model.safetensors`` at :attr:`revision`; checked once after download.
    weights_sha256: str = ""
    files: tuple[str, ...] = (
        "config.json",
        "model.safetensors",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "sentencepiece.bpe.model",
    )

    @property
    def label(self) -> str:
        return f"{self.repo_id}@{self.revision[:12]}"

    def local_dir(self, base: Path | None = None) -> Path:
        name = f"{self.repo_id.replace('/', '--')}-{self.revision[:12]}"
        return (base or models_dir()) / "ner" / name

    def is_ready(self, base: Path | None = None) -> bool:
        """Downloaded and checked: the marker holds the weights' pinned SHA-256."""
        root = self.local_dir(base)
        marker = root / _MARKER
        if not ((root / "config.json").is_file() and (root / "model.safetensors").is_file()):
            return False
        if not self.weights_sha256:
            return True
        if not marker.is_file():
            return False
        return marker.read_text(encoding="utf-8").strip() == self.weights_sha256


_MARKER = ".pii-guard-verified"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


#: The public fallback (LAB-1192): bards.ai's EU PII detector v1, XLM-RoBERTa base fine-tuned
#: for PII in the 24 EU languages (Hungarian, English and German among them). Apache-2.0 per
#: its model card at this revision. It runs on the ``ner`` extra's transformers, unlike GLiNER
#: (``gliner`` pins an older transformers); measured in eval/results/2026-10-27-fast-demo-ner/.
PUBLIC_FALLBACK = PinnedModel(
    repo_id="bardsai/eu-pii-anonimization-multilang",
    revision="62ca5712368705bac11b8fea19e42e65cce088dd",
    licence="Apache-2.0",
    size_mb=1110,
    weights_sha256="03ec34b3cd297c25ab8c720352c125f571ebf844684d3fbb583927a73a7752fd",
)

#: Where the trained pii-guard NER is published (owner decision, LAB-1306).
PUBLISHED_REPO = "hdkiller/pii-guard-ner-xlmr-base"
#: The published checkpoint. LAB-1306 sets ``revision``, ``weights_sha256``, ``licence`` and
#: ``size_mb`` when it publishes; with an empty revision the step is skipped (nothing to pin).
PUBLISHED = PinnedModel(
    repo_id=PUBLISHED_REPO,
    revision="",
    licence="see its model card",
    size_mb=1110,
)


def models_dir() -> Path:
    """``$PII_GUARD_MODELS_DIR``, else ``$XDG_CACHE_HOME/pii-guard/models`` (``~/.cache``)."""
    override = os.environ.get("PII_GUARD_MODELS_DIR")
    if override:
        return Path(override).expanduser()
    cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(cache) / "pii-guard" / "models"


@dataclass(frozen=True, slots=True)
class NerChoice:
    """The resolved NER model. ``model`` is what to load (a directory or hub id), or ``None``."""

    source: Source
    model: str | None
    revision: str | None = None
    pinned: PinnedModel | None = None
    #: The weights are on disk (always true for a configured model: it is not ours to check).
    ready: bool = True
    #: ``download``: a missing pinned model may be fetched on first use.
    may_download: bool = False
    #: Why no model was picked (``source == "none"``).
    reason: str = ""

    @property
    def usable(self) -> bool:
        return self.model is not None and (self.ready or self.may_download)


def _env(env: Mapping[str, str] | None, name: str) -> str:
    return ((env if env is not None else os.environ).get(name) or "").strip()


def _published(value: str) -> PinnedModel | None:
    """The published checkpoint to try, or ``None`` while it has no pinned revision."""
    repo, _, revision = (value or PUBLISHED_REPO).partition("@")
    if not revision and repo == PUBLISHED.repo_id:
        revision = PUBLISHED.revision
    if not revision:
        return None  # not published yet (LAB-1306): never load an unpinned checkpoint
    if repo == PUBLISHED.repo_id and revision == PUBLISHED.revision:
        return PUBLISHED
    return PinnedModel(repo_id=repo, revision=revision, licence="see its model card", size_mb=0)


def resolve(
    *,
    configured: str | None = None,
    revision: str | None = None,
    published: str | None = None,
    fallback: str | None = None,
    base: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> NerChoice:
    """Pick the NER model: configured, then published, then the public fallback.

    Arguments win over the environment variables of the same meaning (``Settings`` passes its
    values, so ``.env`` counts too). Never downloads: :func:`ensure` does.
    """
    model = (configured or _env(env, MODEL_ENV_VAR)).strip()
    if model:
        return NerChoice(
            "configured", model, revision or _env(env, REVISION_ENV_VAR) or None, ready=True
        )
    mode = (fallback or _env(env, FALLBACK_ENV_VAR) or "download").lower()
    if mode not in FALLBACK_MODES:
        raise ValueError(f"{FALLBACK_ENV_VAR} must be one of {FALLBACK_MODES}")
    candidates: list[tuple[Source, PinnedModel]] = []
    pub = _published((published or _env(env, PUBLISHED_ENV_VAR)).strip())
    if pub is not None:
        candidates.append(("published", pub))
    if mode != "off":
        candidates.append(("fallback", PUBLIC_FALLBACK))
    for source, pinned in candidates:
        ready = pinned.is_ready(base)
        if ready or mode == "download":
            return NerChoice(
                source,
                str(pinned.local_dir(base)),
                None,
                pinned,
                ready=ready,
                may_download=not ready and mode == "download",
            )
    if mode == "off":
        reason = f"no NER model configured and {FALLBACK_ENV_VAR}=off"
    else:
        reason = f"public fallback not downloaded and {FALLBACK_ENV_VAR}=cached"
    return NerChoice("none", None, reason=reason)


def ensure(
    choice: NerChoice,
    *,
    base: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> str:
    """The model to load for ``choice``, downloading a missing pinned model first.

    Raises :class:`DetectionError` if there is nothing to load, if downloading is not allowed
    or if it fails (exception type only, ADR 0006).
    """
    if choice.model is None:
        raise DetectionError(f"no ner model: {choice.reason}")
    pinned = choice.pinned
    if pinned is None or choice.ready:
        return choice.model
    if pinned.is_ready(base):
        return str(pinned.local_dir(base))
    if not choice.may_download:
        raise DetectionError(
            f"ner model {pinned.label} is not in the model cache and downloading is off "
            "(python -m pii_guard.detect.ner_resolve fetch)"
        )
    target = pinned.local_dir(base)
    say = progress or (lambda message: print(message, file=sys.stderr, flush=True))
    say(
        f"ner: downloading {pinned.label} ({pinned.licence}, about {pinned.size_mb} MB, "
        f"first run only) into {target}"
    )
    try:
        from huggingface_hub import snapshot_download  # type: ignore[import-not-found]
    except ImportError:
        raise DetectionError("ner download needs huggingface_hub (the 'ner' extra)") from None
    try:
        snapshot_download(
            pinned.repo_id,
            revision=pinned.revision,
            local_dir=target,
            allow_patterns=list(pinned.files),
        )
    except Exception as exc:
        raise DetectionError(f"ner model download failed ({type(exc).__name__})") from exc
    if pinned.weights_sha256 and (target / "model.safetensors").is_file():
        actual = _sha256(target / "model.safetensors")
        if actual != pinned.weights_sha256:
            raise DetectionError(
                f"ner model {pinned.label}: weights sha256 {actual} does not match the pin"
            )
        (target / _MARKER).write_text(actual + "\n", encoding="utf-8")
    if not pinned.is_ready(base):
        raise DetectionError(f"ner model download of {pinned.label} is incomplete")
    say(f"ner: {pinned.label} ready")
    return str(target)


def extra_installed() -> bool:
    """The ``ner`` extra (torch, transformers) is importable."""
    return all(importlib.util.find_spec(m) is not None for m in ("torch", "transformers"))


def describe(choice: NerChoice) -> str:
    """One banner line: which model fast mode runs and where it comes from."""
    if choice.model is None:
        return f"rules only ({choice.reason})"
    if choice.source == "configured":
        name = Path(choice.model).name if Path(choice.model).is_dir() else choice.model
        return f"rules + NER: {name} (PII_GUARD_NER_MODEL)"
    pinned = choice.pinned
    assert pinned is not None  # noqa: S101 - published and fallback are pinned
    where = "published pii-guard model" if choice.source == "published" else "public fallback"
    state = "" if choice.ready else ", downloads on first run"
    return f"rules + NER: {pinned.label} ({where}, {pinned.licence}{state})"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pii_guard.detect.ner_resolve",
        description="Show or fetch the NER model fast mode runs (docs/models.md).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="print the resolved model, download nothing")
    sub.add_parser("fetch", help="download the resolved model into the model cache if missing")
    args = parser.parse_args(list(argv) if argv is not None else None)
    choice = resolve()
    print(f"ner: {describe(choice)}")
    if args.command == "status":
        return 0
    if choice.model is None:
        return 0
    if not extra_installed():
        print("ner: install the 'ner' extra first: uv sync --extra ner", file=sys.stderr)
        return 2
    try:
        print(f"ner: model directory {ensure(choice)}")
    except DetectionError as exc:
        print(f"ner: {exc.message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
