"""Hard negatives for NER v2.1: uncued reference numbers, lone streets, family firms (LAB-1306).

NER v2 (LAB-1150, ``negatives.py``) still over-masks on unseen text in three ways:

- **reference numbers without a cue word** (LAB-1293): tracking numbers (``1Z…``, ``LX…GB``),
  timestamp-style references, order / ticket / invoice ids in JSON, CSV and log lines become
  ``BANK_ACCOUNT`` or ``ID_DOCUMENT``;
- **a street name on its own** (LAB-1220): ``… Street`` without a house number or town becomes
  ``ADDRESS`` (OpenPII calls a lone street an address, pii-guard's policy doesn't);
- **family-firm suffixes** (LAB-1220): ``és Fia``, ``& Söhne``, ``and Sons`` become ``PERSON``.

This script writes seeded, template-based hu / en / de documents for each case:

- ``reference``: random reference numbers, with a generic cue (``Ref.``, ``#``, ``Nr.``) or
  none at all, in prose, JSON, CSV and log lines. **No gold spans.** A number that passes a
  check the rule detector uses for personal data (IBAN, giro, TAJ, tax ID, personal ID, a
  Luhn-valid 13-19 digit run) is redrawn, so nothing here is a valid identifier by accident;
- ``street``: a street name with no number and no town, **no gold spans**; one document in
  three also carries a full fictional address (``pii_guard.eval.identities``) labelled
  ``ADDRESS``, so the model learns the difference, not "streets are never addresses";
- ``company``: a family firm (surname + ``és Fia`` / ``& Sons`` / ``& Söhne`` + legal form)
  labelled ``ORGANIZATION`` as a whole (a keep type by default). In Hungarian the rule detector
  still masks the surname as ``PERSON`` (``pii_guard.languages.hu.companies``,
  docs/entities.md), so the final masking matches the policy.

Everything is fictional: surnames come from the generator's lists, numbers are random, and
:func:`check_disjoint` refuses to write a street or company name that occurs in any evaluation
fixture text (``eval/fixtures``, and the LAB-1226 sets in ``eval/synthetic`` and
``eval/datasets`` when present, plus any ``--eval-dir``), so none of the scored
documents' values is taught. Nothing is derived from a test split::

    uv run --no-sync python training/ner/negatives_v21.py --n 1500 --seed 1306 \\
        --out eval/generated/negatives-v21
"""

# Seeded synthetic data: the standard PRNG is the point.
# ruff: noqa: S311

from __future__ import annotations

import argparse
import json
import random
import string
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from pii_guard.detect.checksums import (
    is_valid_giro,
    is_valid_hu_personal_id,
    is_valid_hu_tax_id,
    is_valid_iban,
    is_valid_taj,
)
from pii_guard.eval.fixtures import Document, GoldSpan, write_fixtures
from pii_guard.eval.identities import identity_generator
from pii_guard.lang import lexicon
from pii_guard.types import EntityType

LANGUAGES = ("hu", "en", "de")
#: Share of each kind in a language's documents (reference, street, company).
MIX = (("reference", 0.5), ("street", 0.25), ("company", 0.25))
#: Where scored text lives; generated names must not occur in it.
EVAL_DIRS = (Path("eval/fixtures"), Path("eval/synthetic"), Path("eval/datasets"))

# --- reference numbers ------------------------------------------------------------------------

_UPPER = string.ascii_uppercase
_ALNUM = string.ascii_uppercase + string.digits
_POSTAL_COUNTRIES = ("GB", "DE", "HU", "NL", "FR", "AT", "CN", "US", "PL", "CZ")


def _digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(string.digits) for _ in range(n))


def luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def looks_like_personal_id(value: str) -> bool:
    """True when ``value`` passes a check the rule detector uses for personal data."""
    compact = "".join(ch for ch in value if ch.isalnum()).upper()
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(compact) >= 15 and compact[:2].isalpha() and is_valid_iban(compact):
        return True
    if len(digits) in (16, 24) and is_valid_giro(digits):
        return True
    if len(digits) == 9 and is_valid_taj(digits):
        return True
    if len(digits) == 10 and is_valid_hu_tax_id(digits):
        return True
    if len(digits) == 11 and is_valid_hu_personal_id(digits):
        return True
    return 13 <= len(digits) <= 19 and digits == compact and luhn_valid(digits)


