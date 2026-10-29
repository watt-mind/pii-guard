"""Permissive synthetic Hugging Face sets as NER v4.1 training sources (LAB-1539).

Four synthetic sets found by the hub scan of 2026-10-29, each pinned to a revision, read
locally and converted with the dataset helpers of ``pii_guard.eval.datasets`` (adjacent name
parts merge into one ``PERSON``, address parts into one ``ADDRESS``; a city or postcode on its
own is excluded from the loss). Only the manifest (source, license, revision, row ids, counts)
is committed; the rows stay in the data directory::

    uv run --no-sync --with pyarrow --with pandas --with langid python training/ner/hf_v41.py \\
        --hf <data>/hf --out <data>/hf-mapped --manifest training/ner/v41-hf-manifest.json

Sources (all synthetic):

- ``DataikuNLP/kiji-pii-training-data`` (Apache-2.0; da de en es fr nl): LLM-written; values
  are located in the text (the source has no offsets).
- ``Wismut/nym-pii-multilingual-data`` (MIT; 13 EU languages): LLM templates filled by Faker,
  exact offsets; no language field, so each row is language-identified (``langid``).
- ``E3-JSI/synthetic-multi-pii-ner-v1`` (MIT; de el en fr it nl sl): LLM-written; free-text
  entity types in seven languages, mapped by keyword (:data:`E3_KEYWORDS`).
- ``subhash-holla/pii-anon`` (CC0-1.0): an ID-format booster only, synthetic rows holding an
  ID, capped at 5 % of the v4.1 mix.

**Excluded rows** (counted in the manifest): health and other GDPR special categories (owner
decision: out of scope), by label (medical record numbers, conditions, medication) and by a
multilingual keyword list (:data:`SPECIAL`); E3's ``healthcare`` domain; pii-anon's clinical
domain, its Art. 9 flagged rows and its non-synthetic ``curated_public`` rows; rows holding a
provider-format credential; rows whose values cannot be located or whose spans overlap.

Dates other than birth dates are left unlabelled (taught as ``O``: v2.0 over-masks ordinary
dates as birth dates, LAB-1539 mining). Usernames, URLs, card security codes and similar labels
without a pii-guard type are excluded from the loss (``meta.loss_ignore``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from pii_guard.eval.datasets._common import ConversionError, LabelMap, Row, convert
from pii_guard.eval.fixtures import Document, write_fixtures
from pii_guard.types import EntityType

_E = EntityType
SEED = 1539
NYM_SCAN = 200_000
EU = frozenset(
    [
        "bg",
        "cs",
        "da",
        "de",
        "el",
        "en",
        "es",
        "et",
        "fi",
        "fr",
        "ga",
        "hu",
        "it",
        "lt",
        "lv",
        "mt",
        "nl",
        "pt",
        "ro",
        "sk",
        "sv",
        "hr",
        "sl",
        "pl",
    ]
)

SOURCES: dict[str, dict[str, str]] = {
    "kiji": {
        "repo": "DataikuNLP/kiji-pii-training-data",
        "revision": "0275550f0b1f1b8f2dc9356fd31ac1c788b8228b",
        "file": "data/train-00000-of-00001.parquet",
        "license": "Apache-2.0",
        "attribution": "Dataiku, DataikuNLP/kiji-pii-training-data",
    },
    "nym": {
        "repo": "Wismut/nym-pii-multilingual-data",
        "revision": "abe23bf08c305f5824b1643dc4f079f06ccb2ad1",
        "file": "train.jsonl",
        "license": "MIT",
        "attribution": "byteowlz / Wismut, Wismut/nym-pii-multilingual-data",
    },
    "e3": {
        "repo": "E3-JSI/synthetic-multi-pii-ner-v1",
        "revision": "2fe1b17ea2d82d80b2570e5c48c416a3b317828f",
        "file": "data/train-00000-of-00001.parquet",
        "license": "MIT",
        "attribution": "E3, Jožef Stefan Institute, E3-JSI/synthetic-multi-pii-ner-v1",
    },
    "pii-anon": {
        "repo": "subhash-holla/pii-anon",
        "revision": "80f9f680e5afd64fe4705214e213e095cf951f95",
        "file": "data/train.parquet",
        "license": "CC0-1.0",
        "attribution": "subhash-holla/pii-anon",
    },
}

#: Rows mentioning health, religion, sexuality, ethnicity, politics or union membership.
SPECIAL = re.compile(
    r"(?i)\b(patient\w*|patiënt\w*|pacjent\w*|pacijent\w*|rtg|röntgen\w*|x-ray|poradni\w*|"
    r"krvn\w* skupin\w*|krevní|zdravstv\w*|sairaal\w*|terveys\w*|hälso\w*|sundhed\w*|"
    r"gesundheit\w*|santé|salud|salute|gezondheid\w*|ιατρ\w*|paciente\w*|pazient\w*|pacient\w*|potila\w*|ασθεν\w*|"
    r"hospital\w*|krankenhaus\w*|klinik\w*|clinic\w*|clínica\w*|clinica\w*|ziekenhuis\w*|"
    r"bolnišnic\w*|bolnic\w*|szpital\w*|nemocnic\w*|sygehus\w*|sjukhus\w*|νοσοκομ\w*|"
    r"diagnos\w*|medic\w*|médic\w*|médecin\w*|arzt|ärztin|doctor|dottor\w*|lékař\w*|lekarz\w*|"
    r"zdravnik\w*|γιατρ\w*|disease|krankheit|maladie|enfermedad|malattia|ziekte|sygdom|"
    r"symptom\w*|therap\w*|terap\w*|pregnan\w*|schwanger\w*|enceinte|embarazad\w*|"
    r"hiv|diabet\w*|cancer|krebs|kanker|rak\w*|depress\w*|hypertens\w*|"
    r"religio\w*|kirche|église|iglesia|chiesa|kerk|muslim\w*|jewish|jüd\w*|catholic\w*|"
    r"katholi\w*|gay|lesbi\w*|bisexu\w*|homosex\w*|transgender|ethnic\w*|ethni\w*|"
    r"political party|partei|union member\w*|gewerkschaft\w*|syndicat\w*|sindicat\w*|"
    r"vakbond|odbor\w*|blood type|blutgruppe|medication|medikament\w*|médicament\w*|"
    r"medicament\w*|farmac\w*|pharmac\w*|vaccin\w*|impf\w*|cepiv\w*)\b"
)
SPECIAL_LABELS = frozenset(
    {
        "MEDICAL_RECORD_NUMBER", "MEDICARE", "NHSNUMBER", "HEALTH_CONDITION", "MEDICATION_NAME",
        "PROCEDURE_NAME", "HEALTH_INSURANCE_ID", "NPI_NUMBER", "DEA_NUMBER", "GENETIC_DATA",
        "BIOMETRIC_ID", "PRESCRIPTION_NUMBER", "POLITICAL_OPINION", "ETHNICITY",
        "RELIGIOUS_BELIEF", "SEXUAL_ORIENTATION", "TRADE_UNION_MEMBERSHIP",
    }
)  # fmt: skip

PERSON_PARTS = {"FIRSTNAME": _E.PERSON, "SURNAME": _E.PERSON}
ADDRESS_PARTS = ("CITY", "ZIP", "STATE", "COUNTRY")

KIJI = LabelMap(
    types={
        **PERSON_PARTS,
        "COMPANYNAME": _E.ORGANIZATION, "ORGANIZATION": _E.ORGANIZATION,
        "STREET": _E.ADDRESS, "BUILDINGNUM": _E.ADDRESS, "BUILDNUM": _E.ADDRESS,
        "CITY": _E.ADDRESS, "ZIP": _E.ADDRESS, "STATE": _E.ADDRESS,
        "EMAIL": _E.EMAIL, "PHONENUMBER": _E.PHONE, "DATEOFBIRTH": _E.DATE_OF_BIRTH,
        "IBAN": _E.BANK_ACCOUNT, "CREDITCARDNUMBER": _E.BANK_ACCOUNT,
        "SSN": _E.ID_DOCUMENT, "NATIONALID": _E.ID_DOCUMENT, "TAXNUM": _E.ID_DOCUMENT,
        "PASSPORTID": _E.ID_DOCUMENT, "IDCARDNUM": _E.ID_DOCUMENT,
        "DRIVERLICENSENUM": _E.ID_DOCUMENT, "PERSONNUMMER": _E.ID_DOCUMENT,
        "PERSONALAUSWEISNUMMER": _E.ID_DOCUMENT,
        "LICENSEPLATENUM": _E.VEHICLE_PLATE,
        "PASSWORD": _E.SECRET, "SECURITYTOKEN": _E.SECRET,
        **dict.fromkeys(("URL", "USERNAME", "AGE", "TITLE", "COUNTRY", "DOMAIN", "AREACODE",
                         "COLONY", "LOCATION", "PROVINCE", "COUNTY", "NATIONALITY", "MONTH",
                         "YEAR", "RUT", "KUNDENNUMMER", "REFERENCE_TITLE")),
    },
    part_only=frozenset({"CITY", "ZIP", "STATE", "BUILDINGNUM", "BUILDNUM"}),
)  # fmt: skip

NYM = LabelMap(
    types={
        "GIVEN_NAME": _E.PERSON, "SURNAME": _E.PERSON,
        "COMPANY_NAME": _E.ORGANIZATION,
        "STREET_ADDRESS": _E.ADDRESS, "STREET_NAME": _E.ADDRESS, "BUILDING_NUMBER": _E.ADDRESS,
        "SECONDARY_ADDRESS": _E.ADDRESS, "CITY": _E.ADDRESS, "ZIP_CODE": _E.ADDRESS,
        "STATE": _E.ADDRESS,
        "EMAIL": _E.EMAIL, "PHONE": _E.PHONE, "FAX_NUMBER": _E.PHONE,
        "DATE_OF_BIRTH": _E.DATE_OF_BIRTH,
        "IBAN": _E.BANK_ACCOUNT, "ACCOUNT_NUMBER": _E.BANK_ACCOUNT,
        "CREDIT_DEBIT_CARD": _E.BANK_ACCOUNT,
        "GOVERNMENT_ID": _E.ID_DOCUMENT, "PASSPORT": _E.ID_DOCUMENT, "TAX_ID": _E.ID_DOCUMENT,
        "SSN": _E.ID_DOCUMENT, "DRIVERS_LICENSE": _E.ID_DOCUMENT,
        "LICENSE_PLATE": _E.VEHICLE_PLATE,
        "PASSWORD": _E.SECRET, "API_KEY": _E.SECRET,
        **dict.fromkeys(("DATE", "TIME", "COUNTRY", "CUSTOMER_ID", "EMPLOYEE_ID", "USERNAME",
                         "CVV", "GENDER", "AGE", "SWIFT_BIC", "MAC_ADDRESS", "ROUTING_NUMBER",
                         "URL", "PIN", "IP_ADDRESS", "MEDICAL_RECORD_NUMBER")),
    },
    part_only=frozenset({"CITY", "ZIP_CODE", "STATE", "BUILDING_NUMBER", "SECONDARY_ADDRESS",
                         "STREET_NAME"}),
)  # fmt: skip

ANON = LabelMap(
    types={
        "PERSON_NAME": _E.PERSON, "ORGANIZATION_NAME": _E.ORGANIZATION,
        "EMAIL_ADDRESS": _E.EMAIL, "PHONE_NUMBER": _E.PHONE, "STREET_ADDRESS": _E.ADDRESS,
        "DATE_OF_BIRTH": _E.DATE_OF_BIRTH,
        "BANK_ACCOUNT_NUMBER": _E.BANK_ACCOUNT, "IBAN": _E.BANK_ACCOUNT,
        "CREDIT_CARD_NUMBER": _E.BANK_ACCOUNT,
        "SOCIAL_SECURITY_NUMBER": _E.ID_DOCUMENT, "PASSPORT_NUMBER": _E.ID_DOCUMENT,
        "NATIONAL_ID_NUMBER": _E.ID_DOCUMENT, "TAX_ID": _E.ID_DOCUMENT,
        "DRIVER_LICENSE_NUMBER": _E.ID_DOCUMENT, "VISA_NUMBER": _E.ID_DOCUMENT,
        "LICENSE_PLATE": _E.VEHICLE_PLATE,
        "PASSWORD": _E.SECRET, "API_KEY": _E.SECRET, "AUTHENTICATION_TOKEN": _E.SECRET,
        **dict.fromkeys(("TIMESTAMP", "EMPLOYEE_ID", "IP_ADDRESS", "BANK_ROUTING_NUMBER",
                         "JOB_TITLE", "SWIFT_BIC_CODE", "INSURANCE_POLICY_NUMBER",
                         "INVOICE_NUMBER", "PIN", "CVV", "SALARY", "USERNAME", "MAC_ADDRESS",
                         "COURT_CASE_NUMBER", "BAR_NUMBER", "DOCKET_NUMBER", "LOCATION_NAME",
                         "CREDIT_CARD_FRAGMENT", "DEVICE_IDENTIFIER", "URL",
                         "CRYPTOCURRENCY_ADDRESS", "LATITUDE_LONGITUDE", "POSTAL_CODE",
                         "VEHICLE_IDENTIFICATION_NUMBER", "SOCIAL_MEDIA_HANDLE", "GENDER",
                         "MARITAL_STATUS", "EDUCATION_LEVEL", "VEHICLE_MODEL", "AGE",
                         "HOUSEHOLD_SIZE", "NATIONALITY")),
    },
)  # fmt: skip
ANON_ID_TYPES = frozenset(
    {"SOCIAL_SECURITY_NUMBER", "PASSPORT_NUMBER", "NATIONAL_ID_NUMBER", "TAX_ID",
     "DRIVER_LICENSE_NUMBER", "VISA_NUMBER", "IBAN", "BANK_ACCOUNT_NUMBER", "LICENSE_PLATE"}
)  # fmt: skip

#: E3's free-text entity types (seven languages) by keyword; first match wins.
E3_SPECIAL = re.compile(r"medic|condition|blood|health|diagnos|cpf|cnpj")
E3_KEYWORDS: tuple[tuple[str, EntityType | None], ...] = (
    (
        r"expir|ablauf|cvv|cvc|user|handle|login|signature|ip address|serial|ticket|flight|"
        r"reservation|transaction|postal|zip",
        None,
    ),
    (r"birth|geburt|naissance|nascita|geboorte|rojstv|γέννησ", _E.DATE_OF_BIRTH),
    (r"e-?mail|courriel|ηλεκτρονικ", _E.EMAIL),
    (r"phone|telefon|téléphone|telefono|telefoon|τηλέφων|mobil|gsm|fax|landline", _E.PHONE),
    (
        r"iban|bank ?account|konto|compte|conto|rekening|račun|λογαριασμ|credit ?card|"
        r"kreditkart|carte de crédit|carta di credito|creditcard|kartic|πιστωτικ",
        _E.BANK_ACCOUNT,
    ),
    (
        r"passport|pass|passeport|passaporto|paspoort|potn|διαβατ|identity|identit|ausweis|"
        r"carta d'identit|osebn\w* izkaz|ταυτότητ|social security|sozialversicher|sécurité sociale|"
        r"previdenza|sofi|bsn|emšo|emso|tax|steuer|fiscal|fiscale|davčn|ΑΦΜ|φορολογ|"
        r"driver|führerschein|permis|patente|rijbewijs|vozniško|δίπλωμα|national id|visa",
        _E.ID_DOCUMENT,
    ),
    (
        r"licen[cs]e plate|kennzeichen|immatriculation|targa|kenteken|registrsk|πινακίδ|"
        r"vehicle registration",
        _E.VEHICLE_PLATE,
    ),
    (
        r"organi[sz]|company|firma|unternehmen|entreprise|société|azienda|societ|bedrijf|"
        r"podjetj|εταιρ|οργανισμ|bank|banque|banca|banka|τράπεζ|insurance company|"
        r"versicherung|assurance|assicura|verzekeraar|zavarovalnic|ασφαλιστικ",
        _E.ORGANIZATION,
    ),
    (r"address|adresse|indirizzo|adres|naslov|διεύθυνσ", _E.ADDRESS),
    (
        r"person|name|\bnom\b|nome|naam|\bime\b|priimek|oseba|όνομα|πρόσωπο|persona|personne|persoon|"
        r"patient|client|klient|kunde|cliente|klant|stranka|πελάτ",
        _E.PERSON,
    ),
    (r".*", None),
)


def e3_type(types: list[str]) -> EntityType | None:
    joined = " | ".join(t.lower() for t in types)
    for pattern, etype in E3_KEYWORDS:
        if re.search(pattern, joined):
            return etype
    return None


# --- Readers ----------------------------------------------------------------------------------

KIJI_LANG = {"English": "en", "Spanish": "es", "Danish": "da", "Dutch": "nl", "German": "de",
             "French": "fr"}  # fmt: skip
E3_LANG = {"English": "en", "Dutch": "nl", "German": "de", "Slovene": "sl", "French": "fr",
           "Italian": "it", "Greek": "el"}  # fmt: skip


def _locate(text: str, values: list[tuple[str, str]]) -> tuple[tuple[int, int, str], ...]:
    """Every whole-word occurrence of each value (longest first, no overlaps)."""
    spans: list[tuple[int, int, str]] = []
    for value, label in sorted(values, key=lambda v: -len(v[0])):
        value = value.strip()
        if not value:
            continue
        pat = re.compile(rf"(?<!\w){re.escape(value)}(?!\w)")
        hits = [m.span() for m in pat.finditer(text)]
        if not hits:
            raise ConversionError("value not found")
        for s, e in hits:
            if not any(s < pe and ps < e for ps, pe, _ in spans):
                spans.append((s, e, label))
    return tuple(sorted(spans))


def read_kiji(path: Path) -> Iterator[tuple[Row | None, str]]:
    import pandas as pd

    df = pd.read_parquet(path)
    for i, r in enumerate(df.itertuples(index=False)):
        lang = KIJI_LANG[r.language]
        labels = [(str(m["value"]), str(m["label"])) for m in r.privacy_mask]
        if any(lab in SPECIAL_LABELS for _, lab in labels):
            yield None, "special_label"
            continue
        try:
            spans = _locate(r.text, labels)
        except ConversionError:
            yield None, "value_not_found"
            continue
        yield Row(str(i), lang, str(r.text), spans, meta={"country": r.country}), ""


def read_nym(path: Path) -> Iterator[tuple[Row | None, str]]:
    import langid

    langid.set_languages(
        [
            "en",
            "de",
            "fr",
            "es",
            "it",
            "pt",
            "nl",
            "pl",
            "sv",
            "cs",
            "ro",
            "tr",
            "fi",
            "da",
            "el",
            "ru",
            "uk",
            "ja",
            "zh",
            "ko",
            "ar",
            "hi",
        ]
    )
    with path.open(encoding="utf-8") as fh:
        lines = fh.readlines()
    #: Hash order, then a bounded scan: 200k of 724k rows give every language >= 2.5k rows.
    picked = sorted(range(len(lines)), key=lambda i: order(str(i), "nym"))[:NYM_SCAN]
    for i in picked:
        if True:
            raw = json.loads(lines[i])
            ents = raw["entities"]
            if any(e["label"] in SPECIAL_LABELS for e in ents):
                yield None, "special_label"
                continue
            lang, _ = langid.classify(raw["text"])
            spans = tuple((int(e["start"]), int(e["end"]), str(e["label"])) for e in ents)
            yield Row(str(i), lang, raw["text"], spans), ""


def read_e3(path: Path) -> Iterator[tuple[Row | None, str]]:
    import pandas as pd

    df = pd.read_parquet(path)
    for i, r in enumerate(df.itertuples(index=False)):
        if r.domain == "healthcare":
            yield None, "health_domain"
            continue
        if any(E3_SPECIAL.search(t.lower()) for ent in r.entities for t in ent["types"]):
            yield None, "special_label"
            continue
        values = []
        for ent in r.entities:
            etype = e3_type(list(ent["types"]))
            values.append((str(ent["entity"]), etype.value if etype else "OTHER"))
        try:
            spans = _locate(r.text, values)
        except ConversionError:
            yield None, "value_not_found"
            continue
        yield Row(str(i), E3_LANG[r.language], str(r.text), spans, meta={"domain": r.domain}), ""


E3_MAP = LabelMap(types={**{t.value: t for t in EntityType}, "OTHER": None})


def read_anon(path: Path) -> Iterator[tuple[Row | None, str]]:
    import pandas as pd

    cols = ["record_id", "language", "text", "annotations", "art9_special_categories",
            "domain", "provenance"]  # fmt: skip
    df = pd.read_parquet(path, columns=cols)
    df = df[df.language.isin(EU)]
    for r in df.itertuples(index=False):
        if r.art9_special_categories != "[]" or r.domain == "clinical":
            yield None, "special_category"
            continue
        if json.loads(r.provenance).get("source_type") not in {
            "synthetic", "synthetic_lattice_enrichment",
        }:  # fmt: skip
            yield None, "not_synthetic"
            continue
        ann = json.loads(r.annotations)
        labels = {a["entity_type"] for a in ann}
        if labels & SPECIAL_LABELS or labels - set(ANON.types):
            yield None, "unmapped_or_special_label"
            continue
        if not labels & ANON_ID_TYPES:
            yield None, "no_id"
            continue
        spans = tuple((int(a["start"]), int(a["end"]), str(a["entity_type"])) for a in ann)
        yield Row(str(r.record_id), str(r.language), str(r.text), spans), ""


# --- Selection --------------------------------------------------------------------------------


def order(uid: str, source: str) -> str:
    return hashlib.sha256(f"{SEED}:{source}:{uid}".encode()).hexdigest()


def to_document(row: Row, source: str, labels: LabelMap) -> Document:
    if SPECIAL.search(row.text):
        raise ConversionError("special category keyword")
    conv = convert(row, labels, prefix=f"v41-{source}", kind=source, source=source)
    doc = conv.document
    meta = dict(doc.meta)
    meta["synthetic"] = True
    meta["loss_ignore"] = [[r["start"], r["end"]] for r in meta.get("ignore", ())
                           if not r["label"].startswith(("DATE", "TIME", "TIMESTAMP"))]  # fmt: skip
    return Document(doc.id, doc.language, doc.text, doc.spans, meta)


def select(
    rows: Iterator[tuple[Row | None, str]], source: str, labels: LabelMap, want: Mapping[str, int]
) -> tuple[dict[str, list[Document]], Counter[str]]:
    counts: Counter[str] = Counter()
    pool: dict[str, list[tuple[str, Row]]] = defaultdict(list)
    for row, reason in rows:
        if row is None:
            counts[f"excluded:{reason}"] += 1
            continue
        if row.language not in want:
            counts["excluded:language"] += 1
            continue
        counts[f"rows:{row.language}"] += 1
        pool[row.language].append((order(row.uid, source), row))
    out: dict[str, list[Document]] = {}
    for lang, items in pool.items():
        chosen: list[Document] = []
        for _, row in sorted(items, key=lambda it: it[0]):
            if len(chosen) >= want[lang]:
                break
            try:
                chosen.append(to_document(row, source, labels))
            except ConversionError as exc:
                key = "special category keyword" if "special" in str(exc) else "conversion"
                counts[f"excluded:{key}"] += 1
        out[lang] = chosen
    return out, counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--hf", type=Path, required=True, help="downloaded repos, <owner>__<name>")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--per-language", type=int, default=2500)
    parser.add_argument(
        "--mix-total",
        type=int,
        required=True,
        help="documents in the v4.1 mix without pii-anon (sets its 5 %% cap)",
    )
    parser.add_argument("--sources", default="kiji,nym,e3,pii-anon")
    args = parser.parse_args(argv)
    readers = {"kiji": (read_kiji, KIJI), "nym": (read_nym, NYM), "e3": (read_e3, E3_MAP),
               "pii-anon": (read_anon, ANON)}  # fmt: skip
    manifest: dict[str, Any] = {
        "ticket": "LAB-1539", "seed": SEED, "synthetic": True,
        "note": "rows are not committed; ids are row indices (kiji, nym, e3) or record_id",
        "sources": {},
    }  # fmt: skip
    cap_anon = 0
    for name in args.sources.split(","):
        spec = SOURCES[name]
        reader, labels = readers[name]
        path = args.hf / spec["repo"].replace("/", "__") / spec["file"]
        if name == "pii-anon":
            # <= 5 % of the final mix: anon / (mix + anon) <= 0.05.
            cap_anon = int(args.mix_total * 0.05 / 0.95)
            want = dict.fromkeys(EU, cap_anon)
        elif name == "e3":
            want = dict.fromkeys(EU, 10**6)
        else:
            want = dict.fromkeys(EU, args.per_language)
        chosen, counts = select(reader(path), name, labels, want)
        if name == "pii-anon":  # one shared cap over all languages, in hash order
            flat = sorted(
                (d for docs in chosen.values() for d in docs), key=lambda d: order(d.id, name)
            )[:cap_anon]
            chosen = defaultdict(list)
            for d in flat:
                chosen[d.language].append(d)
        block: dict[str, Any] = {**spec, "synthetic": True, "counts": dict(sorted(counts.items())),
                                 "languages": {}}  # fmt: skip
        for lang, docs in sorted(chosen.items()):
            if not docs:
                continue
            target = args.out / name / f"{lang}-{name}-train.jsonl"
            target.parent.mkdir(parents=True, exist_ok=True)
            write_fixtures(target, docs)
            block["languages"][lang] = {
                "documents": len(docs),
                "gold_spans": dict(sorted(Counter(s.entity_type.value for d in docs
                                                  for s in d.spans).items())),
                "file_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "row_ids": ",".join(str(d.meta["uid"]) for d in docs),
            }  # fmt: skip
        manifest["sources"][name] = block
        total = sum(v["documents"] for v in block["languages"].values())
        print(f"hf-v41: {name}: {total} documents, {dict(counts)}", file=sys.stderr, flush=True)
    if "pii-anon" in manifest["sources"]:
        manifest["pii_anon_cap"] = {"mix_total_without": args.mix_total, "cap": cap_anon,
                                    "share_max": 0.05}  # fmt: skip
    label_tables = {"kiji": KIJI.table(), "nym": NYM.table(), "pii-anon": ANON.table(),
                    "e3": [{"keyword": k, "pii_guard_type": t.value if t else None}
                           for k, t in E3_KEYWORDS]}  # fmt: skip
    manifest["label_maps"] = label_tables
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
