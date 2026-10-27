"""Evaluation fixtures: the JSON Lines format, its loader and writer, and a markup helper.

One document per line, UTF-8::

    {"id": "hu-contract-0001", "language": "hu", "text": "…",
     "spans": [{"start": 10, "end": 20, "entity_type": "PERSON", "text": "Teszt Elek"}],
     "meta": {"kind": "contract", "tags": ["hard-negative"]}}

- ``id``: unique within everything loaded together; stable across regenerations.
- ``language``: a BCP-47-style tag (``"hu"``, ``"en"``, ``"en-GB"``). It is passed as is to
  detectors and the vault, and selects the surface-form hook used for the leak rate.
- ``spans``: gold labels, code-point offsets, ``end`` exclusive, a *text* ``EntityType``.
  ``text`` is optional; when present it must equal ``text[start:end]``. Spans must not
  overlap, must not be blank and must not start or end with whitespace.
- ``meta``: optional free-form object (document kind, tags, generator seed, template …).
  One key is read by the scorer: ``meta.ignore``, a list of ``{"start", "end", "label"}``
  *ignore regions* (text the source labelled but pii-guard's policy doesn't score, such as a
  date in a public dataset). A prediction that overlaps one and matches no gold span is left
  out of precision and over-masking (:func:`pii_guard.eval.scorer.summarize`).

Fixtures are organised one file per language and set: ``eval/fixtures/<language>-<set>.jsonl``
(``hu-smoke.jsonl``, ``en-smoke.jsonl``). The ``language`` field of each record is what
counts; the file name is a convention for humans.

Errors name the file, line and field, never the span's value.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pii_guard.types import EntityType

__all__ = [
    "Document",
    "FixtureError",
    "GoldSpan",
    "dump_document",
    "file_sha256",
    "from_markup",
    "ignore_regions",
    "label",
    "load_fixtures",
    "parse_document",
    "write_fixtures",
]

_DOC_KEYS = frozenset({"id", "language", "text", "spans", "meta"})
_SPAN_KEYS = frozenset({"start", "end", "entity_type", "text"})
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


class FixtureError(ValueError):
    """A fixture record is malformed. The message never contains a labelled value."""


@dataclass(frozen=True, slots=True)
class GoldSpan:
    """A gold label. ``text`` is the labelled value (``document.text[start:end]``)."""

    start: int
    end: int
    entity_type: EntityType
    text: str

    def __repr__(self) -> str:
        return (
            f"GoldSpan(start={self.start}, end={self.end}, "
            f"entity_type={self.entity_type.value}, text=<redacted>)"
        )

    __str__ = __repr__

    def overlaps(self, other: GoldSpan | Any) -> bool:
        return self.start < other.end and other.start < self.end

    def to_dict(self) -> dict[str, object]:
        return {
            "start": self.start,
            "end": self.end,
            "entity_type": self.entity_type.value,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class Document:
    """One fixture document with its gold spans (sorted by ``start``)."""

    id: str
    language: str
    text: str
    spans: tuple[GoldSpan, ...]
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"Document(id={self.id!r}, language={self.language!r}, "
            f"chars={len(self.text)}, spans={len(self.spans)})"
        )

    __str__ = __repr__

    @property
    def primary_language(self) -> str:
        """``"en"`` for ``"en-GB"``."""
        return self.language.split("-", 1)[0]

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "id": self.id,
            "language": self.language,
            "text": self.text,
            "spans": [span.to_dict() for span in self.spans],
        }
        if self.meta:
            out["meta"] = dict(self.meta)
        return out


def parse_document(obj: object, *, where: str = "record") -> Document:
    """Validate one decoded JSON record and build a :class:`Document`."""
    if not isinstance(obj, dict):
        raise FixtureError(f"{where}: expected a JSON object")
    unknown = set(obj) - _DOC_KEYS
    if unknown:
        raise FixtureError(f"{where}: unknown fields {sorted(unknown)}")
    doc_id = obj.get("id")
    if not isinstance(doc_id, str) or not doc_id:
        raise FixtureError(f"{where}: 'id' must be a non-empty string")
    where = f"{where} ({doc_id})"
    language = obj.get("language")
    if not isinstance(language, str) or not _LANGUAGE_RE.match(language):
        raise FixtureError(f"{where}: 'language' must be a language tag such as 'hu' or 'en-GB'")
    text = obj.get("text")
    if not isinstance(text, str) or not text:
        raise FixtureError(f"{where}: 'text' must be a non-empty string")
    meta = obj.get("meta", {})
    if not isinstance(meta, dict):
        raise FixtureError(f"{where}: 'meta' must be an object")
    raw_spans = obj.get("spans")
    if not isinstance(raw_spans, list):
        raise FixtureError(f"{where}: 'spans' must be a list")
    _check_ignore(meta.get("ignore"), text, where)
    spans = [_parse_span(raw, text, f"{where} span {i}") for i, raw in enumerate(raw_spans)]
    spans.sort(key=lambda s: (s.start, s.end))
    for previous, current in itertools.pairwise(spans):
        if previous.overlaps(current):
            raise FixtureError(
                f"{where}: spans [{previous.start}, {previous.end}) and "
                f"[{current.start}, {current.end}) overlap"
            )
    return Document(doc_id, language, text, tuple(spans), meta)


def _check_ignore(raw: object, text: str, where: str) -> None:
    if raw is None:
        return
    if not isinstance(raw, list):
        raise FixtureError(f"{where}: 'meta.ignore' must be a list")
    for i, region in enumerate(raw):
        start = region.get("start") if isinstance(region, dict) else None
        end = region.get("end") if isinstance(region, dict) else None
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or isinstance(start, bool)
            or not 0 <= start < end <= len(text)
        ):
            raise FixtureError(f"{where}: 'meta.ignore' region {i} has bad offsets")


def ignore_regions(doc: Document) -> tuple[tuple[int, int], ...]:
    """The document's ignore regions (``meta.ignore``) as ``(start, end)`` pairs."""
    return tuple((int(r["start"]), int(r["end"])) for r in doc.meta.get("ignore") or ())