def reference_number(rng: random.Random) -> str:
    """One random reference shape (tracking, ticket, order, invoice, timestamp, hex id)."""
    kind = rng.randrange(11)
    if kind == 0:  # parcel-carrier style tracking number
        return "1Z" + "".join(rng.choice(_ALNUM) for _ in range(6)) + _digits(rng, 10)
    if kind == 1:  # UPU S10 postal item
        return (
            "".join(rng.choice(_UPPER) for _ in range(2))
            + _digits(rng, 9)
            + rng.choice(_POSTAL_COUNTRIES)
        )
    if kind == 2:  # timestamp-style reference
        year = rng.randint(2019, 2027)
        return f"{year}{rng.randint(1, 365):03d}{_digits(rng, rng.randint(6, 9))}"
    if kind == 3:  # epoch milliseconds
        return str(rng.randint(1_550_000_000_000, 1_830_000_000_000))
    if kind == 4:  # ticketing system key
        project = "".join(rng.choice(_UPPER) for _ in range(rng.randint(2, 5)))
        return f"{project}-{rng.randint(1, 99999)}"
    if kind == 5:  # incident / change number
        return rng.choice(("INC", "CHG", "REQ", "TKT", "SR")) + _digits(rng, rng.randint(7, 10))
    if kind == 6:  # order id with a year
        prefix = rng.choice(("ORD", "SO", "PO", "WO", "RMA"))
        return f"{prefix}-{rng.randint(2019, 2027)}-{rng.randint(1, 999999):06d}"
    if kind == 7:  # invoice with slashes
        prefix = rng.choice(("INV", "SZ", "RE", "BIZ", "CN"))
        return f"{prefix}/{rng.randint(2019, 2027)}/{rng.randint(1, 99999):05d}"
    if kind == 8:  # hex request / trace id
        return "".join(rng.choice("0123456789abcdef") for _ in range(rng.choice((12, 16, 24, 32))))
    if kind == 9:  # long bare digit run
        return _digits(rng, rng.randint(10, 22))
    # grouped digits
    groups = [_digits(rng, rng.randint(3, 5)) for _ in range(rng.randint(3, 5))]
    return rng.choice((" ", "-")).join(groups)


def clean_reference(rng: random.Random) -> str:
    for _ in range(100):
        value = reference_number(rng)
        if not looks_like_personal_id(value):
            return value
    raise RuntimeError("could not draw a reference number that fails every identifier check")


#: Generic cues: they say "a reference follows", not what kind.
_GENERIC_CUE = {
    "hu": ("Ref.", "#", "sz.", "Azon.:", "Hiv.:", ""),
    "en": ("Ref.", "#", "No.", "ID", "Ref:", ""),
    "de": ("Ref.", "#", "Nr.", "Az.:", "Ref:", ""),
}
_STATUS = {
    "hu": ("feldolgozva", "kiszállítva", "függőben", "lezárva", "visszautalva", "törölve"),
    "en": ("processed", "shipped", "pending", "closed", "refunded", "cancelled"),
    "de": ("verarbeitet", "versandt", "offen", "geschlossen", "erstattet", "storniert"),
}
_PROSE = {
    "hu": (
        "A {cue}{num} állapota: {status}.",
        "{num}: {status}, a rendszer {n} perce frissítette.",
        "Kérem, nézze meg a {cue}{num} tételt, mert még {status}.",
        "A {num} és a {num_b} összevonva, mindkettő {status}.",
        "Frissítés: {num} ({status}).",
    ),
    "en": (
        "Status of {cue}{num}: {status}.",
        "{num}: {status}, last updated {n} minutes ago.",
        "Can you check {cue}{num}? It is still {status}.",
        "{num} and {num_b} were merged; both are {status}.",
        "Update: {num} ({status}).",
    ),
    "de": (
        "Status von {cue}{num}: {status}.",
        "{num}: {status}, zuletzt vor {n} Minuten aktualisiert.",
        "Bitte prüfen Sie {cue}{num}, es ist noch {status}.",
        "{num} und {num_b} wurden zusammengeführt, beide {status}.",
        "Update: {num} ({status}).",
    ),
}
_JSON_KEYS = ("id", "ref", "reference", "tracking", "order_id", "ticket", "invoice", "request_id",
              "trace_id", "external_id", "shipment", "case")  # fmt: skip
