"""Count sub-word NER spans and score fast mode (rules + NER) on fixture sets (LAB-1338).

A NER span that starts or ends inside a word (``Te|szt|`` in ``Teszt Eleknek``) masks only the
fragment and sends the rest of the name upstream. This script measures that, offline:

- **Fragments**, in the NER detector's own output (before the pipeline's resolver and suffix
  trim) and in the final masked spans, for the text types ``PERSON``, ``ORGANIZATION`` and
  ``ADDRESS``: a span that *starts* inside a word, and one that *ends* inside a word where
  the rest of the word is not a case ending the language pack reads off that stem
  (``Péter|t`` is a stem, ``Pirosk|áról`` is not).
- **Cut values**: text-type gold values with a word cut by a mask edge (``Te[[x]] Elek``),
  and the number of name characters left visible (case endings after a stem excepted).
- **Leak** (values that survive whole, and partially: one identifying token survives),
  **over-masking**, **precision** and **recall**, with the scorer the dataset runner uses.

``--probe`` adds a synthetic set built here: five fictional surnames (Kerekes, Gyakorló,
Minta, Próba, Teszt) with 20 given names inflected by a case ending (100 values) and 24 left
bare (120 values), in short Hungarian sentences. No text or value is printed, only counts.

::

    uv run --no-sync python scripts/probe_ner_subword.py --probe \\
        eval/fixtures/hu-inflection.jsonl eval/fixtures/hu-smoke.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from pii_guard.eval.datasets.run import document_counts
from pii_guard.eval.fixtures import Document, GoldSpan, load_fixtures
from pii_guard.eval.scorer import DetectorAnalyzer, leak_report, run_documents
from pii_guard.types import EntityType, Span
from pii_guard.vault.inflection import inflection_for, splits

TEXT_TYPES = frozenset({EntityType.PERSON, EntityType.ORGANIZATION, EntityType.ADDRESS})

SURNAMES = ("Kerekes", "Gyakorló", "Minta", "Próba", "Teszt")
INFLECTED = (
    ("Elek", "nek"), ("Piroska", "ról"), ("Tihamér", "ért"), ("Jakab", "bal"),
    ("Kelemen", "nek"), ("Ottó", "tól"), ("Hajna", "nak"), ("Zsuzsanna", "val"),
    ("Kende", "nek"), ("Szabolcs", "al"), ("Béla", "t"), ("Zoltán", "nal"),
    ("Ödön", "höz"), ("Gergely", "el"), ("Ilona", "ról"), ("Katalin", "nak"),
    ("Dénes", "től"), ("Imre", "nek"), ("Lajos", "sal"), ("Ágnes", "től"),
)  # fmt: skip
BARE = (
    "Elek", "Piroska", "Tihamér", "Jakab", "Kelemen", "Ottó", "Hajna", "Zsuzsanna",
    "Kende", "Szabolcs", "Béla", "Zoltán", "Ödön", "Gergely", "Márton", "Bálint",
    "Kornél", "Ilona", "Erzsébet", "Katalin", "Ágnes", "Dénes", "Imre", "Lajos",
)  # fmt: skip
INFLECTED_TEMPLATES = (
    "A számlát {} adtuk át.",
    "A levelet {} kaptuk meg tegnap.",
    "Holnap {} egyeztetünk a szerződésről.",
    "A csomagot {} küldtük el.",
)
BARE_TEMPLATES = (
    "{} írta alá a szerződést.",
    "A megrendelést {} rögzítette.",
    "Kérem, hívja vissza {} a héten.",
    "Az ügyintéző neve {}.",
)


def _word(char: str) -> bool:
    return char.isalnum() or char == "_"


def probe_documents() -> list[Document]:
    """The synthetic probe: 100 inflected and 120 bare fictional names, one per sentence."""
    matcher = inflection_for("hu")
    docs: list[Document] = []

    def add(template: str, value: str, tag: str) -> None:
        start = template.index("{}")
        text = template.format(value)
        span = GoldSpan(start, start + len(value), EntityType.PERSON, value)
        docs.append(Document(f"probe-{tag}-{len(docs):04d}", "hu", text, (span,), {"tags": [tag]}))

    for i, surname in enumerate(SURNAMES):
        for j, (given, suffix) in enumerate(INFLECTED):
            value = matcher.restore(f"{surname} {given}", suffix, EntityType.PERSON)
            add(INFLECTED_TEMPLATES[(i + j) % len(INFLECTED_TEMPLATES)], value, "inflected")
        for j, given in enumerate(BARE):
            add(BARE_TEMPLATES[(i + j) % len(BARE_TEMPLATES)], f"{surname} {given}", "bare")
    return docs


def fragment_kind(text: str, span: Span, language: str) -> str | None:
    """``"start"``, ``"end"`` or ``None``: where a text-type span cuts a word, if it does."""
    if span.entity_type not in TEXT_TYPES:
        return None
    if 0 < span.start < len(text) and _word(text[span.start - 1]) and _word(text[span.start]):
        return "start"
    end = span.end
    if 0 < end < len(text) and _word(text[end - 1]) and _word(text[end]):
        word_end = end
        while word_end < len(text) and _word(text[word_end]):
            word_end += 1
        surface = text[span.start : word_end]
        stems = {s.stem for s in splits(inflection_for(language), surface, span.entity_type)}
        if text[span.start : end] not in stems:
            return "end"
    return None


def split_words(doc: Document, masked: Sequence[Span]) -> tuple[int, int]:
    """``(values with a word cut by a mask edge, name characters left visible)``.

    For each text-type gold value, a word is *cut* when masked spans cover part of it and the
    visible rest is not a case ending after a stem the pack reads (``Te[[x]]`` is cut,
    ``[[x]]nak`` is not). Visible characters count every uncovered letter of the value
    except such case endings, so a name the model missed entirely counts too.
    """
    covered = [False] * len(doc.text)
    for s in masked:
        covered[s.start : s.end] = [True] * (s.end - s.start)
    matcher = inflection_for(doc.language)
    cut_values = visible = 0
    for gold in doc.spans:
        if gold.entity_type not in TEXT_TYPES:
            continue
        cut = False
        pos = gold.start
        while pos < gold.end:
            if not _word(doc.text[pos]):
                pos += 1
                continue
            end = pos
            while end < gold.end and _word(doc.text[end]):
                end += 1
            flags = covered[pos:end]
            hidden = sum(flags)
            if 0 < hidden < len(flags):
                head = flags.index(False)
                tail_suffix = all(flags[:head]) and not any(flags[head:])
                stems = {len(x.stem) for x in splits(matcher, doc.text[pos:end], gold.entity_type)}
                if tail_suffix and head in stems:
                    hidden = len(flags)
                else:
                    cut = True
            visible += len(flags) - hidden
            pos = end
        cut_values += cut
    return cut_values, visible


def measure(documents: Sequence[Document], analyzer: DetectorAnalyzer) -> dict[str, object]:
    ner = next(d for d in analyzer.detectors if d.name == "ner")
    seen: list[tuple[str, str, Span]] = []
    to_spans = ner.to_spans

    def recording(text: str, raw: object, language: str = "hu") -> list[Span]:
        out = to_spans(text, raw, language)  # type: ignore[arg-type]
        seen.extend((text, language, s) for s in out)
        return out

    ner.to_spans = recording  # type: ignore[method-assign]
    results = run_documents(documents, analyzer)
    ner.to_spans = to_spans  # type: ignore[method-assign]

    totals: Counter[str] = Counter()
    for r in results:
        counts = document_counts(r)
        for key in ("gold", "tp_gold", "pred", "tp_pred", "values", "leaked", "masked"):
            totals[key] += counts[key]
        totals["over_masked"] += counts["over_masked"]
        totals["partial"] += sum(v.partial for v in leak_report(r.document, r.masked_text))
        cut, visible = split_words(r.document, r.masked_spans)
        totals["values_cut"] += cut
        totals["name_chars_visible"] += visible
        for s in r.masked_spans:
            kind = fragment_kind(r.document.text, s, r.document.language)
            if kind:
                totals[f"masked_fragment_{kind}"] += 1
    for text, language, s in seen:
        if s.entity_type in TEXT_TYPES:
            totals["ner_text_spans"] += 1
        kind = fragment_kind(text, s, language)
        if kind:
            totals[f"ner_fragment_{kind}"] += 1

    def pct(a: str, b: str) -> float:
        return round(100 * totals[a] / totals[b], 2) if totals[b] else 0.0

    return {
        "documents": len(documents),
        "leak_pct": pct("leaked", "values"),
        "leak_or_partial_pct": round(
            100 * (totals["leaked"] + totals["partial"]) / totals["values"], 2
        )
        if totals["values"]
        else 0.0,
        "over_masking_pct": pct("over_masked", "masked"),
        "precision_pct": pct("tp_pred", "pred"),
        "recall_pct": pct("tp_gold", "gold"),
        **dict(sorted(totals.items())),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "paths",
        nargs="*",
        help="fixture files, each scored on its own; NAME=a.jsonl,b.jsonl scores several as one",
    )
    parser.add_argument("--probe", action="store_true", help="also score the synthetic probe")
    parser.add_argument("--json", type=Path, help="write the results here")
    args = parser.parse_args(argv)
    analyzer = DetectorAnalyzer(["rules", "ner"])
    if analyzer.skipped:
        print(f"detector unavailable: {analyzer.skipped}", file=sys.stderr)
        return 1
    analyzer.analyze("Warm-up text without personal data.", "en")
    sets: dict[str, list[Document]] = {}
    if args.probe:
        sets["probe"] = probe_documents()
    for arg in args.paths:
        name, _, files = arg.rpartition("=")
        paths = files.split(",")
        sets[name or Path(paths[0]).stem] = load_fixtures(paths)
    out = {}
    for name, docs in sets.items():
        out[name] = measure(docs, analyzer)
        print(name, json.dumps(out[name]), flush=True)
    if args.json:
        args.json.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
