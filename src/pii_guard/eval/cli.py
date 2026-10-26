"""``pii-guard eval``: run the evaluation fixtures and print the scorecard.

```
pii-guard eval [--fixtures PATH ...] [--detectors rules[,ner,llm]] [--language hu[,en]]
               [--json OUT] [--markdown OUT]
pii-guard eval generate --language hu --n 20 --seed 42 --out DIR|FILE.jsonl  # corpus
pii-guard eval visual --specimens data/specimens  # visual recall on specimen ID documents
```

``--fixtures`` may be repeated and may name a directory (every ``*.jsonl`` in it); the
default is ``eval/fixtures``. Detectors are looked up in the registry by name; one that
can't be loaded is skipped with a warning. The Markdown scorecard goes to stdout (and to
``--markdown``), the JSON scorecard to ``--json``.

Exit codes: 0 success, 1 a detector or the vault failed during the run, 2 bad arguments,
unreadable fixtures or no loadable detector.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pii_guard.eval.fixtures import FixtureError, load_fixtures
from pii_guard.eval.report import build_scorecard, render_markdown
from pii_guard.eval.scorer import DetectorAnalyzer, run_documents
from pii_guard.types import PiiGuardError

__all__ = ["DEFAULT_FIXTURES", "build_parser", "main"]

DEFAULT_FIXTURES = "eval/fixtures"


def _csv(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise argparse.ArgumentTypeError("expected a comma-separated list")
    return items


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pii-guard eval",
        description="Score detectors and masking on the synthetic evaluation fixtures.",
    )
    parser.add_argument(
        "--fixtures",
        action="append",
        metavar="PATH",
        help=f"JSONL file or directory, repeatable (default: {DEFAULT_FIXTURES})",
    )
    parser.add_argument(
        "--detectors",
        type=_csv,
        default=["rules"],
        metavar="NAMES",
        help="comma-separated registry names (default: rules)",
    )
    parser.add_argument(
        "--language",
        type=_csv,
        action="extend",
        metavar="LANGS",
        help="only documents in these languages (comma-separated, repeatable)",
    )
    parser.add_argument("--json", type=Path, metavar="OUT", help="write the JSON scorecard here")
    parser.add_argument(
        "--markdown", type=Path, metavar="OUT", help="also write the Markdown table here"
    )
    return parser


def _expand_fixture_paths(raw: Sequence[str]) -> list[Path]:
    paths: list[Path] = []
    for item in raw:
        path = Path(item)
        paths.extend(sorted(path.glob("*.jsonl")) if path.is_dir() else [path])
    return paths


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    if argv[:1] == ["generate"]:  # ``pii-guard eval generate``: the corpus generator
        from pii_guard.eval.generate import main as generate_main

        return generate_main(argv[1:])
    if argv[:1] == ["visual"]:  # ``pii-guard eval visual``: image masking on specimens
        from pii_guard.eval.visual import main as visual_main

        return visual_main(argv[1:])
    args = build_parser().parse_args(argv)
    fixture_paths = _expand_fixture_paths(args.fixtures or [DEFAULT_FIXTURES])
    try:
        documents = load_fixtures(fixture_paths)
    except (FixtureError, OSError) as exc:
        print(f"pii-guard eval: {exc}", file=sys.stderr)
        return 2
    if args.language:
        wanted = set(args.language)
        documents = [d for d in documents if d.language in wanted or d.primary_language in wanted]
    if not documents:
        print("pii-guard eval: no fixture documents selected", file=sys.stderr)
        return 2

    analyzer = DetectorAnalyzer(args.detectors)
    for name, reason in analyzer.skipped:
        print(f"pii-guard eval: warning: skipping detector {name!r}: {reason}", file=sys.stderr)
    if not analyzer.detectors:
        print("pii-guard eval: no detector could be loaded", file=sys.stderr)
        return 2

    try:
        results = run_documents(documents, analyzer)
    except PiiGuardError as exc:
        # Fail closed and say why without raw values (messages carry types and counts only).
        print(f"pii-guard eval: run failed: {exc.code}: {exc.message}", file=sys.stderr)
        return 1

    scorecard = build_scorecard(
        results,
        detectors=analyzer.loaded,
        skipped_detectors=analyzer.skipped,
        fixture_paths=fixture_paths,
        languages=args.language,
    )
    markdown = render_markdown(scorecard)
    sys.stdout.write(markdown)
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown, encoding="utf-8")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(scorecard, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return 0
