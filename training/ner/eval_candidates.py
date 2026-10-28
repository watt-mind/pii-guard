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

``--set v21`` (LAB-1306) scores :data:`FIXTURES_V21` instead: the smoke sets, the company
names, the ai4privacy sample (in-distribution for every OpenPII-trained candidate) and the
LAB-1226 ``agent-traffic-dev`` split, which is what v2 vs v2.1 is selected on. ``--set
heldout`` is :data:`FIXTURES_HELDOUT`, the LAB-1226 **test** sets, scored once for the chosen
candidates after selection and never used to pick one. The LAB-1226 files are read from
``eval/synthetic`` / ``eval/datasets`` when present, else from ``eval/generated/lab1226/``.
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

SETS = ("v2", "v21", "heldout")


def _lab1226(path: str) -> str:
    """A LAB-1226 fixture: its registry path if present, else a local copy (gitignored)."""
    return path if Path(path).exists() else f"eval/generated/lab1226/{Path(path).name}"


FIXTURES_V21 = (
    "eval/fixtures/hu-smoke.jsonl",
    "eval/fixtures/en-smoke.jsonl",
    "eval/fixtures/de-smoke.jsonl",
    "eval/fixtures/hu-synth-sample.jsonl",
    "eval/fixtures/en-synth-sample.jsonl",
    "eval/fixtures/hu-company-names.jsonl",
    "eval/fixtures/public/hu-ai4privacy.jsonl",
    "eval/fixtures/public/en-ai4privacy.jsonl",
    "eval/fixtures/public/de-ai4privacy.jsonl",
    _lab1226("eval/synthetic/dev/hu-agent-traffic-dev.jsonl"),
    _lab1226("eval/synthetic/dev/en-agent-traffic-dev.jsonl"),
    _lab1226("eval/synthetic/dev/de-agent-traffic-dev.jsonl"),
)
FIXTURES_HELDOUT = (
    _lab1226("eval/synthetic/hu-agent-traffic.jsonl"),
    _lab1226("eval/synthetic/en-agent-traffic.jsonl"),
    _lab1226("eval/synthetic/de-agent-traffic.jsonl"),
    _lab1226("eval/datasets/cee-pii/hu-cee-pii.jsonl"),
    _lab1226("eval/datasets/cee-pii/en-cee-pii.jsonl"),
    _lab1226("eval/datasets/nemotron-pii/en-nemotron-pii.jsonl"),
    _lab1226("eval/datasets/gretel-finance/en-gretel-finance.jsonl"),
    _lab1226("eval/datasets/gretel-finance/de-gretel-finance.jsonl"),
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--candidate", required=True, help="slug, e.g. xlmr-large-v2")
    parser.add_argument("--detectors", required=True, help="rules,ner | rules,ner_gliner | ...")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--only", action="append", help="fixture name filter (repeatable)")
    parser.add_argument("--set", choices=SETS, default="v2", help="fixture list (default v2)")
    args = parser.parse_args(argv)
    fixtures = {"v2": FIXTURES, "v21": FIXTURES_V21, "heldout": FIXTURES_HELDOUT}[args.set]
    register_detector("ner_gliner", "pii_guard.detect.ner_gliner:GlinerDetector", replace=True)
    system = f"fast-{args.candidate}"
    suite.SYSTEMS[system] = args.detectors.split(",")
    status = 0
    for fixture in fixtures:
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
