"""``datasets run <set> --system fast`` with a local NER checkpoint in place of v2.0 (LAB-1656).

The datasets runner labels every fast-mode record "NER v2.0", whichever checkpoint
``PII_GUARD_NER_MODEL`` points at; the detector entry already names the local model and its
weights hash. This wrapper sets the model and gives the record its own label and run-id tag,
so a candidate's per-document counts (``eval/datasets/results``, which the benchmark report
reads for the leak-by-construction slices of agent traffic) sit next to v2.0's without being
mistaken for them. Evaluation only; scoring is ``pii_guard.eval.datasets.run`` unchanged::

    PII_GUARD_NER_DEVICE=cpu uv run --no-sync python training/ner/datasets_candidate.py \\
        agent-traffic agent-traffic-dev --model models/ner/pii-guard-ner-xlmr-base-v42-b3 \\
        --tag v42-b3 --label "pii-guard fast, NER v4.2 candidate B3 (LAB-1625)"
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("names", nargs="+", help="registered dataset names")
    parser.add_argument("--model", type=Path, required=True, help="checkpoint directory")
    parser.add_argument("--tag", required=True, help="run-id suffix, e.g. v42-b3")
    parser.add_argument("--label", required=True, help="the system label for the records")
    parser.add_argument("--day", help="record date (default: today)")
    args = parser.parse_args(argv)
    os.environ["PII_GUARD_NER_MODEL"] = str(args.model)

    from pii_guard.eval.datasets import get
    from pii_guard.eval.datasets import run as runner

    runner._LABELS["fast"] = args.label  # the one value the runner hard-codes
    for name in args.names:
        summaries = runner.run_dataset(get(name), ["fast"], record=True, day=args.day, tag=args.tag)
        runner.print_summaries(summaries)
    return 0


if __name__ == "__main__":
    sys.exit(main())
