from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from check_commit_msg import valid_subject

SCRIPT = Path(__file__).with_name("check_commit_msg.py")


class ValidSubjectTests(unittest.TestCase):
    def test_accepts_repo_history_shapes(self) -> None:
        for subject in (
            "feat(detect): add IBAN checksum rule (LAB-123)",
            "fix(ui): console polish follow-ups from #260 review (LAB-1544) (#261)",
            "docs(demo): add repeatable judge walkthrough (#187)",
            "ci: pin uv across workflows (LAB-1559)",
            "feat(api)!: rename the error envelope (LAB-42)",
        ):
            with self.subTest(subject=subject):
                self.assertTrue(valid_subject(subject))

    def test_accepts_git_generated_subjects(self) -> None:
        for subject in ("Merge branch 'develop'", 'Revert "feat(api): x"', "fixup! feat(api): x"):
            with self.subTest(subject=subject):
                self.assertTrue(valid_subject(subject))

    def test_rejects_non_conventional_subjects(self) -> None:
        for subject in ("wip", "Fix the thing", "feat add thing", "unknown(api): thing", ""):
            with self.subTest(subject=subject):
                self.assertFalse(valid_subject(subject))

    def test_script_reads_first_non_comment_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            msg = Path(tmp) / "message.txt"
            msg.write_text("# comment\n\nfeat(api): ok (LAB-1)\n", encoding="utf-8")
            ok = subprocess.run([sys.executable, str(SCRIPT), str(msg)], check=False)  # noqa: S603
            self.assertEqual(ok.returncode, 0)
            msg.write_text("not conventional\n", encoding="utf-8")
            bad = subprocess.run([sys.executable, str(SCRIPT), str(msg)], check=False)  # noqa: S603
            self.assertEqual(bad.returncode, 1)


if __name__ == "__main__":
    unittest.main()
