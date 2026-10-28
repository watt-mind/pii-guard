"""Select packaging checks from PR paths; every other event checks all packages.

Unknown paths deliberately select all checks. Git errors fail the changes job (and ci-ok),
never turn an unreadable diff into an empty change list. Only packaging jobs are filtered:
Python tests, report validation, audits and secret/PII checks still run for documentation PRs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterable

JOBS = ("ui", "docker", "wheel")
# Metadata used by Python installation, Docker COPY, or the wheel's UI build.
SHARED_FILES = {
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    "README.md",
    "LICENSE",
    "NOTICE",
    "Makefile",
    ".github/workflows/ci.yml",
    "scripts/ci/changes.py",
    "tests/ci/test_changes.py",
}
# --print-index currently calls build_outputs: dataset counts and colours are inputs too.
BENCHMARK_PREFIXES = ("eval/results/", "eval/datasets/results/", "docs/benchmarks/")
# These paths are checked elsewhere in CI and are not packaging inputs. Any new top-level
# area or root configuration file falls back to all packaging checks until classified here.
NON_PACKAGING_PREFIXES = ("tests/", "docs/", "eval/", "training/", "examples/", ".github/")
NON_PACKAGING_FILES = {"AGENTS.md", "CLAUDE.md", "GEMINI.md", "CONTRIBUTING.md"}


def classify(paths: Iterable[str]) -> dict[str, bool]:
    selected: set[str] = set()
    for path in paths:
        if path in SHARED_FILES:
            selected.update(JOBS)
        elif path.startswith("src/"):
            # The report imports other package modules; UI validation must see source changes.
            selected.update(JOBS)
        elif path.startswith("ui/") or path.startswith(BENCHMARK_PREFIXES):
            selected.update(("ui", "wheel"))
        elif path in {"Dockerfile", ".dockerignore", "scripts/ci/docker_smoke.sh"}:
            selected.add("docker")
        elif path in {"scripts/ci/wheel_smoke.sh", ".github/workflows/release.yml"}:
            selected.add("wheel")
        elif path == "scripts/ci/licenses.py":
            selected.add("ui")
        elif path.startswith(NON_PACKAGING_PREFIXES) or path in NON_PACKAGING_FILES:
            continue
        else:
            selected.update(JOBS)
    return {job: job in selected for job in JOBS}


def changed_paths(base: str) -> list[str]:
    if not base:
        raise ValueError("pull requests require BASE")
    # NUL-delimited paths also handle whitespace/newlines. Disable rename detection so moving
    # a build input out of its directory selects the job for both the deletion and addition.
    result = subprocess.run(  # noqa: S603 - fixed executable/options, base supplied as a revision
        ["git", "diff", "--name-only", "--no-renames", "-z", f"{base}...HEAD", "--"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    return [os.fsdecode(path) for path in result.stdout.split(b"\0") if path]


def main() -> int:
    if os.environ.get("EVENT") != "pull_request":
        selected = dict.fromkeys(JOBS, True)
    else:
        try:
            selected = classify(changed_paths(os.environ.get("BASE", "")))
        except (OSError, ValueError, subprocess.CalledProcessError):
            print(
                "::error::Cannot determine PR changes; refusing to skip packaging checks",
                file=sys.stderr,
            )
            return 1
    for job, enabled in selected.items():
        print(f"{job}={str(enabled).lower()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
