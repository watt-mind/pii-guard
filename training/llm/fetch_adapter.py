"""Download a LoRA model trained on Fireworks and put it on the Modal adapters volume.

Uses ``GET /v1/accounts/{account}/models/{model}:getDownloadEndpoint`` (signed URLs, one per
file; downloading is not billed) and then ``modal volume put pii-guard-lora-adapters``, where
``deploy/modal/glimmer.py`` serves it from (``GLIMMER_LORA=<model>``). Weights never go into
git: the local copy lives under ``models/`` (ignored).

::

    FIREWORKS_API_KEY=... uv run python training/llm/fetch_adapter.py \\
        --model accounts/<account>/models/pii-guard-glimmer-lab1109-v1 [--no-upload]

The key is read from the environment and never printed; signed URLs are not printed either.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
API = "https://api.fireworks.ai/v1"
VOLUME = "pii-guard-lora-adapters"


def download_urls(model: str, key: str) -> dict[str, str]:
    r = httpx.get(
        f"{API}/{model}:getDownloadEndpoint",
        headers={"Authorization": f"Bearer {key}"},
        timeout=60,
    )
    r.raise_for_status()
    urls = r.json().get("filenameToSignedUrls") or {}
    if not urls:
        raise RuntimeError("the model has no downloadable files (not ready yet?)")
    return urls


def fetch(model: str, out: Path, key: str) -> dict[str, dict[str, int | str]]:
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict[str, int | str]] = {}
    for name, url in sorted(download_urls(model, key).items()):
        rel = Path(name)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("unsafe file name in download listing")
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        with httpx.stream("GET", url, timeout=600, follow_redirects=True) as resp:
            resp.raise_for_status()
            with target.open("wb") as f:
                for block in resp.iter_bytes(1 << 20):
                    f.write(block)
                    h.update(block)
        files[str(target.relative_to(out))] = {
            "bytes": target.stat().st_size,
            "sha256": h.hexdigest(),
        }
        print(f"downloaded {target.relative_to(out)} ({target.stat().st_size} bytes)", flush=True)
    return files


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model", required=True, help="accounts/<account>/models/<id>")
    p.add_argument("--out", type=Path, default=None, help="default: models/llm/<id>")
    p.add_argument("--no-upload", action="store_true", help="skip modal volume put")
    args = p.parse_args(argv)
    key = os.environ.get("FIREWORKS_API_KEY")
    if not key:
        sys.exit("FIREWORKS_API_KEY is not set")
    name = args.model.rsplit("/", 1)[-1]
    out = args.out or ROOT / "models" / "llm" / name
    files = fetch(args.model, out, key)
    (out / "fetch-manifest.json").write_text(
        json.dumps({"model": args.model, "files": files}, indent=2) + "\n", encoding="utf-8"
    )
    if not (out / "adapter_config.json").is_file():
        print("warning: no adapter_config.json; vLLM expects a PEFT adapter directory", flush=True)
    if not args.no_upload:
        subprocess.run(  # noqa: S603 - fixed argument list
            ["modal", "volume", "put", "--force", VOLUME, str(out), f"/{name}"],  # noqa: S607
            check=True,
        )
        print(f"uploaded to modal volume {VOLUME}:/{name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
