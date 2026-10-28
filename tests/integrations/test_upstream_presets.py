"""``pii-guard up --upstream <preset>`` (LAB-1331): base URL and key variable by name."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pii_guard import cli
from pii_guard.upstreams import PRESETS, by_url, get

FAKE_KEY = "fictional-meta-key-0000"  # never a real key (ADR 0005)


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []

    def fake_run_up(opts: Any) -> int:
        calls.append(opts)
        return 0

    monkeypatch.setattr("pii_guard.app_bundle.run_up", fake_run_up)
    return calls


def test_presets_are_openai_compatible_https_urls_with_a_key_variable() -> None:
    assert set(PRESETS) == {"meta", "openai", "fireworks", "openrouter"}
    for preset in PRESETS.values():
        assert preset.base_url.startswith("https://") and preset.base_url.endswith("/v1")
        assert preset.key_env.endswith("_API_KEY")
        assert preset.command() == (
            f"export {preset.key_env}=<your-key>\npii-guard up --upstream {preset.id}"
        )
    meta = get("meta")
    assert (meta.base_url, meta.key_env, meta.default_model) == (
        "https://api.meta.ai/v1",
        "META_API_KEY",
        "muse-spark-1.3",
    )
    with pytest.raises(KeyError, match="known: meta"):
        get("nope")


def test_by_url_matches_on_the_origin() -> None:
    assert by_url("https://api.meta.ai/v1/") is PRESETS["meta"]
    assert by_url("https://api.meta.ai/v1/chat/completions") is PRESETS["meta"]
    assert by_url("https://openrouter.ai/api/v1") is PRESETS["openrouter"]
    assert by_url("http://api.meta.ai/v1") is None  # another scheme
    assert by_url("http://127.0.0.1:9999/v1") is None
    assert by_url(None) is None


def test_up_upstream_meta_sets_url_and_key_variable(
    monkeypatch: pytest.MonkeyPatch, captured: list[Any]
) -> None:
    monkeypatch.setenv("META_API_KEY", FAKE_KEY)
    assert cli.main(["up", "--upstream", "meta", "--no-browser"]) == 0
    (opts,) = captured
    assert (opts.upstream_url, opts.api_key_env) == ("https://api.meta.ai/v1", "META_API_KEY")


def test_up_upstream_reads_the_key_from_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, captured: list[Any]
) -> None:
    monkeypatch.delenv("FIREWORKS_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(f"FIREWORKS_API_KEY={FAKE_KEY}\n")
    assert cli.main(["up", "--upstream", "fireworks", "--no-browser"]) == 0
    assert captured[0].api_key_env == "FIREWORKS_API_KEY"
    import os

    assert os.environ["FIREWORKS_API_KEY"] == FAKE_KEY
    monkeypatch.delenv("FIREWORKS_API_KEY")


def test_up_upstream_without_its_key_says_which_variable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    captured: list[Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["up", "--upstream", "openai", "--no-browser"]) == 2
    assert captured == []
    err = capsys.readouterr().err
    assert "export OPENAI_API_KEY=<your-key>" in err


def test_up_upstream_and_upstream_url_conflict(
    captured: list[Any], capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["up", "--upstream", "meta", "--upstream-url", "http://x.test/v1", "--no-browser"]
    assert cli.main(args) == 2
    assert "not both" in capsys.readouterr().err


def test_up_upstream_url_still_works(captured: list[Any]) -> None:
    args = ["up", "--upstream-url", "http://models.test/v1", "--api-key-env", "K", "--no-browser"]
    assert cli.main(args) == 0
    assert (captured[0].upstream_url, captured[0].api_key_env) == ("http://models.test/v1", "K")


def test_up_upstream_rejects_an_unknown_preset(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["up", "--upstream", "nope"])
    assert "invalid choice" in capsys.readouterr().err
