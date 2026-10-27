"""``pii-guard lang new``: the skeleton passes the structural checks out of the box."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from pii_guard.cli import main
from pii_guard.languages import LanguagePack
from pii_guard.languages.conformance import check_pack, check_structure
from pii_guard.languages.scaffold import ScaffoldError, new_pack


def _load(package: Path, name: str) -> Iterator[ModuleType]:
    spec = importlib.util.spec_from_file_location(
        name, package / "__init__.py", submodule_search_locations=[str(package)]
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        for key in [k for k in sys.modules if k == name or k.startswith(name + ".")]:
            del sys.modules[key]


@pytest.fixture
def scaffolded(tmp_path: Path) -> Iterator[tuple[LanguagePack, Path]]:
    result = new_pack(
        "xx",
        "Exampleish",
        dest=tmp_path / "pkg",
        fixtures_dir=tmp_path / "fixtures",
        tests_dir=tmp_path / "tests",
    )
    for module in _load(result.package, "pii_guard_scaffold_xx"):
        yield module.pack(), tmp_path


def test_the_skeleton_passes_the_structural_checks(
    scaffolded: tuple[LanguagePack, Path],
) -> None:
    pack, _ = scaffolded
    findings = check_structure(pack)
    assert [f for f in findings if f.severity == "error"] == []
    # Not registered yet, and the next steps are spelled out.
    assert {f.check for f in findings if f.severity == "warning"} == {"structure.registered"}


def test_only_the_fixtures_are_missing(scaffolded: tuple[LanguagePack, Path]) -> None:
    pack, tmp_path = scaffolded
    report = check_pack(pack, fixtures_dir=tmp_path / "fixtures")
    assert [f.check for f in report.errors] == ["fixtures.files"]
    assert "start from xx-smoke.jsonl.example" in report.errors[0].message


def test_the_example_fixture_becomes_a_conforming_pack(
    scaffolded: tuple[LanguagePack, Path],
) -> None:
    pack, tmp_path = scaffolded
    fixtures = tmp_path / "fixtures"
    example = (fixtures / "xx-smoke.jsonl.example").read_text(encoding="utf-8")
    assert json.loads(example)["language"] == "xx"
    (fixtures / "xx-smoke.jsonl").write_text(example, encoding="utf-8")
    report = check_pack(pack, fixtures_dir=fixtures)
    assert report.ok, report.render()
    assert {f.check for f in report.findings if f.severity == "warning"} >= {"fixtures.size"}


def test_the_test_hook_runs_the_conformance_suite(scaffolded: tuple[LanguagePack, Path]) -> None:
    _, tmp_path = scaffolded
    hook = (tmp_path / "tests" / "test_xx_pack.py").read_text(encoding="utf-8")
    assert 'assert_conformant("xx")' in hook
    compile(hook, "test_xx_pack.py", "exec")


@pytest.mark.parametrize(
    ("code", "name", "message"),
    [("XX", "Exampleish", "not a lowercase"), ("x", "Exampleish", "not a lowercase"),
     ("xx", "", "--name"), ("xx", 'Bad"Name', "--name")],
)  # fmt: skip
def test_bad_arguments(tmp_path: Path, code: str, name: str, message: str) -> None:
    with pytest.raises(ScaffoldError, match=message):
        new_pack(code, name, dest=tmp_path)


def test_an_existing_skeleton_is_not_overwritten(tmp_path: Path) -> None:
    new_pack("xx", "Exampleish", dest=tmp_path)
    with pytest.raises(ScaffoldError, match="already exists"):
        new_pack("xx", "Exampleish", dest=tmp_path)
    new_pack("xx", "Exampleish", dest=tmp_path, force=True)


def test_cli_new_list_and_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dest = tmp_path / "pkg"
    assert main(["lang", "new", "xx", "--name", "Exampleish", "--dest", str(dest)]) == 0
    out = capsys.readouterr().out
    assert "wrote" in out and "pii-guard lang check xx" in out and "entry-points" in out
    assert (dest / "xx" / "prompt.md").is_file()
    assert (tmp_path / "eval" / "fixtures" / "xx-smoke.jsonl.example").is_file()  # cwd default

    assert main(["lang", "new", "de", "--name", "German", "--dest", str(dest)]) == 2
    assert "already exists" in capsys.readouterr().err

    assert main(["lang", "list"]) == 0
    assert "hu  Hungarian" in capsys.readouterr().out

    assert main(["lang", "check", "de", "--structure-only"]) == 0
    assert "language pack 'de': conforms" in capsys.readouterr().out
    assert main(["lang", "check", "fi"]) == 1
    assert "no language pack for 'fi'" in capsys.readouterr().out


def test_cli_check_runs_the_smoke_set(capsys: pytest.CaptureFixture[str]) -> None:
    fixtures = Path(__file__).resolve().parents[2] / "eval" / "fixtures"
    assert main(["lang", "check", "en", "--fixtures", str(fixtures)]) == 0
    assert "smoke set (rules detector): documents=10" in capsys.readouterr().out
