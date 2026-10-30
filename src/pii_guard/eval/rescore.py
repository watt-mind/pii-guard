"""Re-score stored run records after a change of scoring method, from their own counts.

```
python -m pii_guard.eval.rescore            # rewrite the records that need it
python -m pii_guard.eval.rescore --check    # exit 1 if any record still needs it (CI-safe)
```

A run record keeps every count next to its ratios (per language and per entity type), so a
rule that only adds or removes whole entity types, or drops a metric, can be applied to an
old run without running it again. Two rules exist (LAB-1213):

- **unscored-types**: on a set where an entity type can't be scored
  (:data:`pii_guard.eval.scorer.LEGACY_UNSCORED_TYPES`, by fixture kind: ``DATE_OF_BIRTH`` on
  Ai4Privacy, whose ``DATE`` label covers every date and is policy-excluded), predictions of
  that type are taken out of precision, F1, macro F1 and over-masking. Recall and leak rate
  don't change (the type has no gold spans there). What *can't* be re-scored from counts:
  predictions overlapping a policy-excluded title or bare city, which need the per-document
  predictions the runs didn't keep; the record's ``rescored.note`` says so.
- **no-consistency**: a comparison tool doesn't report its replacements, so its placeholder
  consistency was a placeholder 0.0 by construction; it becomes ``null``.

It also backfills ``system.role`` (``own`` | ``other-model`` | ``tool``, LAB-1495) on records
written before the field existed; that is not a re-score and adds no ``rescored``.

Each re-scored record gets ``rescored`` (who, which rule, what changed), and a second pass
changes nothing. This is a change of *method*: no detector ran again and no number improved
because a system got better.
"""

from __future__ import annotations

import argparse
import copy
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pii_guard.eval.record import DEFAULT_RUNS_DIR, dumps, load_records, with_role

__all__ = ["RESCORE_BY", "drop_types", "main", "rescore_record"]

RESCORE_BY = "LAB-1213"
#: Fixture-path marker -> types its documents can't score (mirrors the scorer's fallback).
_UNSCORED_BY_FIXTURE: dict[str, tuple[str, ...]] = {"-ai4privacy.jsonl": ("DATE_OF_BIRTH",)}
_OLD_NOTE = (
    "Dates, ages, gender, titles and bare city names are policy-excluded (not in the gold "
    "spans), so masking them counts as over-masking."
)
_NEW_NOTE = (
    "Dates, ages, gender, titles and bare city names are policy-excluded (not in the gold "
    "spans). DATE_OF_BIRTH predictions are not scored on this set (re-scored, LAB-1213); a "
    "masked title or bare city still counts as over-masking, since the run kept no "
    "per-document predictions to apply ignore regions to."
)


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def _q(num: int, den: int) -> float | None:
    return num / den if den else None


def _f1(p: float | None, r: float | None) -> float | None:
    """F1 as the scorer computes it (:class:`pii_guard.eval.scorer.TypeCounts`)."""
    if p is None and r is None:
        return None
    if not p or not r:
        return 0.0
    return 2 * p * r / (p + r)


def _macro(per_type: Mapping[str, Mapping[str, Any]]) -> float | None:
    scores = [
        _f1(_q(t["overlap_tp_pred"], t["pred"]), _q(t["overlap_tp_gold"], t["gold"])) or 0.0
        for t in per_type.values()
        if t["gold"] or t["pred"]
    ]
    return sum(scores) / len(scores) if scores else None


def drop_types(block: Mapping[str, Any], types: Sequence[str]) -> tuple[dict[str, Any], int]:
    """``block`` with the predictions of ``types`` unscored, and how many there were.

    Only types with no gold spans in the block are dropped (otherwise recall would change and
    counts alone can't say which predictions to keep); others are left as they are.
    """
    out = copy.deepcopy(dict(block))
    dropped = 0
    for name in types:
        t = out["per_type"].get(name)
        if t is None or t["gold"] or not t["pred"]:
            continue
        dropped += t["pred"]
        for mode in ("exact", "overlap"):
            m = out[mode]
            m["pred"] -= t["pred"]
            m["tp_pred"] -= t[f"{mode}_tp_pred"]
            p, r = _q(m["tp_pred"], m["pred"]), _q(m["tp_gold"], m["gold"])
            m["precision"], m["recall"], m["f1"] = _r(p), _r(r), _r(_f1(p, r))
        over = t.get("over_masking")
        if over:
            om = out["over_masking"]
            om["masked"] -= over["masked"]
            om["over_masked"] -= over["over_masked"]
            om["rate"] = _r(_q(om["over_masked"], om["masked"]))
        del out["per_type"][name]
    if dropped:
        out["macro_f1_overlap"] = _r(_macro(out["per_type"]))
        out["unscored_predictions"] = int(out.get("unscored_predictions", 0)) + dropped
        # Keep the field order the harness writes (``unscored_predictions`` after the counts).
        order = ["documents", "gold_spans", "predicted_spans", "unscored_predictions"]
        out = {
            **{k: out[k] for k in order if k in out},
            **{k: v for k, v in out.items() if k not in order},
        }
    return out, dropped


