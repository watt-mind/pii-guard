"""The NER v3 training mix (LAB-1393): every source pinned, licensed, converted and sampled.

Fictional / synthetic data only (ADR 0005). Each public source is a pinned file at a pinned
revision with its licence; nothing here is gated, CC-BY-SA or non-commercial. Rows are never
committed: ``training/ner/v3-data-manifest.json`` records, per source, the revision, file
hash, licence, attribution, seed, counts and a SHA-256 over the chosen ids, so the files are
rebuilt from the pinned downloads::

    uv run --no-sync --with pyarrow python training/ner/v3_data.py --cache data/public/v3
    # or on Modal (downloads there, not on this machine): training/ner/modal_v3.py

Sources (the ticket's mix; the shares actually reached are in the manifest):

========================  =========================================  ==============
name                      what                                       licence
========================  =========================================  ==============
``openpii``               Ai4Privacy OpenPII-1M **train**, 9 languages  CC-BY-4.0
``privy``                 Privy protocol traces (JSON, SQL, HTML, XML)  MIT
``wismut``                nym-pii-multilingual (logs, forms, chat)      MIT
``nemotron``              NVIDIA Nemotron-PII **train**                 CC-BY-4.0
``gretel``                gretel-pii-masking-en-v1 **train**            Apache-2.0
``agent``                 pii-guard agent-traffic generator, seed 1393  Apache-2.0
``s11``                   pii-guard distillation corpus s11 (LAB-1128)  Apache-2.0
``negatives``             v2 hard negatives (seed 1150, LAB-1150)       Apache-2.0
========================  =========================================  ==============

Conversion goes through the evaluation's :func:`pii_guard.eval.datasets._common.convert`, so
the same merge rules apply (a given name next to a surname is one ``PERSON``, a city or a
postcode is ``ADDRESS`` only inside an address). Every label pii-guard has no NER type for is
an ignore region and goes into ``meta.loss_ignore``: neither taught as an entity nor as
``O``. That includes SECRET, URL and IP (they stay with the rules), dates that aren't birth
dates, and the GDPR special categories (health, religion, ethnicity, …), which are out of
scope. Rows holding a provider-format credential are skipped (secret scanners flag even a
generated one).

``wismut`` has no language column: :func:`guess_language` keeps the Latin-script rows in the
languages pii-guard targets (en, de, pl, cs, ro) and drops the rest.

The decontamination gate (``decontam.py``, LAB-1392) runs over every file afterwards, and
``train.py`` runs it again when it loads them.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pii_guard.eval.datasets import nemotron
from pii_guard.eval.datasets._common import (
    Converted,
    LabelMap,
    Row,
    convert,
    download,
    read_parquet,
    sample,
)
from pii_guard.eval.fixtures import Document, write_fixtures
from pii_guard.types import EntityType

sys.path.insert(0, str(Path(__file__).resolve().parent))
import negatives as negatives_mod
import openpii as openpii_mod

SEED = 1393
OUT = Path("eval/generated/v3")
MANIFEST = Path("training/ner/v3-data-manifest.json")
OPENPII_MANIFEST = Path("training/ner/v3-openpii-train-manifest.json")

#: Documents per source and language. Chosen so the token shares land near the ticket's mix
#: without the FineWeb-2 slice (see the manifest for what they came to).
OPENPII_TRAIN = {"hu": 5000, "en": 5000, "de": 5000, "pl": 2500, "cs": 2500, "sk": 2500,
                 "ro": 2500, "hr": 2500, "sl": 2500}  # fmt: skip
OPENPII_DEV = dict.fromkeys(OPENPII_TRAIN, 100)
PRIVY_N = {"en": 12000}
WISMUT_N = {"en": 3000, "de": 3000, "pl": 2500, "cs": 2500, "ro": 2000}
NEMOTRON_N = {"en": 1500}
GRETEL_N = {"en": 2500}
AGENT_N = {"hu": 600, "en": 600, "de": 600}
NEGATIVES_N = 2000
NEGATIVES_SEED = 1150


@dataclass(frozen=True)
class Source:
    name: str
    repo: str
    revision: str
    file: str
    sha256: str
    license: str
    attribution: str

    @property
    def url(self) -> str:
        return f"https://huggingface.co/datasets/{self.repo}/resolve/{self.revision}/{self.file}"


PRIVY = Source(
    "privy",
    "piimb/privy",
    "15bd4f475ece9e3f90ca513d72dd83d097ab2a18",
    "privy-dataset/train-small.json",
    "33fcc6a1fb7dcf077999177a4e8e9a382b1aa39c4fb1a945e8f034bd0c7d64cb",
    "MIT",
    "Privy (Pixie / New Relic), published as piimb/privy",
)
WISMUT = Source(
    "wismut",
    "Wismut/nym-pii-multilingual-data",
    "abe23bf08c305f5824b1643dc4f079f06ccb2ad1",
    "train.jsonl",
    "ca04c6c56b9cfa3e702b5c8c541ada60c9e3c0fb4ad6866d8940550753636afb",
    "MIT",
    "byteowlz / Wismut, nym-pii-multilingual-data",
)
NEMOTRON = Source(
    "nemotron",
    nemotron.REPO,
    nemotron.REVISION,
    "data/train-00000-of-00001.parquet",
    "9cb1a88c339ab84ddbc35ccdde4f6bb713300f5585881f9e02b8db1e0dfdbece",
    "CC-BY-4.0",
    "NVIDIA Corporation, nvidia/Nemotron-PII",
)
GRETEL = Source(
    "gretel",
    "gretelai/gretel-pii-masking-en-v1",
    "e06eb1499ca8d54470f085021cd8e54f9efac7fd",
    "data/train-00000-of-00001.parquet",
    "93169003eaa23d0499dbbe26794514216af22bc1bbee71b7b1e1f23edca5ce79",
    "Apache-2.0",
    "Gretel.ai, gretelai/gretel-pii-masking-en-v1",
)
OPENPII = Source(
    "openpii",
    openpii_mod.DATASET,
    openpii_mod.REVISION,
    openpii_mod.FILE,
    openpii_mod.FILE_SHA256,
    openpii_mod.LICENSE,
    openpii_mod.ATTRIBUTION,
)
DOWNLOADS = (OPENPII, PRIVY, WISMUT, NEMOTRON, GRETEL)

_E = EntityType

PRIVY_LABELS = LabelMap(
    types={
        "PERSON": _E.PERSON,
        "PER": _E.PERSON,
        "ORGANIZATION": _E.ORGANIZATION,
        "ORG": _E.ORGANIZATION,
        "EMAIL_ADDRESS": _E.EMAIL,
        "PHONE_NUMBER": _E.PHONE,
        "CREDIT_CARD": _E.BANK_ACCOUNT,
        "IBAN_CODE": _E.BANK_ACCOUNT,
        "US_BANK_NUMBER": _E.BANK_ACCOUNT,
        "US_SSN": _E.ID_DOCUMENT,
        "US_PASSPORT": _E.ID_DOCUMENT,
        "US_DRIVER_LICENSE": _E.ID_DOCUMENT,
        "US_ITIN": _E.ID_DOCUMENT,
        "LICENSE_PLATE": _E.VEHICLE_PLATE,
        "US_LICENSE_PLATE": _E.VEHICLE_PLATE,
        # No NER type, or the rules' job (URL, IP, passwords): ignore regions.
        **dict.fromkeys(
            (
                "O",
                "LOCATION",
                "LOC",
                "FINANCIAL",
                "NRP",
                "DATE_TIME",
                "URL",
                "IP_ADDRESS",
                "TITLE",
                "COORDINATE",
                "IMEI",
                "PASSWORD",
                "CURRENCY",
                "ROUTING_NUMBER",
                "SWIFT_CODE",
                "MAC_ADDRESS",
                "AGE",
            )
        ),
    },
    notes={
        "O": "Privy marks some generated values (e-mails, URLs) 'O': unknown, so ignored",
        "LOCATION": "an address, a city or a country: too mixed to teach, ignored",
    },
)

WISMUT_LABELS = LabelMap(
    types={
        "GIVEN_NAME": _E.PERSON,
        "SURNAME": _E.PERSON,
        "EMAIL": _E.EMAIL,
        "PHONE": _E.PHONE,
        "FAX_NUMBER": _E.PHONE,
        "STREET_ADDRESS": _E.ADDRESS,
        "STREET_NAME": _E.ADDRESS,
        "BUILDING_NUMBER": _E.ADDRESS,
        "SECONDARY_ADDRESS": _E.ADDRESS,
        "CITY": _E.ADDRESS,
        "ZIP_CODE": _E.ADDRESS,
        "STATE": _E.ADDRESS,
        "DATE_OF_BIRTH": _E.DATE_OF_BIRTH,
        "COMPANY_NAME": _E.ORGANIZATION,
        "GOVERNMENT_ID": _E.ID_DOCUMENT,
        "PASSPORT": _E.ID_DOCUMENT,
        "TAX_ID": _E.ID_DOCUMENT,
        "SSN": _E.ID_DOCUMENT,
        "DRIVERS_LICENSE": _E.ID_DOCUMENT,
        "IBAN": _E.BANK_ACCOUNT,
        "ACCOUNT_NUMBER": _E.BANK_ACCOUNT,
        "CREDIT_DEBIT_CARD": _E.BANK_ACCOUNT,
        "LICENSE_PLATE": _E.VEHICLE_PLATE,
        **dict.fromkeys(
            (
                "DATE",
                "TIME",
                "COUNTRY",
                "CUSTOMER_ID",
                "EMPLOYEE_ID",
                "USERNAME",
                "MEDICAL_RECORD_NUMBER",
                "GENDER",
                "AGE",
                "PASSWORD",
                "API_KEY",
                "PIN",
                "CVV",
                "SWIFT_BIC",
                "ROUTING_NUMBER",
                "MAC_ADDRESS",
                "URL",
            )
        ),
    },
    part_only=frozenset(
        {"STREET_NAME", "BUILDING_NUMBER", "SECONDARY_ADDRESS", "CITY", "ZIP_CODE", "STATE"}
    ),
    notes={"STREET_NAME": "a street name on its own is not an address (v2.1 negatives)"},
)

GRETEL_LABELS = LabelMap(
    types={
        "name": _E.PERSON,
        "first_name": _E.PERSON,
        "last_name": _E.PERSON,
        "email": _E.EMAIL,
        "phone_number": _E.PHONE,
        "street_address": _E.ADDRESS,
        "address": _E.ADDRESS,
        "city": _E.ADDRESS,
        "postcode": _E.ADDRESS,
        "state": _E.ADDRESS,
        "date_of_birth": _E.DATE_OF_BIRTH,
        "company_name": _E.ORGANIZATION,
        "ssn": _E.ID_DOCUMENT,
        "national_id": _E.ID_DOCUMENT,
        "tax_id": _E.ID_DOCUMENT,
        "credit_card_number": _E.BANK_ACCOUNT,
        "account_number": _E.BANK_ACCOUNT,
        "license_plate": _E.VEHICLE_PLATE,
        **dict.fromkeys(
            (
                "medical_record_number",
                "date",
                "date_time",
                "time",
                "customer_id",
                "employee_id",
                "ipv4",
                "ipv6",
                "user_name",
                "device_identifier",
                "bank_routing_number",
                "unique_identifier",
                "biometric_identifier",
                "certificate_license_number",
                "vehicle_identifier",
                "coordinate",
                "country",
                "api_key",
                "password",
                "health_plan_beneficiary_number",
                "url",
                "swift_bic",
                "cvv",
                "pin",
            )
        ),
    },
    part_only=frozenset({"city", "postcode", "state"}),
)

# --- language guess (wismut) -------------------------------------------------------------

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_STOP = {
    "en": {"the", "and", "of", "to", "is", "for", "your", "with", "please", "on", "at", "this"},
    "de": {"der", "die", "und", "das", "ist", "nicht", "mit", "bitte", "für", "von", "ihre", "den"},
    "pl": {"i", "w", "na", "się", "nie", "jest", "do", "że", "z", "dla", "proszę", "oraz"},
    "cs": {"a", "v", "na", "se", "je", "že", "pro", "jsou", "prosím", "nebo", "ve", "být"},
    "ro": {"și", "de", "la", "în", "pentru", "este", "cu", "vă", "rugăm", "nu", "din", "sau"},
}
_MARKS = {
    "de": set("äöüß"),
    "pl": set("ąęłńśźż"),
    "cs": set("ěřůťďň"),
    "ro": set("ăâîșțş"),
}
_FOREIGN = set("ñçãõåøæéèêëàùûœ")  # es/pt/fr/sv/da/no/... marks; not in the five targets


def guess_language(text: str) -> str | None:
    """en, de, pl, cs or ro for a Latin-script text, else ``None``. A heuristic, not langid."""
    letters = [c for c in text if c.isalpha()]
    if not letters or sum(c.isascii() or c.lower() in "äöüßąęłńśźżěřůťďňăâîșțşáéíóúýčšž"
                          for c in letters) < 0.97 * len(letters):  # fmt: skip
        return None
    lower = text.lower()
    if any(c in _FOREIGN for c in lower if c not in "é"):
        return None
    words = _WORD.findall(lower)
    scores = {lang: sum(w in stop for w in words) for lang, stop in _STOP.items()}
    for lang, marks in _MARKS.items():
        scores[lang] += 3 * sum(c in marks for c in lower)
    best = max(scores, key=lambda k: scores[k])
    ranked = sorted(scores.values(), reverse=True)
    if ranked[0] < 2 or ranked[0] == ranked[1]:
        return None
    return best


# --- readers -----------------------------------------------------------------------------


def _find_all(text: str, value: str) -> Iterator[int]:
    start = text.find(value)
    while start >= 0:
        yield start
        start = text.find(value, start + len(value))


def _privy_text(raw: str) -> str:
    """Privy stores ``full_text`` as a Python bytes literal (``b'...'``)."""
    if raw.startswith(("b'", 'b"')) and raw.endswith(raw[1]):
        try:
            return ast.literal_eval(raw).decode("utf-8")
        except (ValueError, SyntaxError, UnicodeDecodeError):
            return raw
    return raw


def privy_rows(path: Path) -> Iterator[Row]:
    """Privy rows. Spans are re-found by value (the stored offsets don't match the text)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    for i, raw in enumerate(data):
        text = _privy_text(str(raw["full_text"]))
        spans: list[tuple[int, int, str]] = []
        for s in raw.get("spans") or ():
            value = str(s.get("entity_value") or "")
            if len(value.strip()) < 3:
                continue
            spans.extend(
                (at, at + len(value), str(s["entity_type"])) for at in _find_all(text, value)
            )
        yield Row(f"privy-{i}", "en", text, tuple(sorted(set(spans))))


def wismut_rows(path: Path, counts: Counter[str] | None = None) -> Iterator[Row]:
    with path.open(encoding="utf-8") as handle:
        for i, line in enumerate(handle):
            if not line.strip():
                continue
            raw = json.loads(line)
            text = str(raw["text"])
            language = guess_language(text)
            if counts is not None:
                counts[f"language_{language or 'other'}"] += 1
            if language is None:
                continue
            spans = tuple(
                (int(e["start"]), int(e["end"]), str(e["label"])) for e in raw["entities"]
            )
            yield Row(f"wismut-{i}", language, text, spans)


def gretel_rows(path: Path) -> Iterator[Row]:
    for raw in read_parquet(path, ["uid", "text", "entities"]):
        text = str(raw["text"])
        entities = raw["entities"]
        if isinstance(entities, str):
            entities = ast.literal_eval(entities)
        spans: set[tuple[int, int, str]] = set()
        for e in entities:
            value = str(e.get("entity") or "")
            if len(value.strip()) < 3 or not e.get("types"):
                continue
            label = str(e["types"][0])
            spans.update((at, at + len(value), label) for at in _find_all(text, value))
        yield Row(str(raw["uid"]), "en", text, tuple(sorted(spans)))


# --- conversion --------------------------------------------------------------------------


def training_document(doc: Document, kind: str) -> Document:
    """``doc`` with its ignore regions (``meta.ignore``) also in ``meta.loss_ignore``."""
    meta = dict(doc.meta)
    regions = {(int(r["start"]), int(r["end"])) for r in meta.get("ignore") or ()}
    regions |= {(int(s), int(e)) for s, e in meta.get("loss_ignore") or ()}
    meta["loss_ignore"] = [list(r) for r in sorted(regions)]
    meta["kind"] = kind
    meta["split"] = "train"
    return Document(doc.id, doc.language, doc.text, doc.spans, meta)


def _sampled(
    rows: Iterator[Row],
    want: Mapping[str, int],
    labels: LabelMap,
    name: str,
    seed: int = SEED,
) -> tuple[dict[str, list[Document]], Counter[str]]:
    dropped: Counter[str] = Counter()
    unknown: Counter[str] = Counter()

    def to_document(row: Row) -> Converted:
        out = convert(row, labels, prefix=name, kind=f"v3-{name}", source=name)
        dropped.update(out.dropped)
        unknown.update(out.unknown)
        return out

    chosen, seen = sample(rows, want, seed, to_document)
    counts = Counter(seen)
    counts.update({f"ignored_label_{k}": v for k, v in dropped.items()})
    counts.update({f"unknown_label_{k}": v for k, v in unknown.items()})
    docs = {
        lang: [training_document(c.document, f"v3-{name}") for c in items]
        for lang, items in chosen.items()
    }
    return docs, counts


def agent_traffic_train(n: Mapping[str, int], seed: int = SEED) -> dict[str, list[Document]]:
    """Train-only agent-traffic documents: the LAB-1226 generator with a seed of its own."""
    from pii_guard.eval.datasets import synthetic

    if seed in (synthetic.DEFAULT_SEED, synthetic.DEV_SEED):
        raise ValueError("the train seed must differ from the test and dev seeds")
    out: dict[str, list[Document]] = {}
    for lang, count in n.items():
        docs = []
        for i in range(count):
            d = synthetic.document(lang, i, seed=seed, split="train")
            docs.append(
                training_document(
                    Document(f"{lang}-agent-traffic-train-{i:05d}", lang, d.text, d.spans, d.meta),
                    "v3-agent-traffic",
                )
            )
        out[lang] = docs
    return out


# --- manifest ----------------------------------------------------------------------------


def _ids_sha(docs: Sequence[Document]) -> str:
    return hashlib.sha256("\n".join(sorted(d.id for d in docs)).encode()).hexdigest()


def file_block(path: Path, docs: Sequence[Document], tokenizer: Any = None) -> dict[str, Any]:
    gold = Counter(s.entity_type.value for d in docs for s in d.spans)
    block: dict[str, Any] = {
        "path": str(path),
        "documents": len(docs),
        "pii_free_documents": sum(not d.spans for d in docs),
        "gold_spans": dict(sorted(gold.items())),
        "loss_ignore_regions": sum(len(d.meta.get("loss_ignore") or ()) for d in docs),
        "chars": sum(len(d.text) for d in docs),
        "ids_sha256": _ids_sha(docs),
    }
    if tokenizer is not None:
        block["tokens"] = sum(
            len(ids)
            for ids in tokenizer([d.text for d in docs], add_special_tokens=False)["input_ids"]
        )
    return block


def _write(out: Path, name: str, docs: Mapping[str, list[Document]]) -> list[Path]:
    paths = []
    for lang, items in docs.items():
        path = out / name / f"{lang}-{name}-train.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_fixtures(path, items)
        paths.append(path)
    return paths


def source_entry(src: Source | None, **extra: Any) -> dict[str, Any]:
    if src is None:
        return dict(extra)
    return {
        "dataset": src.repo,
        "url": f"https://huggingface.co/datasets/{src.repo}",
        "revision": src.revision,
        "file": src.file,
        "file_sha256": src.sha256,
        "license": src.license,
        "attribution": src.attribution,
        "gated": False,
        **extra,
    }


def build(
    cache: Path,
    out: Path = OUT,
    *,
    s11: Path | None = Path("eval/generated/distill-s11/labelled"),
    only: Sequence[str] | None = None,
    tokenizer_name: str | None = None,
    fetch: Callable[[str, str, Path], Path] = download,
    openpii_train: Mapping[str, int] | None = None,
    openpii_manifest: Path = OPENPII_MANIFEST,
    ticket: str = "LAB-1393",
) -> dict[str, Any]:
    """Download (if needed), convert and sample every source; return the manifest.

    ``openpii_train`` (default :data:`OPENPII_TRAIN`) and ``openpii_manifest`` let a later mix
    (v3.1, LAB-1410) take more OpenPII rows of a language; the seeded order makes a larger
    sample a superset of a smaller one, and the dev rows stay the same.
    """
    openpii_train = dict(openpii_train or OPENPII_TRAIN)
    tokenizer = None
    if tokenizer_name:
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)
    want = set(only or ("openpii", "privy", "wismut", "nemotron", "gretel", "agent", "s11",
                        "negatives"))  # fmt: skip
    manifest: dict[str, Any] = {"seed": SEED, "ticket": ticket, "rows_committed": False}
    sources: dict[str, Any] = {}

    def local(src: Source) -> Path:
        return fetch(src.url, src.sha256, cache / src.repo.replace("/", "--") / src.file)

    if "openpii" in want:
        path = local(OPENPII)
        train = ",".join(f"{k}={v}" for k, v in openpii_train.items())
        dev = ",".join(f"{k}={OPENPII_DEV[k]}" for k in openpii_train)
        rc = openpii_mod.main(
            ["--source", str(path), "--train", train, "--dev", dev, "--seed", str(SEED),
             "--out", str(out / "openpii"), "--manifest", str(openpii_manifest)]
        )  # fmt: skip
        if rc:
            raise RuntimeError("openpii.py failed")
        files = {}
        from pii_guard.eval.fixtures import load_fixtures

        for lang in openpii_train:
            for split in ("train", "dev"):
                p = out / "openpii" / f"{lang}-openpii-{split}.jsonl"
                files[f"{lang}-{split}"] = file_block(p, load_fixtures([p]), tokenizer)
        sources["openpii"] = source_entry(
            OPENPII,
            sample_manifest=str(openpii_manifest),
            requested=dict(openpii_train),
            languages=sorted(openpii_train),
            note="train split only; eval sample uids and texts excluded (openpii.py)",
            files=files,
        )

    readers: dict[str, tuple[Source, Callable[[Path], Iterator[Row]], LabelMap, dict]] = {
        "privy": (PRIVY, privy_rows, PRIVY_LABELS, PRIVY_N),
        "nemotron": (NEMOTRON, lambda p: nemotron.rows([p]), nemotron.LABELS, NEMOTRON_N),
        "gretel": (GRETEL, gretel_rows, GRETEL_LABELS, GRETEL_N),
    }
    wismut_counts: Counter[str] = Counter()
    readers["wismut"] = (
        WISMUT,
        lambda p: wismut_rows(p, wismut_counts),
        WISMUT_LABELS,
        WISMUT_N,
    )
    for name, (src, reader, labels, n) in readers.items():
        if name not in want:
            continue
        path = local(src)
        docs, counts = _sampled(reader(path), n, labels, name)
        counts.update(wismut_counts if name == "wismut" else {})
        paths = _write(out, name, docs)
        sources[name] = source_entry(
            src,
            requested=dict(n),
            counts=dict(sorted(counts.items())),
            label_map=labels.table(),
            files={str(p): file_block(p, docs[p.name.split("-")[0]], tokenizer) for p in paths},
        )

    if "agent" in want:
        from pii_guard.eval.datasets import synthetic

        docs = agent_traffic_train(AGENT_N)
        paths = _write(out, "agent-traffic", docs)
        sources["agent"] = source_entry(
            None,
            dataset="pii-guard synthetic agent traffic (LAB-1226 generator), train split",
            generator=synthetic.GENERATOR,
            seed=SEED,
            license="Apache-2.0",
            attribution="pii-guard contributors",
            note=(
                "same templates as agent-traffic / agent-traffic-dev, a seed of its own; "
                "the decontamination gate drops near-copies of either"
            ),
            files={str(p): file_block(p, docs[p.name.split("-")[0]], tokenizer) for p in paths},
        )

    if "negatives" in want:
        neg_out = out / "negatives"
        negatives_mod.main(["--n", str(NEGATIVES_N), "--seed", str(NEGATIVES_SEED),
                            "--out", str(neg_out)])  # fmt: skip
        from pii_guard.eval.fixtures import load_fixtures

        files = {}
        for p in sorted(neg_out.glob("*-negatives-train.jsonl")):
            files[str(p)] = file_block(p, load_fixtures([p]), tokenizer)
        sources["negatives"] = source_entry(
            None,
            dataset="pii-guard v2 hard negatives (training/ner/negatives.py, LAB-1150)",
            seed=NEGATIVES_SEED,
            license="Apache-2.0",
            attribution="pii-guard contributors",
            note="the v2 negatives only; not the v2.1 uncued-ID ones (they caused ID/e-mail leaks)",
            files=files,
        )

    if "s11" in want and s11 is not None and s11.is_dir():
        from pii_guard.eval.fixtures import load_fixtures

        files = {}
        for p in sorted(s11.glob("*-distill-*.jsonl")):
            files[str(p)] = file_block(p, load_fixtures([p]), tokenizer)
        sources["s11"] = source_entry(
            None,
            dataset="pii-guard distillation corpus s11 (LAB-1128)",
            license="Apache-2.0",
            attribution="pii-guard contributors",
            note="the LAB-1128 files as generated; s13 is not kept and was not regenerated",
            files=files,
        )

    manifest["sources"] = sources
    if tokenizer is not None:
        manifest["tokenizer"] = tokenizer_name
        totals = {
            name: sum(f.get("tokens", 0) for k, f in src["files"].items() if "dev" not in k)
            for name, src in sources.items()
        }
        all_tokens = sum(totals.values()) or 1
        manifest["train_token_share"] = {
            k: {"tokens": v, "share": round(v / all_tokens, 3)} for k, v in totals.items()
        }
    manifest["excluded"] = {
        "fineweb-2": (
            "real web text: ADR 0005 allows no real personal data in training (LAB-1393 "
            "follow-up asks the owner)"
        ),
        "distill-s13": "not kept after v2 and not reproducible from a seed (LLM output)",
        "negatives-v21": "the uncued-ID negatives caused the v2.1 ID and e-mail leaks",
        "cc-by-sa / nc / gated": "none used (no NerKor, no Universal NER)",
    }
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cache", type=Path, required=True, help="where the downloads go")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--s11", type=Path, default=Path("eval/generated/distill-s11/labelled"))
    parser.add_argument("--only", action="append", help="one source (repeatable)")
    parser.add_argument("--tokenizer", help="count tokens with this tokenizer (hub id)")
    args = parser.parse_args(argv)
    manifest = build(
        args.cache, args.out, s11=args.s11, only=args.only, tokenizer_name=args.tokenizer
    )
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(f"v3_data: manifest -> {args.manifest}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
