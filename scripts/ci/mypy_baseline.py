"""Run mypy on src/ and fail only on errors that are not in the committed baseline.

```
uv run python scripts/ci/mypy_baseline.py           # CI and make types
uv run python scripts/ci/mypy_baseline.py --update  # after fixing errors: shrink the baseline
```

The baseline (scripts/ci/mypy-baseline.txt) lists the errors that existed when type checking
was introduced, one per line as ``path: message [code]`` without line numbers, so unrelated
edits that move code don't break the check. A new error fails; a fixed one is reported so the
baseline can be shrunk with ``--update``. Never add to the baseline to make a PR pass.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "scripts" / "ci" / "mypy-baseline.txt"
_ERROR = re.compile(r"^(?P<path>[^:]+):\d+(?::\d+)?: error: (?P<msg>.*)$")


def current_errors() -> tuple[Counter[str], str]:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--no-error-summary",
            "--show-error-codes",
            "--no-pretty",
            "--no-color-output",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):  # 2 = mypy itself failed (bad config, crash)
        sys.stderr.write(proc.stdout + proc.stderr)
        raise SystemExit(2)
    errors: Counter[str] = Counter()
    for line in proc.stdout.splitlines():
        m = _ERROR.match(line)
        if m:
            errors[f"{m['path']}: {m['msg']}"] += 1
    return errors, proc.stdout


def load_baseline() -> Counter[str]:
    if not BASELINE.exists():
        return Counter()
    lines = BASELINE.read_text(encoding="utf-8").splitlines()
    return Counter(line for line in lines if line and not line.startswith("#"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--update", action="store_true", help="rewrite the baseline")
    args = parser.parse_args(argv)
    errors, raw = current_errors()
    if args.update:
        header = (
            "# mypy errors accepted when type checking was introduced (LAB-1232). Shrink only.\n"
        )
        BASELINE.write_text(header + "".join(f"{e}\n" for e in sorted(errors.elements())))
        print(f"mypy baseline: wrote {sum(errors.values())} errors to {BASELINE.relative_to(ROOT)}")
        return 0
    baseline = load_baseline()
    new = errors - baseline
    fixed = baseline - errors
    if fixed:
        print(f"mypy baseline: {sum(fixed.values())} baselined error(s) fixed; run with --update:")
        for e in sorted(fixed.elements()):
            print(f"  fixed: {e}")
    if new:
        print(f"mypy: {sum(new.values())} new error(s) not in the baseline:", file=sys.stderr)
        keys = set(new)
        for line in raw.splitlines():
            m = _ERROR.match(line)
            if m and f"{m['path']}: {m['msg']}" in keys:
                print(f"  {line}", file=sys.stderr)
        return 1
    print(f"mypy: OK ({sum(errors.values())} baselined errors, no new ones)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
