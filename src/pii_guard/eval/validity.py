"""Number validity: which labelled identifiers pass the language packs' own validators.

pii-guard's rules accept a structured identifier only when it validates: a card number by
issuer prefix and Luhn, an IBAN by its check digits, a Hungarian TAJ or tax ID by its check
digit, a phone number by its numbering plan, an ID document by its checksum or distinctive
format. A public set whose numbers were generated without those constraints (Ai4Privacy's
cards, tax and TAJ numbers mostly fail their checksums) therefore leaks numbers that a
validator would call malformed. A mistyped real identifier is still personal data, so these
values stay in the headline leak rate (``docs/evaluation.md``); this module only splits the
score so a reader can see where the gap comes from.

- :data:`NUMBER_TYPES`: the entity types whose rules validate the value.
- :func:`classify`: ``"valid"`` when a validated rule of the value's type (every pack's
  ``everywhere`` rules plus the document language's own, cued numbers off) recognises the
  whole value on its own, ``"invalid"`` when none does, ``None`` for any other type.
- :func:`validity_block`: per class, gold spans and how many a system found (overlap recall)
  and distinct values and how many leaked; per type the same; and the leak of every value
  that is *not* a number type (``excluding_number_types``). The three parts add up to the
  block's headline counts.

Nothing returned contains a labelled value.

Backfilling a record from a re-run (the run kept no per-document predictions) is
:func:`attach_validity`, also ``python -m pii_guard.eval.validity --help``.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pii_guard.eval.forms import matching_types
from pii_guard.types import EntityType

if TYPE_CHECKING:
    from pii_guard.detect.rules import RuleDetector
    from pii_guard.eval.scorer import DocumentResult

__all__ = [
    "CLASSES",
    "NUMBER_TYPES",
    "Validity",
    "attach_validity",
    "classify",
    "is_public",
    "validity_block",
]

Validity = Literal["valid", "invalid"]
CLASSES: tuple[Validity, ...] = ("valid", "invalid")

#: Structured identifiers whose rules validate the value (checksum, numbering plan or a
#: distinctive validated format). Everything else (names, addresses, e-mail) is not split.
NUMBER_TYPES: frozenset[EntityType] = frozenset(
    {
        EntityType.PHONE,
        EntityType.NATIONAL_ID_HU_TAX,
        EntityType.NATIONAL_ID_HU_TAJ,
        EntityType.ID_DOCUMENT,
        EntityType.BANK_ACCOUNT,
        EntityType.PAYMENT_CARD,
        EntityType.COMPANY_ID_HU,
        EntityType.PARCEL_NUMBER_HU,
        EntityType.VEHICLE_PLATE,
    }
)

_detector: RuleDetector | None = None
_lock = threading.Lock()
_cache: dict[tuple[str, EntityType, str], Validity] = {}


def _rules() -> RuleDetector:
    global _detector
    with _lock:
        if _detector is None:
            from pii_guard.detect.rules import RuleDetector

            # Cued numbers off: a cue masks a number *because* it fails validation.
            _detector = RuleDetector(cued_numbers=False)
        return _detector


def classify(value: str, entity_type: EntityType, language: str) -> Validity | None:
    """``"valid"``/``"invalid"`` for a value of a :data:`NUMBER_TYPES` type, else ``None``.

    Valid means a validated rule of ``entity_type`` for a text in ``language`` covers every
    letter and digit of ``value`` (after the same normalisation detection applies), so
    surrounding punctuation in a gold span doesn't matter.
    """
    if entity_type not in NUMBER_TYPES:
        return None
    key = (value, entity_type, language)
    if key in _cache:
        return _cache[key]
    from pii_guard.detect.normalize import normalize_for_detection

    text = normalize_for_detection(value).text
    alnum = [i for i, ch in enumerate(text) if ch.isalnum()]
    result: Validity = "invalid"
    if alnum:
        first, last = alnum[0], alnum[-1] + 1
        for rule in _rules().rules_for(language):
            if any(
                h.entity_type in matching_types(entity_type) and h.start <= first and h.end >= last
                for h in rule(text)
            ):
                result = "valid"
                break
    _cache[key] = result
    return result


def is_public(results: Sequence[DocumentResult]) -> bool:
    """True when every document comes from a public set (``meta.kind`` ``public-*``)."""
    return bool(results) and all(
        str(r.document.meta.get("kind", "")).startswith("public-") for r in results
    )


def _counts() -> dict[str, int]:
    return {"gold": 0, "found": 0, "values": 0, "leaked": 0}


def validity_block(results: Sequence[DocumentResult]) -> dict[str, Any]:
    """The number-validity breakdown of ``results`` (see the module docstring).

    ``gold``/``found``: gold spans and those overlapped by a prediction of the same type
    (overlap recall, as in the headline). ``values``/``leaked``: distinct labelled values of a
    ``mask``-policy type and those that survive masking (the headline leak rate's counts).
    """
    from pii_guard.eval.scorer import DEFAULT_POLICY, leak_report

    classes: dict[str, dict[str, int]] = {c: _counts() for c in CLASSES}
    other = _counts()
    per_type: dict[str, dict[str, dict[str, int]]] = {}
    for r in results:
        doc = r.document

        def bucket(entity_type: EntityType, value: str) -> list[dict[str, int]]:
            cls = classify(value, entity_type, doc.language)  # noqa: B023 - used in-loop
            if cls is None:
                return [other]
            row = per_type.setdefault(entity_type.value, {c: _counts() for c in CLASSES})
            return [classes[cls], row[cls]]

        for g in doc.spans:
            alike = matching_types(g.entity_type)  # BANK_ACCOUNT gold ~ PAYMENT_CARD, as scored
            found = any(
                p.entity_type in alike and g.start < p.end and p.start < g.end for p in r.predicted
            )
            for c in bucket(g.entity_type, g.text):
                c["gold"] += 1
                c["found"] += found
        for leak in leak_report(doc, r.masked_text, policy=DEFAULT_POLICY):
            for c in bucket(leak.entity_type, leak.value):
                c["values"] += 1
                c["leaked"] += leak.leaked
    order = {t.value: i for i, t in enumerate(EntityType)}
    return {
        **classes,
        "excluding_number_types": other,
        "per_type": {t: per_type[t] for t in sorted(per_type, key=order.__getitem__)},
        "source": None,
    }


# --- Backfilling a record from a re-run --------------------------------------------------

_HEADLINE = (("leak", "values"), ("leak", "leaked"), ("overlap", "gold"), ("overlap", "tp_gold"))


def _sums(validity: Mapping[str, Any]) -> dict[str, int]:
    parts = [validity["valid"], validity["invalid"], validity["excluding_number_types"]]
    return {k: sum(int(p[k]) for p in parts) for k in ("gold", "found", "values", "leaked")}


def _scorecard_counts(block: Mapping[str, Any]) -> dict[str, int]:
    """Headline counts of a scorecard block (:func:`pii_guard.eval.scorer.summarize`)."""
    micro = block["detection"]["overlap"]["micro"]
    return {
        "values": int(block["leak"]["values"]),
        "leaked": int(block["leak"]["leaked"]),
        "gold": int(micro["gold"]),
        "found": int(micro["tp_gold"]),
    }


def _record_counts(block: Mapping[str, Any]) -> dict[str, int]:
    return {
        "values": int(block["leak"]["values"]),
        "leaked": int(block["leak"]["leaked"]),
        "gold": int(block["overlap"]["gold"]),
        "found": int(block["overlap"]["tp_gold"]),
    }


def _system_card(scorecard: Mapping[str, Any], system: str | None) -> Mapping[str, Any]:
    if system is None:
        return scorecard
    baselines = scorecard.get("baselines") or {}
    if system not in baselines:
        raise KeyError(f"scorecard has no baseline {system!r} (has {sorted(baselines)})")
    return baselines[system]


def attach_validity(
    record: dict[str, Any],
    scorecard: Mapping[str, Any],
    *,
    by: str,
    commit: str,
    date: str,
    note: str,
    system: str | None = None,
) -> dict[str, Any]:
    """``record`` with ``validity`` blocks taken from a re-run's ``scorecard``.

    Only the ``validity`` fields are written; every headline metric of the record is left as
    it is. Each block's ``source`` says where it came from and whether the re-run reproduced
    the record's headline counts exactly (``matches_headline``); when it didn't, the re-run's
    own counts are kept in ``rerun_headline`` so the breakdown can be read against them.
    """
    card = _system_card(scorecard, system)
    metrics = record["metrics"]
    pairs: list[tuple[dict[str, Any], Mapping[str, Any]]] = [(metrics["overall"], card["overall"])]
    for lang, block in metrics["languages"].items():
        if lang not in card.get("languages", {}):
            raise KeyError(f"scorecard has no language {lang!r}")
        pairs.append((block, card["languages"][lang]))
    for target, source in pairs:
        validity = source.get("validity")
        if not validity:
            raise KeyError("scorecard has no validity block (re-run with this version)")
        rerun = _scorecard_counts(source)
        matches = rerun == _record_counts(target)
        target["validity"] = {
            **{k: dict(validity[k]) for k in (*CLASSES, "excluding_number_types")},
            "per_type": json.loads(json.dumps(validity["per_type"])),
            "source": {
                "by": by,
                "method": "rerun",
                "commit": commit,
                "date": date,
                "matches_headline": matches,
                "rerun_headline": None if matches else rerun,
                "note": note,
            },
        }
    return record


def validity_errors(block: Mapping[str, Any], path: str) -> list[str]:
    """A text block's ``validity`` that doesn't add up (empty list = consistent).

    The classes plus ``excluding_number_types`` must sum to the block's headline counts, or
    to ``source.rerun_headline`` for a re-run that didn't reproduce them; per type, the
    classes sum to the class totals; found <= gold and leaked <= values everywhere.
    """
    validity = block.get("validity")
    if not validity:
        return []
    errors: list[str] = []
    parts = {k: validity[k] for k in (*CLASSES, "excluding_number_types")}
    for name, c in parts.items():
        if c["found"] > c["gold"] or c["leaked"] > c["values"]:
            errors.append(f"{path}.validity.{name}: found > gold or leaked > values")
    source = validity.get("source")
    if source and not source["matches_headline"]:
        want = dict(source.get("rerun_headline") or {})
        if not want:
            errors.append(f"{path}.validity.source: rerun_headline needed when not matching")
    else:
        want = _record_counts(block)
        if source and source.get("rerun_headline") is not None:
            errors.append(f"{path}.validity.source: rerun_headline set although matching")
    if want and _sums(validity) != want:
        errors.append(
            f"{path}.validity: classes add up to {_sums(validity)}, not the headline {want}"
        )
    for cls in CLASSES:
        total = Counter[str]()
        for row in validity["per_type"].values():
            total.update(row[cls])
        if {k: total[k] for k in parts[cls]} != dict(parts[cls]):
            errors.append(f"{path}.validity.per_type: {cls} rows don't add up to the class total")
    return errors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pii_guard.eval.validity",
        description=(
            "Write the number-validity breakdown of a re-run's scorecard into an existing run "
            "record (headline metrics untouched)."
        ),
    )
    parser.add_argument("--record", type=Path, required=True, help="run record to update")
    parser.add_argument("--scorecard", type=Path, required=True, help="re-run's scorecard JSON")
    parser.add_argument("--system", help="baseline name inside the scorecard (presidio, ...)")
    parser.add_argument("--by", required=True, help="ticket id of the change")
    parser.add_argument("--note", required=True, help="how the re-run was made")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    from pii_guard.eval.record import dumps, validate

    record = json.loads(args.record.read_text("utf-8"))
    scorecard = json.loads(args.scorecard.read_text("utf-8"))
    meta = scorecard.get("meta", {})
    try:
        attach_validity(
            record,
            scorecard,
            by=args.by,
            commit=str(meta.get("commit", "unknown"))[:7],
            date=str(meta.get("generated_at", ""))[:10],
            note=args.note,
            system=args.system,
        )
    except KeyError as exc:
        print(f"validity: {exc}", file=sys.stderr)
        return 2
    errors = validate(record)
    if errors:
        print("validity: record invalid:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 1
    args.record.write_text(dumps(record), "utf-8")
    source = record["metrics"]["overall"]["validity"]["source"]
    print(
        f"validity: {record['run_id']}: matches headline: {source['matches_headline']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