def _parse_span(raw: object, text: str, where: str) -> GoldSpan:
    if not isinstance(raw, dict):
        raise FixtureError(f"{where}: expected an object")
    unknown = set(raw) - _SPAN_KEYS
    if unknown:
        raise FixtureError(f"{where}: unknown fields {sorted(unknown)}")
    start, end = raw.get("start"), raw.get("end")
    if not isinstance(start, int) or not isinstance(end, int) or isinstance(start, bool):
        raise FixtureError(f"{where}: 'start' and 'end' must be integers")
    if not 0 <= start < end <= len(text):
        raise FixtureError(f"{where}: offsets [{start}, {end}) are out of range")
    try:
        entity_type = EntityType(raw.get("entity_type"))
    except ValueError:
        raise FixtureError(f"{where}: unknown entity_type") from None
    if entity_type.is_visual:
        raise FixtureError(f"{where}: {entity_type.value} is a visual type, not a text span")
    value = text[start:end]
    if "text" in raw and raw["text"] != value:
        raise FixtureError(f"{where}: 'text' does not match the document at [{start}, {end})")
    if not value.strip() or value != value.strip():
        raise FixtureError(f"{where}: span is blank or has surrounding whitespace")
    return GoldSpan(start, end, entity_type, value)


def load_fixtures(paths: str | Path | Iterable[str | Path]) -> list[Document]:
    """Load and validate one or more JSONL files (a directory means every ``*.jsonl`` in it).

    Raises :class:`FixtureError` for malformed records or duplicate ids across all files.
    """
    if isinstance(paths, str | Path):
        paths = [paths]
    documents: list[Document] = []
    seen: dict[str, str] = {}
    for path in _expand(paths):
        with path.open(encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                where = f"{path}:{lineno}"
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise FixtureError(f"{where}: invalid JSON ({exc.msg})") from None
                doc = parse_document(obj, where=where)
                if doc.id in seen:
                    raise FixtureError(
                        f"{where}: duplicate id {doc.id!r} (first in {seen[doc.id]})"
                    )
                seen[doc.id] = where
                documents.append(doc)
    return documents


def _expand(paths: Iterable[str | Path]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            out.extend(sorted(path.glob("*.jsonl")))
        elif path.is_file():
            out.append(path)
        else:
            raise FixtureError(f"{path}: no such file or directory")
    return out


def dump_document(doc: Document) -> str:
    """One JSONL line (no trailing newline), non-ASCII kept as is."""
    return json.dumps(doc.to_dict(), ensure_ascii=False)


def write_fixtures(path: str | Path, documents: Sequence[Document]) -> None:
    """Write ``documents`` as JSONL, one per line, after re-validating each."""
    ids = [doc.id for doc in documents]
    if len(set(ids)) != len(ids):
        raise FixtureError("duplicate document ids")
    lines = [dump_document(parse_document(doc.to_dict(), where=doc.id)) for doc in documents]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --- Markup -----------------------------------------------------------------------------

_MARKUP_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\|(.+?)\}\}", re.DOTALL)


def label(entity_type: EntityType | str, value: str) -> str:
    """Inline markup for a labelled value: ``label("PERSON", "X Y")`` -> ``{{PERSON|X Y}}``."""
    return f"{{{{{EntityType(entity_type).value}|{value}}}}}"


def from_markup(
    doc_id: str, marked: str, *, language: str, meta: Mapping[str, Any] | None = None
) -> Document:
    """Build a :class:`Document` from text with inline ``{{TYPE|value}}`` labels.

    Handy for hand-written fixtures and tests: offsets are computed, never typed by hand.
    """
    parts: list[str] = []
    spans: list[dict[str, object]] = []
    cursor = 0
    length = 0
    for match in _MARKUP_RE.finditer(marked):
        before = marked[cursor : match.start()]
        parts.append(before)
        length += len(before)
        value = match.group(2)
        spans.append({"start": length, "end": length + len(value), "entity_type": match.group(1)})
        parts.append(value)
        length += len(value)
        cursor = match.end()
    parts.append(marked[cursor:])
    record = {
        "id": doc_id,
        "language": language,
        "text": "".join(parts),
        "spans": spans,
        "meta": dict(meta or {}),
    }
    return parse_document(record, where=doc_id)
