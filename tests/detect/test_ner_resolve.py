"""NER model resolution: configured, published, public fallback; the model cache (LAB-1192)."""

from __future__ import annotations

import hashlib
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from pii_guard.config import Settings
from pii_guard.detect import ner_resolve
from pii_guard.detect.ner_resolve import (
    PUBLIC_FALLBACK,
    NerChoice,
    PinnedModel,
    describe,
    ensure,
    resolve,
)
from pii_guard.types import DetectionError

WEIGHTS = b"fictional weights"
PIN = PinnedModel(
    repo_id="fictional/pii-ner",
    revision="0123456789abcdef0123456789abcdef01234567",
    licence="Apache-2.0",
    size_mb=1,
    weights_sha256=hashlib.sha256(WEIGHTS).hexdigest(),
)


@pytest.fixture
def fallback(monkeypatch: pytest.MonkeyPatch) -> PinnedModel:
    """The fictional pin as the public fallback, in the default ``download`` mode."""
    monkeypatch.setattr(ner_resolve, "PUBLIC_FALLBACK", PIN)
    monkeypatch.setenv("PII_GUARD_NER_FALLBACK", "download")
    return PIN


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """A fake ``huggingface_hub.snapshot_download`` that writes the pinned files."""
    calls: list[dict[str, Any]] = []

    def snapshot_download(repo_id: str, **kwargs: Any) -> str:
        calls.append({"repo_id": repo_id, **kwargs})
        target = Path(kwargs["local_dir"])
        target.mkdir(parents=True, exist_ok=True)
        (target / "config.json").write_text("{}", encoding="utf-8")
        (target / "model.safetensors").write_bytes(kwargs.get("_weights", WEIGHTS))
        return str(target)

    module = types.ModuleType("huggingface_hub")
    module.snapshot_download = snapshot_download  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "huggingface_hub", module)
    return calls


def test_public_fallback_is_pinned_and_licence_checked() -> None:
    assert PUBLIC_FALLBACK.licence == "Apache-2.0"
    assert len(PUBLIC_FALLBACK.revision) == 40
    assert len(PUBLIC_FALLBACK.weights_sha256) == 64
    # LAB-1306 publishes the trained checkpoint here; until it pins a revision, step 2 is skipped.
    assert ner_resolve.PUBLISHED.repo_id == ner_resolve.PUBLISHED_REPO
    assert ner_resolve.PUBLISHED.revision == ""
    assert Settings().ner_published_model == ner_resolve.PUBLISHED_REPO


def test_models_dir_default_and_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PII_GUARD_MODELS_DIR")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert ner_resolve.models_dir() == tmp_path / "pii-guard" / "models"
    monkeypatch.setenv("PII_GUARD_MODELS_DIR", str(tmp_path / "elsewhere"))
    assert PIN.local_dir() == tmp_path / "elsewhere" / "ner" / "fictional--pii-ner-0123456789ab"


def test_configured_model_wins(fallback: PinnedModel) -> None:
    choice = resolve(configured="./models/fictional-ner", revision="r1", fallback="download")
    assert (choice.source, choice.model, choice.revision) == (
        "configured",
        "./models/fictional-ner",
        "r1",
    )
    assert describe(choice) == "rules + NER: ./models/fictional-ner (PII_GUARD_NER_MODEL)"
    env = {"PII_GUARD_NER_MODEL": "fictional/other", "PII_GUARD_NER_REVISION": "r2"}
    assert resolve(env=env).model == "fictional/other"
    assert resolve(env=env).revision == "r2"


def test_published_before_fallback(fallback: PinnedModel) -> None:
    choice = resolve(published="fictional/pii-guard-ner@abcdef1234567")
    assert choice.source == "published"
    assert choice.pinned is not None and choice.pinned.revision == "abcdef1234567"
    assert not choice.ready and choice.may_download
    assert "published pii-guard model" in describe(choice)
    # "cached" never downloads: an unready published model is skipped, so is the fallback.
    assert resolve(published="fictional/pii-guard-ner@abcdef1", fallback="cached").model is None
    # No revision: not published yet, so never loaded unpinned; the fallback runs instead.
    for unpinned in ("fictional/pii-guard-ner", "", ner_resolve.PUBLISHED_REPO):
        assert resolve(published=unpinned).source == "fallback"


