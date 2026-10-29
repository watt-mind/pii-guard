"""Validate the repo's conventional commit-subject format for the commit-msg hook.

Accepted: ``feat(detect): add IBAN checksum rule (LAB-123)``, an optional squash suffix
``(#123)``, breaking ``!``, and git's own ``Merge``/``Revert``/``fixup!``/``squash!``
subjects. Usage: ``python3 scripts/ci/check_commit_msg.py <message-file>``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_TYPES = "feat|fix|docs|chore|refactor|test|perf|build|ci|style|revert"
_SUBJECT = re.compile(rf"^({_TYPES})(\([a-z0-9][a-z0-9._/-]*\))?!?: \S.*$")
_GIT_GENERATED = ("Merge ", 'Revert "', "fixup! ", "squash! ")


def valid_subject(subject: str) -> bool:
    return subject.startswith(_GIT_GENERATED) or bool(_SUBJECT.match(subject))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    lines = Path(argv[1]).read_text(encoding="utf-8").splitlines()
    subject = next(
        (line.strip() for line in lines if line.strip() and not line.startswith("#")), ""
    )
    if valid_subject(subject):
        return 0
    print(
        "commit subject must be 'type(scope): summary (LAB-XX)' "
        f"(types: {_TYPES.replace('|', ', ')}); got: {subject!r}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
