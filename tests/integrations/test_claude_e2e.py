"""A real, pinned Claude Code works on the fictional mini-repo through the gateway's Anthropic
Messages API, started with the Connect page's paste-and-run block (scripted upstream).

Needs node + npm (skipped otherwise) and network for the first ``npm install``; set
``PII_GUARD_CLAUDE_PREFIX`` to reuse an install across runs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from _harness import assert_scripted

from pii_guard.integrations.e2e import CLAUDE_CODE_VERSION, install_claude_code, run_claude_code

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or shutil.which("npm") is None or shutil.which("bash") is None,
    reason="node/npm/bash not installed",
)


@pytest.fixture(scope="module")
def claude_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    prefix = os.environ.get("PII_GUARD_CLAUDE_PREFIX")
    path = Path(prefix) if prefix else tmp_path_factory.mktemp("claude-prefix")
    try:
        return install_claude_code(path)
    except (subprocess.SubprocessError, OSError, RuntimeError) as exc:  # offline runner
        pytest.skip(f"could not install Claude Code {CLAUDE_CODE_VERSION} ({type(exc).__name__})")


def test_claude_code_through_gateway_masks_upstream_and_restores_files(claude_bin: Path) -> None:
    result = run_claude_code(claude_bin=claude_bin, timeout=300)
    assert_scripted(result)
    assert "system" in result.request_keys["top_level"]
    assert "tools" in result.request_keys["top_level"]
    assert {"assistant", "user"} <= set(result.request_keys["roles"])
