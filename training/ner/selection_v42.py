"""The NER v4.2 selection split (LAB-1625): smoke-style dev documents with v4.1's failure modes.

The LAB-1417 split (``smoke_style_dev.py``) has short hu/en/de chats, e-mails and letters, but
v2.0, v4.1-A1 and v4.1-A2 all leak 0 % on it, while A1 and A2 leak on the real smoke gate
(LAB-1547). Its texts have no genitive name, no common-word surname and no date that is not a
birth date. This split keeps a smaller v1 base and adds one *slice* per failure mode
(``v42_gen.py``, pool ``sel``):

- ``base``: ``smoke_style_dev.build`` with its own seed, 15 documents per language and kind;
- ``de-genitive``: German genitive names (``Annas``, ``Frau Beckers``, ``Jonas'``);
- ``hu-surname-given``: a Hungarian common-word surname with an inflected given name;
- ``dates``: one birth date (``DATE_OF_BIRTH``) next to 1-3 other dates (``O``), or none;
- ``numbers``: order, customer and reference numbers (``O``) next to an IBAN, or none.

The selection rule reads the whole split; ``score`` also prints every slice. It is synthetic,
seeded and decontaminated: no smoke, gate or test document is read for its text (only the
smoke and inflection *person names*, to avoid them), every document naming a person whose full
name occurs in any evaluation text is redrawn, and :func:`write` drops any document that is an
exact or near copy of an evaluation text (``decontam.py``). ``train.py`` gets the files as
``report_dev``, so no training document can copy one either::

    uv run --no-sync python training/ner/selection_v42.py write
    PII_GUARD_NER_DEVICE=cpu uv run --no-sync python training/ner/selection_v42.py score \\
        --candidate v41-a1 --model models/ner/pii-guard-ner-xlmr-base-v41-a1 --json OUT.json

Counts only are written, never a text or a value.
"""

# Seeded synthetic data: the standard PRNG is the point.
# ruff: noqa: S311

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decontam
import smoke_style_dev as ssd
import targeted_v33 as t33
import v42_gen as g

from pii_guard.eval.fixtures import Document, load_fixtures, write_fixtures

ROOT = Path(__file__).resolve().parents[2]
OUT = Path("eval/generated/selection-v42")
VERSION = 1
SEED = 1625
BASE_PER_KIND = 15
#: Documents per slice and language. Fixed before any candidate was scored.
PER_LANG = {"de-genitive": 200, "hu-surname-given": 80, "dates": 60, "numbers": 30}
SLICES = ("base", *g.SLICES)


def _doc_id(lang: str, slice_: str, i: int) -> str:
    return f"{lang}-sel42-{slice_}-{i:04d}"


def build(*, seed: int = SEED, blob: str | None = None, scale: float = 1.0) -> list[Document]:
    """The split, deterministic for ``seed``. ``scale`` shrinks it (tests)."""
    avoid = ssd._smoke_names()
    blob = t33.eval_texts() if blob is None else blob
    base = ssd.build(per_kind=max(1, round(BASE_PER_KIND * scale)), seed=seed, avoid=avoid)
    docs = [
        Document(
            _doc_id(d.language, "base", i),
            d.language,
            d.text,
            d.spans,
            {**d.meta, "slice": "base", "generator": f"selection_v42/{VERSION}"},
        )
        for i, d in enumerate(base)
    ]
    for slice_ in g.SLICES:
        for lang in g.SLICE_LANGS[slice_]:
            for i in range(max(1, round(PER_LANG[slice_] * scale))):
                rng = random.Random(f"selection-v42/{VERSION}/{seed}/{slice_}/{lang}/{i}")
                for _ in range(200):
                    b = g.BUILDERS[slice_](lang, "sel", rng, avoid)
                    if not any(name in blob for name in b.names):
                        break
                else:  # pragma: no cover
                    raise RuntimeError(f"{slice_} {lang} {i}: every draw names an eval person")
                meta = {"slice": slice_, "generator": f"selection_v42/{VERSION}"}
                docs.append(b.document(_doc_id(lang, slice_, i), lang, meta))
    return docs


