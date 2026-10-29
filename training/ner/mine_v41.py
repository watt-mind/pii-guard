"""Error mining for NER v4.1 (LAB-1539): v2.0's leaks and over-masks on **development** splits.

Runs pii-guard fast mode (rules + the published NER v2.0, ``watt-mind/pii-guard-ner-xlmr-base``
at 95f612a9) over development files only, given on the command line:

- ``agent-traffic-dev``: ``eval/synthetic/dev/<lang>-agent-traffic-dev.jsonl`` (hu, en, de);
- ``openpii-dev``: the OpenPII-1M dev rows of v2.0 (hu, en, de) and of LAB-1525 (19 languages);
- ``eu-dev``: the dev splits of LAB-1525 (#251): Muse documents (lv, lt, hr) and English
  court style.

Never a test split, a smoke or inflection gate set, or MAPA / TAB text: :func:`check_inputs`
refuses those paths. Each miss is put in one value-free **pattern** (:func:`leak_pattern`,
:func:`overmask_pattern`): the type plus the context it sits in (a surname alone after an
honorific or a role word, a declined form, all caps, a possessive, a town in prose, a
capitalized common word ...). The mined documents never go into a training file: the variants
written per pattern (``training/ner/variants_v41.py``) are new fictional text::

    PII_GUARD_NER_DEVICE=cpu uv run --no-sync python training/ner/mine_v41.py \\
        --inputs <dir>/*.jsonl --json eval/results/2026-10-29-lab-1539-v41-data/mining.json \\
        --local <data dir>/mining/misses.jsonl

``--json`` holds counts only (per pool, language, pattern); ``--local`` holds the missed values
with a short context for the person naming the patterns and must be outside the repository or
under ``data/`` (git-ignored).
"""

# Honorifics in Cyrillic and Greek script and typographic apostrophes are the point.
# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pii_guard.eval.fixtures import Document, load_fixtures

#: Path fragments that are never mined (test, gates, real court text).
FORBIDDEN = ("test", "smoke", "inflection", "mapa", "tab-", "/tab/", "gate", "eval/fixtures/")

HONORIFICS = re.compile(
    r"(?i)\b(mr|mrs|ms|miss|dr|herr|frau|m|mme|mlle|sr|sra|sig|sig\.ra|dhr|mevr|pan|pani|"
    r"p|pán|pani|g|gospod|gospa|ga|kungen|hr|fru|κ|κα|г-н|г-жа|úr|né|sz|herra|rouva|"
    r"senhor|senhora|domnul|doamna|dna|dl|kun|ponas|ponia|kgs|kdz|sinjur|sinjura|an tUas|"
    r"bean|uasal)\.?\s*$"
)
ROLE_WORDS = re.compile(
    r"(?i)(claimant|defendant|applicant|appellant|respondent|witness|plaintiff|tenant|"
    r"landlord|employee|employer|kläger|beklagte|zeuge|antragsteller|requérant|défendeur|"
    r"témoin|demandante|demandado|testigo|ricorrente|convenuto|testimone|eiser|gedaagde|"
    r"getuige|powód|pozwany|świadek|žalobce|žalovaný|svědek|tužitelj|tuženik|svjedok|"
    r"tožnik|toženec|priča|prasītāj|atbildētāj|liecinie|ieškov|atsakov|liudytoj|"
    r"felperes|alperes|tanú|kantaja|vastaaja|todistaja|hageja|kostja|tunnista|kärande|"
    r"svarande|vittne|sagsøger|sagsøgte|vidne|reclamante|reclamado|testemunha|reclamant|"
    r"pârât|martor|ищец|ответник|свидетел|ενάγ|εναγόμεν|μάρτυρ|"
    r"agent|customer|client|user|patient|employee|manager|contact|sender|recipient)\W{0,3}"
    r"\s*\S{0,3}\s*$"
)
#: Honorifics and titles as whole words (an over-mask of one is its own pattern).
HONORIFIC_WORDS = re.compile(
    r"(?i)^(mr|mrs|ms|miss|madam|sir|dr|herr|frau|fräulein|monsieur|madame|mademoiselle|"
    r"señor|señora|señorita|signor|signora|signorina|senhor|senhora|domnul|doamna|"
    r"domnișoara|pan|pani|panna|pán|slečna|gospod|gospa|gospodična|gospodin|gospođa|"
    r"gospođica|kungs|kundze|ponas|ponia|panelė|úr|asszony|kisasszony|herra|rouva|neiti|"
    r"härra|proua|preili|fru|fröken|hr|κύριος|κυρία|δεσποινίς|κ|κα|господин|госпожа|"
    r"госпожица|sinjur|sinjura|sinjorina|uasal|bean|dhr|mevr|mevrouw|meneer|kgs|kdz)\.?$"
)
_CAPS = re.compile(r"^[^\W\d_]{2,}$")
CASE_RICH = frozenset({"pl", "cs", "sk", "hr", "sl", "lv", "lt", "fi", "et", "hu", "el", "ro"})


