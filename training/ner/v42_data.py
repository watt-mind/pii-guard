"""Assemble the NER v4.2 training mixes (LAB-1625) and record what went in.

Fictional / synthetic data only (ADR 0005); no MAPA, TAB or other real text (LAB-1419). v4.2
keeps the v4.1-A1 recipe and mix (v2.0 warm start, 1 epoch, lr 1e-5; OpenPII EU and kiji
``ADDRESS`` out of the loss) and changes two things, fixed in
``eval/results/2026-10-30-lab-1625-ner-v42/README.md`` before any training:

1. **Birth-date labels in the third-party rows.** kiji, nym and E3 label dates that are not
   birth dates as ``DATE_OF_BIRTH``: a contract date, a payment deadline, a flight date, even a
   town (E3: 89 spans without a digit). Measured on the training files before any run: of their
   9,357 ``DATE_OF_BIRTH`` spans, 93 hold no digit, 6,622 are cued, 2,079 are uncued but
   plausible and 563 are uncued and implausible (no year, or a year from 2010 on). A span
   is **cued** when a birth word (``born``, ``geb.``, ``nato`` ...) is in it or just before it,
   and **plausible** when it has a digit and a year from 1900 to 2009. Mode ``o`` drops the
   implausible uncued spans (taught as ``O``); mode ``ign`` keeps every uncued span out of the
   loss. pii-anon (structured rows), the s11 replay and the targeted sets are not changed.
2. **Targeted documents** (``targeted``, ``v42_gen.py`` pool ``train``, no model call): German
   genitive names, Hungarian common-word surnames with an inflected given name, birth dates next
   to non-birth dates (``O``) in hu/en/de, and order, customer and reference numbers (``O``)
   next to an IBAN. Their frames and names are disjoint from the selection split's
   (``selection_v42.py``); a document naming a person whose full name occurs in any evaluation
   text is redrawn, and ``decontam.py`` gates the files.

::

    uv run --no-sync python training/ner/v41_data.py targeted        # the v4.1 targeted sets
    uv run --no-sync python training/ner/v42_data.py targeted
    uv run --no-sync python training/ner/v42_data.py build \\
        --json eval/results/2026-10-30-lab-1625-ner-v42/data.json

``build`` writes ``eval/generated/v42-mix/`` (git-ignored; uploaded with the Modal call through
the LAB-1527 allowlist) and one config per trained candidate, ``training/ner/v42-<c>.toml``.
The JSON report holds counts, gold spans per type and SHA-256 per file, never text.
"""

# Seeded synthetic data: the standard PRNG is the point.
# ruff: noqa: S311

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decontam
import smoke_style_dev as ssd
import targeted_v33 as t33
import v41_data as v41
import v42_gen as g

from pii_guard.eval.fixtures import Document, write_fixtures

GEN = Path("eval/generated")
OUT = GEN / "v42-mix"
TARGETED = OUT / "targeted"
SELECTION = GEN / "selection-v42"
SEED = 1625
DEV_SEED = 162500
PHASE1_REV = "2df7dc6375a41f293a8eaa5a9caaf0447babc184"  # LAB-1547's regenerated phase1
#: (slice, language, train docs, dev docs). Fixed in the protocol README.
TARGETED_PLAN: tuple[tuple[str, str, int, int], ...] = (
    ("de-genitive", "de", 1500, 100),
    ("hu-surname-given", "hu", 1500, 100),
    ("dates", "hu", 800, 50),
    ("dates", "en", 800, 50),
    ("dates", "de", 800, 50),
    ("numbers", "hu", 300, 30),
    ("numbers", "en", 300, 30),
    ("numbers", "de", 300, 30),
)
#: Trained candidates, in selection order: (DOB mode, copies of each targeted train file).
CANDIDATES: dict[str, tuple[str, int]] = {"b1": ("o", 1), "b2": ("ign", 1), "b3": ("o", 2)}
DOB_SOURCES = ("kiji", "nym", "e3")

# --- birth-date plausibility --------------------------------------------------------------------

#: Birth words of the mix's languages (lower case, matched as substrings near the span).
BIRTH_CUE = re.compile(
    r"birth|born|\bdob\b|d\.o\.b|geb\.|geboren|geburt|\bnée?\b|naiss|nacid|nacim|nascit|\bnat[oa]\b"
    r"|nasc|urodz|född|født|fødsel|synty|γενν|γέννη|naroz|rođen|rojen|dzim|gimę|gim\.|narod"
    r"|szül|twel|imwiel|geboorte|geboren op|nato il|nata il|rodzen|syntynyt|sünd",
    re.IGNORECASE,
)
YEAR = re.compile(r"(?<!\d)(1[89]\d\d|20\d\d)(?!\d)")
CUE_WINDOW = 50


