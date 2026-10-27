"""Run records: one versioned JSON file per evaluation run, the input of the benchmark report.

A **run record** (``eval/results/runs/<YYYY-MM-DD>-<slug>.json``) says what ran (the system:
pii-guard detectors with their models and settings, or a comparison tool), on what (fixture
files with their SHA-256, the fixture set, whether it was hand-written or generated), at which
commit, on which hardware, at what cost, and what came out (per-language and per-entity-type
counts and ratios). The format is specified by ``eval/results/schema/run.schema.json``
(``schema_version`` 1) and documented in ``docs/evaluation.md``.

Records are written by ``pii-guard eval --record <slug>`` (a live run) or
``pii-guard eval record SCORECARD.json --slug <slug>`` (a scorecard saved earlier, text or
visual). ``pii-guard eval report`` turns the records into ``eval/results/index.json``, the
charts in ``docs/benchmarks/`` and ``docs/benchmarks.md``.

Nothing is language- or detector-specific here: languages, entity types, detectors, fixture
sets, countries and region types are all data. Like the scorecard, a record never contains a
labelled value or a document text.
"""

from __future__ import annotations

import argparse
import copy
import json
import platform
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from pii_guard.eval.fixtures import file_sha256

__all__ = [
    "DEFAULT_RUNS_DIR",
    "RECORD_SCHEMA_VERSION",
    "SCHEMA_PATH",
    "RecordError",
    "build_records",
    "fixture_info",
    "host_info",
    "load_records",
    "load_schema",
    "main",
    "merge_extra",
    "system_key",
    "text_metrics",
    "validate",
    "visual_metrics",
    "write_records",
]

RECORD_SCHEMA_VERSION = 1
DEFAULT_RUNS_DIR = Path("eval/results/runs")
SCHEMA_PATH = Path("eval/results/schema/run.schema.json")

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
_RUN_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9.-]*$")


class RecordError(ValueError):
    """A run record is malformed, or one can't be built from the input given."""


# --- Metrics ------------------------------------------------------------------------------


def _r(value: object, digits: int = 6) -> float | None:
    return None if value is None else round(float(value), digits)  # type: ignore[arg-type]


def _counts(block: Mapping[str, Any], keys: Sequence[str]) -> dict[str, int]:
    return {k: int(block.get(k, 0)) for k in keys}


def _match(block: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **_counts(block, ("gold", "pred", "tp_pred", "tp_gold")),
        "precision": _r(block.get("precision")),
        "recall": _r(block.get("recall")),
        "f1": _r(block.get("f1")),
    }


