"""Assemble the NER v4.1 training mixes (LAB-1547) and record what went in.

Fictional / synthetic data only (ADR 0005); no MAPA, TAB or other real text (LAB-1419). v4.1 is
the LAB-1535 candidate A recipe (v2.0 warm start, 1 epoch, lr 1e-5) with three changes, all
fixed in ``eval/results/2026-10-30-lab-1547-ner-v41/README.md`` before any training:

1. **Loose addresses.** v4-A's extra false alarms on agent text were ``ADDRESS``. The OpenPII EU
   rows and the kiji rows label short address fragments (about 20 % of their ``ADDRESS`` spans
   hold no digit, 2.7-3.2 words on average, against 5-6 words and a digit in 95-100 % for nym,
   E3, pii-anon, s11 and the court set). Their ``ADDRESS`` spans are either kept out of the
   loss (mode ``ign``: the span goes to ``meta.loss_ignore``) or taught as ``O`` (mode ``o``:
   the span is dropped). Every other source keeps its addresses.
2. **More data:** the LAB-1539 court-style set and error-mined variants (corpus ``v41``), the
   LAB-1534 phase-1b Muse documents (``phase1b``), the regenerated and Glimmer-labelled
   lv/lt/hr/sl Muse documents (``phase1``), and the v41 Hugging Face sets (kiji, nym, E3,
   pii-anon) per ``training/ner/v41-hf-manifest.json``, not re-hosted.
3. **Targeted synthetic documents** (``targeted``, template-based, no model call): Hungarian
   powers of attorney and authorisations that name the agent in the accusative and other cases
   (the ``hu-poa-0015`` smoke miss of v4-A), and Maltese documents with birth dates in the
   Maltese formats (the ``mt`` value v4-A lost was a birth date). Written for this ticket from
   the generator lists of ``targeted_v33.py`` and ``eu_identities.py``; a document naming a
   person whose full name occurs in any evaluation text is redrawn, and ``decontam.py`` gates
   the files.

::

    uv run --no-sync python training/ner/v4_data.py build --json <scratch>/v4-data.json
    uv run --no-sync python training/ner/v41_data.py targeted
    uv run --no-sync python training/ner/v41_data.py build \\
        --json eval/results/2026-10-30-lab-1547-ner-v41/data.json

``build`` writes ``eval/generated/v41-mix/`` (git-ignored; uploaded with the Modal call through
the LAB-1527 allowlist) and the two configs ``training/ner/v41-a1.toml`` (``ign``) and
``v41-a2.toml`` (``o``). Files named ``data:<corpus>/...`` are read from the Modal volume copy
of the pinned corpus revision (``modal_train.py --data``). The JSON report holds counts, gold
spans per type and SHA-256 per file, never text.
"""

# Seeded synthetic data: the standard PRNG is the point.
# ruff: noqa: S311

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import random
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data_sync
import eu_identities as eu
import targeted_v33 as t33
from targeted_v33 import Builder

from pii_guard.eval.fixtures import Document, write_fixtures
from pii_guard.types import EntityType as E

