"""A real, pinned OpenCode works on the fictional mini-repo through the gateway (Chat Completions),
started with the Connect page's paste-and-run block (scripted upstream).

Needs node + npm (skipped otherwise) and network for the first ``npm install``; set
``PII_GUARD_OPENCODE_PREFIX`` to reuse an install across runs. With ``META_API_KEY`` in the
environment the live variant runs too, against the Meta Model API (docs/integrations/opencode.md).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from _harness import LIVE_KEY, LIVE_MODEL, LIVE_UPSTREAM, assert_live, assert_scripted

from pii_guard.integrations.e2e import OPENCODE_VERSION, install_opencode, run_opencode

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or shutil.which("npm") is None or shutil.which("bash") is None,
    reason="node/npm/bash not installed",
)


@pytest.fixture(scope="module")
def opencode_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    prefix = os.environ.get("PII_GUARD_OPENCODE_PREFIX")
    path = Path(prefix) if prefix else tmp_path_factory.mktemp("opencode-prefix")
    try:
        return install_opencode(path)
    except (subprocess.SubprocessError, OSError, RuntimeError) as exc:  # offline runner
        pytest.skip(f"could not install OpenCode {OPENCODE_VERSION} ({type(exc).__name__})")


def test_opencode_through_gateway_masks_upstream_and_restores_files(opencode_bin: Path) -> None:
    result = run_opencode(opencode_bin=opencode_bin, timeout=300)
    if result.requests == 0 and result.client_exit != 0:
        # OpenCode fetches its provider package (@ai-sdk/openai-compatible) on first use.
        pytest.skip(f"OpenCode sent no request (offline?): {result.client_output[-300:]}")
    assert_scripted(result)
    assert "tool" in result.request_keys["roles"]  # tool results went through masked


@pytest.mark.skipif(LIVE_KEY is None, reason="META_API_KEY not set: live variant skipped")
def test_opencode_live_against_the_meta_model_api(opencode_bin: Path) -> None:
    result = run_opencode(
        opencode_bin=opencode_bin,
        upstream=LIVE_UPSTREAM,
        key=LIVE_KEY,
        model=LIVE_MODEL,
        timeout=600,
    )
    assert_live(result)
