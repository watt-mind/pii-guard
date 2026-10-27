"""Fine-tune GLiNER multi (``training/gliner/train_gliner.py``) on a Modal GPU (LAB-1150).

The data files named in the config are uploaded with the job; the checkpoint goes to the Modal
volume ``pii-guard-ner-runs`` (fetch it with ``modal volume get``). The app is ephemeral
(``modal run``) and stops when the function returns::

    modal run training/gliner/modal_train_gliner.py --config training/gliner/gliner-multi.toml
    modal volume get pii-guard-ner-runs pii-guard-gliner-multi-v2 models/ner/
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import modal

REMOTE = "/root/pii-guard"
ROOT = Path(__file__).resolve().parents[2] if modal.is_local() else Path(REMOTE)
RUNS = "/runs"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "torch==2.14.1",
        "transformers==5.16.1",
        "gliner==0.2.29",
        "accelerate==1.15.0",
        "sentencepiece==0.2.2",
        "protobuf==7.36.2",
        "pydantic==2.14.1",
        "pydantic-settings==2.16.1",
        "httpx==0.28.1",
    )
    .env({"PYTHONPATH": f"{REMOTE}/src", "TOKENIZERS_PARALLELISM": "false"})
    .add_local_dir(ROOT / "src" / "pii_guard", f"{REMOTE}/src/pii_guard", ignore=["__pycache__"])
    .add_local_dir(
        ROOT / "training" / "gliner", f"{REMOTE}/training/gliner", ignore=["__pycache__"]
    )
)
runs = modal.Volume.from_name("pii-guard-ner-runs", create_if_missing=True)
app = modal.App("pii-guard-gliner-train", image=image)


@app.function(gpu="A10G", timeout=2 * 60 * 60, volumes={RUNS: runs})
def train(config_text: str, files: dict[str, bytes]) -> str:
    import os
    import subprocess
    import sys

    os.chdir(REMOTE)
    for rel, data in files.items():
        path = Path(REMOTE) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    name = Path(tomllib.loads(config_text)["out"]).name
    Path("run.toml").write_text(config_text, encoding="utf-8")
    subprocess.run(  # noqa: S603 - fixed argument list
        [
            sys.executable,
            "training/gliner/train_gliner.py",
            "--config",
            "run.toml",
            "--out",
            f"/tmp/{name}",  # noqa: S108 - container scratch
            "--device",
            "cuda",
        ],
        check=True,
    )
    subprocess.run(["cp", "-r", f"/tmp/{name}", f"{RUNS}/{name}"], check=True)  # noqa: S603,S607,S108
    runs.commit()
    return name


@app.local_entrypoint()
def main(config: str) -> None:
    text = (ROOT / config).read_text(encoding="utf-8")
    cfg = tomllib.loads(text)
    files = {rel: (ROOT / rel).read_bytes() for rel in [*cfg["train"], *cfg["dev"]]}
    name = train.remote(text, files)
    print(f"checkpoint on volume pii-guard-ner-runs: {name}")