GEN = Path("eval/generated")
OUT = GEN / "v41-mix"
TARGETED = OUT / "targeted"
SEED = 1547
DEV_SEED = 154700
#: (part, train docs, dev docs, copies in the train list). Fixed in the protocol README.
TARGETED_PLAN: tuple[tuple[str, int, int, int], ...] = (
    ("hu-poa", 1500, 100, 2),
    ("mt-dob", 1000, 80, 1),
)
#: Revisions of the corpora on the private dataset (``data_sync.py``), mounted on Modal.
CORPORA = {
    "phase1": None,  # set by ``build --phase1-rev`` (regenerated in LAB-1547)
    "phase1b": "5b4ddcecbae18ff0f25c5c75439f7d151b7a2b28",
    "v41": "a9f9c6e8d5685bd3f0d5d3a27c6feb0dd9d601be",
}
EU_LANGS = (
    "lv", "lt", "hr", "sl", "fr", "es", "it", "nl", "ro",
    "bg", "cs", "da", "el", "et", "fi", "pl", "pt", "sk", "sv",
)  # fmt: skip
COURT_LANGS = (
    "bg", "cs", "da", "de", "el", "en", "es", "et", "fi", "fr", "ga", "hr",
    "hu", "it", "lt", "lv", "mt", "nl", "pl", "pt", "ro", "sk", "sl", "sv",
)  # fmt: skip
PHASE1 = ("lv", "lt", "hr", "sl")
PHASE1B = ("fr", "es", "it", "nl", "ro", "ga", "mt")
OPENPII_ROWS = 2500  # v4 mix a: the first 2,500 per language
NEGATIVES_ROWS = 1000
MODES = {"a1": "ign", "a2": "o"}
LOOSE_ADDRESS = ("openpii", "kiji")  # the sources whose ADDRESS spans are treated
HF_KEEP = ("nym", "e3", "pii-anon")
REPLAY = (  # v4_data.REPLAY: v2.0's own hu/en/de training files minus s13
    "distill-s11/labelled/hu-distill-train.jsonl",
    "distill-s11/labelled/en-distill-train.jsonl",
    "openpii-train/hu-openpii-train.jsonl",
    "openpii-train/en-openpii-train.jsonl",
    "openpii-train/de-openpii-train.jsonl",
    "negatives/hu-negatives-train.jsonl",
    "negatives/en-negatives-train.jsonl",
    "negatives/de-negatives-train.jsonl",
)


# --- targeted documents ------------------------------------------------------------------------

HU_MONTHS = (
    "január", "február", "március", "április", "május", "június", "július", "augusztus",
    "szeptember", "október", "november", "december",
)  # fmt: skip
HU_TOWNS = (
    ("Budapest", "1"), ("Debrecen", "40"), ("Szeged", "67"), ("Pécs", "76"), ("Győr", "90"),
    ("Miskolc", "35"), ("Kecskemét", "60"), ("Eger", "33"), ("Sopron", "94"), ("Veszprém", "82"),
    ("Szolnok", "50"), ("Tatabánya", "28"), ("Zalaegerszeg", "89"), ("Békéscsaba", "56"),
)  # fmt: skip
HU_STREETS = (
    "Fő utca", "Kossuth Lajos utca", "Rákóczi út", "Ady Endre utca", "Petőfi utca", "Jókai tér",
    "Széchenyi utca", "Bartók Béla út", "Dózsa György út", "Arany János utca", "Bem rakpart",
    "Hunyadi utca", "Kölcsey utca", "Szent István körút", "Táncsics Mihály utca", "Vasút sor",
)  # fmt: skip
HU_PURPOSES = (
    "a gépjárművem átíratásával kapcsolatos ügyintézésben",
    "a földhivatali eljárásban",
    "a bankszámlámmal kapcsolatos ügyekben",
    "a nevemre érkezett ajánlott küldemények átvételében",
    "a NAV előtt folyó ügyemben",
    "a lakásbérleti szerződés aláírásában",
    "a közműszolgáltatóknál",
    "az okmányirodában",
    "a hagyatéki eljárásban",
    "a társasházi közgyűlésen",
    "a munkáltatómmal szemben fennálló bérigényem érvényesítésében",
    "a biztosítási kárügyem intézésében",
)  # fmt: skip
HU_POA_OPENERS = ("MEGHATALMAZÁS\n\n", "Meghatalmazás\n\n", "Tárgy: meghatalmazás\n\n",
                  "Kérés az asszisztensnek: fogalmazd át ezt a meghatalmazást.\n\n",
                  "FELHATALMAZÁS\n\n", "")  # fmt: skip
