"""Report when Muse Code's official channel serves another version than the pinned one.

The e2e installs the pinned ``MUSE_VERSION_CHECKED`` from its release manifest, so a new
upstream release no longer breaks the required ``test`` job (LAB-2433). This check is how a
new release still gets noticed: it reads the channel manifest the official launcher reads
(``muse-stable``, a few hundred bytes, no download) and compares its version with the pin.

Never fails the job: drift and an unreachable channel are reported as a ``::warning::``
annotation and in the job summary, and ``drift=true`` / ``served`` / ``pinned`` go to
``$GITHUB_OUTPUT`` so the workflow can file an issue. Standard library only, so the job needs
no ``uv sync``.

    python3 scripts/ci/muse_drift.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

CHANNEL_URL = "https://api.meta.ai/muse-code/channels/muse-stable"
PIN_FILE = Path(__file__).resolve().parents[2] / "src/pii_guard/integrations/muse_code.py"
PIN = re.compile(r'^MUSE_VERSION_CHECKED = "([^"]+)"$', re.MULTILINE)
VERSION = re.compile(r"[0-9]+(\.[0-9]+)*(-R[0-9]+(\.[0-9]+)*)?")


def pinned_version(source: str) -> str:
    """``MUSE_VERSION_CHECKED`` from the text of ``muse_code.py``."""
    match = PIN.search(source)
    if match is None:
        raise ValueError("MUSE_VERSION_CHECKED not found")
    return match.group(1)


def served_version(channel: Any) -> str:
    """The version a ``muse-stable`` channel manifest points the launcher at."""
    if not isinstance(channel, dict) or channel.get("channel") != "muse-stable":
        raise ValueError("not a muse-stable channel manifest")
    version = channel.get("version")
    if not isinstance(version, str) or VERSION.fullmatch(version) is None:
        raise ValueError("the channel manifest has no valid version")
    return version


def fetch_channel(url: str = CHANNEL_URL) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed https URL
        return json.load(response)


def report(pinned: str, served: str) -> tuple[bool, str]:
    """``(drift, message)`` for the pin and the served version."""
    if served == pinned:
        return False, f"Muse Code: the official installer serves the pinned {pinned}."
    return True, (
        f"Muse Code {served} is out; the e2e harness is pinned to {pinned}. Re-run the protocol "
        "capture in docs/integrations/muse-code.md and bump MUSE_VERSION_CHECKED "
        "(src/pii_guard/integrations/muse_code.py); the required tests keep running "
        f"{pinned} until then."
    )


def _append(env: str, text: str) -> None:
    path = os.environ.get(env)
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text)


def main() -> int:
    pinned = pinned_version(PIN_FILE.read_text(encoding="utf-8"))
    try:
        served = served_version(fetch_channel())
    except (OSError, ValueError) as exc:
        # Unreachable or malformed: say so, but a flaky endpoint must not turn CI red.
        print(f"::warning title=muse-drift::could not read the Muse Code channel ({exc})")
        return 0
    drift, message = report(pinned, served)
    print(f"::warning title=muse-drift::{message}" if drift else message)
    _append("GITHUB_STEP_SUMMARY", f"### Muse Code version\n\n{message}\n")
    _append("GITHUB_OUTPUT", f"drift={'true' if drift else 'false'}\npinned={pinned}\n")
    _append("GITHUB_OUTPUT", f"served={served}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
