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

    uv run --no-sync python training/ner/publish_hf.py models/ner/pii-guard-ner-xlmr-base-v42-b3 \\
        --repo watt-mind/pii-guard-ner-xlmr-base --tag v4.2 --dry-run --stage-dir /tmp/v42-stage
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
- bg
- cs
- da
- el
- es
- et
- fi
- fr
- ga
- hr
- it
- lt
- lv
- mt
- nl
- pl
- pt
- ro
- sk
- sl
- sv
library_name: transformers
pipeline_tag: token-classification
base_model: FacebookAI/xlm-roberta-base
datasets:
- ai4privacy/pii-masking-openpii-1m
- DataikuNLP/kiji-pii-training-data
- Wismut/nym-pii-multilingual-data
- E3-JSI/synthetic-multi-pii-ner-v1
- subhash-holla/pii-anon
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
(https://www.apache.org/licenses/LICENSE-2.0). v4.2 is fine-tuned from v2.0 (revision
95f612a9ad65cc5ade5b9248bd152020541e7097), itself fine-tuned from XLM-RoBERTa base. Between
them they were trained on the third-party works below, each under its own licence:

- XLM-RoBERTa base (FacebookAI/xlm-roberta-base), MIT licence. Conneau et al. 2020.
- Ai4Privacy OpenPII-1M (ai4privacy/pii-masking-openpii-1m), train split: a seeded sample
  of 5,000 rows per language for hu/en/de (v2.0) and 2,500 rows per language for 19 more EU
  languages (v4.2). Licence: CC-BY-4.0. Attribution: Ai4Privacy / Ai Suisse SA,
  https://huggingface.co/datasets/ai4privacy/pii-masking-openpii-1m
- DataikuNLP/kiji-pii-training-data, Apache-2.0. Attribution: Dataiku,
  https://huggingface.co/datasets/DataikuNLP/kiji-pii-training-data
- Wismut/nym-pii-multilingual-data, MIT licence. Attribution: Wismut (byteowlz),
  https://huggingface.co/datasets/Wismut/nym-pii-multilingual-data
- E3-JSI/synthetic-multi-pii-ner-v1, MIT licence (healthcare rows dropped). Attribution:
  E3, Jozef Stefan Institute, https://huggingface.co/datasets/E3-JSI/synthetic-multi-pii-ner-v1
- subhash-holla/pii-anon, CC0-1.0 (rows holding an ID only; curated_public and clinical rows
  excluded), https://huggingface.co/datasets/subhash-holla/pii-anon
- Muse Spark (Meta Model API) wrote the fictional EU-language documents, the court-style
  documents and the error-mined variants around planted fictional values; Muse Glimmer 30B
  (Meta open weights, Apache-2.0) wrote and labelled part of the v2.0 synthetic corpus and
  labelled the EU, court-style and variant documents. The generators are pii-guard's own
  (Apache-2.0).
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


#: Where ``modal_train.py`` mounts the data root (``training/distill/modal_train.py#DATA``).
MODAL_DATA_ROOT = "/root/data/"


def _data_ref(name: str) -> str:
    """A Modal data-root path as the config names it: ``data:<corpus>/<file>`` (LAB-1542)."""
    return "data:" + name[len(MODAL_DATA_ROOT) :] if name.startswith(MODAL_DATA_ROOT) else name


def clean_meta(meta: Mapping[str, Any], extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """``training_meta.json`` without machine-local values; data paths stay repo-relative."""
    out: dict[str, Any] = {k: v for k, v in meta.items() if k not in LOCAL_KEYS}
    for key in ("train", "dev", "report_dev"):
        files = out.get(key) or {}
        if key in out and isinstance(files, dict):  # Modal data root -> data:<corpus>/...
            files = {_data_ref(name): digest for name, digest in files.items()}
            out[key] = files
        for name in files:
            if Path(name).is_absolute() or name.startswith("~"):
                raise ValueError(f"{key} file {name!r} is not repository-relative")
    decontam = out.get("decontam")
    if isinstance(decontam, dict) and isinstance(decontam.get("files"), dict):
        out["decontam"] = {
            **decontam,
            "files": {_data_ref(name): v for name, v in decontam["files"].items()},
        }
    out.update(extra or {})
    text = json.dumps(out)
    if MODAL_DATA_ROOT in text:
        raise ValueError("training_meta.json still names a Modal data-root path")
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
    parser.add_argument(
        "--stage-dir", type=Path, help="stage here and keep it (default: a temporary directory)"
    )
    args = parser.parse_args(argv)
    extra = json.loads(args.meta.read_text(encoding="utf-8")) if args.meta else None
    weights = sha256(args.checkpoint / "model.safetensors")
    with tempfile.TemporaryDirectory() as tmp:
        staged = stage(args.checkpoint, args.stage_dir or Path(tmp), extra)
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
            commit_message=f"pii-guard NER {args.tag}",
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
