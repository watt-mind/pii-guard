"""The benchmark index: every run record, flattened and pooled for charts, tables and the UI.

``build_index(records)`` returns the content of ``eval/results/index.json`` (format
``schema_version`` 1, documented in ``docs/evaluation.md#the-index``):

- ``runs``: run metadata in chronological order (date, then ``recorded_at``, then id);
- ``rows``: one entry per text run and language, with compact metrics;
- ``history``: runs of the same system on the same fixture set at the same commit and date,
  merged (the NER study ran one file per language), each with per-language and pooled
  (``all``) metrics; this is what "progress over time" plots;
- ``snapshots``: for each fixture set and system, the latest result per language *on the
  set's current fixture version* and their pooled ``all``: what the comparison charts and
  tables show. A set's current version is, per language, the SHA-256 of the fixture file its
  newest run used (``fixture_sets[set].fixtures``). A snapshot says which files it used
  (``fixtures``), which current languages it lacks (``missing_languages``) and whether it
  covers them all (``complete``): only complete snapshots of one set compare on pooled
  numbers, since otherwise the documents differ;
- ``stale_snapshots``: the same for languages a system was run on only with an earlier
  version of the fixture file (``superseded``), kept for reference, never pooled with current
  results;
- ``visual``: the image-masking runs;
- ``latency``: the gateway latency runs (``pii-guard bench latency``), one entry per run with
  its cells (mode, concurrency, streaming: overhead and stage percentiles). They are listed in
  ``runs`` but are not detection systems, so they stay out of ``systems`` and
  ``fixture_sets``;
- ``systems``, ``fixture_sets``, ``languages``, ``entity_types``: the vocabularies, all
  derived from the data (a new language, detector or set shows up without code changes);
- ``colours``: the visual-recall and latency chart colour of each system present. System,
  visual and latency colours come from the committed registry
  (:mod:`pii_guard.eval.report_colours`), so adding a system never recolours another.

Pooling is exact for every count-based metric (P/R/F1, leak, over-masking, round trip,
consistency, per-type recall): counts are summed, then divided, so a pooled rate is
micro-averaged (each document, span or value weighs the same; a large language weighs more).
Latency percentiles can't be pooled: a pooled ``all`` built from several runs carries the
document-weighted mean of their p50/p95 and ``latency_pooled: true``.

The output is a pure function of the records (no timestamps), so ``pii-guard eval report
--check`` can compare it byte for byte.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pii_guard.config import DEFAULT_DETECTORS
from pii_guard.eval.report_colours import PALETTE_LATENCY, PALETTE_VISUAL, SECTIONS, assign
from pii_guard.types import EntityType

__all__ = [
    "INDEX_SCHEMA_VERSION",
    "PALETTE_COMPARISON",
    "PALETTE_OURS",
    "SHA_DIGITS",
    "build_index",
    "compact",
    "compact_validity",
    "current_versions",
    "fixture_shas",
    "pool",
    "pool_validity",
    "run_order",
]

INDEX_SCHEMA_VERSION = 1

#: Colour-blind-safe colours for pii-guard systems (Okabe-Ito, then Paul Tol's muted set). A
#: new system takes the least-used one (see :mod:`~pii_guard.eval.report_colours`); ordered so
#: neighbours differ in hue *and* lightness (no two greens or two pinks among the first seven).
PALETTE_OURS = [
    "#0072B2",  # blue
    "#009E73",  # bluish green
    "#D55E00",  # vermillion
    "#CC79A7",  # reddish purple
    "#332288",  # indigo
    "#999933",  # olive
    "#882255",  # wine
    "#117733",  # green
    "#AA4499",  # purple
    "#E69F00",  # orange
]
#: Comparison tools are grey and told apart by marker shape.
PALETTE_COMPARISON = ["#595959", "#595959", "#595959", "#595959", "#595959", "#595959"]
SHAPES_COMPARISON = ["square", "triangle", "diamond", "cross", "square", "triangle"]

_STYLES_OURS = [{"color": c, "shape": "circle"} for c in PALETTE_OURS]
_STYLES_COMPARISON: list[dict[str, str]] = []
for _c, _s in zip(PALETTE_COMPARISON, SHAPES_COMPARISON, strict=True):
    if {"color": _c, "shape": _s} not in _STYLES_COMPARISON:
        _STYLES_COMPARISON.append({"color": _c, "shape": _s})

_TYPE_ORDER = {t.value: i for i, t in enumerate(EntityType)}


def _r(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def _f1(p: float | None, r: float | None) -> float | None:
    if p is None or r is None:
        return None
    return 0.0 if p + r == 0 else 2 * p * r / (p + r)


def type_order(names: Iterable[str]) -> list[str]:
    """Entity types in the taxonomy's order; types it doesn't know yet go last, by name."""
    return sorted(set(names), key=lambda n: (_TYPE_ORDER.get(n, len(_TYPE_ORDER)), n))


def run_order(record: Mapping[str, Any]) -> tuple[str, str, str]:
    return (record["date"], record.get("recorded_at") or "", record["run_id"])


#: Hex digits of a fixture file's SHA-256 kept in the index (enough to tell versions apart).
SHA_DIGITS = 12


def fixture_shas(record: Mapping[str, Any]) -> dict[str, str | None]:
    """Per language of a text run: the (short) SHA-256 of the fixture file it was scored on.

    A record whose fixtures carry no language (one file for the whole run) uses that file for
    every language; a language with no file recorded maps to ``None``.
    """
    by_lang: dict[str | None, str | None] = {}
    for f in record["fixtures"]:
        sha = f.get("sha256")
        by_lang[f["language"]] = sha[:SHA_DIGITS] if sha else None
    fallback = by_lang.get(None) if len(by_lang) == 1 else None
    return {lang: by_lang.get(lang, fallback) for lang in record["metrics"].get("languages", {})}


def current_versions(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, str | None]]:
    """Per text fixture set and language: the fixture SHA of the newest run (run order)."""
    out: dict[str, dict[str, str | None]] = defaultdict(dict)
    for rec in sorted(records, key=run_order):
        if rec["kind"] != "text":
            continue
        for lang, sha in fixture_shas(rec).items():
            out[rec["fixture_set"]][lang] = sha
    return {name: dict(sorted(v.items())) for name, v in sorted(out.items())}


# --- Pooling ------------------------------------------------------------------------------


def pool(blocks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Pool run-record text blocks (several languages or runs) into one, from their counts."""
    if len(blocks) == 1:
        return dict(blocks[0])

    def total(get: Any) -> int:
        return sum(get(b) for b in blocks)

    def match(kind: str) -> dict[str, Any]:
        gold = total(lambda b: b[kind]["gold"])
        pred = total(lambda b: b[kind]["pred"])
        tp_pred = total(lambda b: b[kind]["tp_pred"])
        tp_gold = total(lambda b: b[kind]["tp_gold"])
        p, r = _ratio(tp_pred, pred), _ratio(tp_gold, gold)
        return {
            "gold": gold,
            "pred": pred,
            "tp_pred": tp_pred,
            "tp_gold": tp_gold,
            "precision": p,
            "recall": r,
            "f1": _f1(p, r),
        }

    per_type: dict[str, Any] = {}
    for name in type_order(n for b in blocks for n in b["per_type"]):
        items = [b["per_type"][name] for b in blocks if name in b["per_type"]]
        leaks = [i["leak"] for i in items if i["leak"] is not None]
        overs = [i["over_masking"] for i in items if i["over_masking"] is not None]
        per_type[name] = {
            **{
                k: sum(i[k] for i in items)
                for k in (
                    "gold",
                    "pred",
                    "exact_tp_gold",
                    "exact_tp_pred",
                    "overlap_tp_gold",
                    "overlap_tp_pred",
                )
            },
            "leak": {k: sum(x[k] for x in leaks) for k in ("values", "leaked", "partial")}
            if leaks
            else None,
            "over_masking": {k: sum(x[k] for x in overs) for k in ("masked", "over_masked")}
            if overs
            else None,
        }
    macro = [
        _f1(_ratio(t["overlap_tp_pred"], t["pred"]), _ratio(t["overlap_tp_gold"], t["gold"]))
        for t in per_type.values()
        if t["gold"] or t["pred"]
    ]
    macro_values = [m if m is not None else 0.0 for m in macro]
    leak_values = total(lambda b: b["leak"]["values"])
    leaked = total(lambda b: b["leak"]["leaked"])
    partial = total(lambda b: b["leak"]["partial"])
    masked = total(lambda b: b["over_masking"]["masked"])
    over = total(lambda b: b["over_masking"]["over_masked"])
    roundtrips = [b["roundtrip"] for b in blocks]
    consistency = [b["consistency"] for b in blocks]
    docs = [b["documents"] for b in blocks]

    def latency(stage: str) -> dict[str, Any] | None:
        parts = [(b["latency_ms"][stage], n) for b, n in zip(blocks, docs, strict=True)]
        if any(p is None or p.get("p50") is None for p, _ in parts) or not sum(docs):
            return None
        return {
            q: sum(p[q] * n for p, n in parts) / sum(docs)  # type: ignore[index]
            for q in ("p50", "p95")
        }

    return {
        "documents": sum(docs),
        "gold_spans": total(lambda b: b["gold_spans"]),
        "predicted_spans": total(lambda b: b["predicted_spans"]),
        "unscored_predictions": total(lambda b: b.get("unscored_predictions", 0)),
        "exact": match("exact"),
        "overlap": match("overlap"),
        "macro_f1_overlap": sum(macro_values) / len(macro_values) if macro_values else None,
        "leak": {
            "values": leak_values,
            "leaked": leaked,
            "partial": partial,
            "rate": _ratio(leaked, leak_values),
            "partial_rate": _ratio(partial, leak_values),
        },
        "over_masking": {"masked": masked, "over_masked": over, "rate": _ratio(over, masked)},
        "roundtrip": (
            None
            if any(r is None for r in roundtrips)
            else {
                "documents": sum(r["documents"] for r in roundtrips),  # type: ignore[index]
                "exact": sum(r["exact"] for r in roundtrips),  # type: ignore[index]
                "rate": _ratio(
                    sum(r["exact"] for r in roundtrips), sum(r["documents"] for r in roundtrips)
                ),  # type: ignore[index]
            }
        ),
        "consistency": (
            None
            if any(c is None for c in consistency)
            else {
                "rate": _ratio(
                    sum(c["consistent"] for c in consistency),
                    sum(c["entities"] for c in consistency),
                ),  # type: ignore[index]
                "multi_rate": _ratio(
                    sum(c["multi_consistent"] for c in consistency),  # type: ignore[index]
                    sum(c["multi_occurrence"] for c in consistency),  # type: ignore[index]
                ),
                **{
                    k: sum(c[k] for c in consistency)  # type: ignore[index]
                    for k in ("entities", "consistent", "multi_occurrence", "multi_consistent")
                },
            }
        ),
        "latency_ms": {"detect": latency("detect"), "mask": latency("mask")},
        "per_type": per_type,
        "latency_pooled": True,
        **({"validity": v} if (v := pool_validity(blocks)) else {}),
    }