def text_metrics(block: Mapping[str, Any], *, reversible: bool = True) -> dict[str, Any]:
    """A scorecard block (:func:`pii_guard.eval.scorer.summarize`) in run-record form.

    Counts are kept next to the ratios so the report can pool languages and runs exactly.
    ``reversible=False`` (a tool whose masking can't be undone) records ``roundtrip`` as
    ``null`` instead of 0.
    """
    det = block["detection"]
    exact_pt, overlap_pt = det["exact"]["per_type"], det["overlap"]["per_type"]
    leak_pt = block["leak"].get("per_type", {})
    over_pt = block["over_masking"].get("per_type", {})
    per_type: dict[str, Any] = {}
    for name in exact_pt:
        ex, ov = exact_pt[name], overlap_pt.get(name, {})
        leak, over = leak_pt.get(name), over_pt.get(name)
        per_type[name] = {
            "gold": int(ex.get("gold", 0)),
            "pred": int(ex.get("pred", 0)),
            "exact_tp_gold": int(ex.get("tp_gold", 0)),
            "exact_tp_pred": int(ex.get("tp_pred", 0)),
            "overlap_tp_gold": int(ov.get("tp_gold", 0)),
            "overlap_tp_pred": int(ov.get("tp_pred", 0)),
            "leak": None if leak is None else _counts(leak, ("values", "leaked", "partial")),
            "over_masking": None if over is None else _counts(over, ("masked", "over_masked")),
        }
    consistency = block.get("consistency")
    latency = block.get("latency_ms", {})
    detect, mask = latency.get("detect"), latency.get("mask")
    return {
        "documents": int(block["documents"]),
        "gold_spans": int(block["gold_spans"]),
        "predicted_spans": int(block["predicted_spans"]),
        "exact": _match(det["exact"]["micro"]),
        "overlap": _match(det["overlap"]["micro"]),
        "macro_f1_overlap": _r(det["overlap"].get("macro", {}).get("f1")),
        "leak": {
            **_counts(block["leak"], ("values", "leaked", "partial")),
            "rate": _r(block["leak"].get("rate")),
            "partial_rate": _r(block["leak"].get("partial_rate")),
        },
        "over_masking": {
            **_counts(block["over_masking"], ("masked", "over_masked")),
            "rate": _r(block["over_masking"].get("rate")),
        },
        "roundtrip": (
            {
                **_counts(block["roundtrip"], ("documents", "exact")),
                "rate": _r(block["roundtrip"]["rate"]),
            }
            if reversible and block.get("roundtrip")
            else None
        ),
        "consistency": (
            None
            if not consistency
            else {
                **_counts(
                    consistency,
                    ("entities", "consistent", "multi_occurrence", "multi_consistent"),
                ),
                "rate": _r(consistency.get("rate")),
                "multi_rate": _r(consistency.get("multi_rate")),
            }
        ),
        "latency_ms": {
            "detect": None
            if not detect
            else {"p50": _r(detect["p50"], 3), "p95": _r(detect["p95"], 3)},
            "mask": None if not mask else {"p50": _r(mask["p50"], 3), "p95": _r(mask["p95"], 3)},
        },
        "per_type": per_type,
    }


def _visual_group(block: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "regions": int(block.get("regions", 0)),
        "recall_iou50": _r(block.get("recall_iou50")),
        "recall_cov90": _r(block.get("recall_cov90")),
        "mean_coverage": _r(block.get("mean_coverage")),
    }
    if "specimens" in block:
        out["specimens"] = int(block["specimens"])
    return out


def visual_metrics(card: Mapping[str, Any]) -> dict[str, Any]:
    """A ``pii-guard eval visual`` result (``suite: visual-specimens``) in run-record form."""
    return {
        "specimens": int(card.get("specimens", 0)),
        "overall": _visual_group(card["overall"]),
        "by_region_type": {k: _visual_group(v) for k, v in card.get("by_region_type", {}).items()},
        "by_doc_type": {k: _visual_group(v) for k, v in card.get("by_doc_type", {}).items()},
        "by_country": {k: _visual_group(v) for k, v in card.get("by_country", {}).items()},
        "over_masking_mean": _r(card.get("over_masking_mean")),
        "errors": len(card.get("errors") or {}),
        "latency_ms": {k: _r(v, 3) for k, v in (card.get("latency_ms") or {}).items()},
    }


# --- Systems, fixtures, hardware ----------------------------------------------------------


def _detector(name: str, **fields: Any) -> dict[str, Any]:
    return {
        "name": name,
        "model": fields.get("model"),
        "model_ref": fields.get("model_ref"),
        "revision": fields.get("revision"),
        "settings": dict(fields.get("settings") or {}),
        "serving": fields.get("serving"),
    }


def system_key(system: Mapping[str, Any]) -> str:
    """A stable id for "the same system": detectors, their models and settings.

    ``rules``, ``rules+ner:xlmr-ner-hu-en-ft``, ``rules+llm:muse-glimmer@reasoning_strength=low``;
    a comparison tool is its tool name (``presidio``).
    """
    if system.get("family") == "comparison":
        return str(system["tool"])
    parts = []
    for det in system.get("detectors", []):
        part = str(det["name"])
        if det.get("model"):
            part += f":{det['model']}"
        settings = det.get("settings") or {}
        if settings:
            part += "@" + ",".join(f"{k}={settings[k]}" for k in sorted(settings))
        parts.append(part)
    return "+".join(parts) or "none"


