"""``pii-guard eval``: run the evaluation set and print the scorecard.

Stub. The evaluation harness replaces this module's body; the signature
``main(argv: Sequence[str] | None) -> int`` is the contract the top-level CLI relies on.
``argv`` is everything after ``pii-guard eval``.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    print("pii-guard eval: not implemented yet", file=sys.stderr)
    return 1