#: The agent slot {a} takes the accusative unless the frame says otherwise.
HU_POA_GRANTS = (
    "ezennel meghatalmazom {a}, hogy {p} helyettem és nevemben teljes jogkörrel eljárjon.",
    "meghatalmazom {a}, hogy {p} képviseljen.",
    "felhatalmazom {a}, hogy {p} a nevemben nyilatkozatot tegyen.",
    "megbízom {a} azzal, hogy {p} eljárjon.",
    "meghatalmazottamként megnevezem {a}, aki {p} jár el.",
    "kijelölöm {a}, hogy {p} helyettesítsen.",
)  # fmt: skip
HU_POA_AFTER = (
    "A meghatalmazott, {a_nom}, a meghatalmazást elfogadja.",
    "{a_nom} a meghatalmazást aláírásával elfogadja.",
    "A meghatalmazás visszavonásig érvényes.",
    "A meghatalmazás {y}. december 31-ig érvényes.",
    "Kérem a hatóságot, hogy {a} a fenti ügyben meghatalmazottként kezelje.",
    "Tájékoztatom önöket, hogy {a} illeti meg az iratbetekintés joga is.",
)  # fmt: skip
HU_POA_CLOSERS = (
    "\n\nKelt: {town}, {y}. {mon} {d}.\n\n......................\nmeghatalmazó",
    "\n\nKelt: {town}, {y}. {mon} {d}.",
    "\n\nElőttünk, mint tanúk előtt:\n1. {w1}\n2. {w2}",
    "\n\nTanú: {w1}, {w1addr}",
    "",
)  # fmt: skip
#: Short agent-text lines that name a person in the accusative (instructions to an assistant).
HU_CHAT_ACC = (
    "Kérlek, emlékeztesd {a} a holnapi határidőre.",
    "Írj egy e-mailt, amiben megkérjük {a}, hogy küldje el a meghatalmazást.",
    "Hívd fel {a}, és kérdezd meg, mikor ér rá aláírni.",
    "Tegyük be {a} is a levél másolatába.",
    "Kérdezd meg {a}, hogy átvette-e a csomagot.",
)  # fmt: skip


def _hu_date(rng: random.Random, start: int = 1945, end: int = 2004) -> tuple[str, int]:
    y, m, d = rng.randint(start, end), rng.randint(1, 12), rng.randint(1, 28)
    fmt = rng.choice((f"{y}. {HU_MONTHS[m - 1]} {d}.", f"{y}.{m:02d}.{d:02d}.",
                      f"{y}. {m:02d}. {d:02d}."))  # fmt: skip
    return fmt, y


def _hu_address(rng: random.Random) -> str:
    town, prefix = rng.choice(HU_TOWNS)
    post = prefix + "".join(rng.choice("0123456789") for _ in range(4 - len(prefix)))
    street = rng.choice(HU_STREETS)
    num = f"{rng.randint(1, 140)}." + (f" {rng.randint(1, 9)}. em. {rng.randint(1, 12)}."
                                       if rng.random() < 0.3 else "")  # fmt: skip
    return f"{post} {town}, {street} {num}"


def _cap(text: str) -> str:
    return text[0].upper() + text[1:]


