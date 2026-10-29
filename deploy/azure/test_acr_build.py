"""Exercise the cached ACR build script with `az` stubbed on PATH (no Azure calls)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("acr_build.sh").resolve()
REGISTRY = "piiguardexample"
DIGEST = "sha256:" + "b" * 64

# Records each call, keeps a copy of the uploaded context, and answers the digest lookup.
FAKE_AZ = r"""#!/bin/sh
printf '%s\n' "$*" >> "$AZURE_TEST_LOG"
case "$*" in
  "acr run "*)
    for last; do :; done
    cp -R "$last" "$AZURE_TEST_CONTEXT"
    echo 'synthetic build log'
    exit "${TEST_RUN_EXIT:-0}";;
  "acr repository show "*) echo "${TEST_DIGEST:-__DIGEST__}";;
  *) echo 'UNEXPECTED AZURE CALL' >&2; exit 99;;
esac
""".replace("__DIGEST__", DIGEST)


class AcrBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        # A throwaway repo holding a copy of the script, so `git archive` sees a known tree.
        self.repo = self.tmp / "repo"
        (self.repo / "deploy" / "azure").mkdir(parents=True)
        shutil.copy2(SCRIPT, self.repo / "deploy" / "azure" / "acr_build.sh")
        (self.repo / "Dockerfile.hosted").write_text("FROM scratch\n")
        (self.repo / "uncommitted.txt").write_text("not committed\n")
        self.git("init", "--quiet", "--initial-branch=develop")
        self.git("add", "Dockerfile.hosted", "deploy")
        self.git("commit", "--quiet", "-m", "fixture")
        self.sha = self.git("rev-parse", "HEAD")
        self.short = self.git("rev-parse", "--short=7", "HEAD")
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "az"
        fake.write_text(FAKE_AZ)
        fake.chmod(0o755)
        self.log = self.tmp / "az.log"
        self.context = self.tmp / "context"
        self.scratch = self.tmp / "scratch"
        self.scratch.mkdir()
        self.env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(self.tmp),
            "AZURE_TEST_LOG": str(self.log),
            "AZURE_TEST_CONTEXT": str(self.context),
            "TMPDIR": str(self.scratch),
        }

    def git(self, *args: str) -> str:
        result = subprocess.run(  # noqa: S603 - local throwaway repository
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],  # noqa: S607
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def run_script(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - fixture script with a stubbed az
            [str(self.repo / "deploy" / "azure" / "acr_build.sh"), *args],
            cwd=self.tmp,
            env={**self.env, **env},
            capture_output=True,
            text=True,
            check=False,
        )

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_builds_committed_tree_and_prints_only_tag_and_digest(self) -> None:
        result = self.run_script(ACR_NAME=REGISTRY)
        self.assertEqual(result.returncode, 0, result.stderr)
        tag = f"develop-{self.short}"
        self.assertEqual(
            result.stdout.splitlines(),
            [
                f"TAG {tag}",
                f"DIGEST {DIGEST}",
                f"IMAGE {REGISTRY}.azurecr.io/pii-guard@{DIGEST}",
            ],
        )
        self.assertIn("synthetic build log", result.stderr)
        run, show = self.calls()
        self.assertTrue(run.startswith(f"acr run --registry {REGISTRY} --file acr-task.yaml "))
        self.assertEqual(
            show,
            f"acr repository show --name {REGISTRY} --image pii-guard:{tag} "
            "--query digest --output tsv",
        )
        # git archive: committed files only, plus the task file inside the context.
        self.assertTrue((self.context / "Dockerfile.hosted").is_file())
        self.assertFalse((self.context / "uncommitted.txt").exists())
        self.assertFalse((self.context / ".git").exists())
        task = (self.context / "acr-task.yaml").read_text()
        self.assertTrue(task.startswith("version: v1.1.0\n"))
        self.assertEqual(task.count('env: ["DOCKER_BUILDKIT=1"]'), 3)
        inline = "--build-arg BUILDKIT_INLINE_CACHE=1 -f Dockerfile.hosted ."
        self.assertEqual(task.count(inline), 3)
        for cache in ("buildcache-python-build", "buildcache-ui-build", "buildcache"):
            self.assertEqual(task.count(f"--cache-from $Registry/pii-guard:{cache} "), 3)
            self.assertIn(f"      - $Registry/pii-guard:{cache}\n", task)
        self.assertIn(f"-t $Registry/pii-guard:{tag} -t $Registry/pii-guard:buildcache ", task)
        self.assertIn(f"      - $Registry/pii-guard:{tag}\n", task)
        self.assertNotIn("-f -", task)
        # The temporary context is removed afterwards.
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_arguments_override_environment(self) -> None:
        self.git("commit", "--quiet", "--allow-empty", "-m", "second")
        result = self.run_script(
            "--registry", "otherregistry1", "--tag-prefix", "main", self.sha, ACR_NAME=REGISTRY
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[0], f"TAG main-{self.short}")
        self.assertIn("--registry otherregistry1 ", self.calls()[0])

    def test_registry_is_required(self) -> None:
        result = self.run_script()
        self.assertEqual(result.returncode, 2)
        self.assertIn("ACR_NAME", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_rejects_bad_inputs_before_calling_azure(self) -> None:
        for args, env in (
            ((), {"ACR_NAME": "Bad-Name"}),
            (("--tag-prefix", "bad prefix"), {"ACR_NAME": REGISTRY}),
            (("no-such-ref",), {"ACR_NAME": REGISTRY}),
            (("--registry",), {}),
        ):
            with self.subTest(args=args):
                result = self.run_script(*args, **env)
                self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.calls(), [])

    def test_failed_build_stops_before_digest_lookup(self) -> None:
        result = self.run_script(ACR_NAME=REGISTRY, TEST_RUN_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(self.calls()), 1)

    def test_malformed_digest_fails(self) -> None:
        result = self.run_script(ACR_NAME=REGISTRY, TEST_DIGEST="not-a-digest")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
