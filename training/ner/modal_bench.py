"""NER latency on one CUDA GPU (Modal), for every candidate on the ``pii-guard-ner-runs`` volume.

Runs ``training/ner/bench_latency.py`` (p50/p95 per ~400-character message) on CUDA and on the
container's CPU, once per checkpoint directory named on the command line (XLM-RoBERTa ones in
the ``ner`` image, GLiNER ones and the zero-shot hub model in the ``gliner`` image, which pins
an older transformers). Results are printed as JSON lines; the app is ephemeral::

    modal run training/ner/modal_bench.py --models pii-guard-ner-xlmr-base-v2,... \\
        --gliner pii-guard-gliner-multi-v2,urchade/gliner_multi-v2.1
"""

from __future__ import annotations

import json
from pathlib import Path

import modal

REMOTE = "/root/pii-guard"
ROOT = Path(__file__).resolve().parents[2] if modal.is_local() else Path(REMOTE)
RUNS = "/runs"
COMMON = ["sentencepiece==0.2.2", "protobuf==7.36.2", "pydantic==2.14.1",
          "pydantic-settings==2.16.1", "httpx==0.28.1"]  # fmt: skip


def _image(*packages: str) -> modal.Image:
    return (
        modal.Image.debian_slim(python_version="3.12")
        .pip_install(*packages, *COMMON)
        .env({"PYTHONPATH": f"{REMOTE}/src", "TOKENIZERS_PARALLELISM": "false"})
        .add_local_dir(
            ROOT / "src" / "pii_guard", f"{REMOTE}/src/pii_guard", ignore=["__pycache__"]
        )
        .add_local_dir(ROOT / "training" / "ner", f"{REMOTE}/training/ner", ignore=["__pycache__"])
        .add_local_dir(ROOT / "eval" / "fixtures", f"{REMOTE}/eval/fixtures")
    )


ner_image = _image("torch==2.14.1", "transformers==5.21.0", "safetensors==0.8.0")
gliner_image = _image("torch==2.14.1", "transformers==5.16.1", "gliner==0.2.29")
runs = modal.Volume.from_name("pii-guard-ner-runs", create_if_missing=True)
app = modal.App("pii-guard-ner-bench")


def _bench(model: str, backend: str) -> dict:
    import os
    import subprocess
    import sys

    os.chdir(REMOTE)
    path = f"{RUNS}/{model}" if Path(f"{RUNS}/{model}").is_dir() else model
    out = subprocess.run(  # noqa: S603 - fixed argument list
        [sys.executable, "training/ner/bench_latency.py", "--model", path,
         "--devices", "cuda,cpu", "--backend", backend, "--n", "200"],
        check=True, capture_output=True, text=True,
    )  # fmt: skip
    report = json.loads(out.stdout)
    report["model"] = model
    import torch

    report["gpu"] = torch.cuda.get_device_name(0)
    return report


@app.function(image=ner_image, gpu="T4", volumes={RUNS: runs}, timeout=1800, cpu=4)
def bench_ner(model: str) -> dict:
    return _bench(model, "transformers")


@app.function(image=gliner_image, gpu="T4", volumes={RUNS: runs}, timeout=1800, cpu=4)
def bench_gliner(model: str) -> dict:
    return _bench(model, "gliner")


@app.local_entrypoint()
def main(models: str = "", gliner: str = "") -> None:
    for m in [x for x in models.split(",") if x]:
        print(json.dumps(bench_ner.remote(m)))
    for m in [x for x in gliner.split(",") if x]:
        print(json.dumps(bench_gliner.remote(m)))
