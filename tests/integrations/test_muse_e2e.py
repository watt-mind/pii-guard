"""A real, pinned Muse Code works on the fictional mini-repo through the gateway's Responses
API front end (scripted upstream).

Muse Code comes from its official installer (into a throwaway ``HOME``; ~400 MB): set
``PII_GUARD_MUSE_HOME`` to reuse an install across runs. Skipped when the installer can't be
fetched (offline). An installer that serves another version than the pinned one **fails** the
tests with what to do (re-check the protocol and bump ``MUSE_VERSION_CHECKED``), unless
``PII_GUARD_MUSE_VERSION`` names the version to run. The live variant against the Meta Model
API is ``python -m pii_guard.integrations.e2e --client muse-code --upstream ...``
(docs/integrations/muse-code.md).
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest

from pii_guard.integrations import e2e
from pii_guard.integrations.e2e import (
    MUSE_VERSION,
    MuseVersionError,
    install_muse,
    load_gold,
    run_muse,
)

needs_bash = pytest.mark.skipif(
    shutil.which("bash") is None or platform.system() not in ("Darwin", "Linux"),
    reason="Muse Code installs on macOS and Linux with bash",
)
VERSION = os.environ.get("PII_GUARD_MUSE_VERSION") or MUSE_VERSION


@pytest.fixture(scope="module")
def muse_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    home = os.environ.get("PII_GUARD_MUSE_HOME")
    path = Path(home) if home else tmp_path_factory.mktemp("muse-home")
    try:
        return install_muse(path, VERSION)
    except MuseVersionError as exc:
        pytest.fail(str(exc), pytrace=False)
    except (subprocess.SubprocessError, OSError, httpx.HTTPError, RuntimeError) as exc:
        pytest.skip(f"could not install Muse Code {VERSION} ({type(exc).__name__}: {exc})")


@needs_bash
def test_muse_code_through_gateway_masks_upstream_and_restores_files(muse_bin: Path) -> None:
    result = run_muse(muse_bin=muse_bin, timeout=300, version=VERSION)
    assert result.client_exit == 0, result.client_output
    # Main turns (read, read, read, write, answer) plus Muse's reminder observers.
    assert result.requests >= 5
    assert result.refused == 0, result.gateway_statuses  # the allow-list covers Muse's fields
    assert result.gold_upstream == []
    assert result.placeholders_upstream > 0
    assert result.files_written == ["reply.md"]
    # write_file arguments came back restored: the file holds the real (fictional) values.
    assert sorted(result.restored_in_files) == sorted(result.gold_checked)
    assert result.placeholders_in_files == 0
    assert set(load_gold()["rules"]) <= set(result.gold_checked)
    assert {"function_call", "function_call_output", "reasoning"} <= set(
        result.request_keys["input_items"]
    )
    # The connect path URL: one vault session, each value one placeholder (LAB-1286).
    assert result.session_sources == {"path": result.requests}
    assert result.sessions == 1
    assert result.gold_unstable == 0
    assert result.ok


@needs_bash
def test_muse_code_without_the_session_path_uses_prompt_cache_key(muse_bin: Path) -> None:
    """The plain base URL: the session comes from prompt_cache_key. Muse sends one key for the
    main conversation and one per reminder observer; the observers' keys follow the main
    conversation's session (LAB-1300), so the task stays in one session, as with the path."""
    result = run_muse(muse_bin=muse_bin, timeout=300, session="auto", version=VERSION)
    assert result.client_exit == 0, result.client_output
    assert result.gold_upstream == []
    assert result.session_sources == {"prompt_cache_key": result.requests}
    assert result.sessions == 1
    assert result.gold_unstable == 0
    assert result.gold_max_placeholders == 1
    assert result.placeholders_in_files == 0
    assert result.ok


# --- the version pin, offline (no installer download) ------------------------------------


class _Installer:
    """Stands in for the official installer: writes ``muse-bin-<served>`` and the launcher's
    ``.muse-version``, the way ``install.sh`` does, into the throwaway HOME."""

    def __init__(self, served: str, state: bool = True) -> None:
        self.served = served
        self.state = state
        self.calls = 0

    def get(self, url: str, **_: Any) -> httpx.Response:
        assert url == e2e.MUSE_INSTALLER
        return httpx.Response(
            200, content=b"#!/usr/bin/env bash\n", request=httpx.Request("GET", url)
        )

    def run(
        self, cmd: list[str], env: dict[str, str], **_: Any
    ) -> subprocess.CompletedProcess[str]:
        self.calls += 1
        bin_dir = Path(env["HOME"]) / ".local" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / f"muse-bin-{self.served}").write_text("binary")
        if self.state:
            (bin_dir / ".muse-version").write_text(self.served + "\n")
        return subprocess.CompletedProcess(cmd, 0, "", "")


@pytest.fixture
def installer(monkeypatch: pytest.MonkeyPatch) -> Any:
    def make(served: str, state: bool = True) -> _Installer:
        fake = _Installer(served, state)
        monkeypatch.setattr(e2e.httpx, "get", fake.get)
        monkeypatch.setattr(e2e.subprocess, "run", fake.run)
        monkeypatch.setattr(e2e.shutil, "which", lambda name: "/bin/" + name)
        return fake

    return make


def test_the_pin_is_installed_and_reused(installer: Any, tmp_path: Path) -> None:
    fake = installer(MUSE_VERSION)
    binary = install_muse(tmp_path)
    assert binary.name == f"muse-bin-{MUSE_VERSION}"
    assert install_muse(tmp_path) == binary
    assert fake.calls == 1  # the second call reuses the install


@pytest.mark.parametrize("state", [True, False])
def test_another_served_version_fails_with_what_to_do(
    installer: Any, tmp_path: Path, state: bool
) -> None:
    installer("9.9.9-R1.1", state)
    with pytest.raises(MuseVersionError) as caught:
        install_muse(tmp_path)
    assert (caught.value.served, caught.value.pinned) == ("9.9.9-R1.1", MUSE_VERSION)
    message = str(caught.value)
    assert "MUSE_VERSION_CHECKED" in message
    assert "--muse-version 9.9.9-R1.1" in message
    assert "PII_GUARD_MUSE_VERSION=9.9.9-R1.1" in message


def test_the_served_version_runs_when_asked_for(installer: Any, tmp_path: Path) -> None:
    installer("9.9.9-R1.1")
    assert install_muse(tmp_path, "9.9.9-R1.1").name == "muse-bin-9.9.9-R1.1"


def test_an_installer_that_installs_nothing_is_not_a_version_error(
    monkeypatch: pytest.MonkeyPatch, installer: Any, tmp_path: Path
) -> None:
    fake = installer(MUSE_VERSION)
    monkeypatch.setattr(
        e2e.subprocess, "run", lambda cmd, **_: subprocess.CompletedProcess(cmd, 0, "", "")
    )
    with pytest.raises(RuntimeError, match="no muse-bin") as caught:
        install_muse(tmp_path)
    assert not isinstance(caught.value, MuseVersionError)
    assert fake.calls == 0


def test_the_cli_stops_on_a_version_mismatch(
    installer: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    installer("9.9.9-R1.1")
    with pytest.raises(SystemExit) as caught:
        e2e.main(["--client", "muse-code", "--muse-home", str(tmp_path)])
    assert caught.value.code == 2
    assert "serves 9.9.9-R1.1, but this harness is pinned to" in capsys.readouterr().err
