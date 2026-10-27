"""Run records (``eval/results/runs/``) for a comparison run directory of scorecards.

```
python -m pii_guard.eval.baselines.records eval/results/2026-10-27-comparison/scorecards \
    --slug-prefix comparison [--runs-dir eval/results/runs] [--overwrite]
```

The directory holds, per fixture ``<f>``: ``<f>-baselines.json`` (``pii-guard eval --detectors
rules --baselines ...``: pii-guard rules plus the comparison tools), ``<f>-fast.json`` and
``<f>-audit.json`` (``<f>-strict.json``, the old name, is read too)
(:mod:`pii_guard.eval.baselines.suite`). Each becomes records through
:func:`pii_guard.eval.record.build_records`, with what the generic importer can't know filled
in from the suite's ``run`` block: the NER checkpoint (path and SHA-256), the LLM endpoint,
model and reasoning effort, token usage and cost, the host's load average and blocked
documents. Fixtures from a public dataset (``meta.source`` names it) are marked ``generated``
with the dataset as the generator, since no person wrote them.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pii_guard.eval.record import RecordError, build_records, write_records
from pii_guard.gateway.config import DEPRECATED_MODE_ALIASES

__all__ = ["main", "records_for"]

_PUBLIC_NOTES = {
    "ai4privacy": [
        "Public set: Ai4Privacy OpenPII 1M (CC-BY-4.0, Ai4Privacy / Ai Suisse SA), seeded "
        "sample of the validation split; see eval/fixtures/public/README.md.",
        "Dates, ages, gender, titles and bare city names are policy-excluded (not in the gold "
        "spans), so masking them counts as over-masking. Most card, tax and TAJ numbers in "
        "the set fail their checksums, which pii-guard's rules require.",
    ],
}
_TOOL_NOTES = {
    ("ai4privacy", "llm-guard"): "LLM Guard's default model was fine-tuned on an earlier "
    "Ai4Privacy release (possible train/test contamination): read its numbers as optimistic.",
}


def _public_source(paths: Sequence[str]) -> str | None:
    for raw in paths:
        try:
            first = Path(raw).read_text(encoding="utf-8").splitlines()[0]
        except (OSError, IndexError):
            continue
        source = (json.loads(first).get("meta") or {}).get("source")
        if source and source != "synthetic":
            return str(source)
    return None


def _hardware(run: Mapping[str, Any], *, remote_llm: bool) -> dict[str, Any]:
    host = run.get("host") or {}
    load = run.get("load_average_start")
    desc = f"{host.get('machine')}, {host.get('cpu_count')} CPUs, {host.get('platform')}"
    if "ner" in run:
        desc += f"; NER on PyTorch device {run['ner'].get('device')}"
    if remote_llm:
        desc += "; LLM detector remote (Baseten Model APIs), one request at a time"
    if load:
        desc += f"; load average {load[0]:.1f} at start (machine not idle)"
    return {
        "description": desc,
        "platform": host.get("platform"),
        "machine": host.get("machine"),
        "cpu_count": host.get("cpu_count"),
        "accelerator": "Apple MPS" if "ner" in run and host.get("machine") == "arm64" else None,
        "python": host.get("python"),
    }


def _detectors(run: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"name": "rules"}]
    ner = run.get("ner")
    if ner:
        weights = ner.get("safetensors_sha256") or {}
        out.append(
            {
                "name": "ner",
                "model": "xlmr-large-distilled-glimmer",
                "model_ref": "local checkpoint "
                + Path(str(ner.get("model")).rstrip("/")).name
                + " (LAB-1128, not published)",
                "revision": "sha256:" + weights["model.safetensors"]
                if "model.safetensors" in weights
                else None,
                "settings": {},
                "serving": "local PyTorch",
            }
        )
    llm = run.get("llm")
    if llm:
        out.append(
            {
                "name": "llm",
                "model": "muse-spark-open",
                "model_ref": llm.get("model"),
                "revision": None,
                "settings": {"reasoning_effort": llm.get("reasoning_effort")},
                "serving": "Baseten Model APIs (remote)",
            }
        )
    return out


def _cost(llm: Mapping[str, Any]) -> dict[str, Any]:
    usage = llm["usage"]
    return {
        "usd": llm["cost_usd"],
        "estimated": True,
        "gpu_minutes": None,
        "model_calls": usage.get("requests"),
        "tokens": {
            "prompt": usage.get("prompt_tokens", 0),
            "cached": usage.get("cached_tokens", 0),
            "completion": usage.get("completion_tokens", 0),
            "reasoning": usage.get("reasoning_tokens", 0),
        },
        "shared_with": [],
        "note": (
            f"From the token counts the endpoint reported, at list prices "
            f"(${llm['usd_per_1k_messages']:.2f} per 1,000 messages; warm-up call excluded)."
        ),
    }


def records_for(
    card: Mapping[str, Any], *, slug: str, code_notes: Mapping[str, str] | None = None
) -> list[dict[str, Any]]:
    """Records for one scorecard of the comparison directory.

    ``code_notes`` maps a commit prefix to a note for ``code.note`` (a commit that is no
    longer on a branch after a rebase, say).
    """
    paths = [f["path"] for f in card["meta"]["fixtures"]]
    public = _public_source(paths)
    run = card.get("run")
    notes: list[str] = []
    detectors = None
    hardware = None
    extra: dict[str, Any] = {}
    if run:
        detectors = _detectors(run)
        hardware = _hardware(run, remote_llm="llm" in run)
        notes.append(f"One warm-up call before timing; wall time {run['wall_s']} s.")
        if run.get("blocked"):
            notes.append(
                f"{run['blocked']} document(s) blocked: the detector failed and the pipeline "
                "failed closed (the gateway would refuse that request); not scored."
            )
        if run.get("llm"):
            extra["cost"] = _cost(run["llm"])
            notes.append(
                "Latency includes a remote API call per document, so it is not comparable "
                "with local detectors."
            )
        labels = {
            "fast": "pii-guard fast (rules + NER distilled large)",
            "audit": "pii-guard audit (rules + NER + Muse Spark Open, Baseten)",
        }
        mode = run["system"].removeprefix("pii-guard ")
        mode = DEPRECATED_MODE_ALIASES.get(mode, mode)
        if mode in labels:
            extra["system"] = {"label": labels[mode]}
    records = build_records(
        card, slug=slug, detectors=detectors, hardware=hardware, extra=extra, notes=notes
    )
    set_name = records[0]["fixture_set"]
    for record in records:
        for prefix, note in (code_notes or {}).items():
            if record["code"]["commit"].startswith(prefix):
                record["code"]["note"] = note
        if public:
            for fixture in record["fixtures"]:
                fixture["origin"] = "generated"
                fixture["generator"] = f"{public} (not Muse)"
            record["notes"].extend(_PUBLIC_NOTES.get(set_name, []))
        tool_note = _TOOL_NOTES.get((set_name, record["system"]["tool"]))
        if tool_note:
            record["notes"].append(tool_note)
    return records


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pii_guard.eval.baselines.records",
        description="Write run records for a directory of comparison scorecards.",
    )
    parser.add_argument("directory", type=Path)
    parser.add_argument("--slug-prefix", default="comparison")
    parser.add_argument("--runs-dir", type=Path, default=Path("eval/results/runs"))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--code-note",
        action="append",
        default=[],
        metavar="COMMIT=NOTE",
        help="a note for records run at a commit (prefix), repeatable",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    code_notes = dict(item.split("=", 1) for item in args.code_note if "=" in item)
    records: list[dict[str, Any]] = []
    for path in sorted(args.directory.glob("*.json")):
        stem = path.stem
        for suffix in ("-baselines", "-fast", "-audit", "-strict"):
            if stem.endswith(suffix):
                fixture, kind = stem.removesuffix(suffix), suffix[1:]
                kind = DEPRECATED_MODE_ALIASES.get(kind, kind)
                break
        else:
            continue
        card = json.loads(path.read_text(encoding="utf-8"))
        slug = f"{args.slug_prefix}-{fixture}" + ("" if kind == "baselines" else f"-{kind}")
        records.extend(records_for(card, slug=slug, code_notes=code_notes))
    try:
        written = write_records(records, args.runs_dir, overwrite=args.overwrite)
    except RecordError as exc:
        print(f"records: {exc}", file=sys.stderr)
        return 2
    for p in written:
        print(p)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