def hu_poa_doc(rng: random.Random) -> Builder:
    """A power of attorney: principal in the nominative, the agent in the accusative."""
    b = Builder()
    if rng.random() < 0.85:
        principal, agent = t33.hu_person(rng)[0], t33.hu_person(rng)[0]
        while agent == principal:
            agent = t33.hu_person(rng)[0]
        dob, _ = _hu_date(rng)
        b.add(rng.choice(HU_POA_OPENERS))
        b.add("Alulírott ").gold(principal, E.PERSON, principal).add(" (születési idő: ")
        b.gold(dob, E.DATE_OF_BIRTH).add(", lakcím: ").gold(_hu_address(rng), E.ADDRESS).add(") ")
        grant = rng.choice(HU_POA_GRANTS)
        b.fill(grant, {"a": (t33.hu_inflect(agent, "acc"), E.PERSON, agent),
                       "p": (rng.choice(HU_PURPOSES), None, None)})  # fmt: skip
        if rng.random() < 0.5:
            adob, _ = _hu_date(rng)
            b.add(" A meghatalmazott születési ideje: ").gold(adob, E.DATE_OF_BIRTH)
            b.add("" if adob.endswith(".") else ".")
        for _ in range(rng.randint(0, 2)):
            after = rng.choice(HU_POA_AFTER)
            y = rng.randint(2025, 2028)
            case = "acc" if "{a}" in after else "nom"
            surface = t33.hu_inflect(agent, case)
            if after.startswith("{a"):
                surface = _cap(surface)
            b.add(" ").fill(after.replace("{y}", str(y)),
                            {"a": (surface, E.PERSON, agent),
                             "a_nom": (surface, E.PERSON, agent)})  # fmt: skip
        town = rng.choice(HU_TOWNS)[0]
        closer = rng.choice(HU_POA_CLOSERS)
        w1, w2 = t33.hu_person(rng)[0], t33.hu_person(rng)[0]
        slots = {"town": (town, None, None), "y": (str(rng.randint(2024, 2026)), None, None),
                 "mon": (rng.choice(HU_MONTHS), None, None),
                 "d": (str(rng.randint(1, 28)), None, None),
                 "w1": (w1, E.PERSON, w1), "w2": (w2, E.PERSON, w2),
                 "w1addr": (_hu_address(rng), E.ADDRESS, None)}  # fmt: skip
        b.fill(closer, slots)
        return b
    # one in seven: agent text with accusative names, no legal frame
    for _ in range(rng.randint(1, 3)):
        person = t33.hu_person(rng)[0]
        line = rng.choice(HU_CHAT_ACC)
        b.fill(line, {"a": (t33.hu_inflect(person, "acc"), E.PERSON, person)}).add("\n")
    return b


MT = eu.LANGS["mt"]
MT_DOB_FRAMES_M = (
    "{n}, imwieled fil-{dob}, residenti f'{addr}",
    "{n} (imwieled fl-{dob})",
    "{n}, li twieled nhar il-{dob},",
    "is-Sur {n}, imwieled fil-{dob} u residenti f'{addr},",
)  # fmt: skip
MT_DOB_FRAMES_F = (
    "{n}, imwielda fil-{dob}, residenti f'{addr}",
    "{n} (imwielda fl-{dob})",
    "{n}, li twieldet nhar il-{dob},",
    "is-Sinjura {n}, imwielda fil-{dob} u residenti f'{addr},",
)  # fmt: skip
MT_FORM_LINES = (
    "Isem u kunjom: {n}\nData tat-twelid: {dob}\nIndirizz: {addr}\n"
    "Numru tal-karta tal-identità: {id}\n",
    "Isem: {n}\nData tat-Twelid: {dob}\nTelefon: {phone}\n",
    "Applikant: {n} | DOB: {dob} | ID: {id}\n",
    "Dettalji tal-klijent\nIsem sħiħ: {n}\nData tat-twelid: {dob}\nNru tal-ID: {id}\n",
)  # fmt: skip
MT_TAILS = (
    " qed jitlob it-tiġdid tal-permess.",
    " iddikjara li l-informazzjoni mogħtija hija korretta.",
    " applika għas-servizz fit-12 ta' Settembru.",
    " ser tattendi għal-laqgħa li hija skedata għall-{date}.",
    " ħallas il-kont sal-{date}.",
)  # fmt: skip
MT_OPENERS = ("", "Għażiż Sinjur,\n\n", "Suġġett: applikazzjoni\n\n",
              "Nota għall-assistent: iġbor id-dettalji ta' din il-persuna.\n\n",
              "Rapport tal-uffiċċju\n")  # fmt: skip


