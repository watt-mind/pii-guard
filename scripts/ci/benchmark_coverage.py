"""Compare full-suite coverage overhead without changing any CI coverage gate.

Run after ``uv sync --locked``. Each mode uses the same worker count and full
Hypothesis profile. Logs and coverage data go to a fresh directory outside the
checkout by default. Run on an otherwise idle machine for comparable timings.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import tempfile
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--modes", nargs="+", choices=("branch", "line", "none"), default=["branch", "line", "none"]
    )
    args = parser.parse_args()
    if args.workers < 1 or args.repeats < 1:
        parser.error("workers and repeats must be positive")
    root = args.repo.resolve()
    output = Path(tempfile.mkdtemp(prefix="pii-guard-coverage-"))
    print(f"Results: {output}", flush=True)
    report: dict = {
        "platform": platform.platform(),
        "workers": args.workers,
        "profile": "ci-full",
        "repo": str(root),
        "runs": [],
    }
    for repeat in range(args.repeats):
        for mode in args.modes:
            label = f"{repeat + 1}-{mode}"
            env = os.environ.copy()
            env.update(
                HYPOTHESIS_PROFILE="ci-full",
                COVERAGE_BRANCH=str(mode == "branch").lower(),
                COVERAGE_CORE="sysmon" if mode == "line" else "ctrace",
                COVERAGE_FILE=str(output / f".coverage-{label}"),
                PYTEST_ADDOPTS="",
            )
            command = [
                "uv",
                "run",
                "--no-sync",
                "pytest",
                "-n",
                str(args.workers),
                "--dist",
                "worksteal",
                "--durations=15",
            ]
            command += (
                ["--no-cov"]
                if mode == "none"
                else [f"--cov-report=json:{output / f'{label}-coverage.json'}"]
            )
            started = time.perf_counter()
            with (output / f"{label}.log").open("w") as log:
                result = subprocess.run(  # noqa: S603 - fixed command and validated CLI options
                    command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, check=False
                )
            row = {
                "mode": mode,
                "repeat": repeat + 1,
                "seconds": round(time.perf_counter() - started, 2),
                "exit_code": result.returncode,
            }
            report["runs"].append(row)
            (output / "timings.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(row), flush=True)
            if result.returncode:
                print(
                    f"Failed; inspect {output / f'{label}.log'}. "
                    "Timings are not a passing baseline."
                )
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
