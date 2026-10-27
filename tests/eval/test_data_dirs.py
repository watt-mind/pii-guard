"""PII_GUARD_SPECIMENS_DIR / PII_GUARD_VISUAL_CACHE: visual eval data outside the checkout."""

from __future__ import annotations

from pathlib import Path

import pytest

from pii_guard.eval import visual, visual_fetch
from pii_guard.eval.data_dirs import specimens_dir, visual_cache_dir
from pii_guard.visual import segment_eval


def test_defaults_are_in_the_checkout() -> None:
    assert specimens_dir() == Path("data/specimens")
    assert visual_cache_dir() == Path("data/visual-cache")
    assert segment_eval.set_paths("specimens")[2] == Path("data/specimens")


def test_settings_move_the_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PII_GUARD_SPECIMENS_DIR", str(tmp_path / "specimens"))
    monkeypatch.setenv("PII_GUARD_VISUAL_CACHE", "~/pii-guard-cache")
    assert specimens_dir() == tmp_path / "specimens"
    assert visual_cache_dir() == Path("~/pii-guard-cache").expanduser()
    assert segment_eval.set_paths("specimens")[2] == tmp_path / "specimens"
    assert segment_eval.set_paths("fictional")[2] == Path("eval/fixtures/visual/images")
    args = segment_eval.build_parser().parse_args(["--candidate", "local", "--set", "fictional"])
    assert args.cache == Path("~/pii-guard-cache").expanduser()
    eval_args = visual.build_parser().parse_args([])
    assert (eval_args.specimens, eval_args.cache) == (tmp_path / "specimens", args.cache)
    assert visual_fetch.build_parser().parse_args([]).out == tmp_path / "specimens"


def test_blank_setting_is_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_SPECIMENS_DIR", "  ")
    assert specimens_dir() == Path("data/specimens")


def test_an_outside_directory_is_not_written_into_the_manifest(tmp_path: Path) -> None:
    class Nothing:
        user_agent = "test"
        requests = 0

    manifest = visual_fetch.fetch_catalog({"sources": []}, tmp_path, Nothing())  # type: ignore[arg-type]
    assert manifest["out_dir"] == "$PII_GUARD_SPECIMENS_DIR"