_VALIDITY_PARTS = ("valid", "invalid", "excluding_number_types")
_VALIDITY_COUNTS = ("gold", "found", "values", "leaked")


def _sum_counts(items: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {k: sum(int(i[k]) for i in items) for k in _VALIDITY_COUNTS}


def _headline_counts(block: Mapping[str, Any]) -> dict[str, int]:
    return {
        "gold": block["overlap"]["gold"],
        "found": block["overlap"]["tp_gold"],
        "values": block["leak"]["values"],
        "leaked": block["leak"]["leaked"],
    }


def pool_validity(blocks: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The number-validity breakdowns of ``blocks`` summed, or ``None`` if one has none.

    A pooled ``source`` is ``None`` only when every block computed it in the run itself;
    ``matches_headline`` holds when every re-run reproduced its record's counts, and
    ``rerun_headline`` otherwise sums what the breakdowns add up to.
    """
    vals = [b.get("validity") for b in blocks]
    if not vals or any(not v for v in vals):
        return None
    out: dict[str, Any] = {k: _sum_counts([v[k] for v in vals]) for k in _VALIDITY_PARTS}
    per_type: dict[str, Any] = {}
    for name in type_order(n for v in vals for n in v["per_type"]):
        rows = [v["per_type"][name] for v in vals if name in v["per_type"]]
        per_type[name] = {c: _sum_counts([r[c] for r in rows]) for c in ("valid", "invalid")}
    out["per_type"] = per_type
    sources = [v.get("source") for v in vals]
    if all(s is None for s in sources):
        out["source"] = None
        return out
    matches = all(s is None or s["matches_headline"] for s in sources)
    rerun = [
        (s or {}).get("rerun_headline") or _headline_counts(b)
        for s, b in zip(sources, blocks, strict=True)
    ]
    out["source"] = {
        "by": "+".join(sorted({s["by"] for s in sources if s})),
        "method": "rerun",
        "commit": "+".join(sorted({s["commit"] for s in sources if s})),
        "date": "+".join(sorted({s["date"] for s in sources if s})),
        "matches_headline": matches,
        "rerun_headline": None if matches else _sum_counts(rerun),
        "note": " ".join(dict.fromkeys(s["note"] for s in sources if s)),
    }
    return out


def _compact_counts(c: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **{k: int(c[k]) for k in _VALIDITY_COUNTS},
        "recall": _r(_ratio(c["found"], c["gold"])),
        "leak": _r(_ratio(c["leaked"], c["values"])),
    }


def compact_validity(v: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The validity breakdown with rates, for tables, charts and the UI."""
    if not v:
        return None
    source = v.get("source")
    rerun = (source or {}).get("rerun_headline")
    return {
        **{k: _compact_counts(v[k]) for k in _VALIDITY_PARTS},
        "per_type": {
            name: {c: _compact_counts(row[c]) for c in ("valid", "invalid")}
            for name, row in v["per_type"].items()
        },
        "rerun": source is not None,
        "matches_headline": source is None or bool(source["matches_headline"]),
        "rerun_leak": None if not rerun else _r(_ratio(rerun["leaked"], rerun["values"])),
        "by": None if source is None else source["by"],
    }


def compact(block: Mapping[str, Any]) -> dict[str, Any]:
    """The few numbers charts, tables and the UI need, rounded (rates 0-1, 4 decimals)."""
    detect = block["latency_ms"].get("detect") or {}
    rt, cons = block.get("roundtrip"), block.get("consistency")
    per_type = {}
    for name in type_order(block["per_type"]):
        t = block["per_type"][name]
        leak = t["leak"]
        per_type[name] = {
            "gold": t["gold"],
            "recall": _r(_ratio(t["overlap_tp_gold"], t["gold"])),
            "precision": _r(_ratio(t["overlap_tp_pred"], t["pred"])),
            "leak": None if leak is None else _r(_ratio(leak["leaked"], leak["values"])),
            "leak_values": None if leak is None else leak["values"],
        }
    return {
        "documents": block["documents"],
        "gold": block["gold_spans"],
        "pred": block["predicted_spans"],
        "unscored": block.get("unscored_predictions", 0),
        "precision": _r(block["overlap"]["precision"]),
        "recall": _r(block["overlap"]["recall"]),
        "f1": _r(block["overlap"]["f1"]),
        "f1_exact": _r(block["exact"]["f1"]),
        "macro_f1": _r(block.get("macro_f1_overlap")),
        "leak": _r(block["leak"]["rate"]),
        "partial_leak": _r(block["leak"]["partial_rate"]),
        "leak_values": block["leak"]["values"],
        "over_masking": _r(block["over_masking"]["rate"]),
        "roundtrip": None if rt is None else _r(rt["rate"]),
        "consistency": None if cons is None else _r(cons["rate"]),
        "detect_p50_ms": _r(detect.get("p50"), 3),
        "detect_p95_ms": _r(detect.get("p95"), 3),
        "latency_pooled": bool(block.get("latency_pooled", False)),
        "per_type": per_type,
        **({"validity": compact_validity(block["validity"])} if block.get("validity") else {}),
    }


# --- Index --------------------------------------------------------------------------------


def _short_label(label: str) -> str:
    return label.removeprefix("pii-guard ").strip() or label


def _origin(origins: Iterable[str]) -> str:
    found = sorted(set(origins))
    return found[0] if len(found) == 1 else "mixed"


def _systems(
    records: Sequence[Mapping[str, Any]],
    featured: Sequence[str],
    registry: dict[str, Any],
) -> dict[str, Any]:
    latest: dict[str, Mapping[str, Any]] = {}
    for rec in sorted(records, key=run_order):
        latest[rec["system"]["key"]] = rec
    ours = [k for k in featured if k in latest and latest[k]["system"]["family"] == "pii-guard"]
    ours += sorted(
        k for k, r in latest.items() if r["system"]["family"] == "pii-guard" and k not in ours
    )
    theirs = [k for k in featured if k in latest and latest[k]["system"]["family"] == "comparison"]
    theirs += sorted(
        k for k, r in latest.items() if r["system"]["family"] == "comparison" and k not in theirs
    )
    default_key = "+".join(DEFAULT_DETECTORS)
    assign(registry, ours, _STYLES_OURS)
    assign(registry, theirs, _STYLES_COMPARISON)
    out: dict[str, Any] = {key: dict(registry[key]) for key in [*ours, *theirs]}
    for key, style in out.items():
        system = latest[key]["system"]
        style.update(
            {
                "label": system["label"],
                "short_label": _short_label(system["label"]),
                "family": system["family"],
                "tool": system["tool"],
                "kind": latest[key]["kind"],
                "detectors": [d["name"] for d in system["detectors"]],
                "models": [d["model"] for d in system["detectors"] if d.get("model")],
                "featured": key in featured,
                "default": key == default_key,
            }
        )
    return out


def build_index(
    records: Sequence[Mapping[str, Any]],
    *,
    featured: Sequence[str] = (),
    digests: Mapping[str, str] | None = None,
    colours: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The index (see the module docstring) from validated run records.

    ``colours`` is the colour registry (:func:`~pii_guard.eval.report_colours.load_registry`);
    systems it lacks are appended to it in place. Without one, colours are assigned as if the
    registry were empty.
    """
    if colours is None:
        colours = {}
    for name in SECTIONS:
        colours.setdefault(name, {})
    records = sorted(records, key=run_order)
    text = [r for r in records if r["kind"] == "text"]
    scored = [r for r in records if r["kind"] != "latency"]
    systems = _systems(scored, featured, colours["systems"])

    runs = []
    for rec in records:
        cost = rec.get("cost")
        runs.append(
            {
                "run_id": rec["run_id"],
                "kind": rec["kind"],
                "date": rec["date"],
                "recorded_at": rec.get("recorded_at"),
                "source": rec["source"],
                "title": rec["title"],
                "commit": rec["code"]["commit"],
                "dirty": rec["code"]["dirty"],
                "system": rec["system"]["key"],
                "fixture_set": rec["fixture_set"],
                "origin": _origin(f["origin"] for f in rec["fixtures"]),
                "languages": list(rec["languages"]),
                "detectors": [
                    {k: d[k] for k in ("name", "model", "model_ref", "settings", "serving")}
                    for d in rec["system"]["detectors"]
                ],
                "hardware": (rec.get("hardware") or {}).get("description"),
                "cost": None
                if not cost
                else {
                    k: cost.get(k)
                    for k in ("usd", "estimated", "gpu_minutes", "note", "shared_with")
                },
                "notes": list(rec["notes"]),
                "rescored": None
                if not rec.get("rescored")
                else {k: rec["rescored"][k] for k in ("by", "method", "note")},
                "imported_from": (rec.get("imported_from") or {}).get("path"),
            }
        )

    versions = current_versions(text)
    rows = []
    for rec in text:
        origin = {f["language"]: f["origin"] for f in rec["fixtures"]}
        shas = fixture_shas(rec)
        for lang, block in rec["metrics"]["languages"].items():
            rows.append(
                {
                    "run_id": rec["run_id"],
                    "system": rec["system"]["key"],
                    "fixture_set": rec["fixture_set"],
                    "origin": origin.get(lang) or _origin(origin.values()),
                    "language": lang,
                    "fixture": shas[lang],
                    "current": shas[lang] == versions[rec["fixture_set"]][lang],
                    "date": rec["date"],
                    "commit": rec["code"]["commit"],
                    "metrics": compact(block),
                }
            )

    # History: same system + set + commit + date merged (one run per language counts once).
    groups: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for rec in text:
        groups[
            (rec["system"]["key"], rec["fixture_set"], rec["code"]["commit"], rec["date"])
        ].append(rec)
    history = []
    for (system, fixture_set, commit, day), recs in groups.items():
        by_lang: dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
        for rec in recs:  # chronological: a later run of a language wins
            for lang, block in rec["metrics"]["languages"].items():
                by_lang[lang] = (rec, block)
        all_block = _pooled_all(by_lang)
        shas = {lang: fixture_shas(r)[lang] for lang, (r, _) in sorted(by_lang.items())}
        history.append(
            {
                "system": system,
                "fixture_set": fixture_set,
                "origin": _origin(f["origin"] for r in recs for f in r["fixtures"]),
                "date": day,
                "commit": commit,
                "order": run_order(recs[0]),
                "run_ids": [r["run_id"] for r in recs],
                "fixtures": shas,
                # Same documents as the set's current snapshots: every current language, on
                # the current file. Other points are not directly comparable with them.
                "comparable": shas == versions[fixture_set],
                "rescored": any(bool(r.get("rescored")) for r in recs),
                "languages": {lang: compact(b) for lang, (_, b) in sorted(by_lang.items())},
                "all": compact(all_block),
            }
        )
    history.sort(key=lambda h: (h["order"], h["system"]))
    for h in history:
        del h["order"]

    snapshots, stale_snapshots = _snapshots(text, versions)

    fixture_sets: dict[str, Any] = {}
    for rec in scored:
        for f in rec["fixtures"]:
            entry = fixture_sets.setdefault(
                f["set"],
                {
                    "origin": set(),
                    "languages": set(),
                    "documents": {},
                    "generators": set(),
                    "kind": rec["kind"],
                },
            )
            entry["origin"].add(f["origin"])
            if f["language"]:
                entry["languages"].add(f["language"])
                current = versions.get(rec["fixture_set"], {}).get(f["language"])
                sha = (f.get("sha256") or "")[:SHA_DIGITS] or None
                if f["documents"] is not None and (current is None or sha == current):
                    entry["documents"][f["language"]] = f["documents"]
            elif f["documents"] is not None:
                entry["documents"]["all"] = f["documents"]
            if f["generator"]:
                entry["generators"].add(f["generator"])
    for rec in text:  # sets whose files aren't committed: take document counts from metrics
        current = versions[rec["fixture_set"]]
        for lang, block in rec["metrics"]["languages"].items():
            if fixture_shas(rec)[lang] == current[lang]:
                fixture_sets[rec["fixture_set"]]["documents"].setdefault(lang, block["documents"])
    fixture_sets = {
        name: {
            "origin": _origin(v["origin"]),
            "kind": v["kind"],
            "languages": sorted(v["languages"]),
            "documents": dict(sorted(v["documents"].items())),
            "generators": sorted(v["generators"]),
            "fixtures": versions.get(name, {}),
        }
        for name, v in sorted(fixture_sets.items())
    }

    visual = []
    for rec in records:
        if rec["kind"] != "visual":
            continue
        m = rec["metrics"]
        visual.append(
            {
                "run_id": rec["run_id"],
                "date": rec["date"],
                "commit": rec["code"]["commit"],
                "system": rec["system"]["key"],
                "notes": list(rec["notes"]),
                "fixture_set": rec["fixtures"][0]["set"] if rec["fixtures"] else None,
                "specimens": m["specimens"],
                "overall": m["overall"],
                "by_region_type": m["by_region_type"],
                "by_doc_type": m["by_doc_type"],
                "countries": len(m["by_country"]),
                "over_masking_mean": m["over_masking_mean"],
                "cost_usd": (rec.get("cost") or {}).get("usd"),
            }
        )

    latency = [
        {
            "run_id": rec["run_id"],
            "date": rec["date"],
            "commit": rec["code"]["commit"],
            "system": rec["system"]["key"],
            "label": rec["system"]["label"],
            "detectors": [d["name"] for d in rec["system"]["detectors"]],
            "models": [d["model"] for d in rec["system"]["detectors"] if d.get("model")],
            "hardware": (rec.get("hardware") or {}).get("description"),
            "upstream_delay_ms": rec["metrics"]["upstream_delay_ms"],
            "cells": rec["metrics"]["cells"],
        }
        for rec in records
        if rec["kind"] == "latency"
    ]

    digest = hashlib.sha256(
        json.dumps(sorted((digests or {}).items()), separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "generated_by": "pii-guard eval report",
        "about": (
            "Generated from eval/results/runs/*.json; do not edit. Rates are 0-1; latency in ms."
        ),
        "runs_digest": digest if digests else None,
        "languages": sorted({lang for rec in text for lang in rec["metrics"]["languages"]}),
        "entity_types": type_order(
            n for rec in text for n in rec["metrics"]["overall"]["per_type"]
        ),
        "fixture_sets": fixture_sets,
        "systems": systems,
        "featured": [k for k in featured if k in systems],
        "runs": runs,
        "rows": rows,
        "history": history,
        "snapshots": snapshots,
        "stale_snapshots": stale_snapshots,
        "visual": visual,
        "latency": latency,
        "colours": {
            "visual": _chart_colours(colours["visual"], visual, PALETTE_VISUAL),
            "latency": _chart_colours(colours["latency"], latency, PALETTE_LATENCY),
        },
    }


def _snapshot(
    fixture_set: str,
    system: str,
    by_lang: Mapping[str, tuple[Mapping[str, Any], Mapping[str, Any]]],
) -> dict[str, Any]:
    recs = {r["run_id"]: r for r, _ in by_lang.values()}
    return {
        "fixture_set": fixture_set,
        "system": system,
        "origin": _origin(f["origin"] for r in recs.values() for f in r["fixtures"]),
        "run_ids": sorted(recs),
        "dates": sorted({r["date"] for r in recs.values()}),
        "commits": sorted({r["code"]["commit"] for r in recs.values()}),
        "fixtures": {lang: fixture_shas(r)[lang] for lang, (r, _) in sorted(by_lang.items())},
        "rescored": any(bool(r.get("rescored")) for r in recs.values()),
        "languages": {lang: compact(b) for lang, (_, b) in sorted(by_lang.items())},
        "all": compact(_pooled_all(by_lang)),
    }


def _snapshots(
    text: Sequence[Mapping[str, Any]], versions: Mapping[str, Mapping[str, str | None]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Current snapshots (latest run per language on the current fixture file) and stale ones.

    A language a system has only on an earlier fixture file goes to the stale snapshot; a run
    on the current file always wins over a newer-looking one on an older file.
    """
    Latest = dict[tuple[str, str], dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]]]
    current: Latest = defaultdict(dict)
    stale: Latest = defaultdict(dict)
    for rec in text:  # chronological: a later run of a language wins
        shas = fixture_shas(rec)
        key = (rec["fixture_set"], rec["system"]["key"])
        for lang, block in rec["metrics"]["languages"].items():
            on_current = shas[lang] == versions[rec["fixture_set"]][lang]
            (current if on_current else stale)[key][lang] = (rec, block)
    snapshots = []
    for (fixture_set, system), by_lang in sorted(current.items()):
        snap = _snapshot(fixture_set, system, by_lang)
        missing = sorted(set(versions[fixture_set]) - set(by_lang))
        snap["missing_languages"] = missing
        snap["complete"] = not missing
        snapshots.append(snap)
    stale_snapshots = []
    for (fixture_set, system), by_lang in sorted(stale.items()):
        only = {
            lang: v
            for lang, v in by_lang.items()
            if lang not in current.get((fixture_set, system), {})
        }
        if not only:
            continue
        snap = _snapshot(fixture_set, system, only)
        snap["superseded"] = snap.pop("fixtures")
        stale_snapshots.append(snap)
    return snapshots, stale_snapshots


def _chart_colours(
    section: dict[str, Any], runs: Sequence[Mapping[str, Any]], palette: Sequence[str]
) -> dict[str, str]:
    """Registry colours of the systems in ``runs`` (first-seen order), assigning new ones."""
    keys = list(dict.fromkeys(str(r["system"]) for r in runs))
    assign(section, keys, palette)
    return {k: section[k] for k in sorted(keys)}


def _pooled_all(
    by_lang: Mapping[str, tuple[Mapping[str, Any], Mapping[str, Any]]],
) -> dict[str, Any]:
    """``all`` over the languages: the run's own overall when one run covers every language."""
    recs = {id(r): r for r, _ in by_lang.values()}
    if len(recs) == 1:
        (rec,) = recs.values()
        if set(rec["metrics"]["languages"]) == set(by_lang):
            return dict(rec["metrics"]["overall"])
    return pool([b for _, b in (by_lang[k] for k in sorted(by_lang))])
