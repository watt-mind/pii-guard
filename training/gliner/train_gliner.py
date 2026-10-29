"""Fine-tune GLiNER multi on the same data as the XLM-RoBERTa students (LAB-1150).

Fictional and public-synthetic data only: the distillation corpus (``training/distill/``) and
the Ai4Privacy OpenPII **train** rows (``training/ner/openpii.py``). Documents are converted
to GLiNER's format, words plus ``[first_word, last_word, label]`` triples, with the label
names of :data:`pii_guard.detect.ner_gliner.GLINER_LABELS` (so the fine-tuned model is asked
the same questions as the zero-shot one). Long documents become overlapping windows of
:data:`WINDOW` words. GLiNER has no "ignore" label: regions in ``meta.loss_ignore`` (teacher
disagreements) can't be excluded from the loss, so a window that contains one is dropped
instead; OpenPII's ignored dates (in two thirds of its rows) are left unlabelled.

::

    UV_PROJECT_ENVIRONMENT=.venv-gliner uv run --extra gliner \\
        python training/gliner/train_gliner.py \\
        --config training/gliner/gliner-multi.toml            # needs accelerate, see Modal
    modal run training/gliner/modal_train_gliner.py --config training/gliner/gliner-multi.toml
"""

# Seeded shuffling, not cryptography.
# ruff: noqa: S311

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pii_guard.detect.ner_gliner import GLINER_LABELS, safetensors_checkpoint
from pii_guard.eval.fixtures import Document, load_fixtures

WINDOW = 200
STRIDE = 160
#: GLiNER's default word splitter.
_WORD = re.compile(r"\w+(?:[-_]\w+)*|\S")
TYPE_TO_LABEL = {t.value: name for name, t in GLINER_LABELS.items()}


def to_examples(doc: Document) -> tuple[list[dict[str, Any]], int]:
    """GLiNER examples for ``doc`` and the number of windows dropped for ignored regions."""
    words = [m.span() for m in _WORD.finditer(doc.text)]
    spans = []
    for s in doc.spans:
        label = TYPE_TO_LABEL.get(s.entity_type.value)
        if label is None:
            continue
        idx = [i for i, (a, b) in enumerate(words) if a < s.end and s.start < b]
        if idx:
            spans.append((idx[0], idx[-1], label))
    ignore = [(int(a), int(b)) for a, b in doc.meta.get("loss_ignore", ())]
    if doc.meta.get("kind") == "public-ai4privacy-train":
        ignore = []  # its ignored regions are dates: left unlabelled rather than dropped
    # Gold spans of types GLiNER isn't asked for (plates, parcels...) are ignored too.
    ignore += [(s.start, s.end) for s in doc.spans if s.entity_type.value not in TYPE_TO_LABEL]
    out: list[dict[str, Any]] = []
    dropped = 0
    start = 0
    while start < len(words):
        end = min(start + WINDOW, len(words))
        lo, hi = words[start][0], words[end - 1][1]
        if any(a < hi and lo < b for a, b in ignore):
            dropped += 1
        else:
            ner = [[a - start, b - start, label] for a, b, label in spans if a >= start and b < end]
            out.append({"tokenized_text": [doc.text[a:b] for a, b in words[start:end]], "ner": ner})
        if end == len(words):
            break
        start += STRIDE
    return out, dropped


def load_config(argv: Sequence[str] | None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out")
    parser.add_argument("--device", default="auto")
    args = parser.parse_args(argv)
    cfg = tomllib.loads(args.config.read_text(encoding="utf-8"))
    if args.out:
        cfg["out"] = args.out
    cfg["device"] = args.device
    return cfg


def main(argv: Sequence[str] | None = None) -> int:
    cfg = load_config(argv)
    import torch
    from gliner import GLiNER

    rng = random.Random(cfg.get("seed", 13))
    train: list[dict[str, Any]] = []
    dropped = 0
    for path in cfg["train"]:
        for doc in load_fixtures([Path(path)]):
            examples, n = to_examples(doc)
            train.extend(examples)
            dropped += n
    rng.shuffle(train)
    dev: list[dict[str, Any]] = []
    for path in cfg["dev"]:
        for doc in load_fixtures([Path(path)]):
            dev.extend(to_examples(doc)[0])
    print(f"train examples {len(train)} (windows dropped {dropped}), dev {len(dev)}", flush=True)

    started = time.perf_counter()
    # safetensors only (LAB-1304): load the checkpoint directory fetched without pickles.
    base = safetensors_checkpoint(cfg["base_model"], revision=cfg.get("base_revision"))
    model = GLiNER.from_pretrained(base)
    use_cuda = torch.cuda.is_available() and cfg["device"] in ("auto", "cuda")
    steps = int(cfg["epochs"] * len(train) / cfg["batch_size"])
    model.train_model(
        train_dataset=train,
        eval_dataset=dev,
        output_dir=cfg["out"] + "-trainer",
        learning_rate=cfg["lr"],
        others_lr=cfg["others_lr"],
        weight_decay=0.01,
        others_weight_decay=0.01,
        per_device_train_batch_size=cfg["batch_size"],
        per_device_eval_batch_size=cfg["batch_size"],
        max_steps=steps,
        warmup_ratio=0.1,
        focal_loss_alpha=cfg.get("focal_loss_alpha", 0.75),
        focal_loss_gamma=cfg.get("focal_loss_gamma", 2.0),
        negatives=1.0,
        bf16=use_cuda,
        use_cpu=not use_cuda and cfg["device"] == "cpu",
        save_steps=10**9,
        save_total_limit=1,
        logging_steps=100,
        dataloader_num_workers=2,
        report_to="none",
        seed=cfg.get("seed", 13),
    )
    out = Path(cfg["out"])
    model.save_pretrained(out)
    meta = {
        "base_model": cfg["base_model"],
        "base_revision": cfg.get("base_revision"),
        "labels": list(GLINER_LABELS),
        "train": cfg["train"],
        "dev": cfg["dev"],
        "train_examples": len(train),
        "windows_dropped_for_ignored_regions": dropped,
        "steps": steps,
        "settings": {k: cfg[k] for k in ("epochs", "batch_size", "lr", "others_lr")},
        "minutes": round((time.perf_counter() - started) / 60, 1),
    }
    (out / "training_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"saved {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