def _default_label(system: Mapping[str, Any]) -> str:
    if system.get("family") == "comparison":
        return str(system["tool"])
    names = []
    for det in system.get("detectors", []):
        extra = [str(det["model"])] if det.get("model") else []
        extra += [f"{k} {v}" for k, v in sorted((det.get("settings") or {}).items())]
        names.append(det["name"] + (f" ({', '.join(extra)})" if extra else ""))
    return "pii-guard " + " + ".join(names)


def _language_and_set(path: Path, languages: Sequence[str]) -> tuple[str | None, str]:
    """``hu-smoke.jsonl`` -> ``("hu", "smoke")``: a leading language code names the language."""
    stem = path.stem
    head, _, rest = stem.partition("-")
    if rest and (head in languages or (not languages and re.fullmatch(r"[a-z]{2,3}", head))):
        return head, rest
    return (languages[0] if len(languages) == 1 else None), stem


def _origin_from_file(path: Path) -> tuple[str, str | None, int | None, list[str]] | None:
    """``(origin, generator, documents, languages)`` read from a fixture file, if readable."""
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return None
    generators: set[str] = set()
    languages: set[str] = set()
    synthetic = False
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return None
        meta = record.get("meta") or {}
        if meta.get("source") == "synthetic" or meta.get("generator"):
            synthetic = True
            if meta.get("model"):
                generators.add(str(meta["model"]))
        if record.get("language"):
            languages.add(str(record["language"]))
    origin = "generated" if synthetic else "hand-written"
    generator = ", ".join(sorted(generators)) or None
    return origin, generator, len(lines), sorted(languages)


def fixture_info(
    paths: Iterable[str | Path], *, sha256: Mapping[str, str] | None = None
) -> list[dict[str, Any]]:
    """Describe fixture files: path, SHA-256, language, set name, hand-written or generated.

    The origin comes from the file (a record whose ``meta`` names a generator or
    ``source: synthetic`` makes the file *generated*); when the file isn't available (a
    generated split that isn't committed), a set name starting with ``synth`` or ``distill`` is
    taken as generated and anything else as unknown. A file edited since the run (another
    SHA-256) still says whether the set is hand-written, but not how many documents ran.
    """
    out = []
    for raw in paths:
        path = Path(raw)
        digest = (sha256 or {}).get(str(raw))
        current = file_sha256(path) if path.is_file() else None
        info = _origin_from_file(path) if current else None
        # An edited set keeps its origin, but its document count is not the one that ran.
        same_file = digest in (None, current)
        digest = digest or current
        languages = info[3] if info else []
        language, set_name = _language_and_set(path, languages)
        if info:
            origin, generator = info[0], info[1]
            documents = info[2] if same_file else None
        else:
            origin = "generated" if set_name.startswith(("synth", "distill")) else "unknown"
            generator, documents = None, None
        out.append(
            {
                "path": str(raw),
                "sha256": digest,
                "set": set_name,
                "language": language,
                "origin": origin,
                "generator": generator,
                "documents": documents,
            }
        )
    return out


def host_info() -> dict[str, Any]:
    """What machine ran this: platform, CPU architecture and count. Never the host name."""
    import os

    return {
        "description": None,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "accelerator": None,
        "python": platform.python_version(),
    }


# --- Building records ---------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], extra: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in extra.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def merge_extra(record: dict[str, Any], extra: Mapping[str, Any] | None) -> dict[str, Any]:
    """Merge user-supplied fields into a record (``--record-extra`` / ``--extra``).

    ``extra`` is a partial record, deep-merged. ``system.detectors`` may be a mapping from
    detector name to fields (``{"llm": {"model": "muse-glimmer", "settings": {...}}}``) that
    are merged into that detector's entry. ``system.key`` and ``system.label`` are recomputed
    from the merged detectors unless ``extra`` sets them.
    """
    if not extra:
        return record
    extra = copy.deepcopy(dict(extra))
    system_extra = dict(extra.pop("system", {}) or {})
    detectors_extra = system_extra.pop("detectors", None)
    notes_extra = extra.pop("notes", None)
    system = record["system"]
    explicit_key = system.get("key") not in (None, system_key(system))
    explicit_label = system.get("label") not in (None, _default_label(system))
    if isinstance(extra.get("cost"), Mapping) and not record.get("cost"):
        record["cost"] = empty_cost()  # a partial cost is fine: unknown fields stay null
    _deep_merge(record, extra)
    if isinstance(detectors_extra, Mapping):
        for det in system["detectors"]:
            if det["name"] in detectors_extra:
                _deep_merge(det, detectors_extra[det["name"]])
    elif isinstance(detectors_extra, list):
        system["detectors"] = [_detector(**d) for d in detectors_extra]
    _deep_merge(system, {k: v for k, v in system_extra.items() if k not in ("key", "label")})
    if "key" in system_extra or not explicit_key:
        system["key"] = system_extra.get("key") or system_key(system)
    if "label" in system_extra or not explicit_label:
        system["label"] = system_extra.get("label") or _default_label(system)
    if notes_extra:
        record["notes"] = [*record["notes"], *notes_extra]
    return record


