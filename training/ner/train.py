"""Fine-tune a multilingual encoder for the ``ner`` detector on the synthetic corpus.

Fictional data only (ADR 0005): the train/dev files come from ``pii-guard eval generate``.

::

    uv run --extra ner python training/ner/train.py --config training/ner/config.toml
    uv run --extra ner python training/ner/train.py --device cuda --epochs 6   # one GPU

The output directory is a regular Hugging Face checkpoint (``config.json``, weights,
``tokenizer.json``) with labels named after pii-guard entity types (``B-PERSON``, …) and
``pii_guard_aggregation = "token"``, plus ``training_meta.json`` (data hashes, settings, dev
scores). Point the detector at it with ``PII_GUARD_NER_MODEL=<dir>``. Weights are never
committed (``.gitignore``).

Labelling: every sub-token that overlaps a gold span by at least half of its characters gets
``B-``/``I-`` of the span's type; so a case suffix tokenised apart (``Péter`` + ``t``) stays
outside. The generator labels only the values it supplied, so other names the writing model
added are unlabelled; with ``teacher`` set, tokens that the teacher model (a generic NER
checkpoint) tags as an entity outside every gold span are excluded from the loss instead of
being learned as ``O``. Documents may also carry their own excluded regions in
``meta.loss_ignore`` (``[[start, end], ...]``): the distillation corpus
(``training/distill/label.py``) marks where Muse Glimmer and the planted gold disagree.

``precision = "bf16"`` runs the forward pass under CUDA bf16 autocast (weights and optimiser
stay fp32); ``"fp32"`` (default) everywhere else.
"""

# Seeded shuffling, not cryptography.
# ruff: noqa: S311

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import time
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForTokenClassification, AutoTokenizer

from pii_guard.detect.ner import RawEntity, TransformersBackend, decode_tokens
from pii_guard.eval.fixtures import Document, load_fixtures

#: The v1 label set (LAB-1106, LAB-1128): what the NER found before LAB-1150.
TYPES_V1 = ("PERSON", "ADDRESS", "ORGANIZATION", "DATE_OF_BIRTH")
#: The v2 label set (LAB-1150): v1 plus the identifier types, named after pii-guard entity
#: types so the checkpoint's labels map 1:1 (docs/entities.md, "NER label set").
TYPES_V2 = (
    *TYPES_V1,
    "EMAIL",
    "PHONE",
    "ID_DOCUMENT",
    "NATIONAL_ID_HU_TAX",
    "NATIONAL_ID_HU_TAJ",
    "BANK_ACCOUNT",
)
TYPES = TYPES_V2
IGNORE = -100


def label_list(types: Sequence[str]) -> list[str]:
    return ["O"] + [f"{p}-{t}" for t in types for p in ("B", "I")]


LABELS = label_list(TYPES)
LABEL2ID = {label: i for i, label in enumerate(LABELS)}


def set_types(types: Sequence[str]) -> None:
    """Switch the module's label set (``types`` in the config)."""
    global TYPES, LABELS, LABEL2ID
    TYPES = tuple(types)
    LABELS = label_list(TYPES)
    LABEL2ID = {label: i for i, label in enumerate(LABELS)}