def is_cued(text: str, start: int, end: int, floor: int = 0) -> bool:
    """A birth word inside the span or in the ``CUE_WINDOW`` characters before it, but not
    before ``floor`` (the end of the previous date span: a cue belongs to the first date)."""
    return bool(BIRTH_CUE.search(text[max(0, floor, start - CUE_WINDOW) : end]))


def is_plausible(value: str) -> bool:
    """A digit and a year from 1900 to 2009: what a birth date of a living adult looks like."""
    if not any(ch.isdigit() for ch in value):
        return False
    years = [int(y) for y in YEAR.findall(value)]
    return bool(years) and all(1900 <= y <= 2009 for y in years)


def treat_dob(lines: Sequence[str], mode: str) -> tuple[list[str], Counter[str]]:
    """Apply a DOB mode to JSONL ``lines``: ``o`` drops implausible uncued spans; ``ign`` moves
    every uncued span to ``meta.loss_ignore``. A span without a digit is never a date: ``o``
    drops it, ``ign`` ignores it, cued or not. Returns the lines and what was done."""
    out: list[str] = []
    stats: Counter[str] = Counter()
    for ln in lines:
        doc = json.loads(ln)
        keep: list[dict[str, Any]] = []
        ignore: list[list[int]] = []
        floor = 0
        for s in sorted(doc.get("spans", ()), key=lambda x: x["start"]):
            if s.get("entity_type") != "DATE_OF_BIRTH":
                keep.append(s)
                continue
            stats["dob"] += 1
            value = s.get("text") or doc["text"][s["start"] : s["end"]]
            if not any(ch.isdigit() for ch in value):  # a town or a word, never a date
                stats["no_digit"] += 1
                if mode == "ign":
                    ignore.append([s["start"], s["end"]])
                continue
            cued, floor = is_cued(doc["text"], s["start"], s["end"], floor), s["end"]
            if cued:
                stats["cued"] += 1
                keep.append(s)
                continue
            plausible = is_plausible(value)
            stats["uncued_plausible" if plausible else "uncued_implausible"] += 1
            if mode == "ign":
                ignore.append([s["start"], s["end"]])
            elif plausible:
                keep.append(s)
            # mode "o", implausible: dropped, the date is taught as O
        if len(keep) != len(doc.get("spans", ())):
            doc["spans"] = keep
            if ignore:
                meta = doc.setdefault("meta", {})
                meta["loss_ignore"] = [*meta.get("loss_ignore", ()), *ignore]
        out.append(json.dumps(doc, ensure_ascii=False))
    return out, stats


# --- targeted documents ------------------------------------------------------------------------


def generate(slice_: str, lang: str, n: int, seed: int, blob: str, split: str) -> list[Document]:
    rng = random.Random(f"{seed}-{slice_}-{lang}")
    avoid = ssd._smoke_names()
    docs: list[Document] = []
    for index in range(n):
        for _attempt in range(200):
            b = g.BUILDERS[slice_](lang, "train", rng, avoid)
            if not any(name in blob for name in b.names):
                break
        else:  # pragma: no cover
            raise RuntimeError(f"{slice_} {lang} {index}: every draw names an evaluation person")
        meta = {"source": "synthetic", "generator": "training/ner/v42_data.py", "part": slice_}
        docs.append(b.document(f"{lang}-v42-{slice_}-{split}-{index:05d}", lang, meta))
    return docs


def targeted(out: Path, index: decontam.EvalIndex | None = None) -> dict[str, Any]:
    blob = t33.eval_texts((*t33.EVAL_DIRS, SELECTION))
    index = decontam.eval_corpus() if index is None else index
    report = decontam.Report()
    out.mkdir(parents=True, exist_ok=True)
    stats: dict[str, Any] = {}
    for slice_, lang, n_train, n_dev in TARGETED_PLAN:
        for split, n, seed in (("train", n_train, SEED), ("dev", n_dev, DEV_SEED)):
            path = out / f"{slice_}-{lang}-{split}.jsonl"
            docs = generate(slice_, lang, n, seed, blob, split)
            kept = decontam.gate(docs, index, name=str(path), report=report)
            write_fixtures(path, kept)
            types = Counter(s.entity_type.value for d in kept for s in d.spans)
            names = {nm for d in kept for nm in d.meta["names"]}
            stats[path.name] = {
                "documents": len(kept),
                "gold_spans": dict(sorted(types.items())),
                "distinct_full_names": len(names),
                "names_in_eval_texts": sum(1 for nm in names if nm in blob),
            }
    stats["decontam"] = report.to_dict()
    print(decontam.summary_line(report), file=sys.stderr)
    return stats


# --- the mix -----------------------------------------------------------------------------------


def _source(rel: str) -> str | None:
    for name in DOB_SOURCES:
        if f"/{name}/" in rel:
            return name
    return None


