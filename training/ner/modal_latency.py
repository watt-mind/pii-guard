"""Run the NER latency gate (``eval_v3.py latency``) on a Modal CPU container (LAB-1512).

LAB-1494 timed its candidates on a Mac with a load average of 30 to 54, which inflates latency
(about 80 ms vs 50 ms in LAB-1494's own note). A Modal container runs nothing else, so the
p95 ratio the gate reads is measured on an idle machine. Every model alternates per message in
one process, as on the Mac. ``v20=`` is the published v2.0, fetched at its pinned revision and
checked against its SHA-256 by ``ner_resolve``; the others are checkpoints on the
``pii-guard-ner-runs`` volume::

    modal run training/ner/modal_latency.py \\
        --models v20=,v33-t1=/runs/pii-guard-ner-xlmr-base-v33-t1 \\
        --json-out eval/results/2026-10-29-ner-v33/latency-cpu.json
    modal app stop pii-guard-ner-latency --yes   # if a run was interrupted

The app is ephemeral (``modal run``): it stops when the function returns.
"""

from __future__ import annotations

import json
from pathlib import Path

import modal

REMOTE = "/root/pii-guard"
ROOT = Path(__file__).resolve().parents[2] if modal.is_local() else Path(REMOTE)
RUNS = "/runs"
CPUS = 8

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
    .add_local_dir(ROOT / "eval" / "fixtures", f"{REMOTE}/eval/fixtures", ignore=["visual"])
)
runs = modal.Volume.from_name("pii-guard-ner-runs")
app = modal.App("pii-guard-ner-latency", image=image)


@app.function(cpu=CPUS, memory=16384, timeout=60 * 60, volumes={RUNS: runs})
def latency(models: list[str], n: int, threads: int) -> dict:
    import os
    import subprocess
    import sys

    os.chdir(REMOTE)
    cmd = [sys.executable, "training/ner/eval_v3.py", "latency", "--n", str(n)]
    cmd += ["--threads", str(threads), "--json", "/tmp/latency.json"]  # noqa: S108
    for spec in models:
        cmd += ["--model", spec]
    subprocess.run(cmd, check=True, env={**os.environ, "PII_GUARD_NER_DEVICE": "cpu"})  # noqa: S603
    report = json.loads(Path("/tmp/latency.json").read_text())  # noqa: S108
    report["host"] = f"Modal CPU container, {CPUS} CPUs requested, nothing else running"
    return report


@app.local_entrypoint()
def main(models: str, json_out: str = "", n: int = 122, threads: int = CPUS) -> None:
    report = latency.remote([m for m in models.split(",") if m], n, threads)
    text = json.dumps(report, indent=2) + "\n"
    print(text)
    if json_out:
        Path(json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(json_out).write_text(text, encoding="utf-8")
