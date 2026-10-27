"""Dogfood check: run pii-guard's own rules over a PR's added lines and flag real-looking PII.

```
uv run python scripts/ci/pii_in_diff.py --base origin/develop   # CI: lines added since base
uv run python scripts/ci/pii_in_diff.py --all                   # every tracked file
uv run python scripts/ci/pii_in_diff.py --all --update-allowlist
```

The repository promises fictional data only (ADR 0005). This check holds code and docs to it
with the product itself: the rules detector (rules only, offline) reads each changed file and
flags, on the lines the PR adds,

* identifiers a validated rule found (checksum or format-checked: tax and TAJ numbers, IBANs
  and cards, ID documents, company numbers), unless the value is on the allow-list of known
  fictional values (``scripts/ci/pii-allowlist.txt``);
* e-mail addresses outside the reserved example domains (RFC 2606/6761: ``example.*``,
  ``*.example``, ``*.test``, ``*.invalid``, ``*.localhost``).

Fixture, evaluation and test directories are skipped: they are synthetic by construction and
checked by their own generators. Findings are printed redacted (type, file, line, first two
characters), never the value, so a real leak is not copied into a public CI log.

Exit codes: 0 clean, 1 findings, 2 git failed.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pii_guard.detect.rules import RuleDetector
from pii_guard.languages.cues import CUED_SCORE
from pii_guard.types import EntityType

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = ROOT / "scripts" / "ci" / "pii-allowlist.txt"

LANGUAGES = ("hu", "en-GB", "de")
ID_TYPES = {
    EntityType.NATIONAL_ID_HU_TAX,
    EntityType.NATIONAL_ID_HU_TAJ,
    EntityType.BANK_ACCOUNT,
    EntityType.ID_DOCUMENT,
    EntityType.COMPANY_ID_HU,
}
SKIP_PREFIXES = (
    "eval/",
    "tests/",
    "data/",
    "ui/tests/",
    "ui/src/test/",
    "ui/e2e/",
    ".github/",
    "scripts/ci/pii-allowlist.txt",
)
SKIP_PATTERNS = (re.compile(r"\.(test|spec)\.[cm]?[jt]sx?$"), re.compile(r"(^|/)__snapshots__/"))
TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".toml", ".yml", ".yaml", ".json", ".ts", ".tsx", ".js", ".mjs",
    ".cjs", ".html", ".css", ".sh", ".cfg", ".ini", ".env", ".example",
}  # fmt: skip
_RESERVED_EMAIL = re.compile(
    r"@(?:[\w-]+\.)*(?:example\.[a-z0-9-]{2,}|[\w-]+\.(?:example|test|invalid|localhost)|localhost)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    entity_type: str
    value: str

    def redacted(self) -> str:
        return self.value[:2] + "*" * max(0, len(self.value) - 2)


def normalize(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\s.\-/]", "", folded)


def load_allowlist() -> set[str]:
    if not ALLOWLIST.exists():
        return set()
    lines = ALLOWLIST.read_text(encoding="utf-8").splitlines()
    return {normalize(x.split("#", 1)[0]) for x in lines if x.split("#", 1)[0].strip()}


def scanned(path: str) -> bool:
    if path.startswith(SKIP_PREFIXES) or any(p.search(path) for p in SKIP_PATTERNS):
        return False
    p = Path(path)
    return p.suffix in TEXT_SUFFIXES or p.name in {"Dockerfile", "Makefile", "LICENSE"}


def _git(*args: str) -> str:
    proc = subprocess.run(  # noqa: S603 - fixed git argument lists
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(2)
    return proc.stdout


def added_lines(base: str) -> dict[str, set[int]]:
    """``{path: {line numbers added}}`` between the merge base with ``base`` and HEAD."""
    diff = _git("diff", "--unified=0", "--no-color", "--diff-filter=AMR", f"{base}...HEAD")
    out: dict[str, set[int]] = {}
    path = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@") and path:
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if m:
                start, count = int(m[1]), int(m[2] or 1)
                out.setdefault(path, set()).update(range(start, start + count))
    return out


def scan_text(path: str, text: str, lines: set[int] | None, detector: RuleDetector) -> set[Finding]:
    starts = [0] + [i + 1 for i, ch in enumerate(text) if ch == "\n"]

    def line_of(offset: int) -> int:
        lo, hi = 0, len(starts)
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            lo, hi = (mid, hi) if starts[mid] <= offset else (lo, mid)
        return lo + 1

    found: set[Finding] = set()
    for language in LANGUAGES:
        for span in detector.detect(text, language=language):
            if span.entity_type is EntityType.EMAIL:
                if _RESERVED_EMAIL.search(span.text):
                    continue
            elif span.entity_type not in ID_TYPES or span.score <= CUED_SCORE:
                continue
            line = line_of(span.start)
            if lines is None or line in lines:
                found.add(Finding(path, line, span.entity_type.value, span.text))
    return found


def scan(paths: dict[str, set[int] | None]) -> list[Finding]:
    detector = RuleDetector()
    findings: set[Finding] = set()
    for path, lines in paths.items():
        if not scanned(path):
            continue
        try:
            text = (ROOT / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        findings |= scan_text(path, text, lines, detector)
    return sorted(findings, key=lambda f: (f.path, f.line, f.entity_type))


def report(findings: Iterable[Finding], allow: set[str]) -> int:
    bad = [f for f in findings if normalize(f.value) not in allow]
    for f in bad:
        msg = f"{f.entity_type} {f.redacted()} looks real (not a reserved example / allow-listed)"
        print(f"::error file={f.path},line={f.line},title=real-looking PII::{msg}")
        print(f"  {f.path}:{f.line}: {msg}", file=sys.stderr)
    if bad:
        print(
            f"pii-in-diff: {len(bad)} finding(s). Use fictional values: example.* e-mail domains, "
            "and for identifiers either an invalid checksum or a value added to "
            "scripts/ci/pii-allowlist.txt with a note saying it is fictional.",
            file=sys.stderr,
        )
        return 1
    print("pii-in-diff: OK (no real-looking PII on the scanned lines)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--base", help="scan lines added since the merge base with this ref")
    group.add_argument("--all", action="store_true", help="scan every tracked file")
    parser.add_argument(
        "--update-allowlist",
        action="store_true",
        help="with --all: append every value found to the allow-list (review the diff!)",
    )
    args = parser.parse_args(argv)
    if args.all:
        paths: dict[str, set[int] | None] = dict.fromkeys(_git("ls-files").splitlines())
    else:
        paths = dict(added_lines(args.base))
    findings = scan(paths)
    if args.update_allowlist:
        if not args.all:
            parser.error("--update-allowlist needs --all")
        known = load_allowlist()
        ids = sorted({normalize(f.value) for f in findings} - known)
        if not ALLOWLIST.exists():
            ALLOWLIST.write_text(
                "# Fictional values that pass pii-guard's validated rules, used in code and docs.\n"
                "# scripts/ci/pii_in_diff.py accepts these. Add a value only if it is fictional.\n",
                encoding="utf-8",
            )
        with ALLOWLIST.open("a", encoding="utf-8") as fh:
            fh.writelines(f"{v}\n" for v in ids)
        print(f"pii-in-diff: wrote {len(ids)} values to {ALLOWLIST.relative_to(ROOT)}")
        return 0
    return report(findings, load_allowlist())


if __name__ == "__main__":
    sys.exit(main())
