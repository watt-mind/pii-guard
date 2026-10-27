"""Shared pieces of the dataset loaders: verified downloads, seeded samples, span conversion.

Every loader turns its source rows into :class:`Row` (an id, a language, the text and the
source's ``(start, end, label)`` spans) and hands them to :func:`convert`, which applies the
dataset's label mapping the same way the Ai4Privacy loader does
(:mod:`pii_guard.eval.public.ai4privacy`): mapped labels become gold spans, unmapped ones become
*ignore regions* (``meta.ignore``: offsets and the source label, no value), adjacent parts of
one mapped type separated only by spaces or a comma are merged into one span, and a part that
only counts inside an address (a city, a postcode) is an ignore region when it stands alone.
Errors name row ids and counts, never a document's text.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import re
import urllib.request
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pii_guard.eval.fixtures import Document, FixtureError, parse_document
from pii_guard.types import EntityType

__all__ = [
    "CACHE_DIR",
    "ConversionError",
    "Converted",
    "LabelMap",
    "Row",
    "convert",
    "download",
    "order_key",
    "sample",
    "sha256_file",
    "text_sha256",
]

#: Downloads land here (git-ignored: ``data/*``); nothing in it is ever committed.
CACHE_DIR = Path("data/datasets/raw")

_USER_AGENT = "pii-guard-eval"  # nothing that identifies the person running it
_MERGE_GAP_RE = re.compile(r"[ \t,]{0,3}")


class ConversionError(ValueError):
    """A row can't be converted (offsets don't match, overlapping spans). Never has values."""


@dataclass(frozen=True, slots=True)
class Row:
    """One source document, before label mapping. ``spans`` are ``(start, end, label)``."""

    uid: str
    language: str
    text: str
    spans: tuple[tuple[int, int, str], ...]
    meta: Mapping[str, Any] = field(default_factory=dict)
    #: The source's own copy of each span's text, when it has one: checked against the offsets.
    values: tuple[str, ...] | None = None

    def __repr__(self) -> str:
        return f"Row(uid={self.uid!r}, language={self.language!r}, spans={len(self.spans)})"


@dataclass(frozen=True, slots=True)
class LabelMap:
    """How one dataset's labels become pii-guard types.

    ``types``: label -> type, or ``None`` for "no pii-guard type / policy-excluded" (an ignore
    region). ``per_language`` overrides ``types`` for one language. ``part_only``: labels that
    are gold only when merged into a span of another label (a city inside an address); on their
    own they are ignore regions. A label in none of these is *unknown*: counted, not scored.
    """

    types: Mapping[str, EntityType | None]
    per_language: Mapping[str, Mapping[str, EntityType]] = field(default_factory=dict)
    part_only: frozenset[str] = frozenset()
    notes: Mapping[str, str] = field(default_factory=dict)

    def get(self, label: str, language: str) -> EntityType | None:
        override = self.per_language.get(language, {}).get(label)
        return override if override is not None else self.types.get(label)

    def table(self) -> list[dict[str, Any]]:
        """The mapping as manifest rows."""
        rows = []
        for label, entity_type in self.types.items():
            per_lang = {
                lang: overrides[label].value
                for lang, overrides in self.per_language.items()
                if label in overrides
            }
            rows.append(
                {
                    "label": label,
                    "pii_guard_type": entity_type.value if entity_type else None,
                    "per_language": per_lang,
                    "part_only": label in self.part_only,
                    "note": self.notes.get(label, ""),
                }
            )
        return rows


@dataclass(frozen=True, slots=True)
class Converted:
    document: Document
    dropped: Counter[str]
    unknown: Counter[str]


# Provider-format credentials (Slack, GitHub, AWS, Stripe live, Google, GitLab, PEM keys). Even
# a generated one trips secret scanning and has no pii-guard type, so such a row is skipped.
SECRET_SHAPES = re.compile(
    r"xox[abposr]-[0-9A-Za-z-]{10,}|gh[pousr]_[A-Za-z0-9]{36}|AKIA[0-9A-Z]{16}"
    r"|sk_live_[0-9A-Za-z]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY|AIza[0-9A-Za-z_-]{35}"
    r"|glpat-[0-9A-Za-z_-]{20}"
    r"|eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\."  # JWT
)
# A credential keyword, then a long token-like value: what secret scanners call a generic key.
_KEYED_SECRET = re.compile(
    r"(?i)(?:api[ _-]?key|access[ _-]?key|secret|token|passw(?:or)?d|auth)\w*"
    r"[^\n]{0,24}?[:=]\s*[\"']?([A-Za-z0-9_+/=.-]{12,})"
)


def holds_credential(text: str) -> bool:
    """True when ``text`` holds a provider-format or keyword-assigned token (letters + digits)."""
    if SECRET_SHAPES.search(text):
        return True
    for m in _KEYED_SECRET.finditer(text):
        value = m.group(1)
        if any(c.isdigit() for c in value) and any(c.isalpha() for c in value):
            return True
    return False


def convert(row: Row, labels: LabelMap, *, prefix: str, kind: str, source: str) -> Converted:
    """One :class:`Row` as a fixture :class:`Document` with id ``<prefix>-<uid>``."""
    doc_id = f"{prefix}-{row.uid}"
    text = row.text
    if not text or not text.strip() or not row.language:
        raise ConversionError(f"{doc_id}: missing text or language")
    if holds_credential(text):
        raise ConversionError(f"{doc_id}: holds a provider-format credential")
    dropped: Counter[str] = Counter()
    unknown: Counter[str] = Counter()
    spans: list[tuple[int, int, EntityType, frozenset[str]]] = []
    ignore: list[tuple[int, int, str]] = []
    if row.values is not None:
        if len(row.values) != len(row.spans):
            raise ConversionError(f"{doc_id}: span values don't match the spans")
        for (start, end, _), value in zip(row.spans, row.values, strict=True):
            if text[start:end] != value:
                raise ConversionError(f"{doc_id}: span offsets don't match the text")
    for start, end, label in sorted(row.spans, key=lambda s: (s[0], s[1])):
        if not 0 <= start < end <= len(text):
            raise ConversionError(f"{doc_id}: span offsets out of range")
        if label not in labels.types and label not in labels.per_language.get(row.language, {}):
            unknown[label] += 1
            continue
        entity_type = labels.get(label, row.language)
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
            if p_type is entity_type and _MERGE_GAP_RE.fullmatch(text[p_end:start]):
                spans[-1] = (p_start, end, p_type, p_labels | {label})
                continue
        spans.append((start, end, entity_type, frozenset({label})))
    kept: list[tuple[int, int, EntityType]] = []
    for s, e, t, merged in spans:
        if merged <= labels.part_only:  # a city or postcode on its own: not scored
            for lab in sorted(merged):
                dropped[f"{lab} (on its own)"] += 1
            ignore.append((s, e, "+".join(sorted(merged))))
            continue
        kept.append((s, e, t))
    record = {
        "id": doc_id,
        "language": row.language,
        "text": text,
        "spans": [{"start": s, "end": e, "entity_type": t.value} for s, e, t in kept],
        "meta": {
            "source": source,
            "uid": row.uid,
            "kind": kind,
            **dict(row.meta),
            "ignore": [{"start": s, "end": e, "label": lab} for s, e, lab in sorted(ignore)],
        },
    }
    try:
        document = parse_document(record, where=doc_id)
    except FixtureError as exc:
        raise ConversionError(str(exc)) from None
    return Converted(document, dropped, unknown)


def order_key(seed: int, uid: object) -> str:
    return hashlib.sha256(f"{seed}:{uid}".encode()).hexdigest()


def sample(
    rows: Iterable[Row],
    want: Mapping[str, int],
    seed: int,
    to_document: Callable[[Row], Converted],
) -> tuple[dict[str, list[Converted]], Counter[str]]:
    """The first ``want[lang]`` convertible rows per language in ``sha256(seed:uid)`` order.

    Independent of file order. Keeps a bounded heap per language (``2n + 10`` rows), so a large
    split is never held in memory. Also counts the rows seen and skipped per language.
    """
    heaps: dict[str, list[tuple[str, int, Row]]] = {lang: [] for lang in want}
    seen: Counter[str] = Counter()
    for index, row in enumerate(rows):
        heap = heaps.get(row.language)
        if heap is None:
            continue
        seen[f"rows_{row.language}"] += 1
        # Max-heap of the smallest keys: push the inverted key.
        item = (_invert(order_key(seed, row.uid)), -index, row)
        if len(heap) < want[row.language] * 2 + 10:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
    out: dict[str, list[Converted]] = {}
    for lang, heap in heaps.items():
        chosen: list[Converted] = []
        for _, _, row in sorted(heap, key=lambda it: _invert(it[0])):
            if len(chosen) == want[lang]:
                break
            try:
                chosen.append(to_document(row))
            except ConversionError:
                seen[f"skipped_{lang}"] += 1
        out[lang] = chosen
    return out, seen


_INVERT = str.maketrans("0123456789abcdef", "fedcba9876543210")


def _invert(hex_key: str) -> str:
    return hex_key.translate(_INVERT)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 22):
            digest.update(chunk)
    return digest.hexdigest()


def text_sha256(text: str) -> str:
    """The document hash used for split disjointness: SHA-256 of the whitespace-folded text."""
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


def download(url: str, sha256: str, dest: Path) -> Path:
    """``dest`` if it already has ``sha256``, else download ``url`` there and check it.

    The file is written to ``dest.part`` first and only renamed once the hash matches, so a
    broken download never looks like a cached one.
    """
    if dest.is_file() and sha256_file(dest) == sha256:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})  # noqa: S310
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=300) as response, part.open("wb") as out:  # noqa: S310 (pinned https URL)
        while chunk := response.read(1 << 20):
            digest.update(chunk)
            out.write(chunk)
    if digest.hexdigest() != sha256:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"{dest.name}: SHA-256 mismatch (got {digest.hexdigest()[:16]}…)")
    part.replace(dest)
    return dest


def read_parquet(path: Path, columns: Sequence[str]) -> list[dict[str, Any]]:
    """Rows of a Parquet file. Needs ``pyarrow``, which pii-guard doesn't depend on.

    Only ``fetch`` reads Parquet; the committed samples are JSONL. Run it with
    ``uv run --with pyarrow python -m pii_guard.eval.datasets fetch NAME``.
    """
    try:
        import pyarrow.parquet as pq  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError:
        raise RuntimeError(
            "reading Parquet needs pyarrow: "
            "uv run --with pyarrow python -m pii_guard.eval.datasets fetch …"
        ) from None
    rows: list[dict[str, Any]] = pq.read_table(path, columns=list(columns)).to_pylist()
    return rows


def dump_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
