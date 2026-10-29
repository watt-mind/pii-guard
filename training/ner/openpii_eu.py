"""OpenPII-1M **train** rows for the multilingual NER phase 1 (LAB-1525): 19 more EU languages.

Same source, conversion, filters, sampler and disjointness check as ``openpii.py`` (the v2.0
rows): the pinned ``data/train.jsonl`` of ``ai4privacy/pii-masking-openpii-1m`` (CC-BY-4.0,
attribution "Ai4Privacy / Ai Suisse SA"), synthetic text. pii-guard evaluates only on its
``validation`` split (``eval/fixtures/public/ai4privacy-openpii-1m.json``), and the sampler
refuses any uid or text of that sample. OpenPII has no Irish or Maltese rows.

Only the manifest is committed (``training/ner/eu-openpii-train-manifest.json``: counts and a
SHA-256 over the chosen uids per language), never rows. The seed is new (1525), so the sample
is not v3's (seed 1393, never shipped) and has no overlap with v2.0's languages. Per language
the first ``dev`` rows are a dev file and the next ``train`` rows the train file; a smaller
mix takes a prefix of the train file (the order is the seeded order), so candidate A's 2,500
rows per language are the first half of candidate B's 5,000::

    curl -L -o data/public/openpii-train/train.jsonl \\
        https://huggingface.co/datasets/ai4privacy/pii-masking-openpii-1m/resolve/<REVISION>/data/train.jsonl
    uv run --no-sync python training/ner/openpii_eu.py \\
        --source data/public/openpii-train/train.jsonl
    uv run --no-sync python training/ner/openpii_eu.py --source ... --check

Writes ``eval/generated/openpii-eu/<lang>-openpii-{train,dev}.jsonl`` (git-ignored).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import openpii

#: OpenPII-1M languages pii-guard has not trained on (v2.0: hu, en, de). No ga, no mt.
LANGUAGES = (
    "lv", "lt", "hr", "sl",
    "fr", "es", "it", "nl", "ro",
    "bg", "cs", "da", "el", "et", "fi", "pl", "pt", "sk", "sv",
)  # fmt: skip
SEED = 1525
TRAIN = 5000
DEV = 100
OUT = Path("eval/generated/openpii-eu")
MANIFEST = Path("training/ner/eu-openpii-train-manifest.json")


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    defaults = [
        "--train", ",".join(f"{lang}={TRAIN}" for lang in LANGUAGES),
        "--dev", ",".join(f"{lang}={DEV}" for lang in LANGUAGES),
        "--seed", str(SEED),
        "--out", str(OUT),
        "--manifest", str(MANIFEST),
    ]  # fmt: skip
    # argparse keeps the last occurrence, so explicit arguments override these defaults.
    return openpii.main(defaults + argv)


if __name__ == "__main__":
    sys.exit(main())
