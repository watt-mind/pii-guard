"""Corrected-label variants of a dataset: committed, reviewable gold corrections (LAB-1497).

Some public sets carry gold labels that are plainly wrong: in Gretel finance, German set phrases
("Damen", "Herren", "Im Rahmen"), common nouns ("Saldo") and template slots
("[Borrower Name]") are labelled as names. Every system pays for them as a leak, so the
published leak rate of such a set mixes model error with label noise.

A correction never edits the upstream set. ``eval/datasets/<set>/corrections.json`` lists, per
class of error, the rationale and the exact span texts it covers; this module applies it to the
set's fixture files and writes a **separate** set, ``<set>-corrected``, with its own manifest.
So both numbers exist side by side: every system on ``<set>`` as published upstream, and on
``<set>-corrected``.

Rules (the file's ``about`` says the same):

- A rule matches a gold span of one of its ``entity_types`` whose text, with whitespace runs
  collapsed to one space, equals one of its ``values`` exactly (case-sensitive). It matches on
  the span's own text only, never on any system's output.
- A matched span stops being gold and becomes an ignore region labelled
  ``corrected:<rule id>`` (``meta.ignore``): unmasked it is not a leak, masked it is not
  over-masking. Every system is treated alike.
- Nothing else changes: texts, ids, the other spans and ignore regions are kept byte for byte.

```
python -m pii_guard.eval.datasets fetch gretel-finance-corrected   # writes data/ + manifest
python -m pii_guard.eval.datasets check gretel-finance-corrected   # rebuild, compare
```
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pii_guard.eval.datasets._common import dump_json
from pii_guard.eval.datasets.spec import Dataset
from pii_guard.eval.fixtures import Document, file_sha256, load_fixtures, write_fixtures

__all__ = [
    "LABEL_PREFIX",
    "Corrections",
    "Rule",
    "apply",
    "build",
    "check",
    "corrected",
    "fetch",
    "load",
    "manifest",
]

#: Ignore-region label of a corrected span: ``corrected:<rule id>``.
LABEL_PREFIX = "corrected:"


def _norm(text: str) -> str:
    return " ".join(text.split())


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    entity_types: tuple[str, ...]
    rationale: str
    values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Corrections:
    dataset: str
    rules: tuple[Rule, ...]

    def match(self, entity_type: str, text: str) -> Rule | None:
        value = _norm(text)
        for rule in self.rules:
            if entity_type in rule.entity_types and value in rule.values:
                return rule
        return None


def load(path: str | Path) -> Corrections:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    rules = []
    seen: set[tuple[str, str]] = set()
    for r in raw["rules"]:
        values = tuple(r["values"])
        if any(v != _norm(v) or not v for v in values):
            raise ValueError(f"{path}: rule {r['id']!r} has a value that isn't normalised")
        for t in r["entity_types"]:
            for v in values:
                if (t, v) in seen:
                    raise ValueError(f"{path}: a {t} value is listed twice (rule {r['id']!r})")
                seen.add((t, v))
        rules.append(Rule(r["id"], tuple(r["entity_types"]), r["rationale"], values))
    return Corrections(raw["dataset"], tuple(rules))


def apply(doc: Document, corrections: Corrections) -> tuple[Document, Counter[str]]:
    """``doc`` with the matched gold spans turned into ignore regions, and counts per rule."""
    kept = []
    ignore = list(doc.meta.get("ignore") or [])
    counts: Counter[str] = Counter()
    for span in doc.spans:
        rule = corrections.match(span.entity_type.value, span.text)
        if rule is None:
            kept.append(span)
            continue
        counts[f"{rule.id}:{span.entity_type.value}"] += 1
        ignore.append({"start": span.start, "end": span.end, "label": LABEL_PREFIX + rule.id})
    if not counts:
        return doc, counts
    ignore.sort(key=lambda r: (int(r["start"]), int(r["end"]), str(r["label"])))
    meta = {**doc.meta, "ignore": ignore}
    return dataclasses.replace(doc, spans=tuple(kept), meta=meta), counts


def corrected(base: Dataset, corrections_file: str) -> Dataset:
    """The ``<base>-corrected`` set: same documents, gold corrected by ``corrections_file``."""
    return dataclasses.replace(
        base,
        name=f"{base.name}-corrected",
        title=f"{base.title}, corrected labels",
        files=(),
        commit_rows=False,  # rebuilt from the committed base and corrections, never committed
        read=None,
        description=f"{base.description}; gold corrected ({corrections_file})",
        notes=(
            f"Derived from {base.name}: the same documents, with the gold corrections in "
            f"{corrections_file} (LAB-1497). {base.name} keeps the upstream labels.",
            *base.notes,
        ),
        derived_from=base.name,
        corrections=corrections_file,
    )


def _base(ds: Dataset) -> Dataset:
    from pii_guard.eval.datasets import get

    assert ds.derived_from is not None  # noqa: S101
    return get(ds.derived_from)


def build(
    ds: Dataset,
) -> tuple[dict[str, list[Document]], dict[str, Counter[str]], dict[str, Path]]:
    """Corrected documents per language, the counts per rule, and the base files read."""
    assert ds.corrections is not None  # noqa: S101
    rules = load(ds.corrections)
    base = _base(ds)
    if rules.dataset != base.name:
        raise ValueError(f"{ds.corrections}: corrections for {rules.dataset!r}, not {base.name!r}")
    docs: dict[str, list[Document]] = {}
    counts: dict[str, Counter[str]] = {}
    sources: dict[str, Path] = {}
    for lang, path in zip(base.languages, base.fixture_paths(), strict=True):
        if not path.is_file():
            raise FileNotFoundError(
                f"{base.name}: {path} missing; run `python -m pii_guard.eval.datasets fetch "
                f"{base.name}` first"
            )
        out: list[Document] = []
        c: Counter[str] = Counter()
        for doc in load_fixtures([path]):
            new, n = apply(doc, rules)
            out.append(new)
            c.update(n)
        docs[lang], counts[lang], sources[lang] = out, c, path
    return docs, counts, sources


def manifest(
    ds: Dataset,
    docs: Mapping[str, Sequence[Document]],
    counts: Mapping[str, Counter[str]],
    sources: Mapping[str, Path],
    outputs: Mapping[str, str],
) -> dict[str, Any]:
    """Counts only: what was corrected, per rule and language. No text, no value."""
    assert ds.corrections is not None  # noqa: S101
    rules = load(ds.corrections)
    total: Counter[str] = Counter()
    for c in counts.values():
        total.update(c)
    matched = {k.split(":")[0] for k in total}
    languages: dict[str, Any] = {}
    for lang, items in docs.items():
        gold: Counter[str] = Counter(s.entity_type.value for d in items for s in d.spans)
        languages[lang] = {
            "documents": len(items),
            "base_file": str(sources[lang]),
            "base_sha256": file_sha256(sources[lang]),
            "file": str(ds.fixtures_dir / f"{lang}-{ds.name}.jsonl"),
            "sha256": outputs[lang],
            "gold_spans": dict(sorted(gold.items())),
            "corrected": dict(sorted(counts[lang].items())),
            "documents_changed": sum(
                1 for d in items if any(_is_corrected(r) for r in d.meta.get("ignore") or [])
            ),
        }
    return {
        "dataset": ds.name,
        "title": ds.title,
        "derived_from": ds.derived_from,
        "corrections": ds.corrections,
        "corrections_sha256": file_sha256(Path(ds.corrections)),
        "license": ds.license,
        "synthetic": ds.synthetic,
        "rows_committed": False,
        "split": ds.split,
        "rule": (
            "a gold span of a rule's entity type whose whitespace-normalised text equals one of "
            "its values becomes an ignore region labelled corrected:<rule id>"
        ),
        "rules": [
            {
                "id": r.id,
                "entity_types": list(r.entity_types),
                "values": len(r.values),
                "spans_corrected": sum(v for k, v in total.items() if k.split(":")[0] == r.id),
            }
            for r in rules.rules
        ],
        "unused_rules": [r.id for r in rules.rules if r.id not in matched],
        "corrected": dict(sorted(total.items())),
        "notes": list(ds.notes),
        "languages": languages,
    }


def _is_corrected(region: Mapping[str, Any]) -> bool:
    return str(region.get("label", "")).startswith(LABEL_PREFIX)


def _write(ds: Dataset, out_dir: Path) -> tuple[dict[str, Any], list[Path]]:
    docs, counts, sources = build(ds)
    out_dir.mkdir(parents=True, exist_ok=True)
    written, outputs = [], {}
    for lang, items in docs.items():
        path = out_dir / f"{lang}-{ds.name}.jsonl"
        write_fixtures(path, items)
        outputs[lang] = file_sha256(path)
        written.append(path)
    return manifest(ds, docs, counts, sources, outputs), written


def fetch(ds: Dataset) -> list[Path]:
    """Write the corrected fixture files (git-ignored ``data/``) and the committed manifest."""
    mine, written = _write(ds, ds.fixtures_dir)
    ds.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    ds.manifest_path.write_text(dump_json(mine), encoding="utf-8")
    return [*written, ds.manifest_path]


def check(ds: Dataset) -> list[str]:
    """Differences between a rebuild and the committed manifest (and local files, if any)."""
    with tempfile.TemporaryDirectory() as tmp:
        mine, written = _write(ds, Path(tmp))
        problems = []
        for path in written:
            local = ds.fixtures_dir / path.name
            if local.is_file() and local.read_bytes() != path.read_bytes():
                problems.append(f"{local}: differs from a rebuild; run fetch {ds.name}")
    try:
        committed = json.loads(ds.manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{ds.manifest_path}: unreadable ({exc.__class__.__name__})"]
    problems += [
        f"{ds.manifest_path}: {key!r} differs"
        for key in sorted(set(mine) | set(committed))
        if mine.get(key) != committed.get(key)
    ]
    return problems
