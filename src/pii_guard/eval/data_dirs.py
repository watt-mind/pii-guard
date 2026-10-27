"""Where the locally fetched visual eval data lives (never committed, ADR 0005).

- ``PII_GUARD_SPECIMENS_DIR``: the official specimen images
  (``eval/visual/fetch_specimens.py``), default ``data/specimens`` in the checkout;
- ``PII_GUARD_VISUAL_CACHE``: the SAM 3.1 response cache of the visual evals, default
  ``data/visual-cache``.

Point both outside any git worktree (for example ``~/.pii-guard-data/specimens`` and
``~/.pii-guard-data/visual-cache``) so that removing a worktree does not delete them;
see ``docs/evaluation.md``. Unset or empty: the defaults, relative to the working directory.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "DEFAULT_SPECIMENS_DIR",
    "DEFAULT_VISUAL_CACHE",
    "SPECIMENS_DIR_ENV_VAR",
    "VISUAL_CACHE_ENV_VAR",
    "specimens_dir",
    "visual_cache_dir",
]

SPECIMENS_DIR_ENV_VAR = "PII_GUARD_SPECIMENS_DIR"
VISUAL_CACHE_ENV_VAR = "PII_GUARD_VISUAL_CACHE"
DEFAULT_SPECIMENS_DIR = Path("data/specimens")
DEFAULT_VISUAL_CACHE = Path("data/visual-cache")


def specimens_dir() -> Path:
    """``PII_GUARD_SPECIMENS_DIR`` (``~`` expanded), default ``data/specimens``."""
    raw = os.environ.get(SPECIMENS_DIR_ENV_VAR, "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_SPECIMENS_DIR


def visual_cache_dir() -> Path:
    """``PII_GUARD_VISUAL_CACHE`` (``~`` expanded), default ``data/visual-cache``."""
    raw = os.environ.get(VISUAL_CACHE_ENV_VAR, "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_VISUAL_CACHE
