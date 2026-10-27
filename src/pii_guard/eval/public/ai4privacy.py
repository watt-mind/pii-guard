"""Ai4Privacy OpenPII 1M as an evaluation set: a seeded sample, converted at run time.

```
python -m pii_guard.eval.public.ai4privacy fetch [--sample en=200,hu=200,de=200] [--seed 2026]
    [--out data/public/ai4privacy] [--manifest eval/fixtures/public/ai4privacy-openpii-1m.json]
python -m pii_guard.eval.public.ai4privacy fetch --check   # rebuild and compare, write nothing
```

`ai4privacy/pii-masking-openpii-1m <https://huggingface.co/datasets/ai4privacy/pii-masking-openpii-1m>`_
is a synthetic, multilingual PII-masking dataset by Ai4Privacy / Ai Suisse SA, released under
CC-BY-4.0, which permits redistribution with attribution. ``fetch`` streams the validation
split at a pinned revision (about 920 MB, checked against the pinned SHA-256; nothing but the
sample is kept), draws a seeded sample per language and writes it as fixture JSONL
(``eval/fixtures/public/<lang>-ai4privacy.jsonl``, committed with an attribution note) plus a
manifest (source, revision, file hash, licence, seed, label mapping, sample ids, label counts).

**Sample.** Within each language, rows are ordered by ``sha256("<seed>:<uid>")`` and the
first *n* that convert cleanly are taken, so the sample doesn't depend on file order.

**Labels.** :data:`LABEL_MAP` maps the dataset's 19 labels to pii-guard types. Labels that
pii-guard's policy doesn't mask (any date, age, gender, sex, title, and a city on its own) are
*policy-excluded*: left out of the gold spans, so they are neither leaks nor recall, and
counted per label in the manifest. Each one is kept as an *ignore region* (``meta.ignore``:
offsets and dataset label, no value), so a prediction on it that matches no gold span is
neither credited nor charged in precision and over-masking
(:func:`pii_guard.eval.scorer.unscored`). Adjacent spans of the same mapped type separated only by
spaces or a comma (a given name and a surname; a street and a building number) are merged
into one span, as pii-guard labels a whole name or address. Documents are never printed;
errors name the row id only.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import re
import sys
import tempfile
import urllib.request
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pii_guard.eval.fixtures import Document, FixtureError, parse_document, write_fixtures
from pii_guard.types import EntityType

__all__ = [
    "DATASET",
    "DEFAULT_MANIFEST",
    "DEFAULT_OUT",
    "DEFAULT_SAMPLE",
    "DEFAULT_SEED",
    "FILE",
    "FILE_SHA256",
    "LABEL_MAP",
    "REVISION",
    "ConversionError",
    "check_sample",
    "convert_row",
    "main",
    "sample_rows",
]

DATASET = "ai4privacy/pii-masking-openpii-1m"
#: Dataset repository commit the sample is drawn from.
REVISION = "ecfdc547f4a0955600cfe6ab98ba2a162207fcc0"
FILE = "data/validation.jsonl"
#: Git LFS object id (SHA-256) of ``FILE`` at ``REVISION``; the download is checked against it.
FILE_SHA256 = "f945f662cab477e8aef02ce6d9a5525d8b9d4ff6436809649d8c398156fea010"
FILE_SIZE = 920_284_464
LICENSE = "CC-BY-4.0"
ATTRIBUTION = "Ai4Privacy / Ai Suisse SA"

DEFAULT_SEED = 2026
DEFAULT_SAMPLE: dict[str, int] = {"en": 200, "hu": 200, "de": 200}
DEFAULT_OUT = Path("eval/fixtures/public")
DEFAULT_MANIFEST = Path("eval/fixtures/public/ai4privacy-openpii-1m.json")

#: Dataset label -> pii-guard type; ``None`` means "no pii-guard type, not scored".
LABEL_MAP: dict[str, EntityType | None] = {
    "GIVENNAME": EntityType.PERSON,
    "SURNAME": EntityType.PERSON,
    "EMAIL": EntityType.EMAIL,
    "TELEPHONENUM": EntityType.PHONE,
    "STREET": EntityType.ADDRESS,
    "BUILDINGNUM": EntityType.ADDRESS,
    "CITY": EntityType.ADDRESS,
    "ZIPCODE": EntityType.ADDRESS,
    "CREDITCARDNUMBER": EntityType.BANK_ACCOUNT,
    "IDCARDNUM": EntityType.ID_DOCUMENT,
    "PASSPORTNUM": EntityType.ID_DOCUMENT,
    "DRIVERLICENSENUM": EntityType.ID_DOCUMENT,
    "SOCIALNUM": EntityType.ID_DOCUMENT,
    "TAXNUM": EntityType.ID_DOCUMENT,
    "DATE": None,
    "AGE": None,
    "GENDER": None,
    "SEX": None,
    "TITLE": None,
}

#: Per-language overrides: Hungarian tax and social security numbers have their own types.
LANGUAGE_LABEL_MAP: dict[str, dict[str, EntityType]] = {
    "hu": {
        "TAXNUM": EntityType.NATIONAL_ID_HU_TAX,
        "SOCIALNUM": EntityType.NATIONAL_ID_HU_TAJ,
    },
}

#: Notes for the manifest's mapping table (why a label maps the way it does).
MAPPING_NOTES: dict[str, str] = {
    "GIVENNAME": "merged with an adjacent SURNAME into one PERSON span",
    "SURNAME": "merged with an adjacent GIVENNAME into one PERSON span",
    "STREET": "address parts separated only by spaces or a comma are merged",
    "BUILDINGNUM": "as STREET",
    "CITY": "as STREET when part of an address; a city on its own is policy-excluded",
    "ZIPCODE": "as STREET",
    "CREDITCARDNUMBER": "cards are BANK_ACCOUNT in pii-guard's taxonomy",
    "SOCIALNUM": "NATIONAL_ID_HU_TAJ for hu rows",
    "TAXNUM": "NATIONAL_ID_HU_TAX for hu rows",
    "DATE": "any date, not only birth dates: policy-excluded",
    "AGE": "no pii-guard type: policy-excluded",
    "GENDER": "no pii-guard type: policy-excluded",
    "SEX": "no pii-guard type: policy-excluded",
    "TITLE": "honorifics (Mr, Dr): policy-excluded",
}

_MERGE_GAP_RE = re.compile(r"[ \t,]{0,3}")
_USER_AGENT = "pii-guard-eval"  # nothing that identifies the person running it


class ConversionError(ValueError):
    """A row can't be converted (offsets don't match, overlapping spans). Never has values."""


@dataclass(frozen=True, slots=True)
class Converted:
    document: Document
    dropped: Counter[str]
    unknown: Counter[str]


def _map(label: str, language: str) -> EntityType | None:
    override = LANGUAGE_LABEL_MAP.get(language, {}).get(label)
    return override if override is not None else LABEL_MAP.get(label)


def convert_row(row: Mapping[str, Any]) -> Converted:
    """One dataset row as a fixture :class:`Document` (``ai4privacy-<uid>``)."""
    uid = row.get("uid")
    text = row.get("source_text")
    language = str(row.get("language") or "")
    doc_id = f"ai4privacy-{uid}"
    if not isinstance(text, str) or not text or not language:
        raise ConversionError(f"{doc_id}: missing text or language")
    dropped: Counter[str] = Counter()
    unknown: Counter[str] = Counter()
    # (start, end, type, dataset labels merged into it)
    spans: list[tuple[int, int, EntityType, frozenset[str]]] = []
    ignore: list[tuple[int, int, str]] = []
    for raw in sorted(row.get("privacy_mask") or (), key=lambda s: (s["start"], s["end"])):
        start, end, label = int(raw["start"]), int(raw["end"]), str(raw["label"])
        if text[start:end] != raw.get("value"):
            raise ConversionError(f"{doc_id}: span offsets don't match the text")
        if label not in LABEL_MAP:
            unknown[label] += 1
            continue
        entity_type = _map(label, language)
        # Trim whitespace the annotation may include; fixtures don't allow it.
        value = text[start:end]
        start += len(value) - len(value.lstrip())
        end -= len(value) - len(value.rstrip())
        if entity_type is None:
            dropped[label] += 1
            if start < end:
                ignore.append((start, end, label))
            continue
        if start >= end:
            continue
        if spans:
            p_start, p_end, p_type, p_labels = spans[-1]
            if start < p_end:
                if p_type is not entity_type:
                    raise ConversionError(f"{doc_id}: overlapping spans of different types")
                spans[-1] = (p_start, max(p_end, end), p_type, p_labels | {label})
                continue
            gap = text[p_end:start]
            if p_type is entity_type and _MERGE_GAP_RE.fullmatch(gap):
                spans[-1] = (p_start, end, p_type, p_labels | {label})
                continue
        spans.append((start, end, entity_type, frozenset({label})))
    kept: list[tuple[int, int, EntityType]] = []
    for s, e, t, labels in spans:
        if labels == {"CITY"}:  # a town on its own: pii-guard keeps it on purpose
            dropped["CITY (on its own)"] += 1
            ignore.append((s, e, "CITY"))
            continue
        kept.append((s, e, t))
    record = {
        "id": doc_id,
        "language": language,
        "text": text,
        "spans": [{"start": s, "end": e, "entity_type": t.value} for s, e, t in kept],
        "meta": {
            "source": DATASET,
            "revision": REVISION,
            "uid": uid,
            "region": row.get("region"),
            "kind": "public-ai4privacy",
            "ignore": [{"start": s, "end": e, "label": lab} for s, e, lab in sorted(ignore)],
        },
    }
    try:
        document = parse_document(record, where=doc_id)
    except FixtureError as exc:
        raise ConversionError(str(exc)) from None
    return Converted(document, dropped, unknown)


def _order_key(seed: int, uid: object) -> str:
    return hashlib.sha256(f"{seed}:{uid}".encode()).hexdigest()


def sample_rows(
    rows: Iterable[Mapping[str, Any]], sample: Mapping[str, int], seed: int
) -> tuple[dict[str, list[Converted]], Counter[str]]:
    """The first ``sample[lang]`` convertible rows per language in ``sha256(seed:uid)`` order.

    Keeps a bounded heap per language, so the full split is never held in memory. Also
    returns the number of rows seen per language and of rows skipped as unconvertible.
    """
    # A little headroom over n so that rows dropped by conversion are replaced.
    heaps: dict[str, list[tuple[str, int, Mapping[str, Any]]]] = {lang: [] for lang in sample}
    seen: Counter[str] = Counter()
    for index, row in enumerate(rows):
        lang = row.get("language")
        if lang not in heaps:
            continue
        seen[f"rows_{lang}"] += 1
        key = _order_key(seed, row.get("uid"))
        heap = heaps[lang]
        limit = sample[lang] * 2 + 10
        item = (_neg(key), index, row)
        if len(heap) < limit:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
    out: dict[str, list[Converted]] = {}
    for lang, heap in heaps.items():
        ordered = sorted(heap, key=lambda it: _neg(it[0]))
        chosen: list[Converted] = []
        for _, _, row in ordered:
            if len(chosen) == sample[lang]:
                break
            try:
                chosen.append(convert_row(row))
            except ConversionError:
                seen[f"skipped_{lang}"] += 1
        out[lang] = chosen
    return out, seen


def _neg(hex_key: str) -> str:
    """Invert a hex string's order (a max-heap of the smallest keys via :mod:`heapq`)."""
    return hex_key.translate(_INVERT)


