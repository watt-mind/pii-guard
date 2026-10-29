"""Ai4Privacy OpenPII 1M: the existing public sample, registered as the held-out test split.

OpenPII publishes only ``train`` and ``validation`` splits. The evaluation sample
(:mod:`pii_guard.eval.public.ai4privacy`, ``eval/fixtures/public/<lang>-ai4privacy.jsonl``) is
drawn from ``validation``; NER v2 (LAB-1150) trained on rows of ``train`` only, and its
sampler refused any uid or text of this sample (``training/ner/openpii-train-manifest.json``,
``eval_holdout.disjoint``). So ``validation`` is this registry's ``test`` split. The NER v2
checkpoints still saw the same *distribution*, which their run records say.
"""

from __future__ import annotations

from pii_guard.eval.datasets.spec import Dataset
from pii_guard.eval.public import ai4privacy

__all__ = ["DATASET"]

DATASET = Dataset(
    name="ai4privacy",
    title="Ai4Privacy OpenPII 1M",
    homepage=f"https://huggingface.co/datasets/{ai4privacy.DATASET}",
    revision=ai4privacy.REVISION,
    license=ai4privacy.LICENSE,
    license_url="https://creativecommons.org/licenses/by/4.0/",
    attribution=ai4privacy.ATTRIBUTION,
    languages=("hu", "en", "de"),
    source_split="validation",
    split="test",
    synthetic=True,
    commit_rows=True,
    description="short synthetic multilingual PII sentences (the original public sample)",
    sample=dict(ai4privacy.DEFAULT_SAMPLE),
    seed=ai4privacy.DEFAULT_SEED,
    external=tuple(
        str(ai4privacy.DEFAULT_OUT / f"{lang}-ai4privacy.jsonl") for lang in ("hu", "en", "de")
    ),
    manifest_file=str(ai4privacy.DEFAULT_MANIFEST),
    notes=(
        "Fetched and checked by python -m pii_guard.eval.public.ai4privacy (manifest "
        "eval/fixtures/public/ai4privacy-openpii-1m.json).",
        "NER v2 trained on the train split of the same dataset: in distribution for it.",
    ),
)
