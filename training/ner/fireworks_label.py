"""Glimmer teacher pass on a Fireworks on-demand deployment, deleted when done (LAB-1539).

The Modal path (``modal_eu_label.py``) runs vLLM in a Modal container; when Modal credit is
short, this runs the same ``training/distill/label.py`` against Muse Glimmer 30B (base model,
no LoRA) on a Fireworks on-demand deployment instead (``docs/models.md``, option b): one
H200, BF16, scale-to-zero, billed per GPU-second. One deployment session labels every corpus
folder given, one after the other, and the deployment is **deleted in a ``finally``** whatever
happens (the deletion is checked and printed). A cost guard stops labelling when the elapsed
deployment time reaches ``--cap-usd`` at ``--usd-per-hour``.

Only fictional, synthetic corpus files are sent (``modal_upload.check_payload``, LAB-1419). The
key is read from ``FIREWORKS_API_KEY`` and never printed::

    set -a; source .env; set +a
    uv run --no-sync python training/ner/fireworks_label.py \\
        --corpus ~/Develop/.worktrees/pii-guard/data-eu/v41/court \\
        --corpus ~/Develop/.worktrees/pii-guard/data-eu/v41/variants --cap-usd 25
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
API = "https://api.fireworks.ai/v1"
INFERENCE = "https://api.fireworks.ai/inference/v1"
BASE_MODEL = "accounts/fireworks/models/muse-glimmer-30b"
#: Fireworks' public shape "Muse Glimmer 30B BF16 1x H200" (as the LAB-1109 eval).
SHAPE = "accounts/fireworks/deploymentShapes/dkuwotf7"


def _client() -> httpx.Client:
    key = os.environ.get("FIREWORKS_API_KEY")
    if not key:
        raise SystemExit("FIREWORKS_API_KEY is not set")
    return httpx.Client(headers={"Authorization": f"Bearer {key}"}, timeout=60)


def check_corpus(corpus: Path) -> list[Path]:
    sys.path.insert(0, str(ROOT / "training" / "distill"))
    from modal_upload import check_payload

    files = sorted(corpus.glob("*-distill-*.jsonl"))
    check_payload([f"corpora/{corpus.parent.name}/{corpus.name}/{p.name}" for p in files])
    for p in files:
        for line in p.open(encoding="utf-8"):
            meta = json.loads(line).get("meta", {})
            if meta.get("source") != "synthetic":
                raise SystemExit(f"{p.name}: a document is not marked synthetic")
    return files


def create(
    api: httpx.Client, account: str, deployment_id: str, *, validate_only: bool = False
) -> dict[str, Any]:
    body = {
        "displayName": f"pii-guard {deployment_id}",
        "baseModel": BASE_MODEL,
        "deploymentShape": SHAPE,
        "minReplicaCount": 0,
        "maxReplicaCount": 1,
        "autoscalingPolicy": {"scaleToZeroWindow": "300s"},
    }
    params = {"deploymentId": deployment_id}
    if validate_only:
        params["validateOnly"] = "true"
    r = api.post(f"{API}/{account}/deployments", params=params, json=body)
    if r.status_code >= 400:
        raise SystemExit(f"create failed: HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def delete(api: httpx.Client, name: str) -> str:
    """Delete the deployment and return its final state as seen by a GET."""
    for _ in range(5):
        r = api.delete(f"{API}/{name}", params={"ignoreChecks": "true"})
        if r.status_code < 400 or r.status_code == 404:
            break
        time.sleep(10)
    for _ in range(30):
        g = api.get(f"{API}/{name}")
        if g.status_code == 404:
            return "deleted (404)"
        state = g.json().get("state", "?")
        if state in ("DELETED", "DELETING"):
            return state
        time.sleep(10)
    return f"still {state}: DELETE BY HAND"


def warm_up(model: str, deadline_s: float = 1800) -> float:
    key = os.environ["FIREWORKS_API_KEY"]
    started = time.monotonic()
    body = {"model": model, "messages": [{"role": "user", "content": "ok"}], "max_tokens": 8,
            "reasoning_effort": "low"}  # fmt: skip
    with httpx.Client(headers={"Authorization": f"Bearer {key}"}, timeout=120) as c:
        while time.monotonic() - started < deadline_s:
            try:
                r = c.post(f"{INFERENCE}/chat/completions", json=body)
                if r.status_code == 200:
                    return time.monotonic() - started
            except httpx.HTTPError:
                pass
            time.sleep(15)
    raise SystemExit("deployment did not serve within the deadline")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--corpus", type=Path, action="append", required=True)
    parser.add_argument("--account", default="accounts/hdkiller")
    parser.add_argument("--deployment-id", default=f"pii-guard-label-{int(time.time())}")
    parser.add_argument("--cap-usd", type=float, default=25.0)
    parser.add_argument("--usd-per-hour", type=float, default=8.0)
    parser.add_argument("--workers", type=int, default=64)
    args = parser.parse_args(argv)
    corpora = [c.expanduser() for c in args.corpus]
    for c in corpora:
        print(f"fireworks-label: {c.name}: {len(check_corpus(c))} files checked", file=sys.stderr)
    api = _client()
    dep = create(api, args.account, args.deployment_id)
    name = dep["name"]
    started = time.monotonic()
    report: dict[str, Any] = {"deployment": name, "corpora": {}}
    try:
        model = f"{BASE_MODEL}#{name}"
        report["warm_up_s"] = round(warm_up(model))
        env = {
            **os.environ,
            "PII_GUARD_LLM_DETECTOR_URL": INFERENCE,
            "PII_GUARD_LLM_DETECTOR_API_KEY": os.environ["FIREWORKS_API_KEY"],
        }
        # Probe: one document per file must come back with teacher spans before the full run.
        probe_out = corpora[0] / "probe-labelled"
        probe = [
            sys.executable, str(ROOT / "training/distill/label.py"), "--corpus", str(corpora[0]),
            "--limit", "1", "--out", str(probe_out), "--model", model, "--reasoning-effort", "low",
        ]  # fmt: skip
        subprocess.run(probe, env=env, cwd=ROOT, check=True)  # noqa: S603 - fixed argument list
        counts = json.loads((probe_out / "label-stats.json").read_text())["counts"]
        report["probe"] = counts
        shutil.rmtree(probe_out)
        failed = counts.get("documents_without_teacher", 0)
        if not counts.get("documents") or failed > 0.1 * (failed + counts["documents"]):
            raise SystemExit(f"probe failed: {counts}")
        for corpus in corpora:
            cmd = [
                sys.executable, str(ROOT / "training/distill/label.py"), "--corpus", str(corpus),
                "--workers", str(args.workers), "--model", model, "--reasoning-effort", "low",
            ]  # fmt: skip
            # A second pass retries the documents the first one failed on (the cache keeps
            # every success, so it only calls the teacher for those).
            for attempt in (1, 2):
                proc = subprocess.Popen(cmd, env=env, cwd=ROOT)  # noqa: S603 - fixed argument list
                while proc.poll() is None:
                    spent = (time.monotonic() - started) / 3600 * args.usd_per_hour
                    if spent >= args.cap_usd:
                        proc.terminate()
                        proc.wait(60)
                        report["stopped"] = f"cost cap ${args.cap_usd} reached"
                        break
                    time.sleep(20)
                stats = json.loads((corpus / "labelled" / "label-stats.json").read_text())
                missing = stats["counts"].get("documents_without_teacher", 0)
                report["corpora"][corpus.name] = {
                    "exit": proc.returncode, "pass": attempt, "counts": stats["counts"],
                }  # fmt: skip
                if "stopped" in report or not missing:
                    break
            if "stopped" in report:
                break
    finally:
        hours = (time.monotonic() - started) / 3600
        report["deployment_hours"] = round(hours, 3)
        report["estimated_usd"] = round(hours * args.usd_per_hour, 2)
        report["deletion"] = delete(api, name)
        print(json.dumps(report, indent=2), file=sys.stderr)
    return 0 if all(v["exit"] == 0 for v in report["corpora"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
