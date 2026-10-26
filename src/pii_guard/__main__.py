"""``python -m pii_guard`` is the same as the ``pii-guard`` command."""

import sys

from pii_guard.cli import main

sys.exit(main())
