from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from release_gate import latest_ci_ok_succeeded, select_gate_run

SHA = "a" * 40
REPO = "watt-mind/pii-guard"


def run(**overrides: object) -> dict:
    base = {
        "id": 1,
        "path": ".github/workflows/ci.yml",
        "event": "push",
        "head_branch": "main",
        "head_sha": SHA,
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
        "updated_at": "2026-10-29T00:00:00Z",
        "repository": {"full_name": REPO},
    }
    return {**base, **overrides}


class SelectGateRunTests(unittest.TestCase):
    def test_accepts_canonical_branch_push(self) -> None:
        self.assertEqual(select_gate_run([run()], SHA, REPO)["id"], 1)
        self.assertEqual(select_gate_run([run(head_branch="develop")], SHA, REPO)["id"], 1)

    def test_rejects_non_canonical_evidence(self) -> None:
        for bad in (
            run(event="pull_request"),
            run(head_branch="feat/x"),
            run(head_sha="b" * 40),
            run(status="in_progress", conclusion=None),
            run(conclusion="failure"),
            run(path=".github/workflows/other.yml"),
            run(repository={"full_name": "evil/pii-guard"}),
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(select_gate_run([bad], SHA, REPO))

    def test_newest_attempt_wins(self) -> None:
        runs = [run(id=1), run(id=2, run_attempt=2), run(id=3, updated_at="2026-10-30T00:00:00Z")]
        self.assertEqual(select_gate_run(runs, SHA, REPO)["id"], 2)


class LatestCiOkTests(unittest.TestCase):
    def job(self, **overrides: object) -> dict:
        base = {
            "id": 1,
            "name": "ci-ok",
            "status": "completed",
            "conclusion": "success",
            "run_attempt": 1,
            "started_at": "2026-10-29T00:00:00Z",
        }
        return {**base, **overrides}

    def test_success_and_missing(self) -> None:
        self.assertTrue(latest_ci_ok_succeeded([self.job(), self.job(name="test")]))
        self.assertFalse(latest_ci_ok_succeeded([]))

    def test_latest_attempt_decides(self) -> None:
        jobs = [self.job(id=1), self.job(id=2, run_attempt=2, conclusion="failure")]
        self.assertFalse(latest_ci_ok_succeeded(jobs))


if __name__ == "__main__":
    unittest.main()
