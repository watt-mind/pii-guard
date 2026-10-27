"""Score one NER candidate in fast mode over the LAB-1150 fixture list (scorecards + run block).

Wraps :mod:`pii_guard.eval.baselines.suite` (one warm-up call, NER identity, host load) for
every fixture in :data:`FIXTURES`, with the detector list of the candidate:

- ``rules,ner``: an XLM-RoBERTa (or local GLiNER) checkpoint in ``PII_GUARD_NER_MODEL``;
- ``rules,ner_gliner``: GLiNER from ``PII_GUARD_GLINER_MODEL`` (default the zero-shot hub
  model), needs the ``gliner`` environment;
- ``rules,ner,ner_gliner``: both encoders, the resolver takes the union of their spans.

::

    PII_GUARD_NER_MODEL=models/ner/pii-guard-ner-xlmr-large-v2 uv run --no-sync python \\
        training/ner/eval_candidates.py --candidate xlmr-large-v2 --detectors rules,ner
    # scorecards: eval/results/2026-10-27-ner-v2/scorecards/<fixture>--<candidate>.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from pii_guard.eval.baselines import suite
from pii_guard.registry import register_detector

OUT = Path("eval/results/2026-10-27-ner-v2/scorecards")
FIXTURES = (
    "eval/fixtures/hu-smoke.jsonl",
    "eval/fixtures/en-smoke.jsonl",
    "eval/fixtures/de-smoke.jsonl",
    "eval/fixtures/hu-synth-sample.jsonl",
    "eval/fixtures/en-synth-sample.jsonl",
    "eval/fixtures/hu-company-names.jsonl",
    "eval/generated/distill-s11/labelled/hu-distill-dev.jsonl",
    "eval/generated/distill-s11/labelled/en-distill-dev.jsonl",
    "eval/fixtures/public/hu-ai4privacy.jsonl",
    "eval/fixtures/public/en-ai4privacy.jsonl",
    "eval/fixtures/public/de-ai4privacy.jsonl",
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--candidate", required=True, help="slug, e.g. xlmr-large-v2")
    parser.add_argument("--detectors", required=True, help="rules,ner | rules,ner_gliner | ...")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--only", action="append", help="fixture name filter (repeatable)")
    args = parser.parse_args(argv)
    register_detector("ner_gliner", "pii_guard.detect.ner_gliner:GlinerDetector", replace=True)
    system = f"fast-{args.candidate}"
    suite.SYSTEMS[system] = args.detectors.split(",")
    status = 0
    for fixture in FIXTURES:
        name = Path(fixture).stem
        if args.only and not any(o in name for o in args.only):
            continue
        if not Path(fixture).exists():
            print(f"skip {fixture} (missing)", file=sys.stderr)
            continue
        out = args.out / f"{name}--{args.candidate}.json"
        rc = suite.main(
            ["--system", system, "--fixtures", fixture, "--json", str(out),
             "--markdown", str(out.with_suffix(".md"))]
        )  # fmt: skip
        status = status or rc
        if rc == 0:
            annotate(out, args.candidate, suite.SYSTEMS[system])
    return status


def annotate(path: Path, candidate: str, detectors: list[str]) -> None:
    """Add the candidate slug and, for GLiNER, the model identity to the run block."""
    card = json.loads(path.read_text(encoding="utf-8"))
    run = card["run"]
    run["candidate"] = candidate
    if "ner_gliner" in detectors:
        from pii_guard.detect import ner_gliner

        model = os.environ.get(ner_gliner.MODEL_ENV_VAR) or ner_gliner.DEFAULT_MODEL
        ident: dict[str, object] = {"model": model}
        if model == ner_gliner.DEFAULT_MODEL:
            ident["revision"] = ner_gliner.DEFAULT_REVISION
        elif Path(model).is_dir():
            ident["model"] = Path(model).name
            weights = [*Path(model).glob("*.safetensors"), *Path(model).glob("*.bin")]
            ident["weights_sha256"] = {w.name: suite._sha256(w) for w in sorted(weights)}
        run["gliner"] = ident
    path.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
