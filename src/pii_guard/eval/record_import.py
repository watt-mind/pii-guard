"""One-off importer: the results committed before run records existed, as run records.

```
python -m pii_guard.eval.record_import [--runs-dir eval/results/runs] [--overwrite]
```

Converts the scorecards under ``eval/results/`` (the comparison baselines, the NER study, the
visual specimen runs) plus three Muse Glimmer zero-shot scorecards that were only reported on
the tracker, into ``eval/results/runs/*.json`` with ``source: imported``. The originals stay
where they are. What a scorecard doesn't say (models, settings, serving, hardware, cost) comes
from :data:`MANIFEST`, transcribed from the result READMEs and pull requests that published
them. A source that isn't present is skipped, so this can be re-run after the Glimmer
scorecards (never committed) are gone; it refuses to overwrite records unless asked.

New runs don't go through here: use ``pii-guard eval --record <slug>``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pii_guard.eval.fixtures import file_sha256
from pii_guard.eval.record import DEFAULT_RUNS_DIR, RecordError, build_records, write_records

__all__ = ["MANIFEST", "import_all", "main"]

_MAC_CPU = {
    "description": "Apple Silicon arm64, macOS 26.5, 10 CPUs, CPU only",
    "machine": "arm64",
    "cpu_count": 10,
    "accelerator": None,
}
_MAC_NER = {
    "description": "Apple M1 Max, macOS 26.5, PyTorch device auto (MPS)",
    "machine": "arm64",
    "accelerator": "Apple MPS",
}
_REMOTE = {
    "description": "local harness; the LLM detector is a remote API call",
    "accelerator": None,
}
_H100 = {
    "description": "Modal, 1x NVIDIA H100 80 GB, vLLM (vllm/vllm-openai:muse-glimmer), bf16",
    "accelerator": "NVIDIA H100 80GB",
}

_SPARK = {
    "model": "muse-spark-1.3",
    "model_ref": "muse-spark-1.3-contributor",
    "serving": "Meta Model API (remote)",
}
_SPARK_NOTES = [
    "Latency is a remote API call with retries; not comparable to local detectors.",
    "The LLM detector had no reasoning-effort or token-budget setting yet; some completions "
    "were cut off and retried.",
]
_NER_ZS = {
    "model": "xlmr-ner-hrl",
    "model_ref": "Davlan/xlm-roberta-base-ner-hrl",
    "revision": "253f557bd8249b8515114cfd7f71974fe5fa4d2f",
    "serving": "local PyTorch",
}
_NER_FT = {
    "model": "xlmr-base-ft-s7",
    "model_ref": "FacebookAI/xlm-roberta-base fine-tuned on the seed-7 synthetic train split "
    "(teacher Davlan/xlm-roberta-base-ner-hrl; not published)",
    "revision": None,
    "serving": "local PyTorch",
}
_GLIMMER = {
    "model": "muse-glimmer",
    "model_ref": "meta-models/Muse-Glimmer-30B",
    "serving": "vLLM on Modal, 1x H100, bf16",
}
_GLIMMER_RUNS = [
    "2026-10-27-glimmer-zero-shot-llm-low",
    "2026-10-27-glimmer-zero-shot-llm-medium",
    "2026-10-27-glimmer-zero-shot-rules-llm-low",
]
_GLIMMER_COST = {
    "usd": 4.0,
    "estimated": True,
    "gpu_minutes": 60.0,
    "model_calls": None,
    "tokens": None,
    "shared_with": _GLIMMER_RUNS,
    "note": "About one H100-hour, about $4, for the three zero-shot runs together, including "
    "the cold start (model download and torch.compile).",
}
_GLIMMER_NOTES = [
    "Zero-shot (no fine-tuning). reasoning_strength was passed as chat_template_kwargs by a "
    "patched LlmDetector payload (Glimmer ignores reasoning_effort); the detector had no "
    "setting for it yet.",
    "Decode about 44 tokens/s; reasoning is almost all of the latency.",
]
_VISUAL = {
    "commit": "84b64225df4e8e499818dc6e104c00c95fabd51c",
    "dirty": False,
    "pii_guard_version": "0.1.0",
    "note": "head of the branch that published the result; the result file records no commit",
}


def _ner(kind: str, lang: str, fixture_set: str) -> dict[str, Any]:
    detectors: list[dict[str, Any]] = [{"name": "rules"}]
    if kind != "rules":
        detectors.append({"name": "ner", **(_NER_ZS if kind == "zero-shot" else _NER_FT)})
    slug = {
        "rules": "rules",
        "zero-shot": "rules-ner-zero-shot",
        "fine-tuned": "rules-ner-fine-tuned",
    }[kind]
    label = {
        "rules": "pii-guard rules",
        "zero-shot": "pii-guard rules + NER (zero-shot)",
        "fine-tuned": "pii-guard rules + NER (fine-tuned)",
    }[kind]
    return {
        "label": label,
        "path": f"eval/results/ner/{kind}/{lang}-{fixture_set}.json",
        "slug": f"{slug}-{lang}-{fixture_set}",
        "date": "2026-10-26",
        "detectors": detectors,
        "hardware": _MAC_NER
        if kind != "rules"
        else _MAC_CPU | {"description": "Apple M1 Max, macOS 26.5, CPU"},
        "notes": (
            [
                (
                    "The fine-tuned model was trained on the seed-7 synthetic split; synth-dev is "
                    "its dev split."
                )
            ]
            if kind == "fine-tuned"
            else []
        ),
    }


_SPARK_OPEN = {
    "model": "muse-spark-open",
    "model_ref": "meta-models/muse-spark-open-1026",
    "serving": "Baseten Model APIs (remote)",
    "settings": {"reasoning_effort": "low"},
}
_BASETEN_CLIENT = {
    "description": "Apple Silicon arm64 client; the LLM detector is Baseten Model APIs (remote)",
    "machine": "arm64",
    "accelerator": None,
}
#: USD per 1M tokens (input, cached input, output), from the result READMEs.
_PRICES = {"baseten": (1.25, 0.15, 4.25), "meta-contributor": (0.10, 0.10, 0.20)}


def _token_cost(usage: dict[str, Any], price: str, note: str) -> dict[str, Any]:
    """A cost block from the detector's token counters (reasoning tokens bill as output)."""
    inp, cached, out = _PRICES[price]
    prompt = int(usage.get("prompt_tokens") or 0)
    hit = int(usage.get("cached_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    usd = ((prompt - hit) * inp + hit * cached + completion * out) / 1_000_000
    return {
        "usd": round(usd, 4),
        "estimated": True,
        "gpu_minutes": None,
        "model_calls": usage.get("requests"),
        "tokens": {
            "prompt": prompt,
            "cached": hit,
            "completion": completion,
            "reasoning": int(usage.get("reasoning_tokens") or 0),
        },
        "shared_with": [],
        "note": note,
    }


def _usage(path: str, root: Path, key: str | None = None) -> dict[str, Any]:
    try:
        data = json.loads((root / path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if key is None:
        return (data.get("usage") or {}).get("llm") or {}
    return ((data.get("runs") or {}).get(key) or {}).get("usage") or {}


_DISTILLED = {
    size: {
        "model": f"xlmr-{size}-distilled-glimmer",
        "model_ref": f"FacebookAI/xlm-roberta-{size} distilled from Muse Glimmer (low) on a "
        "5k-document Muse-generated corpus, seed 11 (not published)",
        "revision": None,
        "serving": "local PyTorch",
    }
    for size in ("base", "large")
}
_DISTILLED_RUNS = [
    f"2026-10-27-distilled-{kind}-{lang}-{fs}"
    for kind in ("base", "large")
    for fs in ("smoke", "distill-dev")
    for lang in ("hu", "en")
]
_DISTILLED_COST = {
    "usd": 3.0,
    "estimated": True,
    "gpu_minutes": 56.0,
    "model_calls": 5004,
    "tokens": None,
    "shared_with": _DISTILLED_RUNS,
    "note": "Whole distillation: Meta Model API $1.05 for the corpus, about 38 H100 minutes for "
    "the Glimmer teacher, 8 A10G and 10 L40S minutes for training; roughly $3 in total.",
}


def _distilled(kind: str, lang: str, fixture_set: str) -> dict[str, Any]:
    detectors: list[dict[str, Any]] = [{"name": "rules"}]
    if kind != "rules":
        detectors.append({"name": "ner", **_DISTILLED[kind]})
    notes = ["Rules as of LAB-1106 (before the Hungarian ID and parcel rules of LAB-1127)."]
    if kind != "rules":
        notes.append(
            "The student was trained on the Muse-generated distillation corpus; distill-dev is "
            "its dev split."
        )
    return {
        "label": "pii-guard rules"
        if kind == "rules"
        else f"pii-guard rules + NER (distilled {kind})",
        "path": f"eval/results/ner/distilled/{kind}/{lang}-{fixture_set}.json",
        "slug": f"distilled-{kind}-{lang}-{fixture_set}",
        "date": "2026-10-27",
        "detectors": detectors,
        "hardware": _MAC_NER
        if kind != "rules"
        else _MAC_CPU | {"description": "Apple M1 Max, macOS 26.5, CPU"},
        "cost": _DISTILLED_COST if kind != "rules" else None,
        "notes": notes,
    }


_INJECTION = "eval/results/2026-10-27-injection"
_BASETEN = "eval/results/2026-10-27-baseten"


#: Every imported result: the source file and what the scorecard itself doesn't record.
MANIFEST: list[dict[str, Any]] = [
    {
        "path": "eval/results/2026-10-26-baselines/smoke-rules-baselines.json",
        "slug": "comparison-smoke",
        "date": "2026-10-26",
        "hardware": _MAC_CPU,
    },
    {
        "path": "eval/results/2026-10-26-baselines/synth-rules-baselines.json",
        "slug": "comparison-synth-sample",
        "date": "2026-10-26",
        "hardware": _MAC_CPU,
    },
    *[
        {
            "path": f"eval/results/2026-10-26-baselines/smoke-{lang}-rules-llm.json",
            "slug": f"rules-muse-spark-smoke-{lang}",
            "label": "pii-guard rules + Muse Spark 1.3",
            "date": "2026-10-26",
            "detectors": [{"name": "rules"}, {"name": "llm", **_SPARK}],
            "hardware": _REMOTE,
            "notes": _SPARK_NOTES,
        }
        for lang in ("hu", "en")
    ],
    *[
        _ner(kind, lang, fixture_set)
        for kind in ("rules", "zero-shot", "fine-tuned")
        for fixture_set in ("smoke", "synth-sample", "synth-dev")
        for lang in ("hu", "en")
    ],
    *[
        {
            "path": f".import-glimmer/{name}.json",
            "slug": f"glimmer-zero-shot-{name}",
            "label": ("pii-guard rules + " if name.startswith("rules") else "pii-guard ")
            + f"Muse Glimmer ({strength})",
            "date": "2026-10-27",
            "detectors": ([{"name": "rules"}] if name.startswith("rules") else [])
            + [{"name": "llm", **_GLIMMER, "settings": {"reasoning_strength": strength}}],
            "hardware": _H100,
            "cost": _GLIMMER_COST,
            "notes": _GLIMMER_NOTES,
            "import_note": (
                "zero-shot Glimmer scorecard reported on the tracker, not committed before"
            ),
        }
        for name, strength in (
            ("llm-low", "low"),
            ("llm-medium", "medium"),
            ("rules-llm-low", "low"),
        )
    ],
    *[
        _distilled(kind, lang, fixture_set)
        for kind in ("rules", "base", "large")
        for fixture_set in ("smoke", "distill-dev")
        for lang in ("hu", "en")
    ],
    *[
        {
            "path": f"{_BASETEN}/{lang}-{fs}-rules-llm.json",
            "slug": f"baseten-spark-open-{lang}-{fs}",
            "label": "pii-guard rules + Muse Spark Open (Baseten)",
            "date": "2026-10-27",
            "detectors": [{"name": "rules"}, {"name": "llm", **_SPARK_OPEN}],
            "hardware": _BASETEN_CLIENT,
            "cost_from": (f"{_BASETEN}/usage.json", f"{lang}-{fs}", "baseten"),
            "notes": [
                "Latency is a remote API call (one request at a time), not comparable to local "
                "detectors. Four runs on the day; this is the committed one (see the README for "
                "the ranges)."
            ],
        }
        for fs in ("smoke", "synth-sample")
        for lang in ("hu", "en")
    ],
    {
        "path": f"{_INJECTION}/injection-rules.json",
        "slug": "injection-rules",
        "date": "2026-10-27",
        "hardware": _MAC_CPU,
        "notes": ["Prompt-injection red team; per-attack-class leaks are in the source scorecard."],
    },
    *[
        {
            "path": f"{_INJECTION}/injection-rules-llm-{name}.json",
            "slug": f"injection-{slug}",
            "label": label,
            "date": "2026-10-27",
            "detectors": [{"name": "rules"}, {"name": "llm", **model}],
            "hardware": _BASETEN_CLIENT if model is _SPARK_OPEN else _REMOTE,
            "cost_from": (f"{_INJECTION}/injection-rules-llm-{name}.json", None, price),
            "notes": [
                note,
                "Prompt-injection red team; per-attack-class leaks are in the source scorecard.",
            ],
        }
        for name, slug, label, model, price, note in (
            (
                "baseten-before",
                "spark-open-before-hardening",
                "pii-guard rules + Muse Spark Open (Baseten)",
                _SPARK_OPEN,
                "baseten",
                "Detector as of LAB-1108, before the injection hardening.",
            ),
            (
                "baseten-run1",
                "spark-open-run1",
                "pii-guard rules + Muse Spark Open (Baseten)",
                _SPARK_OPEN,
                "baseten",
                "After the LAB-1107 hardening, run 1.",
            ),
            (
                "baseten-run2",
                "spark-open-run2",
                "pii-guard rules + Muse Spark Open (Baseten)",
                _SPARK_OPEN,
                "baseten",
                "After the LAB-1107 hardening, run 2.",
            ),
            (
                "meta-spark-1.3",
                "spark-1.3",
                "pii-guard rules + Muse Spark 1.3",
                _SPARK,
                "meta-contributor",
                "After the LAB-1107 hardening, Muse Spark 1.3 on the Meta Model API.",
            ),
        )
    ],
    *[
        {
            "path": f"{_INJECTION}/{lang}-smoke-rules-llm-baseten.json",
            "slug": f"baseten-spark-open-hardened-{lang}-smoke",
            "label": "pii-guard rules + Muse Spark Open (Baseten)",
            "date": "2026-10-27",
            "detectors": [{"name": "rules"}, {"name": "llm", **_SPARK_OPEN}],
            "hardware": _BASETEN_CLIENT,
            "cost_from": (f"{_INJECTION}/{lang}-smoke-rules-llm-baseten.json", None, "baseten"),
            "notes": ["Smoke regression after the LAB-1107 injection hardening."],
        }
        for lang in ("hu", "en")
    ],
    {
        "path": "eval/results/visual/specimens-before.json",
        "slug": "visual-specimens-id-photo-prompt",
        "date": "2026-10-27",
        "code": _VISUAL,
        "notes": ["Before the prompt study: ID_PHOTO prompted as 'id photo'."],
    },
    {
        "path": "eval/results/visual/specimens.json",
        "slug": "visual-specimens-person-prompt",
        "date": "2026-10-27",
        "code": _VISUAL,
        "notes": ["After the prompt study: ID_PHOTO prompted as 'photo of a person'."],
    },
]


def _records_for(entry: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    source = root / entry["path"]
    card = json.loads(source.read_text(encoding="utf-8"))
    extra: dict[str, Any] = {}
    if entry.get("cost"):
        extra["cost"] = entry["cost"]
    elif entry.get("cost_from"):
        path, key, price = entry["cost_from"]
        usage = _usage(path, root, key)
        if usage:
            extra["cost"] = _token_cost(
                usage, price, "From the token counts the endpoint reported, at list prices."
            )
    if entry.get("code"):
        extra["code"] = entry["code"]
    if entry.get("label"):
        extra["system"] = {"label": entry["label"]}
    records = build_records(
        card,
        slug=entry["slug"],
        source="imported",
        day=entry["date"],
        detectors=entry.get("detectors"),
        hardware=entry.get("hardware"),
        extra=extra or None,
        notes=entry.get("notes", ()),
    )
    digest = file_sha256(source)
    for record in records:
        record["imported_from"] = {
            "path": entry["path"],
            "sha256": digest,
            "note": entry.get("import_note"),
        }
        if record["system"]["family"] == "comparison":
            record["notes"].append("Detection latency measured inside the tool, CPU only.")
    return records


def import_all(
    root: Path = Path(), runs_dir: Path = DEFAULT_RUNS_DIR, *, overwrite: bool = False
) -> list[Path]:
    """Import every :data:`MANIFEST` entry whose source exists; returns the files written."""
    written: list[Path] = []
    for entry in MANIFEST:
        if not (root / entry["path"]).is_file():
            print(f"skip {entry['path']}: not found", file=sys.stderr)
            continue
        records = _records_for(entry, root)
        todo = [r for r in records if overwrite or not (runs_dir / f"{r['run_id']}.json").exists()]
        written += write_records(todo, runs_dir, overwrite=overwrite)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pii_guard.eval.record_import")
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        written = import_all(runs_dir=args.runs_dir, overwrite=args.overwrite)
    except (OSError, RecordError, json.JSONDecodeError) as exc:
        print(f"record_import: {exc}", file=sys.stderr)
        return 2
    for path in written:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