_INVERT = str.maketrans("0123456789abcdef", "fedcba9876543210")


def _stream(url: str, expected_sha256: str) -> Iterator[dict[str, Any]]:
    """JSON rows from ``url``, hashing as they arrive; raises if the hash doesn't match."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})  # noqa: S310
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 (fixed https URL)
        buffer = b""
        while chunk := response.read(1 << 20):
            digest.update(chunk)
            buffer += chunk
            *lines, buffer = buffer.split(b"\n")
            for line in lines:
                if line.strip():
                    yield json.loads(line)
        if buffer.strip():
            yield json.loads(buffer)
    if digest.hexdigest() != expected_sha256:
        raise RuntimeError(f"{FILE}: SHA-256 mismatch (got {digest.hexdigest()[:16]}…)")


def _rows_from_file(path: Path, expected_sha256: str) -> Iterator[dict[str, Any]]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for line in handle:
            digest.update(line)
            if line.strip():
                yield json.loads(line)
    if digest.hexdigest() != expected_sha256:
        raise RuntimeError(f"{path}: SHA-256 mismatch")


def mapping_table() -> list[dict[str, Any]]:
    """The label mapping as manifest rows."""
    rows = []
    for label, entity_type in LABEL_MAP.items():
        per_lang = {
            lang: overrides[label].value
            for lang, overrides in LANGUAGE_LABEL_MAP.items()
            if label in overrides
        }
        rows.append(
            {
                "label": label,
                "pii_guard_type": entity_type.value if entity_type else None,
                "per_language": per_lang,
                "note": MAPPING_NOTES.get(label, ""),
            }
        )
    return rows


def build_manifest(
    chosen: Mapping[str, Sequence[Converted]],
    seen: Mapping[str, int],
    sample: Mapping[str, int],
    seed: int,
) -> dict[str, Any]:
    languages: dict[str, Any] = {}
    for lang, items in chosen.items():
        gold: Counter[str] = Counter()
        dropped: Counter[str] = Counter()
        unknown: Counter[str] = Counter()
        for c in items:
            gold.update(s.entity_type.value for s in c.document.spans)
            dropped.update(c.dropped)
            unknown.update(c.unknown)
        languages[lang] = {
            "requested": sample[lang],
            "documents": len(items),
            "rows_in_split": seen.get(f"rows_{lang}", 0),
            "skipped_unconvertible": seen.get(f"skipped_{lang}", 0),
            "gold_spans": dict(sorted(gold.items())),
            "policy_excluded": dict(sorted(dropped.items())),
            "unknown_labels": dict(sorted(unknown.items())),
            "uids": [c.document.meta["uid"] for c in items],
        }
    return {
        "dataset": DATASET,
        "url": f"https://huggingface.co/datasets/{DATASET}",
        "revision": REVISION,
        "file": FILE,
        "file_sha256": FILE_SHA256,
        "license": LICENSE,
        "attribution": ATTRIBUTION,
        "rows_committed": True,
        "seed": seed,
        "sample_rule": "per language, rows ordered by sha256('<seed>:<uid>'), first n convertible",
        "label_mapping": mapping_table(),
        "merge_rule": "adjacent spans of one mapped type separated by <= 3 spaces/tabs/commas",
        "languages": languages,
    }


def _parse_sample(value: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in value.split(","):
        lang, _, n = item.partition("=")
        if not lang.strip() or not n.strip().isdigit():
            raise argparse.ArgumentTypeError("expected lang=n[,lang=n…]")
        out[lang.strip()] = int(n)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pii_guard.eval.public.ai4privacy",
        description="Fetch a seeded Ai4Privacy OpenPII sample and convert it to fixture JSONL.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="download, sample, convert")
    fetch.add_argument("--sample", type=_parse_sample, default=dict(DEFAULT_SAMPLE))
    fetch.add_argument("--seed", type=int, default=DEFAULT_SEED)
    fetch.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help="output dir for <lang>-ai4privacy.jsonl"
    )
    fetch.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    fetch.add_argument(
        "--source-file", type=Path, help="a local copy of the split instead of downloading"
    )
    fetch.add_argument(
        "--check",
        action="store_true",
        help="write nothing; fail unless the committed sample and manifest match the rebuild",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    url = f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/{FILE}"
    rows = (
        _rows_from_file(args.source_file, FILE_SHA256)
        if args.source_file
        else _stream(url, FILE_SHA256)
    )
    chosen, seen = sample_rows(rows, args.sample, args.seed)
    manifest = build_manifest(chosen, seen, args.sample, args.seed)
    if args.check:
        problems = check_sample(chosen, manifest, out=args.out, manifest_path=args.manifest)
        for problem in problems:
            print(f"ai4privacy: {problem}", file=sys.stderr)
        if problems:
            return 1
        print("ai4privacy: the committed sample and manifest match the source", file=sys.stderr)
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    for lang, items in chosen.items():
        path = args.out / f"{lang}-ai4privacy.jsonl"
        write_fixtures(path, [c.document for c in items])
        print(f"ai4privacy: {len(items)} {lang} documents -> {path}", file=sys.stderr)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(_dump_manifest(manifest), encoding="utf-8")
    print(f"ai4privacy: manifest -> {args.manifest}", file=sys.stderr)
    return 0


def _dump_manifest(manifest: Mapping[str, Any]) -> str:
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


def check_sample(
    chosen: Mapping[str, Sequence[Converted]],
    manifest: Mapping[str, Any],
    *,
    out: Path,
    manifest_path: Path,
) -> list[str]:
    """Differences between a rebuilt sample and the committed one; writes nothing.

    Compares the whole manifest (sample ids, label counts, mapping, revision, seed) and every
    fixture file byte for byte, so a hand-edited document or label count is caught, not only
    a changed id list. Messages name files and fields, never a document's text.
    """
    problems: list[str] = []
    try:
        committed = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{manifest_path}: unreadable ({exc.__class__.__name__})"]
    for key in sorted(set(manifest) | set(committed)):
        if key == "languages":
            continue
        if manifest.get(key) != committed.get(key):
            problems.append(f"{manifest_path}: {key!r} differs")
    for lang in sorted(set(manifest["languages"]) | set(committed.get("languages", {}))):
        mine = manifest["languages"].get(lang)
        theirs = committed.get("languages", {}).get(lang)
        if mine is None or theirs is None:
            problems.append(f"{manifest_path}: language {lang!r} is only on one side")
            continue
        for field in sorted(set(mine) | set(theirs)):
            if mine.get(field) != theirs.get(field):
                problems.append(f"{manifest_path}: languages.{lang}.{field} differs")
    with tempfile.TemporaryDirectory() as tmp:
        for lang, items in chosen.items():
            name = f"{lang}-ai4privacy.jsonl"
            rebuilt = Path(tmp) / name
            write_fixtures(rebuilt, [c.document for c in items])
            path = out / name
            if not path.is_file():
                problems.append(f"{path}: missing")
            elif path.read_bytes() != rebuilt.read_bytes():
                problems.append(f"{path}: differs from the rebuilt sample")
    return problems


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
