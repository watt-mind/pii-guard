"""Licence check: fail when a runtime dependency is GPL or AGPL licensed.

```
uv sync --locked --no-dev --extra ocr && uv run --no-sync python scripts/ci/licenses.py
(cd ui && pnpm licenses list --prod --json) > ui-licenses.json
uv run --no-sync python scripts/ci/licenses.py --pnpm-json ui-licenses.json
```

pii-guard is Apache-2.0 and is meant to be embedded; a strong-copyleft runtime dependency
would change what users may do with it. The Python check reads the metadata of every
distribution installed in the current environment (CI installs the runtime set only: no dev
group, the ``ocr`` extra the image ships), from ``License-Expression``, ``License`` and the
trove classifiers. LGPL is weak copyleft and allowed; GPL and AGPL (any version) fail. The UI
check reads ``pnpm licenses list --prod --json``. A package whose licence can't be read is
reported but does not fail the check.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from importlib import metadata
from pathlib import Path

_COPYLEFT = re.compile(r"(?<![L\w])(?:A?GPL|(?:GNU )?(?:Affero )?General Public License)", re.I)
_LESSER = re.compile(r"LGPL|Lesser General Public|Library General Public", re.I)
# Packages built from this repository.
_SELF = {"pii-guard", "pii_guard"}


def _copyleft_term(term: str) -> bool:
    return bool(_COPYLEFT.search(term)) and not _LESSER.search(term)


def is_copyleft(licence: str) -> bool:
    """True for GPL/AGPL in a licence string, expression or classifier; LGPL is not.

    ``GPL-2.0-only OR MIT`` lets the user pick MIT, so it fails only when every alternative
    of an OR is copyleft; in an AND (or a list) any copyleft term fails.
    """
    alternatives = re.split(r"\s+OR\s+", licence)
    return all(
        any(_copyleft_term(t) for t in re.split(r"\s+(?:AND|WITH)\s+|[;,]", alt))
        for alt in alternatives
    )


def python_licences() -> dict[str, str]:
    out = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if not name or name in _SELF:
            continue
        expression = dist.metadata.get("License-Expression")
        classifiers = [
            c.removeprefix("License :: ")
            for c in dist.metadata.get_all("Classifier") or ()
            if c.startswith("License ::")
        ]
        text = dist.metadata.get("License") or ""
        if expression:
            out[name] = expression
        elif classifiers:  # several classifiers mean a choice of licence
            out[name] = " OR ".join(classifiers)
        elif text and len(text) < 100:
            out[name] = text
        else:
            out[name] = ""
    return out


def pnpm_licences(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for licence, packages in data.items():
        for pkg in packages:
            out[f"{pkg['name']}@{','.join(pkg.get('versions') or [])}"] = licence
    return out


def check(licences: dict[str, str], ecosystem: str) -> int:
    bad = {n: lic for n, lic in licences.items() if lic and is_copyleft(lic)}
    unknown = sorted(n for n, lic in licences.items() if not lic or lic.lower() == "unknown")
    for name in unknown:
        print(f"  {ecosystem}: {name}: licence not declared in metadata (not a failure)")
    for name, lic in sorted(bad.items()):
        print(f"::error title=copyleft dependency::{ecosystem} {name} is {lic}")
    if bad:
        print(f"licences: FAILED ({len(bad)} GPL/AGPL {ecosystem} runtime dependencies)")
        return 1
    print(f"licences: OK ({len(licences)} {ecosystem} runtime dependencies, no GPL/AGPL)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pnpm-json", type=Path, help="check this pnpm licences list instead")
    args = parser.parse_args(argv)
    if args.pnpm_json:
        return check(pnpm_licences(args.pnpm_json), "npm")
    return check(python_licences(), "python")


if __name__ == "__main__":
    sys.exit(main())