def write(out: Path = OUT, *, seed: int = SEED, index: decontam.EvalIndex | None = None,
          scale: float = 1.0) -> list[Path]:  # fmt: skip
    """``<out>/<lang>-selection-v42.jsonl`` after the decontamination gate, and a manifest."""
    index = decontam.eval_corpus(ROOT) if index is None else index
    report = decontam.Report()
    docs = build(seed=seed, scale=scale)
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    counts: dict[str, dict[str, int]] = {}
    for lang in ssd.LANGS:
        path = out / f"{lang}-selection-v42.jsonl"
        kept = decontam.gate(
            [d for d in docs if d.language == lang], index, name=str(path), report=report
        )
        write_fixtures(path, kept)
        paths.append(path)
        for d in kept:
            counts.setdefault(d.meta["slice"], {}).setdefault(lang, 0)
            counts[d.meta["slice"]][lang] += 1
    manifest = {"version": VERSION, "seed": seed, "documents": counts,
                "decontam": report.to_dict()}  # fmt: skip
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(decontam.summary_line(report), flush=True)
    return paths


def _block(card: dict[str, Any]) -> dict[str, Any]:
    o = card["overall"]
    over_types = {
        t: b["over_masked"] for t, b in o["over_masking"]["per_type"].items() if b["over_masked"]
    }
    leak_types = {t: b["leaked"] for t, b in o["leak"]["per_type"].items() if b["leaked"]}
    return {
        "documents": o["documents"],
        "values": o["leak"]["values"],
        "leaked": o["leak"]["leaked"],
        "leak": round(100 * (o["leak"]["rate"] or 0), 2),
        "masked": o["over_masking"]["masked"],
        "over_masked": o["over_masking"]["over_masked"],
        "over": round(100 * (o["over_masking"]["rate"] or 0), 2),
        "leaked_by_type": leak_types,
        "over_masked_by_type": over_types,
    }


def score(paths: Sequence[Path], model: str | None) -> dict[str, Any]:
    """Fast mode (rules + NER) on the split: the whole split and every slice."""
    if model:
        os.environ["PII_GUARD_NER_MODEL"] = model
    from pii_guard.eval.report import build_scorecard
    from pii_guard.eval.scorer import DetectorAnalyzer, run_documents

    analyzer = DetectorAnalyzer(["rules", "ner"])
    if analyzer.skipped:
        raise SystemExit(f"detector unavailable: {analyzer.skipped}")
    analyzer.analyze("Warm-up text without personal data.", "en")
    started = time.perf_counter()
    results = run_documents(load_fixtures(list(paths)), analyzer)
    wall = time.perf_counter() - started

    def card(rs: Sequence[Any]) -> dict[str, Any]:
        return _block(build_scorecard(rs, detectors=analyzer.loaded, commit=("-", False)))

    out: dict[str, Any] = {"all": card(results), "wall_s": round(wall, 1), "slices": {}}
    for slice_ in SLICES:
        rs = [r for r in results if r.document.meta.get("slice") == slice_]
        if rs:
            out["slices"][slice_] = card(rs)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    w = sub.add_parser("write")
    w.add_argument("--out", type=Path, default=OUT)
    s = sub.add_parser("score")
    s.add_argument("--candidate", required=True)
    s.add_argument("--model", help="checkpoint directory (default: the published v2.0)")
    s.add_argument("--dir", type=Path, default=OUT)
    s.add_argument("--json", type=Path)
    s.add_argument("--thresholds", type=Path, help="a thresholds_v33.py JSON (dev-calibrated)")
    args = parser.parse_args(argv)
    if args.command == "write":
        for path in write(args.out):
            print(path)
        return 0
    paths = sorted(args.dir.glob("*-selection-v42.jsonl"))
    if args.thresholds:
        import thresholds_v33

        table = json.loads(args.thresholds.read_text(encoding="utf-8"))["thresholds"]
        thresholds_v33.apply(table)
    result = {"candidate": args.candidate, "model": args.model or "v2.0 (published)",
              **score(paths, args.model)}  # fmt: skip
    a = result["all"]
    print(f"{args.candidate}: leak {a['leak']:.2f} ({a['leaked']}/{a['values']}) "
          f"over {a['over']:.2f} ({a['over_masked']}/{a['masked']})", file=sys.stderr)  # fmt: skip
    for name, b in result["slices"].items():
        print(f"  {name:18s} leak {b['leak']:6.2f} ({b['leaked']}/{b['values']}) "
              f"over {b['over']:6.2f} ({b['over_masked']}/{b['masked']}) "
              f"{b['leaked_by_type']} {b['over_masked_by_type']}", file=sys.stderr)  # fmt: skip
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
