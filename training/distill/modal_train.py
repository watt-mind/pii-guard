"""Train the NER student (``training/ner/train.py``) on a Modal GPU.

Fictional data only. The labelled corpus files named in the config are uploaded with the job;
the checkpoint is written to the Modal volume ``pii-guard-ner-runs`` and fetched back with
``modal volume get``::

    modal run training/distill/modal_train.py --config training/ner/distilled-base.toml
    modal volume get pii-guard-ner-runs pii-guard-ner-xlmr-base-distilled models/ner/
    modal app stop pii-guard-ner-train --yes   # if a run was interrupted

``--gpu`` picks the card (default ``A10G``; ``L40S`` or ``A100`` for xlm-roberta-large).
The app is ephemeral (``modal run``): it stops when the function returns.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import modal

REMOTE = "/root/pii-guard"
# Inside the container this file is /root/modal_train.py; the repo root only exists locally.
ROOT = Path(__file__).resolve().parents[2] if modal.is_local() else Path(REMOTE)
RUNS = "/runs"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "torch==2.14.1",
        "transformers==5.21.0",
        "tokenizers==0.23.3",
        "safetensors==0.8.0",
        "huggingface-hub==2.3.0",
        "sentencepiece==0.2.2",
        "protobuf==7.36.2",
        "numpy==2.5.4",
        "pydantic==2.14.1",
        "pydantic-settings==2.16.1",
        "httpx==0.28.1",
    )
    .env({"PYTHONPATH": f"{REMOTE}/src", "TOKENIZERS_PARALLELISM": "false"})
    .add_local_dir(ROOT / "src" / "pii_guard", f"{REMOTE}/src/pii_guard", ignore=["__pycache__"])
    .add_local_dir(ROOT / "training" / "ner", f"{REMOTE}/training/ner", ignore=["__pycache__"])
)
runs = modal.Volume.from_name("pii-guard-ner-runs", create_if_missing=True)
app = modal.App("pii-guard-ner-train", image=image)


def _train(config_text: str, files: dict[str, bytes]) -> str:
    import os
    import subprocess
    import sys

    os.chdir(REMOTE)
    for rel, data in files.items():
        path = Path(REMOTE) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    cfg = tomllib.loads(config_text)
    name = Path(cfg["out"]).name
    out = f"{RUNS}/{name}"
    Path("run.toml").write_text(config_text, encoding="utf-8")
    subprocess.run(  # noqa: S603 - fixed argument list
        [
            sys.executable,
            "training/ner/train.py",
            "--config",
            "run.toml",
            "--out",
            out,
            "--device",
            "cuda",
        ],
        check=True,
    )
    runs.commit()
    return name


_kwargs = {
    "timeout": 3 * 60 * 60,
    "volumes": {RUNS: runs},
}


@app.function(gpu="A10G", **_kwargs)
def train_a10g(config_text: str, files: dict[str, bytes]) -> str:
    return _train(config_text, files)


@app.function(gpu="L40S", **_kwargs)
def train_l40s(config_text: str, files: dict[str, bytes]) -> str:
    return _train(config_text, files)


@app.function(gpu="A100", **_kwargs)
def train_a100(config_text: str, files: dict[str, bytes]) -> str:
    return _train(config_text, files)


@app.local_entrypoint()
def main(config: str, gpu: str = "A10G") -> None:
    text = (ROOT / config).read_text(encoding="utf-8")
    cfg = tomllib.loads(text)
    files = {rel: (ROOT / rel).read_bytes() for rel in [*cfg["train"], *cfg["dev"]]}
    fn = {"A10G": train_a10g, "L40S": train_l40s, "A100": train_a100}[gpu.upper()]
    name = fn.remote(text, files)
    print(f"checkpoint on volume pii-guard-ner-runs: {name}")
