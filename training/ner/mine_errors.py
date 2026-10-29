"""Error mining for NER v3.2 (LAB-1494): what v2.0 misses on **development** data only.

Runs pii-guard fast mode (rules + the published NER v2.0) over three development pools, never a
test split and never agent-traffic-dev (the selection set):

- ``openpii``: a fresh seeded sample (seed 1494) of the Ai4Privacy OpenPII-1M **train** split,
  pl / hu / en / de, disjoint from the eval sample and from v2.0's own train and dev rows.
- ``mapa-dev``: the MAPA project's EUR-Lex **validation** split (``joelniklaus/mapa``,
  CC-BY-4.0): one General Court judgment in 21 languages, a different document from the two
  in the MAPA test set. Real court text: read locally, never sent to a remote model.
- ``gretel-dev``: a seeded sample of Gretel ``synthetic_pii_finance_multilingual`` **train**
  (en / de; the eval set is its test split).

Writes counts per pool, language, type and context family (``--json``; no value, no text) and,
for the person running it, the missed values with a short context to a git-ignored file
(``--local``, under ``data/``) so error families can be named. Mined documents never go into a
training file: the variants written from the families are new fictional text::

    PII_GUARD_NER_DEVICE=cpu uv run --no-sync python training/ner/mine_errors.py \\
        --openpii data/public/openpii-train/train.jsonl \\
        --mapa data/mining/raw/mapa-validation.jsonl \\
        --gretel data/mining/raw/gretel-train.parquet \\
        --json eval/results/2026-10-29-ner-v32/mining.json --local data/mining/misses.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from pii_guard.eval.datasets import gretel
from pii_guard.eval.datasets._common import ConversionError, LabelMap, Row, convert
from pii_guard.eval.fixtures import Document, load_fixtures
from pii_guard.types import EntityType

sys.path.insert(0, str(Path(__file__).resolve().parent))
import openpii

SEED = 1494
OPENPII_WANT = {"pl": 400, "hu": 300, "en": 300, "de": 300}
GRETEL_WANT = {"en": 300, "de": 300}
#: v2.0's OpenPII rows (train + dev): skipped, so the pool is new to the model.
V2_OPENPII = sorted(Path("eval/generated/openpii-train").glob("*-openpii-*.jsonl"))

MAPA_LABELS = LabelMap(
    types={
        "PERSON": EntityType.PERSON,
        "ADDRESS": EntityType.ADDRESS,
        "ORGANISATION": EntityType.ORGANIZATION,
        "DATE": None,
        "AMOUNT": None,
    }
)


def mapa_rows(path: Path) -> Iterator[Row]:
    """One document per file, tokens and sentences joined with a space.

    MAPA's sentence splitter breaks after an initial ("B ." | "Spinoit"), so joining sentences
    with a newline would cut every initial off its surname; a space keeps "B . Spinoit" whole.
    """
    docs: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            raw = json.loads(line)
            doc = docs.setdefault(raw["file_name"], {"lang": raw["language"], "sents": []})
            doc["sents"].append((int(raw["sentence_number"]), raw["tokens"], raw["coarse_grained"]))
    for name, doc in sorted(docs.items()):
        text, spans, pos = [], [], 0
        for _, tokens, tags in sorted(doc["sents"], key=lambda s: s[0]):
            open_span: list[Any] | None = None
            for token, tag in zip(tokens, tags, strict=True):
                start = pos
                text.append(token)
                pos += len(token)
                end = pos
                text.append(" ")
                pos += 1
                kind, _, label = tag.partition("-")
                if kind == "B" or (kind == "I" and (open_span is None or open_span[2] != label)):
                    if open_span:
                        spans.append(tuple(open_span))
                    open_span = [start, end, label]
                elif kind == "I" and open_span is not None:
                    open_span[1] = end
                else:
                    if open_span:
                        spans.append(tuple(open_span))
                    open_span = None
            if open_span:
                spans.append(tuple(open_span))
        yield Row(name.removesuffix(".txt"), doc["lang"], "".join(text), tuple(spans))


def _order(uid: str) -> str:
    return hashlib.sha256(f"{SEED}:{uid}".encode()).hexdigest()


def gretel_docs(path: Path) -> list[Document]:
    by_lang: dict[str, list[Row]] = defaultdict(list)
    for row in gretel.rows([path]):
        by_lang[row.language].append(row)
    out: list[Document] = []
    for lang, want in GRETEL_WANT.items():
        for row in sorted(by_lang[lang], key=lambda r: _order(r.uid)):
            if sum(d.language == lang for d in out) == want:
                break
            try:
                out.append(
                    convert(
                        row, gretel.LABELS, prefix="gretel-dev", kind="finance", source="gretel"
                    ).document
                )
            except ConversionError:
                continue
    return out


def mapa_docs(path: Path) -> list[Document]:
    out = []
    for row in mapa_rows(path):
        try:
            out.append(
                convert(row, MAPA_LABELS, prefix="mapa-dev", kind="legal", source="mapa").document
            )
        except ConversionError:
            continue
    return out


def openpii_docs(path: Path) -> list[Document]:
    eval_uids, eval_texts = openpii.eval_holdout()
    v2 = {str(d.meta.get("uid")) for d in load_fixtures(V2_OPENPII)} if V2_OPENPII else set()
    chosen, _ = openpii.select(
        openpii.stream_file(path), OPENPII_WANT, SEED, eval_uids | v2, eval_texts
    )
    return [d for docs in chosen.values() for d in docs]


_CAPS = re.compile(r"^[A-ZÀ-ÖØ-ÞĄĆĘŁŃÓŚŹŻŐŰ][A-ZÀ-ÖØ-ÞĄĆĘŁŃÓŚŹŻŐŰ\-]+$")


def family(pool: str, doc: Document, entity_type: str, value: str, start: int) -> str:
    """A coarse, value-free name for the context a miss sits in."""
    before = doc.text[max(0, start - 30) : start]
    if entity_type == "PERSON":
        words = value.split()
        if all(_CAPS.match(w) for w in words if len(w) > 1):
            return "person:all-caps"
        if len(words) == 1:
            return "person:single-token"
        if re.search(r"\b[A-Z]\.\s*$", before) or re.search(r"\b[A-Z]\.", value):
            return "person:initials"
        if doc.language == "pl":
            return "person:pl-inflected-or-full"
        return "person:full-name"
    if entity_type in ("BANK_ACCOUNT", "ID_DOCUMENT", "PHONE"):
        compact = re.sub(r"[\s\-./]", "", value)
        if compact.isdigit():
            return f"{entity_type.lower()}:digits-{'long' if len(compact) > 12 else 'short'}"
        return f"{entity_type.lower()}:alnum"
    return entity_type.lower()


def mine(docs: Sequence[Document], pool: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from pii_guard.eval.scorer import DetectorAnalyzer, leak_report, run_documents

    analyzer = DetectorAnalyzer(["rules", "ner"])
    results = run_documents(docs, analyzer)
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    local: list[dict[str, Any]] = []
    for res in results:
        doc = res.document
        lang = doc.language
        for leak in leak_report(doc, res.masked_text, replacements=res.replacements):
            t = leak.entity_type.value
            counts[lang][f"{t}:values"] += 1
            if not leak.leaked:
                continue
            counts[lang][f"{t}:leaked"] += 1
            start = next((s.start for s in doc.spans if s.text == leak.value), 0)
            fam = family(pool, doc, t, leak.value, start)
            counts[lang][f"family:{fam}"] += 1
            local.append(
                {
                    "pool": pool,
                    "doc": doc.id,
                    "language": lang,
                    "type": t,
                    "family": fam,
                    "value": leak.value,
                    "context": doc.text[max(0, start - 80) : start + len(leak.value) + 80],
                }
            )
    summary = {
        "documents": len(docs),
        "languages": {lang: dict(sorted(c.items())) for lang, c in sorted(counts.items())},
    }
    return summary, local


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--openpii", type=Path, required=True)
    parser.add_argument("--mapa", type=Path, required=True)
    parser.add_argument("--gretel", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--local", type=Path, required=True)
    parser.add_argument("--pools", nargs="+", default=["mapa-dev", "gretel-dev", "openpii-dev"])
    args = parser.parse_args(argv)
    if not str(args.local).startswith("data/"):
        parser.error("--local must be under data/ (git-ignored): it holds values")
    loaders = {
        "mapa-dev": lambda: mapa_docs(args.mapa),
        "gretel-dev": lambda: gretel_docs(args.gretel),
        "openpii-dev": lambda: openpii_docs(args.openpii),
    }
    pools = {name: loaders[name]() for name in args.pools}
    report: dict[str, Any] = {
        "ticket": "LAB-1494",
        "model": "watt-mind/pii-guard-ner-xlmr-base v2.0 (95f612a9), fast mode (rules + NER)",
        "seed": SEED,
        "pools": {},
    }
    local: list[dict[str, Any]] = []
    for name, docs in pools.items():
        summary, rows = mine(docs, name)
        report["pools"][name] = summary
        local.extend(rows)
        print(f"{name}: {len(docs)} docs, {len(rows)} missed values", file=sys.stderr, flush=True)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.local.parent.mkdir(parents=True, exist_ok=True)
    with args.local.open("w", encoding="utf-8") as fh:
        for row in local:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
