"""Model loaders refuse pickled weights: only ``model.safetensors`` is read (LAB-1304).

A ``pytorch_model.bin`` is unpickled on load, which can run code from a tampered checkpoint.
The transformers backend's own refusal is ``test_ner.py``'s
``test_transformers_backend_refuses_pickled_weights``; these cover GLiNER and the
published / fallback NER that ``ner_resolve`` downloads. None needs torch or the hub.
"""

from __future__ import annotations

import fnmatch
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from pii_guard.detect import ner, ner_gliner, ner_resolve
from pii_guard.detect.ner_resolve import PinnedModel
from pii_guard.types import DetectionError

REVISION = "0123456789abcdef0123456789abcdef01234567"


def _pickled(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in ner_gliner.PICKLE_PATTERNS)


def _checkpoint(root: Path, *weights: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "gliner_config.json").write_text("{}", encoding="utf-8")
    for name in weights:
        (root / name).write_bytes(b"fictional weights")
    return root


@pytest.fixture
def fake_gliner(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """A stand-in ``gliner`` package whose ``GLiNER.from_pretrained`` records its calls."""
    calls: list[tuple[str, dict[str, Any]]] = []

    class FakeModel:
        def to(self, device: Any) -> FakeModel:
            return self

        def eval(self) -> FakeModel:
            return self

        def inference(self, chunks: list[str], *args: Any, **kwargs: Any) -> list[list[Any]]:
            return [[] for _ in chunks]

    class GLiNER:
        @staticmethod
        def from_pretrained(model: str, **kwargs: Any) -> FakeModel:
            calls.append((model, kwargs))
            return FakeModel()

    module = types.ModuleType("gliner")
    module.GLiNER = GLiNER  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gliner", module)
    monkeypatch.setattr(ner_gliner, "select_device", lambda device: "cpu")
    return calls


@pytest.fixture
def fake_hub(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[dict[str, Any]]:
    """A stand-in ``huggingface_hub.snapshot_download`` that honours ``ignore_patterns``."""
    calls: list[dict[str, Any]] = []

    def snapshot_download(repo_id: str, **kwargs: Any) -> str:
        calls.append({"repo_id": repo_id, **kwargs})
        published = ("gliner_config.json", "model.safetensors", "pytorch_model.bin")
        ignored = kwargs.get("ignore_patterns") or []
        root = tmp_path / "hub" / repo_id.replace("/", "--")
        root.mkdir(parents=True, exist_ok=True)
        for name in published:
            if not any(fnmatch.fnmatch(name, p) for p in ignored):
                (root / name).write_text("{}", encoding="utf-8")
        return str(root)

    module = types.ModuleType("huggingface_hub")
    module.snapshot_download = snapshot_download  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "huggingface_hub", module)
    return calls


# -- GLiNER --


def test_gliner_backend_refuses_a_checkpoint_with_only_pickled_weights(
    tmp_path: Path, fake_gliner: list[tuple[str, dict[str, Any]]]
) -> None:
    pickled = _checkpoint(tmp_path / "pickled", "pytorch_model.bin")
    with pytest.raises(DetectionError, match="safetensors"):
        ner_gliner.GlinerBackend(str(pickled), device="cpu")
    assert fake_gliner == []  # GLiNER never saw the directory, so nothing was unpickled


def test_gliner_backend_loads_a_local_safetensors_checkpoint(
    tmp_path: Path, fake_gliner: list[tuple[str, dict[str, Any]]]
) -> None:
    local = _checkpoint(tmp_path / "local", "model.safetensors", "pytorch_model.bin")
    backend = ner_gliner.GlinerBackend(str(local), device="cpu")
    assert fake_gliner == [(str(local), {"local_files_only": False})]
    assert backend.predict("Teszt Elek") == []


def test_gliner_hub_checkpoint_is_fetched_without_pickles(
    fake_hub: list[dict[str, Any]], fake_gliner: list[tuple[str, dict[str, Any]]]
) -> None:
    ner_gliner.GlinerBackend(
        ner_gliner.DEFAULT_MODEL, revision=REVISION, device="cpu", local_files_only=True
    )
    (call,) = fake_hub
    assert call["repo_id"] == ner_gliner.DEFAULT_MODEL
    assert call["revision"] == REVISION and call["local_files_only"] is True
    assert call["ignore_patterns"] == list(ner_gliner.PICKLE_PATTERNS)
    (loaded, kwargs) = fake_gliner[0]
    # GLiNER gets the fetched directory, not the hub id: it downloads nothing itself.
    assert Path(loaded).is_dir() and kwargs == {"local_files_only": True}
    assert sorted(p.name for p in Path(loaded).iterdir()) == [
        "gliner_config.json",
        "model.safetensors",
    ]


def test_safetensors_checkpoint_refuses_a_hub_repo_without_safetensors(
    monkeypatch: pytest.MonkeyPatch, fake_hub: list[dict[str, Any]], tmp_path: Path
) -> None:
    def pickles_only(repo_id: str, **kwargs: Any) -> str:
        return str(_checkpoint(tmp_path / "pickles-only"))  # the .bin was filtered out

    monkeypatch.setattr(sys.modules["huggingface_hub"], "snapshot_download", pickles_only)
    with pytest.raises(DetectionError, match="safetensors"):
        ner_gliner.safetensors_checkpoint("fictional/gliner-pickles", revision=REVISION)


@pytest.mark.parametrize(
    "name", ["pytorch_model.bin", "model.pt", "weights.pth", "x.pkl", "x.pickle", "x.ckpt"]
)
def test_pickle_patterns_cover_the_pickled_weight_formats(name: str) -> None:
    assert _pickled(name)
    assert not _pickled("model.safetensors")


# -- published and fallback NER (ner_resolve) --


@pytest.mark.parametrize(
    "pinned",
    [
        ner_resolve.PUBLIC_FALLBACK,
        ner_resolve.PUBLISHED,
        ner_resolve._published(f"fictional/pii-ner@{REVISION}"),
    ],
    ids=["fallback", "published", "published-override"],
)
def test_pinned_models_download_safetensors_and_no_pickles(pinned: PinnedModel | None) -> None:
    assert pinned is not None
    assert "model.safetensors" in pinned.files
    assert not [name for name in pinned.files if _pickled(name)]


def test_resolved_fallback_loads_through_the_safetensors_only_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A published or fallback model is a local directory read by ``TransformersBackend``."""
    pin = PinnedModel(repo_id="fictional/pii-ner", revision=REVISION, licence="MIT", size_mb=1)
    root = pin.local_dir(tmp_path)
    root.mkdir(parents=True)
    (root / "config.json").write_text("{}", encoding="utf-8")
    (root / "model.safetensors").write_bytes(b"fictional weights")
    monkeypatch.setattr(ner_resolve, "PUBLIC_FALLBACK", pin)
    monkeypatch.setenv("PII_GUARD_MODELS_DIR", str(tmp_path))
    monkeypatch.delenv(ner.MODEL_ENV_VAR, raising=False)
    monkeypatch.delenv(ner.BACKEND_ENV_VAR, raising=False)
    monkeypatch.setattr(ner, "dependencies_available", lambda: True)
    monkeypatch.setattr(ner, "_shared_backends", {})
    built: list[str] = []

    class Recorder:
        def __init__(self, model: str, **kwargs: Any) -> None:
            built.append(model)

    monkeypatch.setattr(ner, "TransformersBackend", Recorder)
    detector = ner.NerDetector(fallback="cached", preload=False)
    assert detector.choice is not None and detector.choice.source == "fallback"
    assert isinstance(detector.load(), Recorder)
    assert built == [str(root)]
