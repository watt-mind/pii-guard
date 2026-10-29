"""Split a venv into its dependency layer and the project's additions (LAB-1449)."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from venv_layer import main, split

DOCKERFILE = Path(__file__).resolve().parents[2] / "Dockerfile.hosted"


class VenvLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.base = self.tmp / "base"
        site = self.base / "lib" / "python3.12" / "site-packages"
        (site / "torch").mkdir(parents=True)
        (site / "torch" / "__init__.py").write_text("import torch\n")
        (self.base / "bin").mkdir()
        (self.base / "bin" / "python").symlink_to("/usr/local/bin/python3")
        (self.base / "pyvenv.cfg").write_text("home = /usr/local/bin\n")
        self.full = self.tmp / "full"
        shutil.copytree(self.base, self.full, symlinks=True)
        self.out = self.tmp / "out"
        self.out.mkdir()

    def install_project(self) -> None:
        site = self.full / "lib" / "python3.12" / "site-packages"
        (site / "pii_guard" / "__pycache__").mkdir(parents=True)
        (site / "pii_guard" / "__init__.py").write_text("VERSION = 1\n")
        (site / "pii_guard" / "__pycache__" / "__init__.cpython-312.pyc").write_bytes(b"\0" * 8)
        (site / "wattmind_pii_guard-0.1.0.dist-info").mkdir()
        (site / "wattmind_pii_guard-0.1.0.dist-info" / "RECORD").write_text("pii_guard/...\n")
        script = self.full / "bin" / "pii-guard"
        script.write_text("#!/app/.venv/bin/python\n")
        script.chmod(0o755)

    def layered(self) -> set[str]:
        return {str(p.relative_to(self.out)) for p in self.out.rglob("*") if not p.is_dir()}

    def test_only_the_project_lands_in_the_layer(self) -> None:
        self.install_project()
        files, size = split(self.base, self.full, self.out)
        self.assertEqual(
            self.layered(),
            {
                "bin/pii-guard",
                "lib/python3.12/site-packages/pii_guard/__init__.py",
                "lib/python3.12/site-packages/pii_guard/__pycache__/__init__.cpython-312.pyc",
                "lib/python3.12/site-packages/wattmind_pii_guard-0.1.0.dist-info/RECORD",
            },
        )
        self.assertEqual(files, 4)
        self.assertGreater(size, 0)
        self.assertTrue(os.access(self.out / "bin" / "pii-guard", os.X_OK))

    def test_rewritten_dependency_with_new_bytes_is_layered(self) -> None:
        self.install_project()
        (self.full / "lib/python3.12/site-packages/torch/__init__.py").write_text("import torch2\n")
        split(self.base, self.full, self.out)
        self.assertIn("lib/python3.12/site-packages/torch/__init__.py", self.layered())

    def test_retouched_dependency_with_same_bytes_is_not_layered(self) -> None:
        self.install_project()
        torch = self.full / "lib/python3.12/site-packages/torch/__init__.py"
        os.utime(torch, ns=(1, 1))
        split(self.base, self.full, self.out)
        self.assertNotIn("lib/python3.12/site-packages/torch/__init__.py", self.layered())

    def test_changed_symlink_is_copied_as_a_link(self) -> None:
        self.install_project()
        (self.full / "bin" / "python").unlink()
        (self.full / "bin" / "python").symlink_to("python3.12")
        split(self.base, self.full, self.out)
        self.assertEqual(os.readlink(self.out / "bin" / "python"), "python3.12")

    def test_removed_dependency_file_fails(self) -> None:
        self.install_project()
        (self.full / "pyvenv.cfg").unlink()
        with self.assertRaisesRegex(SystemExit, "removed"):
            split(self.base, self.full, self.out)

    def test_empty_project_layer_fails(self) -> None:
        with self.assertRaisesRegex(SystemExit, "added nothing"):
            main([str(self.base), str(self.full), str(self.out)])

    def test_dockerfile_runtime_copies_deps_then_project(self) -> None:
        text = DOCKERFILE.read_text(encoding="utf-8")
        deps = text.index("COPY --from=python-deps /app/.venv /app/.venv")
        project = text.index("COPY --from=python-build /app/venv-project /app/.venv")
        ui = text.index("COPY --from=ui-build /ui/dist /app/.venv/lib/python3.12/site-packages/")
        self.assertLess(deps, project)
        self.assertLess(project, ui)
        self.assertNotIn("COPY --from=python-build /app/.venv ", text)

    def test_dockerfile_runtime_copies_ner_from_the_src_independent_stage(self) -> None:
        text = DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("COPY --from=ner-model /app/models/ner /app/models/ner", text)
        self.assertNotIn("COPY --from=python-build /app/models /app/models", text)
        self.assertLess(text.index("AS ner-model"), text.index("COPY src ./src"))


if __name__ == "__main__":
    unittest.main()