_LOG_LEVELS = ("INFO", "DEBUG", "WARN", "ERROR")
_LOG_EVENTS = ("processed", "enqueued", "retrying", "completed", "timeout", "synced")


def _cue(rng: random.Random, language: str) -> str:
    cue = rng.choice(_GENERIC_CUE[language])
    return f"{cue} " if cue and not cue.endswith(("#",)) else cue


def _reference_text(rng: random.Random, language: str) -> str:
    shape = rng.randrange(4)
    status = _STATUS[language]
    if shape == 0:
        return rng.choice(_PROSE[language]).format(
            cue=_cue(rng, language),
            num=clean_reference(rng),
            num_b=clean_reference(rng),
            status=rng.choice(status),
            n=rng.randint(1, 59),
        )
    if shape == 1:
        rows = [
            {rng.choice(_JSON_KEYS): clean_reference(rng), "status": rng.choice(status)}
            for _ in range(rng.randint(1, 4))
        ]
        return json.dumps(rows if len(rows) > 1 else rows[0], ensure_ascii=False)
    if shape == 2:
        head = rng.choice(("ref,status,qty", "id;status;count", "reference\tstatus\titems"))
        sep = {"ref,status,qty": ",", "id;status;count": ";"}.get(head, "\t")
        lines = [head] + [
            sep.join((clean_reference(rng), rng.choice(status), str(rng.randint(1, 500))))
            for _ in range(rng.randint(2, 5))
        ]
        return "\n".join(lines)
    stamp = f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}T{rng.randint(0, 23):02d}"
    lines = [
        f"{stamp}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}Z {rng.choice(_LOG_LEVELS)} "
        f"{rng.choice(_LOG_EVENTS)} {clean_reference(rng)} in {rng.randint(3, 4000)} ms"
        for _ in range(rng.randint(1, 4))
    ]
    return "\n".join(lines)


# --- lone streets -------------------------------------------------------------------------

_EN_STREET_STEMS = (
    "Larch", "Cooper", "Abbey", "Sycamore", "Tanner", "Granary", "Wharf", "Linden", "Hawthorn",
    "Quarry", "Foundry", "Rectory", "Bridge", "Cedar", "Paddock", "Saddler", "Vicarage", "Mercer",
    "Juniper", "Brewery", "Kiln", "Pottery", "Dyer", "Weaver", "Rope", "Tannery", "Market",
)  # fmt: skip
_DE_STREET_STEMS = (
    "Linden", "Ahorn", "Birken", "Mühlen", "Kirch", "Garten", "Wiesen", "Brunnen", "Schul",
    "Bahnhof", "Feld", "Berg", "Wald", "Rosen", "Tannen", "Eichen", "Markt", "Hafen", "Schloss",
    "Kastanien", "Holunder", "Weiden", "Kiefern", "Schmiede", "Färber", "Gerber", "Salz",
)  # fmt: skip
_DE_STREET_TYPES = ("straße", "weg", "gasse", "allee", "ring", "platz")
_STREET_PROSE = {
    "hu": (
        "A {street} felújítása péntekig tart, terelés lesz.",
        "A {street} sarkán van egy jó pékség.",
        "Tegnap este a {street} környékén sétáltunk.",
        "A buszjárat ideiglenesen nem áll meg a {street} megállóban.",
        "A {street} egyirányú lett, kérlek, kerüld el.",
    ),
    "en": (
        "Roadworks on {street} will last until Friday.",
        "There is a good bakery at the corner of {street}.",
        "We walked along {street} after dinner.",
        "The bus no longer stops on {street} this week.",
        "{street} is one-way now, so take the next turn.",
    ),
    "de": (
        "Die Baustelle in der {street} dauert bis Freitag.",
        "An der Ecke {street} gibt es eine gute Bäckerei.",
        "Nach dem Essen sind wir die {street} entlanggelaufen.",
        "Der Bus hält diese Woche nicht in der {street}.",
        "Die {street} ist jetzt eine Einbahnstraße.",
    ),
}
_ADDRESS_PROSE = {
    "hu": ("A csomagot erre a címre kérem: {address}.", "Szállítási cím: {address}."),
    "en": ("Please send the parcel to {address}.", "Delivery address: {address}."),
}


