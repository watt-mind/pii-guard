"""spaCy models the Presidio baselines need that are not plain package dependencies.

huSpaCy's ``hu_core_news_lg`` is published on Hugging Face. Its download URL redirects to a
signed CDN URL served with ``cache-control: no-store``, so as a ``[tool.uv.sources]`` URL uv
could never reuse its cached copy and re-downloaded the 401 MB wheel on every ``uv sync`` /
``uv run`` in every worktree (LAB-1249). It is fetched once instead:

1. ``pii-guard baselines download`` (``make baselines``) fetches the wheel with
   ``huggingface_hub.snapshot_download`` at the pinned revision: one copy in the Hugging Face
   cache (``~/.cache/huggingface``), keyed by revision;
2. checks the wheel's sha256 against the pin;
3. unpacks its ``hu_core_news_lg`` package once into the pii-guard model cache
   (``$PII_GUARD_MODELS_DIR``, default ``~/.cache/pii-guard/models``).

The baselines then import that package (which registers huSpaCy's custom lemmatizer
components) and hand spaCy the pipeline's data directory, the same files and code the
installed wheel loaded. Model licence and attribution: see ``docs/evaluation.md``.
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from pii_guard.eval.baselines.base import BaselineUnavailable
from pii_guard.eval.stats import sha256_file

__all__ = [
    "DOWNLOAD_HINT",
    "HU_CORE_NEWS_LG",
    "PinnedSpacyWheel",
    "download",
    "import_model",
    "models_dir",
]

DOWNLOAD_HINT = "run once: pii-guard baselines download (or make baselines)"
_MARKER = ".sha256"


@dataclass(frozen=True)
class PinnedSpacyWheel:
    """A spaCy model wheel in a Hugging Face repo, pinned by revision and sha256."""

    package: str
    version: str
    repo_id: str
    revision: str
    sha256: str

    @property
    def filename(self) -> str:
        return f"{self.package}-{self.version}-py3-none-any.whl"

    @property
    def label(self) -> str:
        return f"{self.package} {self.version} @ {self.repo_id}@{self.revision[:12]}"

    def root(self, base: Path | None = None) -> Path:
        """Directory holding the unpacked package (what goes on ``sys.path``)."""
        return (base or models_dir()) / f"{self.package}-{self.version}-{self.revision[:12]}"

    def data_dir(self, base: Path | None = None) -> Path:
        """The pipeline directory spaCy loads (``config.cfg``, ``meta.json``, weights)."""
        return self.root(base) / self.package / f"{self.package}-{self.version}"

    def is_ready(self, base: Path | None = None) -> bool:
        marker = self.root(base) / _MARKER
        try:
            return marker.read_text(encoding="utf-8").strip() == self.sha256
        except OSError:
            return False


HU_CORE_NEWS_LG = PinnedSpacyWheel(
    package="hu_core_news_lg",
    version="3.8.1",
    repo_id="huspacy/hu_core_news_lg",
    revision="9160ba69dbbcfe1a2346f3c7c2d72831f8250219",
    sha256="e8cd6a5478419a8cdf3af1c3e3447565a49b8c60228acf76fdbd4c5ae3611cf1",
)


def models_dir() -> Path:
    override = os.environ.get("PII_GUARD_MODELS_DIR")
    if override:
        return Path(override).expanduser()
    cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(cache) / "pii-guard" / "models"


def _fetch_wheel(model: PinnedSpacyWheel) -> Path:
    try:
        from huggingface_hub import snapshot_download  # type: ignore[import-not-found]
    except ImportError:
        raise BaselineUnavailable(
            "huggingface_hub is not installed (install the extra: uv sync --extra baselines)"
        ) from None
    snapshot = snapshot_download(
        model.repo_id, revision=model.revision, allow_patterns=[model.filename]
    )
    return Path(snapshot) / model.filename


def unpack(model: PinnedSpacyWheel, wheel: Path, base: Path | None = None) -> Path:
    """Check ``wheel`` against the pin and unpack its package into the model cache."""
    actual = sha256_file(wheel)
    if actual != model.sha256:
        raise BaselineUnavailable(
            f"{model.filename}: sha256 {actual} does not match the pinned {model.sha256}"
        )
    root = model.root(base)
    root.parent.mkdir(parents=True, exist_ok=True)
    prefix = f"{model.package}/"
    with tempfile.TemporaryDirectory(dir=root.parent, prefix=f".{root.name}-") as tmp:
        staging = Path(tmp) / "pkg"
        staging.mkdir()
        with zipfile.ZipFile(wheel) as zf:
            members = [m for m in zf.namelist() if m.startswith(prefix)]
            for member in members:
                target = (staging / member).resolve()
                if not target.is_relative_to(staging.resolve()):
                    raise BaselineUnavailable(f"{model.filename}: unsafe path {member!r}")
            zf.extractall(staging, members=members)
        (staging / _MARKER).write_text(model.sha256 + "\n", encoding="utf-8")
        if root.exists():
            shutil.rmtree(root)
        staging.rename(root)
    return root


def download(model: PinnedSpacyWheel = HU_CORE_NEWS_LG, base: Path | None = None) -> Path:
    """Fetch, verify and unpack ``model`` unless it already is; returns its data directory."""
    if not model.is_ready(base):
        unpack(model, _fetch_wheel(model), base)
    return model.data_dir(base)


def import_model(model: PinnedSpacyWheel = HU_CORE_NEWS_LG, base: Path | None = None) -> Path:
    """Import the unpacked package (registers its components); returns the data directory."""
    if not model.is_ready(base):
        raise BaselineUnavailable(f"spaCy model {model.package} not downloaded ({DOWNLOAD_HINT})")
    root = str(model.root(base))
    if root not in sys.path:
        sys.path.insert(0, root)
    importlib.import_module(model.package)
    return model.data_dir(base)
