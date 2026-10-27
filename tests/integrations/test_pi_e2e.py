"""A real, pinned pi works on the fictional mini-repo through the gateway (scripted upstream).

Needs node + npm (skipped otherwise) and network for the first ``npm install``; set
``PII_GUARD_PI_PREFIX`` to reuse an install across runs. The live variant against the Meta
Model API is ``python -m pii_guard.integrations.e2e --upstream ...`` (docs/integrations/pi.md).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from pii_guard.integrations.e2e import install_pi, load_gold, run

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or shutil.which("npm") is None, reason="node/npm not installed"
)


@pytest.fixture(scope="module")
def pi_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    prefix = os.environ.get("PII_GUARD_PI_PREFIX")
    path = Path(prefix) if prefix else tmp_path_factory.mktemp("pi-prefix")
    try:
        return install_pi(path)
    except (subprocess.SubprocessError, OSError) as exc:  # offline CI runner
        pytest.skip(f"could not install pi ({type(exc).__name__})")


def test_pi_through_gateway_masks_upstream_and_restores_files(pi_bin: Path) -> None:
    result = run(pi_bin=pi_bin, timeout=300)
    assert result.pi_exit == 0, result.pi_output
    assert result.requests >= 5  # read, read, read, write, final answer
    assert result.refused == 0, result.gateway_statuses  # nothing hit the fail-closed allow-list
    assert result.gold_upstream == []
    assert result.placeholders_upstream > 0
    assert result.files_written == ["reply.md"]
    # Tool-call arguments came back restored: the file holds the real (fictional) values.
    assert sorted(result.restored_in_files) == sorted(result.gold_checked)
    assert result.placeholders_in_files == 0
    assert set(load_gold()["rules"]) <= set(result.gold_checked)
    assert result.ok
