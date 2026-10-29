"""``pii-guard lang``: list, check and scaffold language packs.

```
pii-guard lang list                       # the available packs and their parts
pii-guard lang check [CODE ...]           # conformance report (all packs by default)
                     [--fixtures DIR] [--structure-only]
pii-guard lang new CODE --name NAME       # a pack skeleton (docs/languages.md)
                   [--dest DIR] [--fixtures DIR] [--tests DIR] [--force]
```

Exit codes: 0 success, 1 a pack fails its conformance checks, 2 bad arguments.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

__all__ = ["build_parser", "main"]

DEFAULT_DEST = "src/pii_guard/languages"
DEFAULT_FIXTURES = "eval/fixtures"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pii-guard lang", description="List, check and scaffold language packs."
    )
    sub = parser.add_subparsers(dest="action", metavar="<action>", required=True)
    sub.add_parser("list", help="the available language packs and their parts")
    check = sub.add_parser("check", help="run the conformance checks")
    check.add_argument("codes", nargs="*", metavar="CODE", help="packs to check (default: all)")
    check.add_argument(
        "--fixtures",
        default=DEFAULT_FIXTURES,
        help=f"smoke fixture dir (default: {DEFAULT_FIXTURES})",
    )
    check.add_argument("--structure-only", action="store_true", help="skip fixtures and scores")
    new = sub.add_parser("new", help="generate a language pack skeleton")
    new.add_argument("code", help="ISO 639-1 code, e.g. 'pl'")
    new.add_argument("--name", required=True, help="the language's English name, e.g. 'Polish'")
    new.add_argument("--dest", default=DEFAULT_DEST, help=f"parent dir (default: {DEFAULT_DEST})")
    new.add_argument(
        "--fixtures",
        default=DEFAULT_FIXTURES,
        help=f"where the fixture template goes (default: {DEFAULT_FIXTURES})",
    )
    new.add_argument("--tests", default=None, help="also write a conformance test hook here")
    new.add_argument("--force", action="store_true", help="overwrite an existing skeleton")
    return parser


def _list() -> int:
    from pii_guard.languages import packs

    for code, pack in packs().items():
        parts = [
            f"{len(pack.everywhere)}+{len(pack.rules)} rules",
            f"inflection={type(pack.inflection).__name__ if pack.inflection else '-'}",
            f"prompt={'yes' if pack.prompt else '-'}",
            f"surface_forms={'yes' if pack.surface_forms else '-'}",
            f"lexicons={len(pack.lexicons.kinds) if pack.lexicons else '-'}",
            f"fixtures={','.join(str(f) for f in pack.smoke_fixtures) or '-'}",
        ]
        print(f"{code}  {pack.name:<12} " + "  ".join(parts))
    return 0


def _check(args: argparse.Namespace) -> int:
    from pii_guard.languages import available_languages
    from pii_guard.languages.conformance import check_pack

    failed = 0
    for code in args.codes or available_languages():
        report = check_pack(code, fixtures_dir=args.fixtures, structure_only=args.structure_only)
        print(report.render())
        failed += not report.ok
    return 1 if failed else 0


def _new(args: argparse.Namespace) -> int:
    from pii_guard.languages import get_pack
    from pii_guard.languages.scaffold import ScaffoldError, new_pack

    if get_pack(args.code) is not None and not args.force:
        print(f"pii-guard lang: a {args.code!r} pack already exists", file=sys.stderr)
        return 2
    try:
        result = new_pack(
            args.code,
            args.name,
            dest=args.dest,
            fixtures_dir=args.fixtures,
            tests_dir=args.tests,
            force=args.force,
        )
    except ScaffoldError as exc:
        print(f"pii-guard lang: {exc}", file=sys.stderr)
        return 2
    for path in result.written:
        print(f"wrote {path}")
    inside = Path(args.dest).resolve() == Path(DEFAULT_DEST).resolve()
    print(
        "\nNext steps (docs/languages.md):\n"
        f"  1. write {args.fixtures}/{args.code}-smoke.jsonl (start from the .example file)\n"
        f"  2. add rules, an inflection matcher and prompt notes to {result.package}/\n"
        + (
            ""
            if inside
            else f'  3. register it: [project.entry-points."pii_guard.languages"] '
            f'{args.code} = "<your_package>.{args.code}:pack"\n'
        )
        + f"  then: pii-guard lang check {args.code}"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.action == "list":
        return _list()
    if args.action == "check":
        return _check(args)
    return _new(args)