def mt_dob_doc(rng: random.Random) -> Builder:
    """Maltese text with birth dates (and, as ``O``, other dates)."""
    ids = eu.Identities(MT, rng)
    b = Builder().add(rng.choice(MT_OPENERS))
    for _ in range(rng.randint(1, 3)):
        gender = rng.choice("fm")
        given, family = ids._name(gender)
        name = f"{given} {family}"
        dob = ids.date(ids.birth())
        slots = {"n": (name, E.PERSON, name), "dob": (dob, E.DATE_OF_BIRTH, None),
                 "addr": (ids.address(), E.ADDRESS, None),
                 "id": (eu.mt_id_card(rng), E.ID_DOCUMENT, None),
                 "phone": (ids.phone(), E.PHONE, None)}  # fmt: skip
        if rng.random() < 0.4:
            b.fill(rng.choice(MT_FORM_LINES), slots)
        else:
            frames = MT_DOB_FRAMES_F if gender == "f" else MT_DOB_FRAMES_M
            frame = rng.choice(frames)
            b.fill(frame, slots)
            tail = rng.choice(MT_TAILS)
            later = dt.date(2026, rng.randint(1, 12), rng.randint(1, 28))
            b.add(tail.replace("{date}", ids.date(later))).add("\n")
    return b


BUILDERS = {"hu-poa": ("hu", hu_poa_doc), "mt-dob": ("mt", mt_dob_doc)}


def generate(part: str, n: int, seed: int, blob: str, split: str) -> list[Document]:
    language, builder = BUILDERS[part]
    rng = random.Random(f"{seed}-{part}")
    docs: list[Document] = []
    for index in range(n):
        for _attempt in range(200):
            b = builder(rng)
            if not any(name in blob for name in b.names):
                break
        else:  # pragma: no cover
            raise RuntimeError(f"{part} {index}: every draw names an evaluation person")
        meta = {"source": "synthetic", "generator": "training/ner/v41_data.py", "part": part}
        docs.append(b.document(f"{language}-v41-{part}-{split}-{index:05d}", language, meta))
    return docs


def targeted(out: Path) -> dict[str, Any]:
    blob = t33.eval_texts((*t33.EVAL_DIRS,))
    out.mkdir(parents=True, exist_ok=True)
    stats: dict[str, Any] = {}
    for part, n_train, n_dev, _copies in TARGETED_PLAN:
        for split, n, seed in (("train", n_train, SEED), ("dev", n_dev, DEV_SEED)):
            docs = generate(part, n, seed, blob, split)
            path = out / f"{part}-{split}.jsonl"
            write_fixtures(path, docs)
            types = Counter(s.entity_type.value for d in docs for s in d.spans)
            names = {nm for d in docs for nm in d.meta["names"]}
            stats[path.name] = {
                "documents": len(docs),
                "gold_spans": dict(sorted(types.items())),
                "distinct_full_names": len(names),
                "names_in_eval_texts": sum(1 for nm in names if nm in blob),
            }
    return stats


# --- the mix -----------------------------------------------------------------------------------


def _lines(path: Path) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _address_mode(lines: Sequence[str], mode: str) -> tuple[list[str], int]:
    """Drop ``ADDRESS`` spans; with ``ign`` their regions go to ``meta.loss_ignore``."""
    out, moved = [], 0
    for ln in lines:
        doc = json.loads(ln)
        keep: list[dict[str, Any]] = []
        gone: list[dict[str, Any]] = []
        for s in doc.get("spans", ()):
            (gone if s.get("entity_type") == "ADDRESS" else keep).append(s)
        if gone:
            moved += len(gone)
            doc["spans"] = keep
            if mode == "ign":
                meta = doc.setdefault("meta", {})
                meta["loss_ignore"] = [*meta.get("loss_ignore", ()),
                                       *([s["start"], s["end"]] for s in gone)]  # fmt: skip
        out.append(json.dumps(doc, ensure_ascii=False))
    return out, moved


