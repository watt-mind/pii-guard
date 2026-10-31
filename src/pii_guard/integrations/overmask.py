"""Over-masking check: what fast mode (rules + NER) masks in source code.

```
uv run python -m pii_guard.integrations.overmask FILE... [--record PATH]
```

Coding agents send code, paths and URLs. A placeholder in place of an identifier, a path or a
URL breaks the agent's work (it edits the wrong name, opens a file that doesn't exist), so this
runs the gateway's fast detectors over each file and sorts every masked span into:

- ``identifier``: looks like a code name (``load_customers``, ``Customer.iban``);
- ``path``: has a ``/`` or ``\\`` and no scheme; ``url``: has ``://``;
- ``value``: anything else (personal data, which is what should be masked).

The record holds counts per kind and type, and the identifier/path/url spans themselves (code
from this repo or the fictional mini-repo, never personal data). ``value`` spans are counted only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

__all__ = ["classify", "main", "scan"]

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


def classify(text: str) -> str:
    if "://" in text:
        return "url"
    if "/" in text or "\\" in text:
        return "path"
    if _IDENTIFIER_RE.match(text) and ("_" in text or "." in text or text[:1].islower()):
        return "identifier"
    return "value"


def scan(paths: list[Path], language: str = "en") -> dict[str, Any]:
    from pii_guard.config import Settings
    from pii_guard.gateway import GatewayConfig, Mode, build_mode_detectors

    detector = build_mode_detectors(Settings(), GatewayConfig(), llm_detector=_NoLlm())[Mode.FAST]
    kinds: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    code_spans: list[dict[str, str]] = []
    chars = 0
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        chars += len(text)
        spans, _ = detector.detect(text, language)
        for span in spans:
            value = text[span.start : span.end]
            kind = classify(value)
            kinds[kind] += 1
            by_type[f"{kind}:{span.entity_type.value}"] += 1
            if kind != "value":
                code_spans.append(
                    {"file": path.name, "type": span.entity_type.value, "kind": kind, "text": value}
                )
    return {
        "detectors": detector.config_id.split(";policies=")[0],
        "files": [p.name for p in paths],
        "chars": chars,
        "masked": sum(kinds.values()),
        "by_kind": dict(sorted(kinds.items())),
        "by_kind_and_type": dict(sorted(by_type.items())),
        "code_spans": code_spans,
    }


class _NoLlm:
    name = "llm"
    model = "unused"

    def detect(self, text: str, language: str = "hu") -> list[Any]:  # pragma: no cover
        raise AssertionError("fast mode never calls the LLM detector")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pii_guard.integrations.overmask")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--language", default="en")
    parser.add_argument("--record", type=Path, default=None)
    args = parser.parse_args(argv)
    result = scan(args.files, args.language)
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.record:
        args.record.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