def _unscored_types(record: Mapping[str, Any]) -> tuple[str, ...]:
    found: list[str] = []
    for f in record["fixtures"]:
        for marker, types in _UNSCORED_BY_FIXTURE.items():
            if str(f["path"]).endswith(marker):
                found += [t for t in types if t not in found]
    return tuple(found)


def rescore_record(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """The re-scored record, or ``None`` if no rule applies (or it was already re-scored).

    A record without ``system.role`` (LAB-1495) gets it here too, on any kind of record. That
    is a backfill, not a change of scoring method, so it adds no ``rescored`` marker.
    """
    out = copy.deepcopy(dict(record))
    backfilled = "role" not in out["system"]
    if backfilled:
        with_role(out["system"])
    scored = _rescore(out) if record["kind"] == "text" and not record.get("rescored") else None
    return scored if scored is not None else (out if backfilled else None)


def _rescore(out: dict[str, Any]) -> dict[str, Any] | None:
    """``out`` (a copy) with the scoring rules applied, or ``None`` if none applies."""
    record = out
    methods: list[str] = []
    notes: list[str] = []
    # A record written by the current scorer has ``unscored_predictions``: nothing to redo.
    types = (
        () if "unscored_predictions" in record["metrics"]["overall"] else _unscored_types(record)
    )
    if types:
        metrics = out["metrics"]
        metrics["overall"], dropped = drop_types(metrics["overall"], types)
        for lang, block in list(metrics["languages"].items()):
            metrics["languages"][lang], _ = drop_types(block, types)
        methods.append("unscored-types")
        what = "/".join(types)
        notes.append(
            (
                f"{dropped} {what} prediction(s) taken out of precision and over-masking"
                if dropped
                else f"No {what} predictions to take out"
            )
            + " (the set labels every date DATE, which is policy-excluded). Predictions on a"
            " policy-excluded title or bare city are still counted: the run kept no"
            " per-document predictions, so ignore regions can't be applied."
        )
        out["notes"] = [_NEW_NOTE if n == _OLD_NOTE else n for n in out["notes"]]
    if record["system"]["family"] == "comparison":
        blocks = [out["metrics"]["overall"], *out["metrics"]["languages"].values()]
        if any(b.get("consistency") is not None for b in blocks):
            for b in blocks:
                b["consistency"] = None
            methods.append("no-consistency")
            notes.append(
                "Placeholder consistency set to null: the tool doesn't report its "
                "replacements, so the 0.0 it had was a placeholder, not a measurement."
            )
    if not methods:
        return None
    rescored: dict[str, Any] = {
        "by": RESCORE_BY,
        "method": "+".join(methods),
        "note": " ".join(notes),
    }
    if types:
        rescored["unscored_types"] = list(types)
    # ``rescored`` goes right after ``notes``, as in the schema.
    keys = list(out)
    at = keys.index("notes") + 1
    return {
        **{k: out[k] for k in keys[:at]},
        "rescored": rescored,
        **{k: out[k] for k in keys[at:]},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pii_guard.eval.rescore",
        description="Re-score stored run records after a change of scoring method.",
    )
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument(
        "--check", action="store_true", help="write nothing; exit 1 if a record needs it"
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    pending = []
    for record in load_records(args.runs_dir):
        new = rescore_record(record)
        # ``--check`` is about the scoring method; a missing ``system.role`` (a backfill the
        # index derives anyway) doesn't fail it.
        if new is not None and not (args.check and new.get("rescored") == record.get("rescored")):
            pending.append((args.runs_dir / f"{record['run_id']}.json", new))
    if args.check:
        if pending:
            names = ", ".join(p.name for p, _ in pending)
            print(f"rescore: {len(pending)} record(s) need re-scoring: {names}", file=sys.stderr)
            return 1
        print("rescore: every record is scored with the current method")
        return 0
    for path, new in pending:
        path.write_text(dumps(new), encoding="utf-8")
        print(f"re-scored {path}")
    if not pending:
        print("rescore: nothing to do")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
