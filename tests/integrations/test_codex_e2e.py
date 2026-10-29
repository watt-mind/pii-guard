"""A real, pinned Codex works on the fictional mini-repo through the gateway's Responses API,
started with the Connect page's paste-and-run block (scripted upstream).

Needs node + npm (skipped otherwise) and network for the first ``npm install``; set
``PII_GUARD_CODEX_PREFIX`` to reuse an install across runs. With ``META_API_KEY`` in the
environment the live variant runs too, against the Meta Model API (docs/integrations/codex.md).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from _harness import LIVE_KEY, LIVE_MODEL, LIVE_UPSTREAM, assert_live, assert_scripted

from pii_guard.integrations.e2e import CODEX_VERSION, install_codex, run_codex

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or shutil.which("npm") is None or shutil.which("bash") is None,
    reason="node/npm/bash not installed",
)


@pytest.fixture(scope="module")
def codex_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    prefix = os.environ.get("PII_GUARD_CODEX_PREFIX")
    path = Path(prefix) if prefix else tmp_path_factory.mktemp("codex-prefix")
    try:
        return install_codex(path)
    except (subprocess.SubprocessError, OSError, RuntimeError) as exc:  # offline runner
        pytest.skip(f"could not install Codex {CODEX_VERSION} ({type(exc).__name__})")


def test_codex_through_gateway_masks_upstream_and_restores_files(codex_bin: Path) -> None:
    result = run_codex(codex_bin=codex_bin, timeout=300)
    assert_scripted(result)
    # Codex's own fields reach the gateway's allow-list, and are covered.
    assert "client_metadata" in result.request_keys["top_level"]
    assert {"function_call", "function_call_output"} <= set(result.request_keys["input_items"])


@pytest.mark.skipif(LIVE_KEY is None, reason="META_API_KEY not set: live variant skipped")
def test_codex_live_against_the_meta_model_api(codex_bin: Path) -> None:
    result = run_codex(
        codex_bin=codex_bin, upstream=LIVE_UPSTREAM, key=LIVE_KEY, model=LIVE_MODEL, timeout=600
    )
    assert_live(result)