def street_name(rng: random.Random, language: str) -> str:
    if language == "hu":
        name = lexicon("street_names", "hu").sample(rng, 0.7)
        kind = rng.choice(("utca", "utca", "út", "tér", "köz", "sor", "fasor"))
        return f"{name} {kind}"
    if language == "en":
        kind = lexicon("street_types", "en").sample(rng, 0.7)
        return f"{rng.choice(_EN_STREET_STEMS)} {kind}"
    stem = rng.choice(_DE_STREET_STEMS)
    kind = rng.choice(_DE_STREET_TYPES)
    return f"{stem}{kind}" if kind != "platz" or rng.random() < 0.5 else f"Am {stem}platz"


def _street_doc(rng: random.Random, language: str) -> tuple[str, list[GoldSpan], str]:
    street = street_name(rng, language)
    parts = [rng.choice(_STREET_PROSE[language]).format(street=street)]
    spans: list[GoldSpan] = []
    if language in _ADDRESS_PROSE and rng.random() < 1 / 3:
        address = identity_generator(language, rng).address()
        sentence = rng.choice(_ADDRESS_PROSE[language])
        prefix = " ".join(parts) + " "
        start = len(prefix) + sentence.index("{address}")
        text = sentence.format(address=address)
        parts.append(text[:-1] if address.endswith(".") and text.endswith("..") else text)
        spans.append(GoldSpan(start, start + len(address), EntityType.ADDRESS, address))
    return " ".join(parts), spans, street


# --- family firms -------------------------------------------------------------------------

_EN_SURNAMES = (
    "Ashcombe", "Brackley", "Cotterill", "Danvers", "Elsworth", "Fenwick", "Garside", "Hebden",
    "Ingleby", "Jessop", "Kirkham", "Lowther", "Marchbank", "Netherby", "Ormerod", "Pickles",
    "Rathbone", "Sowerby", "Tatham", "Upton", "Varley", "Wainwright", "Yeadon", "Bramley",
)  # fmt: skip
_DE_SURNAMES = (
    "Brenner", "Dorfmann", "Eckert", "Falkner", "Gerlach", "Haberl", "Imhof", "Jungwirth",
    "Kessler", "Lindauer", "Mosbach", "Niederer", "Oberle", "Pfister", "Reinhold", "Sauter",
    "Thaler", "Ulbrich", "Vogler", "Wendling", "Zeller", "Amrhein", "Bürkle", "Hilger",
)  # fmt: skip
_FIRM = {
    "hu": ("{s} és Fia Kft.", "{s} és Fiai Kkt.", "{s} és Fia Bt.", "{s} és Társa Bt.",
           "{s} és Fiai Kft.", "{s} Testvérek Kft.", "{s} és Lánya Bt."),
    "en": ("{s} & Sons Ltd", "{s} and Sons", "{s} & Sons", "{s} Brothers Ltd", "{s} & Daughters",
           "{s} and Son Ltd", "{s} & Co."),
    "de": ("{s} & Söhne GmbH", "{s} und Söhne KG", "Gebrüder {s} GmbH", "{s} & Sohn",
           "{s} & Co. KG", "{s} Söhne OHG", "{s} & Tochter GmbH"),
}  # fmt: skip
_FIRM_PROSE = {
    "hu": (
        "Az ajánlatot a {org} küldte, a határidő a jövő hét.",
        "Szállító: {org}. A teljesítés a szerződés szerint történik.",
        "A {org} raktára hétvégén zárva tart.",
        "A megbízást a {org} nyerte el.",
    ),
    "en": (
        "The quote came from {org}; the deadline is next week.",
        "Supplier: {org}. Delivery as per the contract.",
        "The {org} warehouse is closed at the weekend.",
        "The contract was awarded to {org}.",
    ),
    "de": (
        "Das Angebot kam von {org}, die Frist ist nächste Woche.",
        "Lieferant: {org}. Lieferung laut Vertrag.",
        "Das Lager von {org} ist am Wochenende geschlossen.",
        "Den Auftrag hat {org} erhalten.",
    ),
}


_LEGAL_FORMS = frozenset({"Kft.", "Kkt.", "Bt.", "Ltd", "GmbH", "KG", "OHG"})


