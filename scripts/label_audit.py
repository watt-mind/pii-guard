"""Gold-label audit (LAB-1497): the same predictions scored on upstream and corrected labels.

``gretel`` runs one pii-guard system (``rules`` or ``fast`` = rules + NER) once over the
gretel-finance fixture files and scores **the same predictions twice**: against the upstream
gold, and against ``gretel-finance-corrected`` (``eval/datasets/gretel-finance/corrections.json``).
The difference is then label noise only, not a change of code, machine or model. It also counts,
per correction rule, how many corrected values the system had "leaked" on the upstream labels.

``mapa`` runs fast mode over MAPA EUR-Lex (local, git-ignored fixtures; real court text, never
sent anywhere) and describes each leaked ``PERSON`` value by its shape only: in how many of the
21 language versions the same string is a gold ``PERSON`` value (a name stays the same across
translations, a role word such as "the applicant" is translated), and whether it is one of a
fixed list of role words. Nothing written contains a text or a value; only counts::

    PII_GUARD_NER_DEVICE=cpu uv run --no-sync python scripts/label_audit.py gretel --system fast \\
        --json eval/results/2026-10-29-lab-1497-label-audit/gretel-fast.json
    PII_GUARD_NER_DEVICE=cpu uv run --no-sync python scripts/label_audit.py mapa \\
        --json eval/results/2026-10-29-lab-1497-label-audit/mapa-fast.json
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pii_guard.eval.datasets import corrections, get
from pii_guard.eval.fixtures import load_fixtures
from pii_guard.eval.record import text_metrics
from pii_guard.eval.report import build_scorecard, git_commit
from pii_guard.eval.scorer import DetectorAnalyzer, leak_report, run_documents
from pii_guard.vault import normalize_value

SYSTEMS = {"rules": ["rules"], "fast": ["rules", "ner"]}

#: Role and party words of EU court judgments, in the MAPA languages, lower-cased (with and
#: without an article where one is usual). Used only to count; written before the audit ran.
ROLE_WORDS = frozenset(
    {
        "applicant", "applicants", "the applicant", "the applicants", "defendant",
        "the defendant", "appellant", "the appellant", "respondent", "the respondent",
        "intervener", "the intervener", "claimant", "the claimant", "plaintiff",
        "advocate general", "rapporteur", "registrar", "judge", "president", "agent", "agents",
        "counsel", "kläger", "klägerin", "beklagte", "beklagter", "rechtsmittelführer",
        "rechtsmittelführerin", "generalanwalt", "generalanwältin", "berichterstatter",
        "kanzler", "requérant", "requérante", "défendeur", "défenderesse", "avocat général",
        "juge", "greffier", "demandante", "demandada", "recurrente", "recurrida",
        "abogado general", "ponente", "secretario", "agente", "agentes", "ricorrente",
        "convenuta", "avvocato generale", "relatore", "cancelliere", "verzoeker", "verzoekster",
        "verweerder", "verweerster", "advocaat-generaal", "rechter-rapporteur", "griffier",
        "sekretārs", "sekretāre", "felperes", "alperes", "főtanácsnok", "előadó",
        "hivatalvezető", "sökande", "svarande", "generaladvokat", "referent",
        "justitiesekreterare", "sagsøger", "sagsøgte", "žalobce", "žalovaný",
        "generální advokát", "soudce zpravodaj",
    }
)  # fmt: skip


def _analyzer(system: str) -> DetectorAnalyzer:
    analyzer = DetectorAnalyzer(SYSTEMS[system])
    if analyzer.skipped:
        raise SystemExit(f"{system}: detector unavailable: {analyzer.skipped}")
    analyzer.analyze("Warm-up text without personal data.", "en")
    return analyzer


def _summary(card: dict[str, Any]) -> dict[str, Any]:
    """The run-record view of a scorecard (``record.text_metrics``), trimmed to what changes."""
    o = text_metrics(card["overall"])
    languages = {lang: text_metrics(b) for lang, b in card["languages"].items()}
    per_type = {
        t: {"gold": b["gold"], "leaked": b["leak"]["leaked"], "values": b["leak"]["values"]}
        for t, b in sorted(o["per_type"].items())
        if b.get("leak")
    }
    return {
        "documents": o["documents"],
        "gold_spans": o["gold_spans"],
        "leak": o["leak"],
        "overlap_f1": round(o["overlap"]["f1"], 6),
        "over_masking": o["over_masking"],
        "per_type_leak": per_type,
        "languages": {
            lang: {"leak": b["leak"]["rate"], "values": b["leak"]["values"]}
            for lang, b in sorted(languages.items())
        },
    }


def _gretel(args: argparse.Namespace) -> dict[str, Any]:
    base = get("gretel-finance")
    fixed = get("gretel-finance-corrected")
    rules = corrections.load(fixed.corrections or "")
    paths = base.fixture_paths()
    docs = load_fixtures(paths)
    results = run_documents(docs, _analyzer(args.system))
    swapped = [
        dataclasses.replace(r, document=corrections.apply(r.document, rules)[0]) for r in results
    ]
    detectors = SYSTEMS[args.system]
    upstream = build_scorecard(results, detectors=detectors, fixture_paths=paths)
    corrected_card = build_scorecard(swapped, detectors=detectors)
    # Per rule: corrected values this system left unmasked on the upstream labels.
    by_rule: Counter[str] = Counter()
    for r in results:
        leaked = {
            (v.entity_type, normalize_value(v.value))
            for v in leak_report(r.document, r.masked_text)
            if v.leaked
        }
        counted: set[tuple[Any, str]] = set()
        for span in r.document.spans:
            rule = rules.match(span.entity_type.value, span.text)
            key = (span.entity_type, normalize_value(span.text))
            if rule is not None and key in leaked and key not in counted:
                counted.add(key)
                by_rule[rule.id] += 1
    commit, dirty = git_commit()
    return {
        "audit": "gretel-finance: the same predictions on upstream and corrected labels",
        "ticket": "LAB-1497",
        "system": args.system,
        "ner_model": "watt-mind/pii-guard-ner-xlmr-base@95f612a9 (v2.0)"
        if "ner" in detectors
        else None,
        "code": {"commit": commit, "dirty": dirty},
        "corrections": fixed.corrections,
        "upstream": _summary(upstream),
        "corrected": _summary(corrected_card),
        "upstream_leaks_that_are_corrected_values": dict(sorted(by_rule.items())),
    }


def _mapa(args: argparse.Namespace) -> dict[str, Any]:
    ds = get("mapa-eur-lex")
    docs = load_fixtures(ds.fixture_paths())
    results = run_documents(docs, _analyzer("fast"))
    langs: defaultdict[str, set[str]] = defaultdict(set)
    leaks = []
    gold_person = 0
    for r in results:
        for v in leak_report(r.document, r.masked_text):
            if v.entity_type.value != "PERSON":
                continue
            gold_person += 1
            langs[v.value.casefold()].add(r.document.language)
            if v.leaked:
                leaks.append((r.document.language, v.value))

    def bucket(n: int) -> str:
        return "1" if n == 1 else ("2-5" if n <= 5 else "6+")

    shape: Counter[str] = Counter(bucket(len(langs[v.casefold()])) for _, v in leaks)
    role_gold = sum(1 for v in langs if " ".join(v.split()) in ROLE_WORDS)
    role_leaked = sum(1 for _, v in leaks if " ".join(v.casefold().split()) in ROLE_WORDS)
    commit, dirty = git_commit()
    return {
        "audit": "mapa-eur-lex: what the leaked PERSON values are, by shape only",
        "ticket": "LAB-1511",
        "system": "fast",
        "ner_model": "watt-mind/pii-guard-ner-xlmr-base@95f612a9 (v2.0)",
        "code": {"commit": commit, "dirty": dirty},
        "documents": len(docs),
        "person_values": gold_person,
        "person_values_leaked": len(leaks),
        "leaked_by_languages_with_the_same_gold_string": dict(sorted(shape.items())),
        "leaked_by_language": dict(sorted(Counter(lang for lang, _ in leaks).items())),
        "role_word_list_size": len(ROLE_WORDS),
        "distinct_gold_person_strings_that_are_role_words": role_gold,
        "leaked_values_that_are_role_words": role_leaked,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("gretel")
    g.add_argument("--system", choices=list(SYSTEMS), default="fast")
    g.add_argument("--json", type=Path)
    m = sub.add_parser("mapa")
    m.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    out = _gretel(args) if args.command == "gretel" else _mapa(args)
    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