def empty_cost() -> dict[str, Any]:
    """A cost block with every field unknown (the schema requires them all, as nulls)."""
    return {
        "usd": None,
        "estimated": False,
        "gpu_minutes": None,
        "model_calls": None,
        "tokens": None,
        "shared_with": [],
        "note": None,
    }


def _base_record(
    *,
    run_id: str,
    kind: str,
    day: str,
    recorded_at: str | None,
    source: str,
    code: Mapping[str, Any],
    system: dict[str, Any],
    fixtures: list[dict[str, Any]],
    languages: list[str],
    metrics: dict[str, Any],
    title: str | None = None,
    hardware: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    system.setdefault("key", system_key(system))
    system.setdefault("label", _default_label(system))
    sets = sorted({f["set"] for f in fixtures}) or ["unknown"]
    return {
        "schema_version": RECORD_SCHEMA_VERSION,
        "run_id": run_id,
        "kind": kind,
        "date": day,
        "recorded_at": recorded_at,
        "source": source,
        "imported_from": None,
        "title": title or f"{system['label']} on {'+'.join(sets)}",
        "notes": [],
        "code": {
            "commit": str(code.get("commit") or "unknown"),
            "dirty": bool(code.get("dirty", False)),
            "pii_guard_version": code.get("pii_guard_version"),
            "note": code.get("note"),
        },
        "system": system,
        "fixture_set": "+".join(sets),
        "fixtures": fixtures,
        "languages": languages,
        "hardware": dict(hardware) if hardware else None,
        "cost": None,
        "metrics": metrics,
    }


def _day_of(stamp: str | None) -> str:
    if stamp:
        try:
            return datetime.fromisoformat(stamp).date().isoformat()
        except ValueError:
            pass
    return date.today().isoformat()


def build_records(
    card: Mapping[str, Any],
    *,
    slug: str,
    source: str = "recorded",
    day: str | None = None,
    detectors: Sequence[Mapping[str, Any]] | None = None,
    hardware: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
    notes: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Run records from a scorecard: one for pii-guard, one per comparison tool in it.

    ``card`` is a text scorecard (:func:`pii_guard.eval.report.build_scorecard`, optionally
    with ``baselines``) or a visual result (``suite: visual-specimens``). ``detectors``
    describes the detectors that ran (``name``, ``model``, ``settings`` …); by default only
    their names are known. ``extra`` is merged into the pii-guard record (see
    :func:`merge_extra`); comparison-tool records keep their own ``info``.
    """
    if not _SLUG_RE.match(slug):
        raise RecordError(f"slug {slug!r} must be lower-case letters, digits, '.' and '-'")
    if card.get("suite") == "visual-specimens":
        return [
            _visual_record(
                card, slug=slug, source=source, day=day, hardware=hardware, extra=extra, notes=notes
            )
        ]
    if "overall" not in card or "meta" not in card:
        raise RecordError("not a pii-guard scorecard (no 'meta' / 'overall')")
    meta = card["meta"]
    recorded_at = meta.get("generated_at")
    day = day or _day_of(recorded_at)
    run_id = f"{day}-{slug}"
    fixtures = fixture_info(
        [f["path"] for f in meta.get("fixtures", [])],
        sha256={f["path"]: f.get("sha256") for f in meta.get("fixtures", [])},
    )
    languages = sorted(card.get("languages", {}))
    dets = [_detector(**d) for d in (detectors or [{"name": n} for n in meta.get("detectors", [])])]
    code = {k: meta.get(k) for k in ("commit", "dirty", "pii_guard_version")}
    ours = _base_record(
        run_id=run_id,
        kind="text",
        day=day,
        recorded_at=recorded_at,
        source=source,
        code=code,
        system={
            "family": "pii-guard",
            "tool": "pii-guard",
            "version": meta.get("pii_guard_version"),
            "detectors": dets,
        },
        fixtures=fixtures,
        languages=languages,
        metrics={
            "overall": text_metrics(card["overall"]),
            "languages": {lang: text_metrics(b) for lang, b in sorted(card["languages"].items())},
        },
        hardware=hardware,
    )
    for skipped in meta.get("skipped_detectors", []):
        ours["notes"].append(f"detector {skipped['name']!r} skipped: {skipped['reason']}")
    ours["notes"].extend(notes)
    merge_extra(ours, extra)
    records = [ours]
    for name, section in sorted((card.get("baselines") or {}).items()):
        info = section.get("info") or {}
        reversible = bool(section.get("reversible", True))
        versions = info.get("versions") or {}
        version = next(iter(versions.values()), None) if versions else None
        host = info.get("host")
        rec = _base_record(
            run_id=f"{run_id}-{name}",
            kind="text",
            day=day,
            recorded_at=recorded_at,
            source=source,
            code=code,
            system={
                "family": "comparison",
                "tool": name,
                "version": version,
                "label": _TOOL_LABELS.get(name, name),
                "detectors": [
                    _detector(
                        name,
                        model=", ".join(str(m) for m in info.get("models", [])) or None,
                        settings={},
                    )
                ],
                "info": info,
            },
            fixtures=copy.deepcopy(fixtures),
            languages=languages,
            metrics={
                "overall": text_metrics(section["overall"], reversible=reversible),
                "languages": {
                    lang: text_metrics(b, reversible=reversible)
                    for lang, b in sorted(section.get("languages", {}).items())
                },
            },
            hardware=(
                {
                    "description": f"{host.get('machine')}, {host.get('cpu_count')} CPUs, CPU only",
                    **{k: host.get(k) for k in ("platform", "machine", "cpu_count", "python")},
                    "accelerator": None,
                }
                if host
                else hardware
            ),
            title=(
                f"{_TOOL_LABELS.get(name, name)} (comparison) on "
                f"{'+'.join(sorted({f['set'] for f in fixtures}))}"
            ),
        )
        if section.get("unmapped_labels"):
            rec["notes"].append(
                "unmapped tool labels: " + ", ".join(sorted(section["unmapped_labels"]))
            )
        records.append(rec)
    return records


_TOOL_LABELS = {"presidio": "Presidio", "llm-guard": "LLM Guard", "privaite": "PrivAiTe"}


def _visual_record(
    card: Mapping[str, Any],
    *,
    slug: str,
    source: str,
    day: str | None,
    hardware: Mapping[str, Any] | None,
    extra: Mapping[str, Any] | None,
    notes: Sequence[str],
) -> dict[str, Any]:
    pipe = card.get("pipeline") or {}
    day = day or date.today().isoformat()
    sam = card.get("sam") or {}
    detectors = [
        _detector(
            "sam",
            model=pipe.get("sam_model"),
            settings={
                "prompts": json.dumps(
                    pipe.get("sam_prompts") or {}, sort_keys=True, ensure_ascii=False
                )
            },
        ),
        _detector("ocr", model=pipe.get("ocr_engine")),
        _detector(str(pipe.get("text_detector") or "rules")),
    ]
    system = {
        "family": "pii-guard",
        "tool": "pii-guard",
        "version": None,
        "detectors": detectors,
        "key": "visual:" + "+".join(str(d["model"] or d["name"]) for d in detectors),
        "label": "pii-guard image masking ("
        + " + ".join(str(d["model"] or d["name"]) for d in detectors)
        + ")",
    }
    record = _base_record(
        run_id=f"{day}-{slug}",
        kind="visual",
        day=day,
        recorded_at=None,
        source=source,
        code={"commit": "unknown", "dirty": False},
        system=system,
        fixtures=[
            {
                "path": "eval/visual/manifest.json",
                "sha256": None,
                "set": "specimens",
                "language": None,
                "origin": "specimens",
                "generator": None,
                "documents": int(card.get("specimens", 0)),
            }
        ],
        languages=[],
        metrics=visual_metrics(card),
        hardware=hardware,
    )
    if sam:
        record["cost"] = {
            "usd": _r(sam.get("estimated_cost_usd"), 4),
            "estimated": True,
            "gpu_minutes": None,
            "model_calls": sam.get("calls"),
            "tokens": None,
            "shared_with": [],
            "note": (
                f"SAM {pipe.get('sam_model')}: {sam.get('calls')} calls at "
                f"${sam.get('cost_per_call_usd')}/call (planning estimate; responses report no "
                "price)"
            ),
        }
    record["notes"].extend(notes)
    return merge_extra(record, extra)


# --- Schema validation --------------------------------------------------------------------

#: The JSON Schema keywords :func:`validate` implements (a subset of draft 2020-12). The
#: committed schema may only use these; a test enforces it.
SUPPORTED_KEYWORDS = frozenset(
    {
        "$schema", "$id", "$defs", "$ref", "$comment", "title", "description", "examples",
        "type", "properties", "required", "additionalProperties", "items", "enum", "const",
        "pattern", "propertyNames", "minimum", "maximum", "minLength", "anyOf", "default",
    }
)  # fmt: skip

_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "null": (type(None),),
}


def _type_ok(value: object, name: str) -> bool:
    if name in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[name])


def _validate(
    value: Any, schema: Mapping[str, Any], root: Mapping[str, Any], path: str, errors: list[str]
) -> None:
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            raise RecordError(f"unsupported $ref {ref!r}")
        _validate(value, root["$defs"][ref.removeprefix("#/$defs/")], root, path, errors)
        return
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            trial: list[str] = []
            _validate(value, option, root, path, trial)
            if not trial:
                break
        else:
            errors.append(f"{path}: matches none of the allowed forms")
            return
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(value, n) for n in names):
            errors.append(f"{path}: expected {'/'.join(names)}, got {type(value).__name__}")
            return
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must be {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not one of {schema['enum']}")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: shorter than {schema['minLength']}")
    if isinstance(value, int | float) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above {schema['maximum']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing {key!r}")
        props = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            if "propertyNames" in schema:
                _validate(key, schema["propertyNames"], root, f"{path}.{key}<name>", errors)
            if key in props:
                _validate(item, props[key], root, f"{path}.{key}", errors)
            elif additional is False:
                errors.append(f"{path}: unexpected field {key!r}")
            elif isinstance(additional, dict):
                _validate(item, additional, root, f"{path}.{key}", errors)
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            _validate(item, schema["items"], root, f"{path}[{i}]", errors)


def load_schema(path: str | Path = SCHEMA_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate(record: Mapping[str, Any], schema: Mapping[str, Any] | None = None) -> list[str]:
    """Errors of ``record`` against the run-record schema (empty list = valid).

    Besides the JSON Schema, checks what a schema can't say: ``metrics`` matches ``kind``, and
    ``system.key`` is what :func:`system_key` computes unless set explicitly (visual runs).
    """
    schema = schema if schema is not None else load_schema()
    errors: list[str] = []
    _validate(record, schema, schema, "$", errors)
    if errors:
        return errors
    kind, metrics = record["kind"], record["metrics"]
    if kind == "text" and "languages" not in metrics:
        errors.append("$.metrics: a text run needs 'overall' and 'languages'")
    if kind == "visual" and "by_region_type" not in metrics:
        errors.append("$.metrics: a visual run needs 'by_region_type'")
    if kind == "latency" and "cells" not in metrics:
        errors.append("$.metrics: a latency run needs 'cells'")
    if not str(record["run_id"]).startswith(record["date"]):
        errors.append("$.run_id: must start with the run date")
    return errors


# --- Files --------------------------------------------------------------------------------


def dumps(record: Mapping[str, Any]) -> str:
    return json.dumps(record, indent=2, ensure_ascii=False) + "\n"


def write_records(
    records: Sequence[Mapping[str, Any]],
    directory: str | Path = DEFAULT_RUNS_DIR,
    *,
    overwrite: bool = False,
) -> list[Path]:
    """Validate and write records as ``<run_id>.json``; refuses to overwrite unless asked."""
    directory = Path(directory)
    schema = load_schema(_schema_for(directory))
    paths = []
    for record in records:
        errors = validate(record, schema)
        if errors:
            raise RecordError(
                f"run record {record.get('run_id')!r} is invalid: " + "; ".join(errors[:5])
            )
        path = directory / f"{record['run_id']}.json"
        if path.exists() and not overwrite:
            raise RecordError(f"{path} exists (pick another slug, or pass --overwrite)")
        paths.append(path)
    directory.mkdir(parents=True, exist_ok=True)
    for record, path in zip(records, paths, strict=True):
        path.write_text(dumps(record), encoding="utf-8")
    return paths


def _schema_for(runs_dir: Path) -> Path:
    """The schema next to a runs directory (``<dir>/../schema/run.schema.json``), else default."""
    candidate = runs_dir.parent / "schema" / "run.schema.json"
    if candidate.is_file():
        return candidate
    checkout = Path(__file__).resolve().parents[3] / SCHEMA_PATH  # source checkout, any cwd
    return checkout if not SCHEMA_PATH.is_file() and checkout.is_file() else SCHEMA_PATH


def load_records(directory: str | Path = DEFAULT_RUNS_DIR) -> list[dict[str, Any]]:
    """Every ``*.json`` run record in ``directory``, sorted by file name; invalid ones raise."""
    directory = Path(directory)
    schema = load_schema(_schema_for(directory))
    records = []
    for path in sorted(directory.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        errors = validate(record, schema)
        if errors:
            raise RecordError(f"{path}: " + "; ".join(errors[:5]))
        if path.stem != record["run_id"]:
            raise RecordError(f"{path}: file name must be the run_id ({record['run_id']}.json)")
        records.append(record)
    return records


# --- ``pii-guard eval record`` ------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pii-guard eval record",
        description="Turn a saved scorecard (text or visual) into run records under "
        "eval/results/runs/.",
    )
    parser.add_argument(
        "scorecard", type=Path, help="JSON from `pii-guard eval --json` or `eval visual --json`"
    )
    parser.add_argument("--slug", required=True, help="short id: the file is <date>-<slug>.json")
    parser.add_argument("--date", help="run date YYYY-MM-DD (default: the scorecard's, else today)")
    parser.add_argument("--source", choices=["recorded", "imported"], default="recorded")
    parser.add_argument(
        "--extra", type=Path, metavar="FILE", help="JSON partial record to merge (models, cost …)"
    )
    parser.add_argument("--note", action="append", default=[], help="free-text note, repeatable")
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--overwrite", action="store_true", help="replace an existing record")
    parser.add_argument(
        "--no-report", action="store_true", help="don't rebuild the index and charts"
    )
    return parser


def load_extra(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecordError(f"--extra {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RecordError(f"--extra {path}: expected a JSON object")
    return data


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        card = json.loads(args.scorecard.read_text(encoding="utf-8"))
        records = build_records(
            card,
            slug=args.slug,
            source=args.source,
            day=args.date,
            extra=load_extra(args.extra),
            notes=args.note,
        )
        if args.source == "imported":
            for rec in records:
                rec["imported_from"] = {
                    "path": str(args.scorecard),
                    "sha256": file_sha256(args.scorecard),
                    "note": None,
                }
        paths = write_records(records, args.runs_dir, overwrite=args.overwrite)
    except (OSError, json.JSONDecodeError, RecordError) as exc:
        print(f"pii-guard eval record: {exc}", file=sys.stderr)
        return 2
    for path in paths:
        print(f"wrote {path}")
    if not args.no_report:
        from pii_guard.eval.report_cli import main as report_main

        return report_main(["--runs-dir", str(args.runs_dir)])
    return 0


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