def firm_name(rng: random.Random, language: str) -> tuple[str, str]:
    """``(name, core)``: the firm, and the firm without its legal form (what is checked)."""
    if language == "hu":
        surname = lexicon("surnames", "hu").sample(rng, 0.7)
    else:
        surname = rng.choice(_EN_SURNAMES if language == "en" else _DE_SURNAMES)
    name = rng.choice(_FIRM[language]).format(s=surname)
    head, _, last = name.rpartition(" ")
    return name, head if last in _LEGAL_FORMS else name


def _company_doc(rng: random.Random, language: str) -> tuple[str, list[GoldSpan], str]:
    org, core = firm_name(rng, language)
    sentence = rng.choice(_FIRM_PROSE[language])
    start = sentence.index("{org}")
    span = GoldSpan(start, start + len(org), EntityType.ORGANIZATION, org)
    return sentence.format(org=org), [span], core


# --- documents ----------------------------------------------------------------------------


def kind_of(index: int, n: int) -> str:
    edge = 0.0
    for kind, share in MIX:
        edge += share
        if index < round(edge * n):
            return kind
    return MIX[-1][0]


def document(language: str, seed: int, index: int, n: int, attempt: int = 0) -> Document:
    key = f"pii-guard-negatives-v21/{seed}/{language}/{index}"
    rng = random.Random(key if attempt == 0 else f"{key}/{attempt}")
    kind = kind_of(index, n)
    spans: list[GoldSpan] = []
    name = ""
    if kind == "reference":
        text = "\n".join(_reference_text(rng, language) for _ in range(rng.randint(1, 2)))
    elif kind == "street":
        text, spans, name = _street_doc(rng, language)
    else:
        text, spans, name = _company_doc(rng, language)
    meta = {"kind": f"negative-{kind}", "split": "train", "source": "synthetic", "seed": seed}
    if name:  # the fictional street / firm, for check_disjoint
        meta["name"] = name
    doc_id = f"{language}-negatives-v21-s{seed}-{index:05d}"
    return Document(doc_id, language, text, tuple(spans), meta)


def eval_texts(dirs: Iterable[Path] = EVAL_DIRS) -> list[str]:
    texts = []
    for root in dirs:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    texts.append(json.loads(line).get("text", ""))
    return texts


def protected_names(docs: Sequence[Document]) -> set[str]:
    """The street and firm names in ``docs`` that :func:`check_disjoint` looks up."""
    return {doc.meta["name"] for doc in docs if doc.meta.get("name")}


def check_disjoint(docs: Sequence[Document], texts: Sequence[str]) -> list[str]:
    """Street / company names of ``docs`` that occur in an evaluation text (should be none)."""
    blob = "\n".join(texts)
    return sorted(name for name in protected_names(docs) if name in blob)


def generate(language: str, n: int, seed: int, texts: Sequence[str]) -> list[Document]:
    """``n`` documents; one whose name occurs in ``texts`` is redrawn (same index and kind)."""
    blob = "\n".join(texts)
    docs: list[Document] = []
    for index in range(n):
        for attempt in range(1000):
            doc = document(language, seed, index, n, attempt)
            if not any(name in blob for name in protected_names([doc])):
                docs.append(doc)
                break
        else:  # pragma: no cover - the name lists are far larger than the eval sets' overlap
            raise RuntimeError(f"{language} {index}: every draw occurs in an eval fixture")
    return docs


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--n", type=int, default=1500, help="documents per language")
    parser.add_argument("--seed", type=int, default=1306)
    parser.add_argument("--out", type=Path, default=Path("eval/generated/negatives-v21"))
    parser.add_argument(
        "--eval-dir", type=Path, action="append", default=[], help="more scored JSONL to avoid"
    )
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    texts = eval_texts([*EVAL_DIRS, *args.eval_dir])
    for language in LANGUAGES:
        docs = generate(language, args.n, args.seed, texts)
        clash = check_disjoint(docs, texts)
        if clash:
            raise SystemExit(f"{language}: {len(clash)} names occur in eval fixtures: {clash[:5]}")
        path = args.out / f"{language}-negatives-v21-train.jsonl"
        write_fixtures(path, docs)
        kinds = {k: sum(d.meta["kind"] == f"negative-{k}" for d in docs) for k, _ in MIX}
        print(f"negatives v2.1: {len(docs)} {language} {kinds} -> {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
