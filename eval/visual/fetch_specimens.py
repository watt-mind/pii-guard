"""Download the specimen ID documents listed in ``catalog.json`` into ``data/specimens/``.

Images are never committed (ADR 0005); only ``manifest.json`` (URLs + SHA-256) is. See
:mod:`pii_guard.eval.visual_fetch` for the politeness rules.

    uv run python eval/visual/fetch_specimens.py
"""

import sys

from pii_guard.eval.visual_fetch import main

if __name__ == "__main__":
    sys.exit(main())