def _write(path: Path, lines: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _hf_dir() -> Path:
    return data_sync.data_root() / "v41" / "hf-mapped"


def build(candidate: str, phase1_rev: str) -> tuple[dict[str, list[str]], dict[str, int]]:
    mode = MODES[candidate]
    base = OUT / mode
    moved: Counter[str] = Counter()
    train: list[str] = []
    for lang in EU_LANGS:
        src = GEN / f"openpii-eu/{lang}-openpii-train.jsonl"
        lines, n = _address_mode(_lines(src)[:OPENPII_ROWS], mode)
        dst = base / f"openpii/{lang}-openpii-train-{OPENPII_ROWS}.jsonl"
        _write(dst, lines)
        moved["openpii"] += n
        train.append(dst.as_posix())
    for lang in (*EU_LANGS, "ga", "mt"):  # ga and mt now have positives (phase1b, court)
        src = GEN / f"negatives-eu/{lang}-negatives-train.jsonl"
        dst = OUT / f"negatives/{lang}-negatives-train-{NEGATIVES_ROWS}.jsonl"
        _write(dst, _lines(src)[:NEGATIVES_ROWS])
        train.append(dst.as_posix())
    for src in sorted((_hf_dir() / "kiji").glob("*-kiji-train.jsonl")):
        lines, n = _address_mode(_lines(src), mode)
        dst = base / f"kiji/{src.name}"
        _write(dst, lines)
        moved["kiji"] += n
        train.append(dst.as_posix())
    for name in HF_KEEP:
        for src in sorted((_hf_dir() / name).glob("*-train.jsonl")):
            dst = OUT / f"hf/{name}/{src.name}"
            _write(dst, _lines(src))
            train.append(dst.as_posix())
    for lang in PHASE1:  # twice, as in v4 (about 1,080 documents a language)
        rel = f"data:phase1/distill-eu-s1525/labelled/{lang}-distill-train.jsonl"
        train += [rel, rel]
    train += [f"data:phase1b/distill-eu-1b-s1525/labelled/{lang}-distill-train.jsonl"
              for lang in PHASE1B]  # fmt: skip
    train += [f"data:v41/court/labelled/{lang}-distill-train.jsonl" for lang in COURT_LANGS]
    train += [f"data:v41/variants/labelled/{lang}-distill-train.jsonl" for lang in COURT_LANGS]
    for part, _n, _d, copies in TARGETED_PLAN:
        train += [(TARGETED / f"{part}-train.jsonl").as_posix()] * copies
    train.append((GEN / "court-en/en-court-train.jsonl").as_posix())
    train += [(GEN / rel).as_posix() for rel in REPLAY]
    dev = [
        (GEN / rel).as_posix()
        for rel in (
            "distill-s11/labelled/hu-distill-dev.jsonl",
            "distill-s11/labelled/en-distill-dev.jsonl",
            "openpii-train/hu-openpii-dev.jsonl",
            "openpii-train/en-openpii-dev.jsonl",
            "openpii-train/de-openpii-dev.jsonl",
        )
    ]
    dev += [(GEN / f"openpii-eu/{lang}-openpii-dev.jsonl").as_posix() for lang in EU_LANGS]
    dev += [f"data:phase1/distill-eu-s1525/labelled/{lang}-distill-dev.jsonl" for lang in PHASE1]
    dev += [(GEN / "court-en/en-court-dev.jsonl").as_posix()]
    dev += [(TARGETED / f"{part}-dev.jsonl").as_posix() for part, *_ in TARGETED_PLAN]
    return {"train": train, "dev": dev}, dict(moved)


def _resolve(rel: str) -> Path:
    return data_sync.resolve(rel) if rel.startswith("data:") else Path(rel)


def _describe(path: Path) -> dict[str, Any]:
    lines = _lines(path)
    spans: Counter[str] = Counter()
    ignored = 0
    for ln in lines:
        doc = json.loads(ln)
        for s in doc.get("spans", ()):
            spans[s.get("entity_type") or "?"] += 1
        ignored += len(doc.get("meta", {}).get("loss_ignore", ()))
    return {
        "documents": len(lines),
        "gold_spans": dict(sorted(spans.items())),
        "loss_ignore_regions": ignored,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


HEADER = """\
# NER v4.1 candidate {cand} (LAB-1547): v2.0 warm start, 1 epoch, lr 1e-5 (the v4-A recipe), with
# the OpenPII EU and kiji ADDRESS spans {what}. Written by training/ner/v41_data.py build.
# Candidates and gates: eval/results/2026-10-30-lab-1547-ner-v41/README.md, fixed before any run.
# Fictional / synthetic data only (ADR 0005); no MAPA/TAB text (LAB-1419, LAB-1527 allowlist).
#   modal run training/distill/modal_train.py --config training/ner/v41-{cand}.toml --gpu A10G \\
#     --data {data}
"""


def write_config(candidate: str, lists: dict[str, list[str]], data: str) -> Path:
    what = {"a1": "kept out of the loss", "a2": "taught as O"}[candidate]
    body = [HEADER.format(cand=candidate, what=what, data=data)]
    body.append('base_model = "watt-mind/pii-guard-ner-xlmr-base"   # v2.0, Apache-2.0')
    body.append('base_revision = "95f612a9ad65cc5ade5b9248bd152020541e7097"')
    for key in ("train", "dev"):
        body.append(f"{key} = [")
        body += [f'  "{p}",' for p in lists[key]]
        body.append("]")
    body.append(f'out = "models/ner/pii-guard-ner-xlmr-base-v41-{candidate}"')
    body += [
        'teacher = "none"', "epochs = 1", "batch_size = 16", "lr = 1e-5", "weight_decay = 0.01",
        "warmup = 0.1", "max_length = 512", "stride = 128", "seed = 13", 'device = "cuda"',
        'precision = "bf16"', 'other_types = "ignore"', "save_epochs = false",
    ]  # fmt: skip
    path = Path(f"training/ner/v41-{candidate}.toml")
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("targeted", help="write the targeted hu-poa and mt-dob documents")
    t.add_argument("--out", type=Path, default=TARGETED)
    t.add_argument("--json", type=Path)
    b = sub.add_parser("build", help="write both mixes, the configs and the data report")
    b.add_argument("--json", type=Path, required=True)
    b.add_argument("--phase1-rev", required=True, help="revision of the regenerated phase1 corpus")
    args = parser.parse_args(argv)
    if args.command == "targeted":
        stats = targeted(args.out)
        print(json.dumps(stats, indent=2))
        if args.json:
            args.json.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
        return 0
    revs = {**CORPORA, "phase1": args.phase1_rev}
    data = ",".join(f"{c}@{r}" for c, r in revs.items())
    report: dict[str, Any] = {"ticket": "LAB-1547", "synthetic": True, "corpora": revs,
                              "targeted_plan": TARGETED_PLAN, "candidates": {}}  # fmt: skip
    for cand in MODES:
        lists, moved = build(cand, args.phase1_rev)
        files = {
            rel: _describe(_resolve(rel)) for rel in dict.fromkeys(lists["train"] + lists["dev"])
        }
        docs = sum(files[p]["documents"] for p in lists["train"])
        report["candidates"][cand] = {
            "address_mode": MODES[cand], "address_spans_treated": moved,
            "config": write_config(cand, lists, data).as_posix(),
            "train_documents": docs,
            "dev_documents": sum(files[p]["documents"] for p in lists["dev"]),
            "train": lists["train"], "dev": lists["dev"], "files": files,
        }  # fmt: skip
        print(f"v41-data: {cand} ({MODES[cand]}): {docs} train documents, ADDRESS {moved}",
              file=sys.stderr)  # fmt: skip
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