def test_published_default_once_pinned(
    monkeypatch: pytest.MonkeyPatch, fallback: PinnedModel
) -> None:
    pinned = PinnedModel(
        repo_id=ner_resolve.PUBLISHED_REPO,
        revision="fedcba9876543210fedcba9876543210fedcba98",
        licence="Apache-2.0",
        size_mb=1,
    )
    monkeypatch.setattr(ner_resolve, "PUBLISHED", pinned)
    choice = resolve()
    assert (choice.source, choice.pinned) == ("published", pinned)
    assert choice.model == str(pinned.local_dir())


def test_fallback_modes(fallback: PinnedModel, hub: list[dict[str, Any]]) -> None:
    missing = resolve(fallback="download")
    assert (missing.source, missing.ready, missing.may_download) == ("fallback", False, True)
    assert "downloads on first run" in describe(missing)
    none = resolve(fallback="cached")
    assert (none.source, none.model, none.usable) == ("none", None, False)
    assert describe(none).startswith("rules only (public fallback not downloaded")
    off = resolve(fallback="off")
    assert off.model is None and "PII_GUARD_NER_FALLBACK=off" in off.reason
    with pytest.raises(ValueError, match="PII_GUARD_NER_FALLBACK"):
        resolve(fallback="sometimes")

    ensure(missing, progress=lambda _: None)
    cached = resolve(fallback="cached")
    assert (cached.source, cached.ready) == ("fallback", True)
    assert cached.model == str(PIN.local_dir())
    assert "downloads on first run" not in describe(cached)


def test_ensure_downloads_once_at_the_pinned_revision(
    fallback: PinnedModel, hub: list[dict[str, Any]]
) -> None:
    messages: list[str] = []
    path = ensure(resolve(), progress=messages.append)
    assert path == str(PIN.local_dir())
    assert hub == [
        {
            "repo_id": PIN.repo_id,
            "revision": PIN.revision,
            "local_dir": PIN.local_dir(),
            "allow_patterns": list(PIN.files),
        }
    ]
    assert "first run only" in messages[0] and "Apache-2.0" in messages[0]
    assert (Path(path) / ".pii-guard-verified").read_text().strip() == PIN.weights_sha256
    assert ensure(resolve()) == path
    assert len(hub) == 1  # cached: no second download


def test_ensure_rejects_weights_that_do_not_match_the_pin(
    monkeypatch: pytest.MonkeyPatch, fallback: PinnedModel, hub: list[dict[str, Any]]
) -> None:
    module = sys.modules["huggingface_hub"]
    real = module.snapshot_download  # type: ignore[attr-defined]
    monkeypatch.setattr(
        module, "snapshot_download", lambda repo, **kw: real(repo, _weights=b"tampered", **kw)
    )
    with pytest.raises(DetectionError, match="does not match the pin"):
        ensure(resolve(), progress=lambda _: None)
    assert not PIN.is_ready()


def test_ensure_hides_download_errors(
    monkeypatch: pytest.MonkeyPatch, fallback: PinnedModel, hub: list[dict[str, Any]]
) -> None:
    def fail(*_: Any, **__: Any) -> str:
        raise OSError("network said: fictional detail")

    monkeypatch.setattr(sys.modules["huggingface_hub"], "snapshot_download", fail)
    with pytest.raises(DetectionError) as info:
        ensure(resolve(), progress=lambda _: None)
    assert str(info.value) == "ner model download failed (OSError)"


def test_ensure_without_a_model_or_permission(fallback: PinnedModel) -> None:
    with pytest.raises(DetectionError, match="no ner model"):
        ensure(resolve(fallback="off"))
    no_download = NerChoice("fallback", str(PIN.local_dir()), pinned=PIN, ready=False)
    with pytest.raises(DetectionError, match="downloading is off"):
        ensure(no_download)
    configured = resolve(configured="fictional/other")
    assert ensure(configured) == "fictional/other"


def test_cli_status_and_fetch(
    monkeypatch: pytest.MonkeyPatch,
    fallback: PinnedModel,
    hub: list[dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PII_GUARD_NER_FALLBACK", "cached")  # empty cache: nothing to fetch
    assert ner_resolve.main(["status"]) == 0
    assert "rules only" in capsys.readouterr().out
    assert ner_resolve.main(["fetch"]) == 0
    assert hub == []
    monkeypatch.setenv("PII_GUARD_NER_FALLBACK", "download")
    if ner_resolve.extra_installed():
        assert ner_resolve.main(["fetch"]) == 0
        assert "model directory" in capsys.readouterr().out
        assert len(hub) == 1
    else:
        assert ner_resolve.main(["fetch"]) == 2
