"""``pii-guard eval``: run the evaluation fixtures and print the scorecard.

```
pii-guard eval [--fixtures PATH ...] [--detectors rules[,ner,llm]] [--language hu[,en]]
               [--json OUT] [--markdown OUT] [--baselines presidio,llm-guard,privaite]
               [--known-values] [--redteam [--redteam-contexts masked-only,decoys]]
pii-guard eval generate --language hu --n 20 --seed 42 --out DIR|FILE.jsonl  # corpus
pii-guard eval visual --specimens data/specimens  # visual recall on specimen ID documents
pii-guard eval injection --detectors rules,llm   # leak rate per prompt-injection attack class
```

``--fixtures`` may be repeated and may name a directory (every ``*.jsonl`` in it); the
default is ``eval/fixtures``. Detectors are looked up in the registry by name; one that
can't be loaded is skipped with a warning. The Markdown scorecard goes to stdout (and to
``--markdown``), the JSON scorecard to ``--json``. ``--baselines`` also runs open-source
tools over the same documents (:mod:`pii_guard.eval.baselines`) and appends a comparison.
Fixtures whose documents carry ``meta.attack`` (the prompt-injection sets) also get a leak
table per attack class (:mod:`pii_guard.eval.injection`).
``--known-values`` pre-loads each document's ``meta.known_values`` into its vault session (the
``known`` detector), to measure the uplift of pre-loading values an application already knows.
``--redteam`` then asks an attacker model (Muse Spark Open on Baseten by default) to recover
the masked values from the masked text, and reports the re-identification rate and exposure
per context, language and entity type (:mod:`pii_guard.eval.redteam`).

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
    parser.add_argument(
        "--baselines",
        type=_csv,
        default=[],
        metavar="NAMES",
        help="also score these open-source tools: presidio, llm-guard, privaite",
    )
    parser.add_argument(
        "--known-values",
        action="store_true",
        help="pre-load each document's meta.known_values into its session (known detector)",
    )
    from pii_guard.eval.redteam import add_redteam_arguments

    add_redteam_arguments(parser)
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
    if argv[:1] == ["injection"]:  # ``pii-guard eval injection``: red team per attack class
        from pii_guard.eval.injection import main as injection_main

        return injection_main(argv[1:])
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

    attacker = None
    if args.redteam:  # configuration errors before any detector or model call
        from pii_guard.eval.redteam import attacker_from_args

        try:
            attacker = attacker_from_args(args)
        except PiiGuardError as exc:
            print(f"pii-guard eval: {exc.message}", file=sys.stderr)
            return 2

    analyzer = DetectorAnalyzer(args.detectors)
    for name, reason in analyzer.skipped:
        print(f"pii-guard eval: warning: skipping detector {name!r}: {reason}", file=sys.stderr)
    if not analyzer.detectors:
        print("pii-guard eval: no detector could be loaded", file=sys.stderr)
        return 2

    try:
        results = run_documents(documents, analyzer, known_values=args.known_values)
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
    if args.known_values:
        scorecard["meta"]["known_values"] = sum(
            len(d.meta.get("known_values") or ()) for d in documents
        )
    markdown = render_markdown(scorecard)
    if any("attack" in d.meta for d in documents):
        from pii_guard.eval.injection import attack_breakdown, attack_of, render_attack_table

        order = list(dict.fromkeys(attack_of(d) for d in documents))
        scorecard["attacks"] = attack_breakdown(results, order=order)
        markdown += "\n## Per attack class\n\n" + render_attack_table(scorecard["attacks"])
    if args.known_values:
        markdown += (
            f"\nKnown values pre-loaded from fixture meta: {scorecard['meta']['known_values']} "
            "(`known` detector).\n"
        )
    if attacker is not None:
        from pii_guard.eval.redteam import redteam_section

        try:
            scorecard["redteam"], section = redteam_section(
                results, args, attacker, analyzer=analyzer
            )
        except PiiGuardError as exc:
            print(f"pii-guard eval: red team failed: {exc.code}: {exc.message}", file=sys.stderr)
            return 1
        markdown += section
    if args.baselines:
        from pii_guard.eval.baselines import render_comparison, run_baselines

        try:
            scorecard["baselines"], skipped = run_baselines(documents, args.baselines)
        except PiiGuardError as exc:
            print(f"pii-guard eval: baseline failed: {exc.code}: {exc.message}", file=sys.stderr)
            return 1
        scorecard["meta"]["skipped_baselines"] = [{"name": n, "reason": r} for n, r in skipped]
        for name, reason in skipped:
            print(f"pii-guard eval: warning: skipping baseline {name!r}: {reason}", file=sys.stderr)
        markdown += "\n" + render_comparison([scorecard])
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
