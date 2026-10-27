"""A real, pinned Muse Code works on the fictional mini-repo through the gateway's Responses
API front end (scripted upstream).

Muse Code comes from its official installer (into a throwaway ``HOME``; ~400 MB): set
``PII_GUARD_MUSE_HOME`` to reuse an install across runs. Skipped when the installer can't be
fetched or gives another version than the pinned one. The live variant against the Meta Model
API is ``python -m pii_guard.integrations.e2e --client muse-code --upstream ...``
(docs/integrations/muse-code.md).
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from pii_guard.integrations.e2e import install_muse, load_gold, run_muse

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or platform.system() not in ("Darwin", "Linux"),
    reason="Muse Code installs on macOS and Linux with bash",
)


@pytest.fixture(scope="module")
def muse_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    home = os.environ.get("PII_GUARD_MUSE_HOME")
    path = Path(home) if home else tmp_path_factory.mktemp("muse-home")
    try:
        return install_muse(path)
    except (subprocess.SubprocessError, OSError, httpx.HTTPError, RuntimeError) as exc:
        pytest.skip(f"could not install the pinned Muse Code ({type(exc).__name__}: {exc})")


def test_muse_code_through_gateway_masks_upstream_and_restores_files(muse_bin: Path) -> None:
    result = run_muse(muse_bin=muse_bin, timeout=300)
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


def test_muse_code_without_the_session_path_uses_prompt_cache_key(muse_bin: Path) -> None:
    """The plain base URL: one session per prompt_cache_key. Muse sends one key for the main
    conversation and one per reminder observer, so a task spans a few sessions (a value can
    get one placeholder in each); the files are still restored."""
    result = run_muse(muse_bin=muse_bin, timeout=300, session="auto")
    assert result.client_exit == 0, result.client_output
    assert result.gold_upstream == []
    assert set(result.session_sources) == {"prompt_cache_key"}
    assert 1 <= result.sessions < result.requests
    assert result.placeholders_in_files == 0
    assert result.ok