DEFAULTS: dict[str, Any] = {
    "base_model": "FacebookAI/xlm-roberta-base",
    "base_revision": None,
    "train": [
        "eval/generated/ner-s7/hu-synth-train.jsonl",
        "eval/generated/ner-s7/en-synth-train.jsonl",
    ],
    "dev": ["eval/generated/ner-s7/hu-synth-dev.jsonl", "eval/generated/ner-s7/en-synth-dev.jsonl"],
    "out": "models/ner/pii-guard-ner-xlmr-base",
    "teacher": "Davlan/xlm-roberta-base-ner-hrl",
    "teacher_threshold": 0.6,
    "epochs": 5,
    "batch_size": 8,
    "lr": 5e-5,
    "weight_decay": 0.01,
    "warmup": 0.1,
    "max_length": 512,
    "stride": 128,
    "seed": 13,
    "device": "auto",
    "precision": "fp32",
    # v2 (LAB-1150): the label set, and what to do with gold spans of other types: "ignore"
    # keeps their tokens out of the loss (a phone number is not taught as "O" just because
    # the model doesn't predict phones); "o" is the v1 behaviour.
    "types": list(TYPES_V2),
    "other_types": "ignore",
    # Batches of similar length (less padding): sort within pools of this many batches.
    "length_pool": 50,
    # v2.1 (LAB-1306): also save every epoch to <out>/epoch-<n>, for selection on held-out
    # sets after training (the dev split picks the top-level checkpoint as before).
    "save_epochs": False,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def pick_device(name: str) -> str:
    if name != "auto":
        return name
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def token_labels(
    offsets: Sequence[tuple[int, int]],
    spans: Sequence[tuple[int, int, str]],
    ignore: Sequence[tuple[int, int]] = (),
) -> list[int]:
    """Gold BIO label id per token (``IGNORE`` for special tokens and ignored regions)."""
    out: list[int] = []
    previous: tuple[int, int, str] | None = None
    for start, end in offsets:
        if end <= start:
            out.append(IGNORE)
            previous = None
            continue
        hit = None
        for span in spans:
            overlap = min(end, span[1]) - max(start, span[0])
            if overlap > 0 and overlap * 2 >= end - start:
                hit = span
                break
        if hit is None:
            unsure = any(min(end, e) > max(start, s) for s, e in ignore)
            out.append(IGNORE if unsure else LABEL2ID["O"])
            previous = None
            continue
        prefix = "I" if previous == hit else "B"
        out.append(LABEL2ID[f"{prefix}-{hit[2]}"])
        previous = hit
    return out


def teacher_regions(teacher: TransformersBackend | None, doc: Document, threshold: float):
    """Teacher entities that overlap no gold span (unlabelled, probably real entities)."""
    if teacher is None:
        return []
    found: list[RawEntity] = teacher.predict(doc.text)
    regions = []
    for e in found:
        if e.label not in ("PER", "ORG", "LOC") or e.score < threshold:
            continue
        if not any(s.start < e.end and e.start < s.end for s in doc.spans):
            regions.append((e.start, e.end))
    return regions


def encode(tokenizer, docs: Sequence[Document], cfg: dict[str, Any], teacher=None):
    features: list[dict[str, list[int]]] = []
    ignored = 0
    for doc in docs:
        spans = [
            (s.start, s.end, s.entity_type.value) for s in doc.spans if s.entity_type.value in TYPES
        ]
        ignore = teacher_regions(teacher, doc, cfg["teacher_threshold"])
        if cfg.get("other_types", "ignore") == "ignore":
            ignore += [(s.start, s.end) for s in doc.spans if s.entity_type.value not in TYPES]
        ignore += [(int(s), int(e)) for s, e in doc.meta.get("loss_ignore", ())]
        ignored += len(ignore)
        enc = tokenizer(
            doc.text,
            return_offsets_mapping=True,
            return_overflowing_tokens=True,
            truncation=True,
            max_length=cfg["max_length"],
            stride=cfg["stride"],
        )
        for i in range(len(enc["input_ids"])):
            features.append(
                {
                    "input_ids": enc["input_ids"][i],
                    "attention_mask": enc["attention_mask"][i],
                    "labels": token_labels(enc["offset_mapping"][i], spans, ignore),
                }
            )
    return features, ignored


def batch_order(lengths: Sequence[int], batch_size: int, rng: random.Random, pool: int):
    """Shuffled batches of similar length: shuffle, sort within pools, shuffle the batches."""
    order = list(range(len(lengths)))
    rng.shuffle(order)
    size = max(pool, 1) * batch_size
    out: list[list[int]] = []
    for i in range(0, len(order), size):
        chunk = sorted(order[i : i + size], key=lambda j: lengths[j])
        out.extend(chunk[k : k + batch_size] for k in range(0, len(chunk), batch_size))
    rng.shuffle(out)
    return out


def batches(features, batch_size: int, pad_id: int, rng: random.Random | None, pool: int = 0):
    if rng is not None and pool > 0:
        groups = batch_order([len(f["input_ids"]) for f in features], batch_size, rng, pool)
    else:
        order = list(range(len(features)))
        if rng is not None:
            rng.shuffle(order)
        groups = [order[i : i + batch_size] for i in range(0, len(order), batch_size)]
    for group in groups:
        chunk = [features[j] for j in group]
        width = max(len(f["input_ids"]) for f in chunk)
        yield {
            "input_ids": torch.tensor(
                [f["input_ids"] + [pad_id] * (width - len(f["input_ids"])) for f in chunk]
            ),
            "attention_mask": torch.tensor(
                [f["attention_mask"] + [0] * (width - len(f["attention_mask"])) for f in chunk]
            ),
            "labels": torch.tensor(
                [f["labels"] + [IGNORE] * (width - len(f["labels"])) for f in chunk]
            ),
        }


def span_f1(
    model, tokenizer, docs: Sequence[Document], device: str, cfg: dict[str, Any]
) -> dict[str, Any]:
    """Exact and overlap span P/R/F1 over the dev documents (every type in ``TYPES``)."""
    tp_exact = tp_overlap_pred = tp_overlap_gold = n_pred = n_gold = 0
    per_type: dict[str, list[int]] = {t: [0, 0, 0, 0] for t in TYPES}  # pred, gold, tp_p, tp_g
    model.eval()
    with torch.inference_mode():
        for doc in docs:
            enc = tokenizer(
                doc.text,
                return_offsets_mapping=True,
                return_overflowing_tokens=True,
                truncation=True,
                max_length=cfg["max_length"],
                stride=cfg["stride"],
                padding=True,
                return_tensors="pt",
            )
            offsets = enc.pop("offset_mapping").tolist()
            enc.pop("overflow_to_sample_mapping", None)
            word_ids = [enc.word_ids(i) for i in range(len(offsets))]
            probs = torch.softmax(
                model(**{k: v.to(device) for k, v in enc.items()}).logits.float(), -1
            )
            best, ids = (t.cpu().tolist() for t in probs.max(-1))
            pred: set[tuple[int, int, str]] = set()
            for w in range(len(offsets)):
                for e in decode_tokens(
                    [tuple(o) for o in offsets[w]],
                    word_ids[w],
                    [LABELS[i] for i in ids[w]],
                    best[w],
                    aggregation="token",
                ):
                    pred.add((e.start, e.end, e.label))
            gold = {
                (s.start, s.end, s.entity_type.value)
                for s in doc.spans
                if s.entity_type.value in TYPES
            }
            n_pred += len(pred)
            n_gold += len(gold)
            tp_exact += len(pred & gold)
            tp_overlap_pred += sum(
                any(p[2] == g[2] and p[0] < g[1] and g[0] < p[1] for g in gold) for p in pred
            )
            tp_overlap_gold += sum(
                any(p[2] == g[2] and p[0] < g[1] and g[0] < p[1] for p in pred) for g in gold
            )
            for p in pred:
                row = per_type[p[2]]
                row[0] += 1
                row[2] += any(p[2] == g[2] and p[0] < g[1] and g[0] < p[1] for g in gold)
            for g in gold:
                row = per_type[g[2]]
                row[1] += 1
                row[3] += any(p[2] == g[2] and p[0] < g[1] and g[0] < p[1] for p in pred)
    model.train()

    def f1(p: float, r: float) -> float:
        return 2 * p * r / (p + r) if p + r else 0.0

    pe, re_ = tp_exact / max(n_pred, 1), tp_exact / max(n_gold, 1)
    po, ro = tp_overlap_pred / max(n_pred, 1), tp_overlap_gold / max(n_gold, 1)
    return {
        "pred": n_pred,
        "gold": n_gold,
        "f1_exact": round(f1(pe, re_), 4),
        "p_overlap": round(po, 4),
        "r_overlap": round(ro, 4),
        "f1_overlap": round(f1(po, ro), 4),
        "per_type_f1_overlap": {
            t: round(f1(r[2] / max(r[0], 1), r[3] / max(r[1], 1)), 4)
            for t, r in per_type.items()
            if r[0] or r[1]
        },
    }


def load_config(argv: Sequence[str] | None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", type=Path, help="TOML file (keys as in DEFAULTS)")
    parser.add_argument("--base-model")
    parser.add_argument("--out")
    parser.add_argument("--train", action="append")
    parser.add_argument("--dev", action="append")
    parser.add_argument("--teacher", help="teacher model id, or 'none'")
    parser.add_argument("--epochs", type=int)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--lr", type=float)
    parser.add_argument("--device")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--precision", choices=("fp32", "bf16"))
    args = parser.parse_args(argv)
    cfg = dict(DEFAULTS)
    if args.config:
        cfg.update(tomllib.loads(args.config.read_text(encoding="utf-8")))
    for key, value in vars(args).items():
        if key != "config" and value is not None:
            cfg[key] = value
    if str(cfg.get("teacher") or "none").lower() == "none":
        cfg["teacher"] = None
    return cfg


def main(argv: Sequence[str] | None = None) -> int:
    cfg = load_config(argv)
    set_types(cfg["types"])
    random.seed(cfg["seed"])
    torch.manual_seed(cfg["seed"])
    device = pick_device(cfg["device"])
    train_paths = [Path(p) for p in cfg["train"]]
    dev_paths = [Path(p) for p in cfg["dev"]]
    train_docs, dev_docs = load_fixtures(train_paths), load_fixtures(dev_paths)
    print(f"train docs {len(train_docs)}, dev docs {len(dev_docs)}, device {device}", flush=True)

    tokenizer = AutoTokenizer.from_pretrained(
        cfg["base_model"], revision=cfg["base_revision"], use_fast=True
    )
    teacher = None
    if cfg["teacher"]:
        teacher = TransformersBackend(cfg["teacher"], device="cpu", aggregation="first")
    started = time.perf_counter()
    train_features, ignored = encode(tokenizer, train_docs, cfg, teacher)
    print(f"train windows {len(train_features)}, teacher-ignored regions {ignored}", flush=True)
    del teacher

    model = AutoModelForTokenClassification.from_pretrained(
        cfg["base_model"],
        revision=cfg["base_revision"],
        num_labels=len(LABELS),
        id2label=dict(enumerate(LABELS)),
        label2id=LABEL2ID,
        ignore_mismatched_sizes=True,
        use_safetensors=True,  # never unpickle pytorch_model.bin (LAB-1304)
    ).to(device)
    no_decay = ("bias", "LayerNorm.weight", "layer_norm")
    groups = [
        {
            "params": [p for n, p in model.named_parameters() if not any(k in n for k in no_decay)],
            "weight_decay": cfg["weight_decay"],
        },
        {
            "params": [p for n, p in model.named_parameters() if any(k in n for k in no_decay)],
            "weight_decay": 0.0,
        },
    ]
    optimizer = torch.optim.AdamW(groups, lr=cfg["lr"])
    steps = cfg["epochs"] * math.ceil(len(train_features) / cfg["batch_size"])
    warmup = int(steps * cfg["warmup"])
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda s: (
            s / max(warmup, 1) if s < warmup else max(0.0, (steps - s) / max(steps - warmup, 1))
        ),
    )
    rng = random.Random(cfg["seed"])
    out = Path(cfg["out"])
    best: dict[str, Any] | None = None
    history = []
    autocast = cfg["precision"] == "bf16" and device == "cuda"
    model.train()
    for epoch in range(1, cfg["epochs"] + 1):
        total, n = 0.0, 0
        for batch in batches(
            train_features, cfg["batch_size"], tokenizer.pad_token_id, rng, cfg["length_pool"]
        ):
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=autocast):
                loss = model(**{k: v.to(device) for k, v in batch.items()}).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()
            total += loss.item()
            n += 1
        scores = span_f1(model, tokenizer, dev_docs, device, cfg)
        scores.update(
            epoch=epoch,
            loss=round(total / max(n, 1), 4),
            minutes=round((time.perf_counter() - started) / 60, 1),
        )
        history.append(scores)
        print(json.dumps(scores), flush=True)
        model.config.pii_guard_aggregation = "token"
        model.config.pii_guard_labels = list(TYPES)
        if cfg["save_epochs"]:
            model.save_pretrained(out / f"epoch-{epoch}")
            tokenizer.save_pretrained(out / f"epoch-{epoch}")
        if (
            best is None
            or scores["f1_overlap"] + scores["f1_exact"] > best["f1_overlap"] + best["f1_exact"]
        ):
            best = scores
            model.save_pretrained(out)
            tokenizer.save_pretrained(out)

    meta = {
        "base_model": cfg["base_model"],
        "base_revision": cfg["base_revision"],
        "teacher": cfg["teacher"],
        "labels": LABELS,
        "settings": {
            k: cfg[k]
            for k in (
                "epochs",
                "batch_size",
                "lr",
                "weight_decay",
                "warmup",
                "max_length",
                "stride",
                "seed",
                "teacher_threshold",
                "precision",
                "other_types",
                "length_pool",
                "save_epochs",
            )
        },
        "types": list(TYPES),
        "device": device,
        "train": {str(p): sha256(p) for p in train_paths},
        "dev": {str(p): sha256(p) for p in dev_paths},
        "train_docs": len(train_docs),
        "train_windows": len(train_features),
        "best": best,
        "history": history,
        "minutes": round((time.perf_counter() - started) / 60, 1),
    }
    (out / "training_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"saved {out} (best epoch {best['epoch'] if best else '-'})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
