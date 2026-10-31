"""Score one system on one registered dataset; write its run record(s) and per-document counts.

```
PII_GUARD_NER_MODEL=models/ner/pii-guard-ner-xlmr-base-v2-hn \\
  uv run --no-sync python -m pii_guard.eval.datasets run gretel-finance --system fast --record
UV_PROJECT_ENVIRONMENT=.venv-baselines uv run --no-sync python -m pii_guard.eval.datasets \\
  run gretel-finance --system rules,presidio,llm-guard,privaite --record
```

``--system`` takes pii-guard systems (``rules``, ``fast`` = rules + NER, ``audit`` = rules + NER +
LLM, which needs ``--limit``) and comparison tools (``presidio``, ``llm-guard``, ``privaite``),
comma-separated. Each runs once over the dataset's fixture files, with one warm-up call, one
document at a time (a document a detector fails on is *blocked*, counted and not scored, as the
gateway would refuse it).

With ``--record`` it writes, per system, a run record ``eval/results/runs/<date>-datasets-<set>-
<system>.json`` (the usual format, :mod:`pii_guard.eval.record`) and the per-document counts
``eval/datasets/results/<run_id>.json``: for every document its id, language, overlap counts,
leaked values, masked and over-masked spans and detection time, plus the leak split by checksum
validity and perturbation where the set marks them. **No text and no value**: only counts. The
bootstrap confidence intervals in ``docs/benchmarks.md`` are computed from those files
(:mod:`pii_guard.eval.datasets.ci`), since a run record keeps only the totals.
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pii_guard.eval.datasets._common import dump_json
from pii_guard.eval.datasets.ci import summarize as summarize_counts
from pii_guard.eval.datasets.spec import DATASETS_DIR, Dataset
from pii_guard.eval.fixtures import Document, load_fixtures
from pii_guard.eval.scorer import (
    DocumentResult,
    leak_report,
    match_counts,
    over_masked,
    unscored,
)
from pii_guard.vault import normalize_value

__all__ = ["COUNTS_DIR", "PII_GUARD_SYSTEMS", "document_counts", "run_dataset"]

#: Per-document counts, one file per run record.
COUNTS_DIR = DATASETS_DIR / "results"

PII_GUARD_SYSTEMS: dict[str, list[str]] = {
    "rules": ["rules"],
    "fast": ["rules", "ner"],
    "audit": ["rules", "ner", "llm"],
}
_WARMUP = ("Warm-up text without personal data.", "en")


def document_counts(r: DocumentResult) -> dict[str, Any]:
    """Counts for one document: what a bootstrap over documents needs. No text, no values."""
    doc = r.document
    preds = [p for p in r.predicted if not unscored(doc, p)]
    counts = match_counts(doc.spans, preds, "overlap")
    leaks = leak_report(doc, r.masked_text)
    masked = [s for s in r.masked_spans if not unscored(doc, s)]
    out: dict[str, Any] = {
        "id": doc.id,
        "language": doc.language,
        "gold": sum(c.gold for c in counts.values()),
        "tp_gold": sum(c.tp_gold for c in counts.values()),
        "pred": sum(c.pred for c in counts.values()),
        "tp_pred": sum(c.tp_pred for c in counts.values()),
        "values": len(leaks),
        "leaked": sum(v.leaked for v in leaks),
        "masked": len(masked),
        "over_masked": len(over_masked(doc, masked)),
        "detect_ms": round(r.detect_ms, 3),
    }
    leaked_keys = {(v.entity_type, normalize_value(v.value)) for v in leaks if v.leaked}

    def leaked(start: int, end: int) -> bool:
        span = next((s for s in doc.spans if s.start == start and s.end == end), None)
        return span is not None and (span.entity_type, normalize_value(span.text)) in leaked_keys

    for key, field in (("checksum", "valid"), ("perturbed", "kind")):
        marks = doc.meta.get(key) or []
        if not marks:
            continue
        split: Counter[str] = Counter()
        for m in marks:
            bucket = str(m[field]).lower() if field == "valid" else "perturbed"
            split[f"{bucket}_values"] += 1
            split[f"{bucket}_leaked"] += leaked(m["start"], m["end"])
        out[key] = dict(split)
    return out


def _ner_detector() -> dict[str, Any]:
    from pii_guard.detect import ner_resolve
    from pii_guard.eval.baselines.suite import ner_identity

    ident = ner_identity()
    weights = ident.get("safetensors_sha256") or {}
    published = ner_resolve.PUBLISHED
    # The published release: fast mode's default choice, or a local copy of the same weights.
    # Its model name carries the release (v2.0 records keep their old name, xlmr-base-v2-hn).
    if (
        weights.get("model.safetensors") == published.weights_sha256
        or ner_resolve.resolve().source == "published"
    ):
        return {
            "name": "ner",
            "model": f"xlmr-base-{ner_resolve.PUBLISHED_RELEASE}",
            "model_ref": (
                f"{published.repo_id} {ner_resolve.PUBLISHED_RELEASE}, "
                f"revision {published.revision[:12]}"
            ),
            "revision": f"sha256:{published.weights_sha256}",
            "settings": {},
            "serving": "local PyTorch",
        }
    model = str(ident.get("model"))
    short = model.removeprefix("pii-guard-ner-")
    return {
        "name": "ner",
        "model": short,
        "model_ref": f"local checkpoint {model} (LAB-1150, 10 types, not published)"
        if weights
        else model,
        "revision": f"sha256:{weights['model.safetensors']}"
        if "model.safetensors" in weights
        else None,
        "settings": {},
        "serving": "local PyTorch",
    }


def _llm_detector(analyzer: Any) -> dict[str, Any]:
    llm = next(d for d in analyzer.detectors if d.name == "llm")
    effort = getattr(llm, "reasoning_effort", None)
    return {
        "name": "llm",
        "model": getattr(llm, "model", None),
        "model_ref": getattr(llm, "url", None),
        "revision": None,
        "settings": {"reasoning_effort": effort} if effort else {},
        "serving": "remote API",
    }


_LABELS = {
    "rules": "pii-guard rules",
    # The published release; v2.0 records carry "NER v2.0 (published ..., LAB-1306)".
    "fast": "pii-guard fast, NER v4.2 (published watt-mind/pii-guard-ner-xlmr-base, LAB-1625)",
    "audit": "pii-guard audit (rules + NER v2 + LLM)",
}


def _run_pii_guard(system: str, documents: list[Document]) -> tuple[list[DocumentResult], dict]:
    from pii_guard.eval.injection import run_injection
    from pii_guard.eval.scorer import DetectorAnalyzer

    names = PII_GUARD_SYSTEMS[system]
    analyzer = DetectorAnalyzer(names)
    if analyzer.skipped:
        reasons = "; ".join(f"{n}: {why}" for n, why in analyzer.skipped)
        raise RuntimeError(f"{system}: detector unavailable ({reasons})")
    started = time.perf_counter()
    analyzer.analyze(*_WARMUP)
    results, blocked = run_injection(documents, analyzer)
    detectors: list[dict[str, Any]] = [{"name": "rules"}]
    if "ner" in names:
        detectors.append(_ner_detector())
    if "llm" in names:
        detectors.append(_llm_detector(analyzer))
    info = {
        "detectors": detectors,
        "wall_s": round(time.perf_counter() - started, 1),
        "blocked": len(blocked),
        "loaded": analyzer.loaded,
    }
    return results, info


def _run_tool(name: str, documents: list[Document]) -> tuple[list[DocumentResult], dict]:
    from pii_guard.eval.baselines import baseline_section, create_baseline, host_info, run_baseline

    baseline = create_baseline(name)
    started = time.perf_counter()
    try:
        results, unmapped = run_baseline(documents, baseline)
    finally:
        baseline.close()
    section = baseline_section(baseline, results, unmapped)
    section["info"] = {**section["info"], "host": host_info()}
    return results, {"section": section, "wall_s": round(time.perf_counter() - started, 1)}


def _prepare_dataset_documents(
    ds: Dataset, systems: Sequence[str], limit: int | None
) -> tuple[list[Path], list[Document]]:
    paths = ds.fixture_paths()
    missing = [p for p in paths if not p.is_file()]
    if missing:
        raise FileNotFoundError(
            f"{ds.name}: fixture files missing ({', '.join(map(str, missing))}); "
            f"run `python -m pii_guard.eval.datasets fetch {ds.name}` first"
        )
    documents = load_fixtures(paths)
    if limit is not None:  # the first n per language, in file order (the seeded sample order)
        per: Counter[str] = Counter()
        kept = []
        for d in documents:
            if per[d.language] < limit:
                kept.append(d)
                per[d.language] += 1
        documents = kept
    if any(s == "audit" for s in systems) and limit is None:
        raise ValueError("audit calls a remote model: pass --limit N (documents per language)")
    if any(s == "audit" for s in systems) and not ds.synthetic:
        raise ValueError(f"{ds.name}: real documents are never sent to a remote model")
    return paths, documents


def _run_system_records(
    ds: Dataset,
    system: str,
    slug_system: str,
    documents: list[Document],
    paths: list[Path],
    limit: int | None,
    day: str | None,
) -> tuple[list[DocumentResult], list[dict[str, Any]]]:
    from pii_guard.eval.record import build_records, host_info
    from pii_guard.eval.report import build_scorecard

    if system in PII_GUARD_SYSTEMS:
        results, info = _run_pii_guard(system, documents)
        card = build_scorecard(results, detectors=info["loaded"], fixture_paths=paths)
        notes = [f"One warm-up call before timing; wall time {info['wall_s']} s."]
        if info["blocked"]:
            notes.append(f"{info['blocked']} document(s) blocked (fail closed); not scored.")
        if ds.name == "ai4privacy" and "ner" in PII_GUARD_SYSTEMS[system]:
            notes.append("NER v2 trained on OpenPII train rows: in distribution here.")
        records = build_records(
            card,
            slug=f"datasets-{ds.name}-{slug_system}",
            day=day,
            detectors=info["detectors"],
            hardware=host_info(),
            extra={"system": {"label": _LABELS[system]}},
            notes=[*notes, *_dataset_notes(ds, limit)],
        )[:1]
        return results, records

    results, info = _run_tool(system, documents)
    card = build_scorecard(results, detectors=[], fixture_paths=paths)
    card["baselines"] = {system: info["section"]}
    records = build_records(
        card, slug=f"datasets-{ds.name}" + ("" if limit is None else f"-n{limit}"), day=day
    )[1:]
    for rec in records:
        rec["notes"].append(f"Wall time {info['wall_s']} s.")
        rec["notes"].extend(_dataset_notes(ds, limit))
    return results, records


def run_dataset(
    ds: Dataset,
    systems: Sequence[str],
    *,
    record: bool = False,
    limit: int | None = None,
    runs_dir: Path = Path("eval/results/runs"),
    counts_dir: Path = COUNTS_DIR,
    day: str | None = None,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    """Run each system; returns one summary per system. Writes records when ``record``.

    ``tag`` (``--tag``) appends a slug-safe suffix to the run slug
    (``datasets-<set>-<system>[-<tag>]``), so a second fast-mode run on the same day gets
    its own record instead of refusing to overwrite (LAB-1347).
    """
    from pii_guard.eval.record import write_records

    paths, documents = _prepare_dataset_documents(ds, systems, limit)
    summaries = []
    for system in systems:
        slug_system = system if limit is None else f"{system}-n{limit}"
        if tag:
            if not re.match(r"^[a-z0-9][a-z0-9.-]*$", tag):
                raise ValueError(f"--tag {tag!r} must be lower-case letters, digits, '.' and '-'")
            slug_system = f"{slug_system}-{tag}"
        results, records = _run_system_records(
            ds, system, slug_system, documents, paths, limit, day
        )
        rec = records[0]
        counts = {
            "run_id": rec["run_id"],
            "dataset": ds.name,
            "split": ds.split,
            "system": {"key": rec["system"]["key"], "label": rec["system"]["label"]},
            "fixtures": [{"path": f["path"], "sha256": f["sha256"]} for f in rec["fixtures"]],
            "documents": [document_counts(r) for r in results],
        }
        counts["summary"] = summarize_counts(counts["documents"])
        overall = rec["metrics"]["overall"]
        summaries.append(
            {
                "system": system,
                "run_id": rec["run_id"],
                "documents": overall["documents"],
                "leak": overall["leak"]["rate"],
                "f1": overall["overlap"]["f1"],
                "over_masking": overall["over_masking"]["rate"],
            }
        )
        if record:
            for path in write_records(records, runs_dir):
                print(f"datasets: wrote {path}", file=sys.stderr)
            counts_dir.mkdir(parents=True, exist_ok=True)
            out = counts_dir / f"{rec['run_id']}.json"
            out.write_text(dump_counts(counts), encoding="utf-8")
            print(f"datasets: wrote {out}", file=sys.stderr)
    return summaries


def dump_counts(counts: Mapping[str, Any]) -> str:
    """The counts file: readable header, one compact line per document (small diffs)."""
    head = {k: v for k, v in counts.items() if k != "documents"}
    lines = [json.dumps(d, ensure_ascii=False, separators=(",", ":")) for d in counts["documents"]]
    body = dump_json(head).rstrip()[:-1].rstrip()  # reopen the object
    return body + ',\n  "documents": [\n    ' + ",\n    ".join(lines) + "\n  ]\n}\n"


def _dataset_notes(ds: Dataset, limit: int | None) -> list[str]:
    notes = [f"Dataset {ds.name} ({ds.license}), {ds.split} split; docs/datasets.md."]
    if limit is not None:
        notes.append(f"Fixed sample: the first {limit} documents per language.")
    if not ds.commit_rows:
        notes.append("Fixture files are rebuilt locally by fetch, not committed.")
    return notes


def print_summaries(summaries: Sequence[Mapping[str, Any]]) -> None:
    for s in summaries:
        print(json.dumps(s, ensure_ascii=False))
