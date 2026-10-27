"""The pinned huSpaCy model: fetched once, sha256-checked, unpacked, loaded by path (LAB-1249)."""

from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

import pytest

from pii_guard import cli
from pii_guard.eval.baselines import image, models
from pii_guard.eval.baselines.base import BaselineUnavailable
from pii_guard.eval.baselines.models import PinnedSpacyWheel


def _wheel(tmp_path: Path, package: str, *, extra: dict[str, str] | None = None) -> Path:
    path = tmp_path / f"{package}-1.0.0-py3-none-any.whl"
    files = {
        f"{package}/__init__.py": "LOADED = True\n",
        f"{package}/meta.json": '{"version": "1.0.0"}',
        f"{package}/{package}-1.0.0/config.cfg": "[nlp]\n",
        f"{package}-1.0.0.dist-info/METADATA": "Name: x\n",
        **(extra or {}),
    }
    with zipfile.ZipFile(path, "w") as zf:
        for name, body in files.items():
            zf.writestr(name, body)
    return path


def _pin(wheel: Path, package: str) -> PinnedSpacyWheel:
    return PinnedSpacyWheel(
        package=package,
        version="1.0.0",
        repo_id="example/model",
        revision="0123456789abcdef0123456789abcdef01234567",
        sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
    )


def test_the_huspacy_pin_is_the_wheel_the_lock_used_to_carry() -> None:
    pin = models.HU_CORE_NEWS_LG
    assert pin.filename == "hu_core_news_lg-3.8.1-py3-none-any.whl"
    assert pin.revision == "9160ba69dbbcfe1a2346f3c7c2d72831f8250219"
    assert pin.sha256 == "e8cd6a5478419a8cdf3af1c3e3447565a49b8c60228acf76fdbd4c5ae3611cf1"


def test_models_dir_honours_the_override_and_xdg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PII_GUARD_MODELS_DIR", str(tmp_path / "m"))
    assert models.models_dir() == tmp_path / "m"
    monkeypatch.delenv("PII_GUARD_MODELS_DIR")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert models.models_dir() == tmp_path / "xdg" / "pii-guard" / "models"


def test_unpack_checks_the_sha256_and_keeps_only_the_package(tmp_path: Path) -> None:
    package = "pg_fake_model_unpack"
    wheel = _wheel(tmp_path, package)
    pin = _pin(wheel, package)
    base = tmp_path / "cache"
    assert not pin.is_ready(base)

    root = models.unpack(pin, wheel, base)

    assert root == pin.root(base)
    assert pin.is_ready(base)
    assert (pin.data_dir(base) / "config.cfg").is_file()
    assert not any(p.name.endswith(".dist-info") for p in root.iterdir())
    assert [p.name for p in root.parent.iterdir()] == [root.name]  # no staging left behind
    models.unpack(pin, wheel, base)  # re-unpacking replaces the copy
    assert pin.is_ready(base)


def test_unpack_refuses_a_wheel_that_does_not_match_the_pin(tmp_path: Path) -> None:
    package = "pg_fake_model_bad"
    wheel = _wheel(tmp_path, package)
    pin = _pin(wheel, package)
    tampered = PinnedSpacyWheel(**{**pin.__dict__, "sha256": "0" * 64})
    with pytest.raises(BaselineUnavailable, match="does not match the pinned"):
        models.unpack(tampered, wheel, tmp_path / "cache")
    assert not tampered.is_ready(tmp_path / "cache")


def test_unpack_refuses_paths_outside_the_cache(tmp_path: Path) -> None:
    package = "pg_fake_model_evil"
    wheel = _wheel(tmp_path, package, extra={f"{package}/../../escape.py": "x = 1\n"})
    with pytest.raises(BaselineUnavailable, match="unsafe path"):
        models.unpack(_pin(wheel, package), wheel, tmp_path / "cache")


def test_download_fetches_only_when_not_unpacked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package = "pg_fake_model_download"
    wheel = _wheel(tmp_path, package)
    pin = _pin(wheel, package)
    fetched: list[str] = []

    def fake_fetch(model: PinnedSpacyWheel) -> Path:
        fetched.append(model.package)
        return wheel

    monkeypatch.setattr(models, "_fetch_wheel", fake_fetch)
    base = tmp_path / "cache"
    assert models.download(pin, base) == pin.data_dir(base)
    assert models.download(pin, base) == pin.data_dir(base)
    assert fetched == [package]


def test_import_model_needs_the_download_then_imports_the_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package = "pg_fake_model_import"
    wheel = _wheel(tmp_path, package)
    pin = _pin(wheel, package)
    base = tmp_path / "cache"
    with pytest.raises(BaselineUnavailable, match="pii-guard baselines download"):
        models.import_model(pin, base)

    models.unpack(pin, wheel, base)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delitem(sys.modules, package, raising=False)
    assert models.import_model(pin, base) == pin.data_dir(base)
    assert sys.modules[package].LOADED is True
    assert sys.path.count(str(pin.root(base))) == 1
    models.import_model(pin, base)
    assert sys.path.count(str(pin.root(base))) == 1


def test_fetch_wheel_without_huggingface_hub_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    with pytest.raises(BaselineUnavailable, match="huggingface_hub is not installed"):
        models._fetch_wheel(models.HU_CORE_NEWS_LG)


def test_fetch_wheel_asks_for_the_pinned_revision_and_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, str, list[str]]] = []

    class FakeHub:
        @staticmethod
        def snapshot_download(repo_id: str, *, revision: str, allow_patterns: list[str]) -> str:
            calls.append((repo_id, revision, allow_patterns))
            return str(tmp_path)

    monkeypatch.setitem(sys.modules, "huggingface_hub", FakeHub)
    pin = models.HU_CORE_NEWS_LG
    assert models._fetch_wheel(pin) == tmp_path / pin.filename
    assert calls == [(pin.repo_id, pin.revision, [pin.filename])]


def test_cli_download_reports_the_data_dir(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(models, "download", lambda model: tmp_path / "data")
    assert cli.main(["baselines", "download"]) == 0
    assert str(tmp_path / "data") in capsys.readouterr().out


def test_cli_download_failure_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(model: PinnedSpacyWheel) -> Path:
        raise BaselineUnavailable("no network")

    monkeypatch.setattr(models, "download", fail)
    assert cli.main(["baselines", "download"]) == 1
    assert "no network" in capsys.readouterr().err


def test_cli_baselines_without_a_subcommand_prints_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["baselines"])
    assert exc.value.code == 0
    assert "download" in capsys.readouterr().out


def test_presidio_image_needs_the_downloaded_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PII_GUARD_MODELS_DIR", str(tmp_path / "empty"))
    with pytest.raises(BaselineUnavailable, match="pii-guard baselines download"):
        image.IMAGE_BASELINES["presidio-image"]()


def test_presidio_image_hands_the_worker_the_unpacked_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(models.HU_CORE_NEWS_LG.__class__, "is_ready", lambda self, base=None: True)
    monkeypatch.setenv("PII_GUARD_MODELS_DIR", str(tmp_path))
    seen: list[tuple[str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        image, "_worker", lambda name, env, script, *args: seen.append((name, args))
    )
    image.IMAGE_BASELINES["presidio-image-tuned"]()
    name, args = seen[0]
    assert name == "presidio-image-tuned"
    assert args[:2] == ("--hu-model", str(models.HU_CORE_NEWS_LG.root()))
    assert args[2:] == image.TUNED_ARGS
