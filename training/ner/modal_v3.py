"""Build the NER v3 training mix (LAB-1393) on Modal: downloads, conversion, teacher audit.

The pinned source files (about 4.8 GB, the OpenPII train split most of it) are downloaded into
the container's own disk, not a volume, and dropped when it stops. Only the converted training
files (``eval/generated/v3``, about 100 MB) and the manifests are written to the
``pii-guard-ner-runs`` volume under ``v3-data/``, then fetched::

    modal run training/ner/modal_v3.py                 # prep (CPU) + teacher audit (A10G)
    modal volume get pii-guard-ner-runs v3-data /tmp/v3-data
    modal app stop pii-guard-ner-v3-data --yes        # if a run was interrupted

Fictional / synthetic data only: every source is a synthetic set (ADR 0005).
"""

from __future__ import annotations

import json
from pathlib import Path

import modal

REMOTE = "/root/pii-guard"
ROOT = Path(__file__).resolve().parents[2] if modal.is_local() else Path(REMOTE)
RUNS = "/runs"
DATA = f"{RUNS}/v3-data"
AUDITED = ("privy", "wismut", "nemotron", "gretel")

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
        "pyarrow==26.0.0",
        "pydantic==2.14.1",
        "pydantic-settings==2.16.1",
        "httpx==0.28.1",
    )
    .env({"PYTHONPATH": f"{REMOTE}/src", "TOKENIZERS_PARALLELISM": "false"})
    .add_local_dir(ROOT / "src" / "pii_guard", f"{REMOTE}/src/pii_guard", ignore=["__pycache__"])
    .add_local_dir(ROOT / "training" / "ner", f"{REMOTE}/training/ner", ignore=["__pycache__"])
    .add_local_dir(ROOT / "eval" / "fixtures", f"{REMOTE}/eval/fixtures", ignore=["visual"])
)
runs = modal.Volume.from_name("pii-guard-ner-runs", create_if_missing=True)
app = modal.App("pii-guard-ner-v3-data", image=image)


@app.function(cpu=4, memory=24576, timeout=2 * 60 * 60, volumes={RUNS: runs})
def prep(s11: dict[str, bytes], only: list[str] | None = None) -> dict:
    import os
    import shutil
    import sys

    os.chdir(REMOTE)
    for rel, data in s11.items():
        path = Path(REMOTE) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    sys.path.insert(0, f"{REMOTE}/training/ner")
    import v3_data

    manifest = v3_data.build(
        Path("/tmp/cache"),  # noqa: S108 - container-local scratch, gone when it stops
        v3_data.OUT,
        only=only,
        tokenizer_name="FacebookAI/xlm-roberta-base",
    )
    out = Path(DATA)
    old = out / v3_data.MANIFEST
    if only and old.exists():  # a partial rebuild: keep the other sources
        merged = json.loads(old.read_text())
        merged["sources"].update(manifest["sources"])
        for k in ("train_token_share",):
            merged.setdefault(k, {}).update(manifest.get(k, {}))
        total = sum(v["tokens"] for v in merged["train_token_share"].values()) or 1
        for v in merged["train_token_share"].values():
            v["share"] = round(v["tokens"] / total, 3)
        manifest = merged
    elif out.exists():
        shutil.rmtree(out)
    v3_data.MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    shutil.copytree(v3_data.OUT, out / "eval/generated/v3", dirs_exist_ok=True)
    for m in (v3_data.MANIFEST, v3_data.OPENPII_MANIFEST):
        if m.exists():
            (out / m).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(m, out / m)
    runs.commit()
    return manifest.get("train_token_share", {})


@app.function(gpu="A10G", memory=16384, timeout=90 * 60, volumes={RUNS: runs})
def audit(only: list[str] | None = None) -> dict:
    import os
    import sys

    os.chdir(REMOTE)
    sys.path.insert(0, f"{REMOTE}/training/ner")
    import v3_teachers

    runs.reload()
    base = Path(DATA) / "eval/generated/v3"
    names = [n for n in AUDITED if not only or n in only]
    paths = [p for name in names for p in sorted((base / name).glob("*-train.jsonl"))]
    runners = [v3_teachers.Runner(t, "cuda") for t in v3_teachers.TEACHERS]
    report = v3_teachers.audit_files(paths, Path(DATA) / "audited", runners)
    report["files"] = {str(Path(k).relative_to(DATA)): v for k, v in report["files"].items()}
    old = Path(DATA) / "audit.json"
    if only and old.exists():
        merged = json.loads(old.read_text())
        merged["files"].update(report["files"])
        report = merged
    old.write_text(json.dumps(report, indent=2) + "\n")
    runs.commit()
    return {k: v["regions_added"] for k, v in report["files"].items()}


@app.local_entrypoint()
def main(step: str = "all", only: str = "") -> None:
    s11 = {
        str(p.relative_to(ROOT)): p.read_bytes()
        for p in sorted((ROOT / "eval/generated/distill-s11/labelled").glob("*-distill-*.jsonl"))
    }
    if step in ("all", "prep"):
        print(json.dumps(prep.remote(s11, [o for o in only.split(",") if o] or None), indent=2))
    if step in ("all", "audit"):
        print(json.dumps(audit.remote([o for o in only.split(",") if o] or None), indent=2))