def check_inputs(paths: Sequence[Path]) -> None:
    for p in paths:
        low = p.as_posix().lower()
        name = p.name.lower()
        if not ("-dev" in name or "/dev/" in low):
            raise SystemExit(f"{p}: not a development split")
        if any(f in name for f in FORBIDDEN) or "/eval/fixtures/" in low:
            raise SystemExit(f"{p}: test, gate or real-text file: never mined")


def pool_of(path: Path) -> str:
    n = path.name
    if "agent-traffic-dev" in n:
        return "agent-traffic-dev"
    if "openpii-dev" in n:
        return "openpii-dev"
    return "eu-dev"


def _before(doc: Document, start: int, n: int = 40) -> str:
    return doc.text[max(0, start - n) : start]


def _after(doc: Document, end: int, n: int = 6) -> str:
    return doc.text[end : end + n]


def leak_pattern(doc: Document, entity_type: str, start: int, end: int) -> str:
    """A value-free name for the context a leaked gold value sits in."""
    value = doc.text[start:end]
    before, after = _before(doc, start), _after(doc, end)
    if entity_type == "PERSON":
        words = value.split()
        if all(w.isupper() for w in words if len(w) > 1 and _CAPS.match(w)) and any(
            len(w) > 1 for w in words
        ):
            return "person:all-caps"
        if re.search(r"(?:^|\s)[^\W\d_]\.\s*$", before) or re.search(r"\b[^\W\d_]\.", value):
            return "person:initials"
        if len(words) == 1:
            if HONORIFICS.search(before):
                return "person:surname-after-honorific"
            if ROLE_WORDS.search(before):
                return "person:name-after-role-word"
            if re.match(r"^['’]s?\b|^s\b", after):
                return "person:possessive"
            if value[:1].islower():
                return "person:lowercase"
            if doc.language in CASE_RICH:
                return "person:single-token-case-rich"
            return "person:single-token"
        if any(p in words for p in ("de", "van", "von", "der", "di", "da", "du", "le", "la")):
            return "person:particle"
        if "-" in value:
            return "person:hyphenated"
        if re.search(r"[:\-]\s*$|^\s*$", before.splitlines()[-1] if before.splitlines() else ""):
            return "person:line-start-or-label"
        if doc.language in CASE_RICH:
            return "person:full-name-case-rich"
        return "person:full-name"
    if entity_type == "ORGANIZATION":
        return "organization:" + ("all-caps" if value.isupper() else "mixed")
    if entity_type == "ADDRESS":
        return "address:" + ("multi-line" if "\n" in value else "one-line")
    if entity_type in ("BANK_ACCOUNT", "ID_DOCUMENT", "PHONE", "TAX_ID"):
        compact = re.sub(r"[\s\-./()+]", "", value)
        if compact.isdigit():
            return f"{entity_type.lower()}:digits-{'long' if len(compact) > 12 else 'short'}"
        return f"{entity_type.lower()}:alnum"
    return entity_type.lower()


