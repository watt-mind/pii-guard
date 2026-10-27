"""Run records for the LAB-1150 NER candidates (``eval/results/runs/``).

Reads ``<dir>/<fixture>--<candidate>.json`` scorecards (``training/ner/eval_candidates.py``)
and writes one record per scorecard with slug ``ner-v2-<fixture>-<candidate>``, describing the
NER model(s) that ran (:data:`CANDIDATES`), the host and its load, and, for every candidate
trained on Ai4Privacy rows, the note that the ai4privacy scorecards are **no longer an
out-of-distribution check** for it (the "trained without ai4privacy" ablation keeps one)::

    uv run --no-sync python training/ner/records.py eval/results/2026-10-27-ner-v2/scorecards
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pii_guard.eval.baselines.records import _PUBLIC_NOTES, _hardware, _public_source
from pii_guard.eval.record import RecordError, build_records, write_records

#: candidate slug -> (label, model id for the record, model_ref, saw Ai4Privacy train rows)
CANDIDATES: dict[str, dict[str, Any]] = {
    "xlmr-large-v1": {
        "label": "pii-guard fast, NER v1 (xlm-roberta-large distilled, LAB-1128)",
        "ner": ("xlmr-large-distilled-glimmer", "LAB-1128, 4 types, not published"),
        "ai4privacy_train": False,
    },
    "xlmr-base-v2": {
        "label": "pii-guard fast, NER v2 base (xlm-roberta-base, LAB-1150)",
        "ner": ("xlmr-base-v2", "LAB-1150, 10 types, not published"),
        "ai4privacy_train": True,
    },
    "xlmr-large-v2": {
        "label": "pii-guard fast, NER v2 large (xlm-roberta-large, LAB-1150)",
        "ner": ("xlmr-large-v2", "LAB-1150, 10 types, not published"),
        "ai4privacy_train": True,
    },
    "xlmr-large-v2-no-ai4privacy": {
        "label": "pii-guard fast, NER v2 large without Ai4Privacy rows (ablation, LAB-1150)",
        "ner": ("xlmr-large-v2-no-ai4privacy", "LAB-1150 ablation, 10 types, not published"),
        "ai4privacy_train": False,
    },
    "xlmr-base-v2-no-ai4privacy": {
        "label": "pii-guard fast, NER v2 base without Ai4Privacy rows (LAB-1150)",
        "ner": ("xlmr-base-v2-no-ai4privacy", "LAB-1150, 10 types, not published"),
        "ai4privacy_train": False,
    },
    "xlmr-base-v2-openpii-1k": {
        "label": "pii-guard fast, NER v2 base, OpenPII cut to 1k rows/language (LAB-1150)",
        "ner": ("xlmr-base-v2-openpii-1k", "LAB-1150, 10 types, not published"),
        "ai4privacy_train": True,
    },
    "xlmr-large-v2-openpii-1k": {
        "label": "pii-guard fast, NER v2 large, OpenPII cut to 1k rows/language (LAB-1150)",
        "ner": ("xlmr-large-v2-openpii-1k", "LAB-1150, 10 types, not published"),
        "ai4privacy_train": True,
    },
    "xlmr-base-v2-hn": {
        "label": "pii-guard fast, NER v2 base + hard negatives (LAB-1150)",
        "ner": ("xlmr-base-v2-hn", "LAB-1150, 10 types, not published"),
        "ai4privacy_train": True,
    },
    "xlmr-large-v2-hn": {
        "label": "pii-guard fast, NER v2 large + hard negatives (LAB-1150)",
        "ner": ("xlmr-large-v2-hn", "LAB-1150, 10 types, not published"),
        "ai4privacy_train": True,
    },
    "davlan-xlmr-base-zero-shot": {
        "label": "pii-guard fast, built-in zero-shot NER (Davlan/xlm-roberta-base-ner-hrl)",
        "ner": ("xlm-roberta-base-ner-hrl", "Davlan/xlm-roberta-base-ner-hrl (AFL-3.0), pinned"),
        "ai4privacy_train": False,
    },
    "gliner-multi-zero-shot": {
        "label": "pii-guard fast, GLiNER multi v2.1 zero-shot (LAB-1150)",
        "gliner": ("gliner-multi-v2.1", "urchade/gliner_multi-v2.1 (Apache-2.0)"),
        "ai4privacy_train": False,
    },
    "gliner-multi-v2": {
        "label": "pii-guard fast, GLiNER multi fine-tuned (LAB-1150)",
        "gliner": ("gliner-multi-v2-ft", "LAB-1150 fine-tune of gliner_multi-v2.1, not published"),
        "ai4privacy_train": True,
    },
    "xlmr-base-v2-hn-gliner-union": {
        "label": "pii-guard fast, NER v2 base + hard negatives, union with GLiNER (LAB-1150)",
        "ner": ("xlmr-base-v2-hn", "LAB-1150, 10 types, not published"),
        "gliner": ("gliner-multi-v2.1", "urchade/gliner_multi-v2.1 (Apache-2.0)"),
        "ai4privacy_train": True,
    },
}
NOT_OOD = (
    "This NER was trained on Ai4Privacy OpenPII train-split rows (never the evaluated "
    "validation rows; training/ner/openpii-train-manifest.json), so the ai4privacy scorecard "
    "is no longer an out-of-distribution check for it; see the no-ai4privacy ablation."
)


def _detectors(run: Mapping[str, Any], spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"name": "rules"}]
    if "ner" in spec and run.get("ner"):
        model, ref = spec["ner"]
        weights = run["ner"].get("safetensors_sha256") or {}
        out.append(
            {
                "name": "ner",
                "model": model,
                "model_ref": f"local checkpoint {run['ner'].get('model')} ({ref})",
                "revision": "sha256:" + weights["model.safetensors"]
                if "model.safetensors" in weights
                else None,
                "settings": {},
                "serving": "local PyTorch",
            }
        )
    if "gliner" in spec and run.get("gliner"):
        model, ref = spec["gliner"]
        g = run["gliner"]
        weights = g.get("weights_sha256") or {}
        name = next(iter(weights), None)
        out.append(
            {
                "name": "ner_gliner",
                "model": model,
                "model_ref": ref,
                "revision": g.get("revision") or (f"sha256:{weights[name]}" if name else None),
                "settings": {"labels": "pii_guard.detect.ner_gliner.GLINER_LABELS"},
                "serving": "local PyTorch (gliner 0.2.29)",
            }
        )
    return out


def records_for(card: Mapping[str, Any], fixture: str, candidate: str) -> list[dict[str, Any]]:
    spec = CANDIDATES[candidate]
    run = card["run"]
    paths = [f["path"] for f in card["meta"]["fixtures"]]
    public = _public_source(paths)
    notes = [f"One warm-up call before timing; wall time {run['wall_s']} s."]
    if run.get("blocked"):
        notes.append(f"{run['blocked']} document(s) blocked (fail closed); not scored.")
    records = build_records(
        card,
        slug=f"ner-v2-{fixture}-{candidate}",
        detectors=_detectors(run, spec),
        hardware=_hardware(run, remote_llm=False),
        extra={"system": {"label": spec["label"]}},
        notes=notes,
    )
    for record in records:
        if public:
            for f in record["fixtures"]:
                f["origin"] = "generated"
                f["generator"] = f"{public} (not Muse)"
            record["notes"].extend(_PUBLIC_NOTES.get(record["fixture_set"], []))
            if spec["ai4privacy_train"]:
                record["notes"].append(NOT_OOD)
    return records


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--runs-dir", type=Path, default=Path("eval/results/runs"))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    records: list[dict[str, Any]] = []
    for path in sorted(args.directory.glob("*--*.json")):
        fixture, _, candidate = path.stem.partition("--")
        if candidate not in CANDIDATES:
            print(f"records: unknown candidate {candidate!r} in {path.name}", file=sys.stderr)
            return 2
        card = json.loads(path.read_text(encoding="utf-8"))
        records.extend(records_for(card, fixture, candidate))
    try:
        written = write_records(records, args.runs_dir, overwrite=args.overwrite)
    except RecordError as exc:
        print(f"records: {exc}", file=sys.stderr)
        return 2
    for p in written:
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
