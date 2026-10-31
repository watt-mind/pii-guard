"""``python -m pii_guard.eval.datasets`` / ``pii-guard eval datasets``: list, fetch, check, run."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pii_guard.eval.datasets import REGISTRY, get
from pii_guard.eval.datasets._common import dump_json
from pii_guard.eval.datasets.spec import Dataset, check, fetch
from pii_guard.eval.fixtures import write_fixtures

__all__ = ["main"]


def _fetch_one(ds: Dataset) -> list[Path]:
    if ds.derived_from is not None:
        from pii_guard.eval.datasets import corrections

        return corrections.fetch(ds)
    if ds.builder is not None:
        written = []
        for path, (_, docs) in zip(
            ds.fixture_paths(), sorted(ds.builder().items(), key=_lang_order(ds)), strict=True
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            write_fixtures(path, docs)
            written.append(path)
        ds.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        ds.manifest_path.write_text(dump_json(_builder_manifest(ds)), encoding="utf-8")
        return [*written, ds.manifest_path]
    if ds.external:
        from pii_guard.eval.public import ai4privacy

        if ai4privacy.main(["fetch"]) != 0:
            raise RuntimeError("ai4privacy fetch failed")
        return [Path(p) for p in ds.external]
    return fetch(ds)


def _lang_order(ds: Dataset) -> Callable[[tuple[str, Any]], int]:
    return lambda item: ds.languages.index(item[0])


def _builder_manifest(ds: Dataset) -> dict[str, object]:
    from collections import Counter

    from pii_guard.eval.datasets._common import text_sha256
    from pii_guard.eval.fixtures import load_fixtures

    languages = {}
    for path, lang in zip(ds.fixture_paths(), ds.languages, strict=True):
        docs = load_fixtures([path])
        gold = Counter(s.entity_type.value for d in docs for s in d.spans)
        shapes = Counter(str(d.meta.get("shape")) for d in docs)
        checks = Counter(str(m["valid"]).lower() for d in docs for m in d.meta.get("checksum", []))
        perturbed = Counter(m["kind"] for d in docs for m in d.meta.get("perturbed", []))
        languages[lang] = {
            "documents": len(docs),
            "file": str(path),
            "gold_spans": dict(sorted(gold.items())),
            "shapes": dict(sorted(shapes.items())),
            "checksum": dict(sorted(checks.items())),
            "perturbed": dict(sorted(perturbed.items())),
            "text_sha256": [text_sha256(d.text) for d in docs],
        }
    return {
        "dataset": ds.name,
        "title": ds.title,
        "generator": ds.revision,
        "license": ds.license,
        "synthetic": True,
        "rows_committed": True,
        "split": ds.split,
        "seed": ds.seed,
        "notes": list(ds.notes),
        "languages": languages,
    }


def _check_one(ds: Dataset) -> list[str]:
    if ds.derived_from is not None:
        from pii_guard.eval.datasets import corrections

        return corrections.check(ds)
    if ds.builder is not None:
        import tempfile

        problems = []
        with tempfile.TemporaryDirectory() as tmp:
            for path, (_, docs) in zip(
                ds.fixture_paths(), sorted(ds.builder().items(), key=_lang_order(ds)), strict=True
            ):
                rebuilt = Path(tmp) / path.name
                write_fixtures(rebuilt, docs)
                if not path.is_file() or path.read_bytes() != rebuilt.read_bytes():
                    problems.append(f"{path}: differs from the generator output")
        if ds.manifest_path.read_text(encoding="utf-8") != dump_json(_builder_manifest(ds)):
            problems.append(f"{ds.manifest_path}: differs")
        return problems
    if ds.external:
        from pii_guard.eval.public import ai4privacy

        return [] if ai4privacy.main(["fetch", "--check"]) == 0 else ["ai4privacy: check failed"]
    return check(ds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pii_guard.eval.datasets",
        description="Evaluation datasets: list, fetch (download + seeded sample), check, run.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="every registered dataset")
    for name, help_ in (
        ("fetch", "build the sample / fixture files"),
        ("check", "rebuild and compare"),
    ):
        p = sub.add_parser(name, help=help_)
        p.add_argument("names", nargs="+", metavar="NAME")
    p = sub.add_parser("paths", help="a dataset's fixture files")
    p.add_argument("name", metavar="NAME")
    p = sub.add_parser("run", help="score systems on a dataset")
    p.add_argument("name", metavar="NAME")
    p.add_argument(
        "--system", required=True, help="rules, fast, audit, presidio, llm-guard, privaite"
    )
    p.add_argument("--record", action="store_true", help="write run records and counts")
    p.add_argument("--limit", type=int, help="first N documents per language")
    p.add_argument("--day", help="record date (default: today)")
    p.add_argument(
        "--tag",
        "--slug",
        dest="tag",
        help="slug-safe suffix for the run id (a second fast-mode run on the same day)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "list":
            for ds in REGISTRY.values():
                langs = ",".join(ds.languages)
                rows = "rows committed" if ds.commit_rows else "manifest only"
                print(f"{ds.name:24} {ds.split:4} {ds.license[:28]:28} {langs:9} {rows}")
            return 0
        if args.command == "paths":
            for path in get(args.name).fixture_paths():
                print(path)
            return 0
        if args.command == "fetch":
            for name in args.names:
                for path in _fetch_one(get(name)):
                    print(f"datasets: wrote {path}", file=sys.stderr)
            return 0
        if args.command == "check":
            problems = [p for name in args.names for p in _check_one(get(name))]
            for problem in problems:
                print(f"datasets: {problem}", file=sys.stderr)
            if not problems:
                print("datasets: the committed files match a rebuild", file=sys.stderr)
            return 1 if problems else 0
        from pii_guard.eval.datasets.run import print_summaries, run_dataset

        systems = [s.strip() for s in args.system.split(",") if s.strip()]
        summaries = run_dataset(
            get(args.name),
            systems,
            record=args.record,
            limit=args.limit,
            day=args.day,
            tag=args.tag,
        )
        print_summaries(summaries)
        if args.record:
            from pii_guard.eval.report_cli import main as report_main

            return report_main([])
        return 0
    except (KeyError, ValueError, RuntimeError, FileNotFoundError, OSError) as exc:
        print(f"datasets: {exc}", file=sys.stderr)
        return 2