def overmask_pattern(doc: Document, entity_type: str, start: int, end: int) -> str:
    """A value-free name for a masked span that overlaps no gold value."""
    value = doc.text[start:end]
    before = _before(doc, start, 3)
    words = value.split()
    t = entity_type.lower()
    if entity_type in ("PERSON", "ORGANIZATION", "ADDRESS"):
        if any(HONORIFIC_WORDS.match(w) for w in words):
            return f"{t}:honorific"
        if not value[:1].isupper():
            return f"{t}:lowercase-word"
        if value.isupper() and len(value) > 1:
            return f"{t}:all-caps-word"
        if re.search(r"(^|[.!?]\s+|\n)$", before) and len(words) == 1:
            return f"{t}:sentence-initial-word"
        if any(c.isdigit() for c in value):
            return f"{t}:with-digits"
        if len(words) == 1:
            return f"{t}:single-capitalized-word"
        return f"{t}:multi-word"
    compact = re.sub(r"[\s\-./()+]", "", value)
    if compact.isdigit():
        return f"{t}:digits-{'long' if len(compact) > 12 else 'short'}"
    return f"{t}:other"


def mine(docs: Sequence[Document], pool: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from pii_guard.eval.scorer import DetectorAnalyzer, leak_report, over_masked, run_documents

    analyzer = DetectorAnalyzer(["rules", "ner"])
    results = run_documents(docs, analyzer)
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    local: list[dict[str, Any]] = []
    for res in results:
        doc = res.document
        lang = doc.language
        counts[lang]["documents"] += 1
        for leak in leak_report(doc, res.masked_text, replacements=res.replacements):
            t = leak.entity_type.value
            counts[lang][f"{t}:values"] += 1
            if not leak.leaked:
                continue
            span = next((s for s in doc.spans if s.text == leak.value), None)
            start, end = (span.start, span.end) if span else (0, 0)
            pat = leak_pattern(doc, t, start, end)
            counts[lang][f"leak:{pat}"] += 1
            local.append(_row(pool, doc, "leak", t, pat, start, end))
        counts[lang]["masked"] += len(res.masked_spans)
        for span in over_masked(doc, res.masked_spans):
            t = span.entity_type.value
            pat = overmask_pattern(doc, t, span.start, span.end)
            counts[lang][f"overmask:{pat}"] += 1
            local.append(_row(pool, doc, "overmask", t, pat, span.start, span.end))
    summary = {
        "documents": len(docs),
        "languages": {lang: dict(sorted(c.items())) for lang, c in sorted(counts.items())},
    }
    return summary, local


def _row(
    pool: str, doc: Document, kind: str, t: str, pat: str, start: int, end: int
) -> dict[str, Any]:
    return {
        "pool": pool,
        "doc": doc.id,
        "language": doc.language,
        "kind": kind,
        "type": t,
        "pattern": pat,
        "value": doc.text[start:end],
        "context": doc.text[max(0, start - 80) : end + 80],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--local", type=Path, required=True)
    args = parser.parse_args(argv)
    check_inputs(args.inputs)
    repo = Path(__file__).resolve().parents[2]
    local_path = args.local.resolve()
    if local_path.is_relative_to(repo) and not local_path.is_relative_to(repo / "data"):
        parser.error("--local must be outside the repository or under data/: it holds values")
    by_pool: dict[str, list[Document]] = defaultdict(list)
    for path in sorted(args.inputs):
        by_pool[pool_of(path)].extend(load_fixtures([path]))
    report: dict[str, Any] = {
        "ticket": "LAB-1539",
        "model": "watt-mind/pii-guard-ner-xlmr-base v2.0 (95f612a9), fast mode (rules + NER)",
        "inputs": [p.name for p in sorted(args.inputs)],
        "pools": {},
        "patterns": {},
    }
    local: list[dict[str, Any]] = []
    for name, docs in sorted(by_pool.items()):
        summary, rows = mine(docs, name)
        report["pools"][name] = summary
        local.extend(rows)
        print(f"{name}: {len(docs)} docs, {len(rows)} misses", file=sys.stderr, flush=True)
    patterns = Counter(f"{r['kind']}:{r['pattern']}" for r in local)
    report["patterns"] = dict(patterns.most_common())
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.local.parent.mkdir(parents=True, exist_ok=True)
    with args.local.open("w", encoding="utf-8") as fh:
        for row in local:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
