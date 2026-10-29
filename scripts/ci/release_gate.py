"""Fail closed unless the tagged commit already passed canonical branch CI.

The release workflow is triggered by a tag, which creates no ci.yml run of its own.
This gate therefore looks for a completed successful ``ci.yml`` *push* run on ``main``
or ``develop`` for the exact peeled tag commit, and proves that run's latest ``ci-ok``
job succeeded. It mirrors the Actions-API provenance checks in ``hosted_deploy.py``
rather than trusting a bare (forgeable) check name.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Any

WORKFLOW = ".github/workflows/ci.yml"
BRANCHES = {"main", "develop"}
HEXA40 = re.compile(r"[a-f0-9]{40}")
REPOSITORY_SHAPE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class Refused(RuntimeError):
    """A bounded policy failure; messages contain no upstream response values."""


def select_gate_run(runs: list[dict[str, Any]], sha: str, repository: str) -> dict[str, Any] | None:
    """The newest canonical branch CI run for ``sha``, or None."""
    candidates = []
    for run in runs:
        repo = run.get("repository") if isinstance(run.get("repository"), dict) else {}
        if (
            run.get("path") == WORKFLOW
            and run.get("event") == "push"
            and run.get("head_branch") in BRANCHES
            and run.get("head_sha") == sha
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
            and repo.get("full_name") == repository
        ):
            candidates.append(run)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda run: (
            run.get("run_attempt") or 0,
            run.get("updated_at") or "",
            run.get("id") or 0,
        ),
    )


def latest_ci_ok_succeeded(jobs: list[dict[str, Any]]) -> bool:
    gates = [job for job in jobs if job.get("name") == "ci-ok"]
    if not gates:
        return False
    latest = max(
        gates,
        key=lambda job: (
            job.get("run_attempt") or 0,
            job.get("started_at") or "",
            job.get("id") or 0,
        ),
    )
    return latest.get("status") == "completed" and latest.get("conclusion") == "success"


def command(*args: str) -> str:
    try:
        result = subprocess.run(args, capture_output=True, check=True, timeout=120, text=True)  # noqa: S603
        return result.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        # CLI stderr can contain upstream URLs/configuration; never relay it.
        raise Refused("required GitHub or Git operation failed") from None


def api(path: str) -> dict[str, Any]:
    try:
        data = json.loads(command("gh", "api", path))
    except (ValueError, TypeError):
        raise Refused("GitHub returned invalid metadata") from None
    if not isinstance(data, dict):
        raise Refused("GitHub returned invalid metadata")
    return data


def peeled_head_sha() -> str:
    sha = command("git", "rev-parse", "HEAD^{commit}")
    if not HEXA40.fullmatch(sha):
        raise Refused("checked-out tag does not peel to a commit")
    return sha


def gate(repository: str, sha: str) -> int:
    runs = api(f"repos/{repository}/actions/workflows/ci.yml/runs?head_sha={sha}&per_page=100").get(
        "workflow_runs", []
    )
    run = select_gate_run(runs, sha, repository) if isinstance(runs, list) else None
    if run is None:
        raise Refused("no successful ci.yml push run on main/develop for the tagged commit")
    jobs: list[dict[str, Any]] = []
    for page in range(1, 11):
        batch = api(
            f"repos/{repository}/actions/runs/{run['id']}/jobs?filter=all&per_page=100&page={page}"
        ).get("jobs", [])
        if not isinstance(batch, list):
            raise Refused("GitHub returned invalid job metadata")
        jobs.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise Refused("too many job attempts to prove the CI gate")
    if not latest_ci_ok_succeeded(jobs):
        raise Refused("latest ci-ok job for the tagged commit did not succeed")
    print(f"release gate: ci-ok succeeded for {sha} in run {run['id']}")
    return 0


def main() -> int:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    try:
        if not REPOSITORY_SHAPE.fullmatch(repository):
            raise Refused("GITHUB_REPOSITORY is missing or malformed")
        return gate(repository, peeled_head_sha())
    except Refused as exc:
        print(f"::error title=release gate::{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