def build(candidate: str) -> tuple[dict[str, list[str]], dict[str, dict[str, int]]]:
    """A1's lists with the DOB mode applied to kiji/nym/E3 and the targeted files added."""
    mode, copies = CANDIDATES[candidate]
    lists, _moved = v41.build("a1", PHASE1_REV)
    stats: dict[str, Counter[str]] = {name: Counter() for name in DOB_SOURCES}
    train: list[str] = []
    done: dict[str, str] = {}
    for rel in lists["train"]:
        source = _source(rel)
        if source is None:
            train.append(rel)
            continue
        if rel not in done:
            lines, st = treat_dob(v41._lines(Path(rel)), mode)
            dst = OUT / f"dob-{mode}" / source / Path(rel).name
            v41._write(dst, lines)
            stats[source] += st
            done[rel] = dst.as_posix()
        train.append(done[rel])
    for slice_, lang, *_ in TARGETED_PLAN:
        train += [(TARGETED / f"{slice_}-{lang}-train.jsonl").as_posix()] * copies
    dev = [*lists["dev"]]
    dev += [(TARGETED / f"{s}-{lang}-dev.jsonl").as_posix() for s, lang, *_ in TARGETED_PLAN]
    return {"train": train, "dev": dev}, {k: dict(v) for k, v in stats.items()}


HEADER = """\
# NER v4.2 candidate {cand} (LAB-1625): the v4.1-A1 recipe and mix (v2.0 warm start, 1 epoch,
# lr 1e-5, loose ADDRESS out of the loss) with kiji/nym/E3 DATE_OF_BIRTH mode "{mode}" and the
# v4.2 targeted files x{copies}. Written by training/ner/v42_data.py build.
# Candidates and gates: eval/results/2026-10-30-lab-1625-ner-v42/README.md, fixed before any run.
# Fictional / synthetic data only (ADR 0005); no MAPA/TAB text (LAB-1419, LAB-1527 allowlist).
#   PII_GUARD_TRAIN_TIMEOUT_S=2700 modal run training/distill/modal_train.py \\
#     --config training/ner/v42-{cand}.toml --gpu A10G --data {data}
"""


def write_config(candidate: str, lists: dict[str, list[str]], data: str) -> Path:
    mode, copies = CANDIDATES[candidate]
    body = [HEADER.format(cand=candidate, mode=mode, copies=copies, data=data)]
    body.append('base_model = "watt-mind/pii-guard-ner-xlmr-base"   # v2.0, Apache-2.0')
    body.append('base_revision = "95f612a9ad65cc5ade5b9248bd152020541e7097"')
    for key in ("train", "dev"):
        body.append(f"{key} = [")
        body += [f'  "{p}",' for p in lists[key]]
        body.append("]")
    body.append("report_dev = [")
    body += [f'  "{(SELECTION / f"{lang}-selection-v42.jsonl").as_posix()}",'
             for lang in ssd.LANGS]  # fmt: skip
    body.append("]")
    body.append(f'out = "models/ner/pii-guard-ner-xlmr-base-v42-{candidate}"')
    body += [
        'teacher = "none"', "epochs = 1", "batch_size = 16", "lr = 1e-5", "weight_decay = 0.01",
        "warmup = 0.1", "max_length = 512", "stride = 128", "seed = 13", 'device = "cuda"',
        'precision = "bf16"', 'other_types = "ignore"', "save_epochs = false",
    ]  # fmt: skip
    path = Path(f"training/ner/v42-{candidate}.toml")
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("targeted", help="write the v4.2 targeted documents")
    t.add_argument("--out", type=Path, default=TARGETED)
    t.add_argument("--json", type=Path)
    b = sub.add_parser("build", help="write the mixes, the configs and the data report")
    b.add_argument("--json", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "targeted":
        stats = targeted(args.out)
        print(json.dumps(stats, indent=2))
        if args.json:
            args.json.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
        return 0
    revs = {**v41.CORPORA, "phase1": PHASE1_REV}
    data = ",".join(f"{c}@{r}" for c, r in revs.items())
    report: dict[str, Any] = {"ticket": "LAB-1625", "synthetic": True, "corpora": revs,
                              "targeted_plan": TARGETED_PLAN, "candidates": {}}  # fmt: skip
    for cand, (mode, copies) in CANDIDATES.items():
        lists, dob = build(cand)
        files = {
            rel: v41._describe(v41._resolve(rel))
            for rel in dict.fromkeys(lists["train"] + lists["dev"])
        }
        docs = sum(files[p]["documents"] for p in lists["train"])
        report["candidates"][cand] = {
            "dob_mode": mode, "targeted_copies": copies, "dob_treatment": dob,
            "config": write_config(cand, lists, data).as_posix(),
            "train_documents": docs,
            "dev_documents": sum(files[p]["documents"] for p in lists["dev"]),
            "train": lists["train"], "dev": lists["dev"], "files": files,
        }  # fmt: skip
        print(f"v42-data: {cand} (dob {mode}, x{copies}): {docs} train documents, {dob}",
              file=sys.stderr)  # fmt: skip
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
