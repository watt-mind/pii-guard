"""Publish a trained NER checkpoint to the Hugging Face Hub (LAB-1306).

Uploads only what the ``ner`` detector reads, plus the model card and the provenance:

- ``model.safetensors`` (never a pickle), ``config.json``, ``tokenizer.json``,
  ``tokenizer_config.json``;
- ``training_meta.json`` without anything machine-local (absolute paths, the device): data
  files are named by their repository-relative path and SHA-256 prefix only;
- ``README.md``: the model card (``training/ner/model-card.md``), with the Hub metadata block
  (licence, languages, base model, datasets) in front;
- ``NOTICE``: the licences and the attribution the training data requires.

Then it tags the upload commit (``--tag``) and prints the commit SHA and the weights'
SHA-256, the two values ``pii_guard.detect.ner_resolve.PUBLISHED`` pins. The token comes from
the local Hugging Face login (``hf auth login``); it is never read, printed or passed here::

    uv run --no-sync python training/ner/publish_hf.py models/ner/pii-guard-ner-xlmr-base-v2-hn \\
        --repo watt-mind/pii-guard-ner-xlmr-base --tag v2.0 --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CARD = ROOT / "training" / "ner" / "model-card.md"
FILES = ("model.safetensors", "config.json", "tokenizer.json", "tokenizer_config.json")
#: Keys of training_meta.json that only describe the machine it ran on.
LOCAL_KEYS = ("device",)

FRONT_MATTER = """---
license: apache-2.0
language:
- hu
- en
- de
library_name: transformers
pipeline_tag: token-classification
base_model: FacebookAI/xlm-roberta-base
datasets:
- ai4privacy/pii-masking-openpii-1m
tags:
- pii
- ner
- token-classification
- privacy
- xlm-roberta
---

"""

NOTICE = """pii-guard NER (watt-mind/pii-guard-ner-xlmr-base)
Copyright 2026 the pii-guard contributors

The model weights are licensed under the Apache License, Version 2.0
(https://www.apache.org/licenses/LICENSE-2.0). They were fine-tuned from, and trained on,
the third-party works below, each under its own licence:

- XLM-RoBERTa base (FacebookAI/xlm-roberta-base), MIT licence. Conneau et al. 2020.
- Ai4Privacy OpenPII-1M (ai4privacy/pii-masking-openpii-1m), train split, a seeded sample
  of 5,000 rows per language (hu/en/de). Licence: CC-BY-4.0. Attribution:
  Ai4Privacy / Ai Suisse SA, https://huggingface.co/datasets/ai4privacy/pii-masking-openpii-1m
- Muse Glimmer 30B (Meta open weights, Apache-2.0) wrote and labelled part of the synthetic
  training corpus.
- Hungarian name and place lexicons used to generate fictional training text: KSH (Hungarian
  Central Statistical Office), CC-BY-4.0; street names from OpenStreetMap,
  (c) OpenStreetMap contributors, ODbL 1.0 (non-substantial extract).

No real personal data was used: everything else is fictional, generated text.
"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_meta(meta: Mapping[str, Any], extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """``training_meta.json`` without machine-local values; data paths stay repo-relative."""
    out: dict[str, Any] = {k: v for k, v in meta.items() if k not in LOCAL_KEYS}
    for key in ("train", "dev"):
        files = out.get(key) or {}
        for name in files:
            if Path(name).is_absolute() or name.startswith("~"):
                raise ValueError(f"{key} file {name!r} is not repository-relative")
    out.update(extra or {})
    text = json.dumps(out)
    if str(Path.home()) in text or "/Users/" in text or "/home/" in text:
        raise ValueError("training_meta.json still names a local path")
    return out


def stage(checkpoint: Path, dest: Path, extra_meta: Mapping[str, Any] | None = None) -> Path:
    """Copy the publishable files of ``checkpoint`` into ``dest``; refuse anything else."""
    if any(checkpoint.glob("*.bin")) or any(checkpoint.glob("*.pt")):
        raise ValueError("pickle weights found; only model.safetensors is published")
    for name in FILES:
        if not (checkpoint / name).is_file():
            raise FileNotFoundError(checkpoint / name)
        shutil.copy2(checkpoint / name, dest / name)
    meta_path = checkpoint / "training_meta.json"
    if not meta_path.is_file():
        meta_path = checkpoint.parent / "training_meta.json"  # an epoch-<n> directory
    meta = clean_meta(json.loads(meta_path.read_text(encoding="utf-8")), extra_meta)
    (dest / "training_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (dest / "README.md").write_text(FRONT_MATTER + CARD.read_text(encoding="utf-8"), "utf-8")
    (dest / "NOTICE").write_text(NOTICE, encoding="utf-8")
    return dest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--repo", default="watt-mind/pii-guard-ner-xlmr-base")
    parser.add_argument("--tag", required=True, help="release tag for the upload commit")
    parser.add_argument("--meta", type=Path, help="JSON merged into training_meta.json")
    parser.add_argument("--dry-run", action="store_true", help="stage and list, upload nothing")
    args = parser.parse_args(argv)
    extra = json.loads(args.meta.read_text(encoding="utf-8")) if args.meta else None
    weights = sha256(args.checkpoint / "model.safetensors")
    with tempfile.TemporaryDirectory() as tmp:
        staged = stage(args.checkpoint, Path(tmp), extra)
        for path in sorted(staged.iterdir()):
            print(f"  {path.name:24} {path.stat().st_size:>12,} bytes", file=sys.stderr)
        if args.dry_run:
            print(json.dumps({"repo": args.repo, "weights_sha256": weights}))
            return 0
        from huggingface_hub import HfApi

        api = HfApi()  # the token of the local login; never handled here
        api.create_repo(args.repo, repo_type="model", exist_ok=True)
        commit = api.upload_folder(
            repo_id=args.repo,
            folder_path=str(staged),
            commit_message=f"pii-guard NER {args.tag} (LAB-1306)",
            delete_patterns=["*.bin", "*.pt", "*.pth"],
        )
    sha = commit.oid
    api.create_tag(args.repo, tag=args.tag, revision=sha, tag_message=f"pii-guard NER {args.tag}")
    print(
        json.dumps({"repo": args.repo, "tag": args.tag, "revision": sha, "weights_sha256": weights})
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
