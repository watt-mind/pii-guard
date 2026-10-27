"""CEE-PII-Bench v0.2: a held-out synthetic benchmark weighted to Central European identifiers.

`flowxai/cee-pii-bench <https://huggingface.co/datasets/flowxai/cee-pii-bench>`_ (Apache-2.0):
2,000 synthetic documents (bank statements, chats, contract clauses, e-mails, form fields,
OCR-ish fragments, support tickets) in Romanian, Polish, Hungarian, Uzbek and UK/US English,
with checksum-valid national identifiers (TAJ for Hungarian), deliberate noise (stripped
diacritics, OCR confusions, casing, whitespace damage) and unlabelled hard negatives (order
and tracking numbers). Its own card says it is the frozen test split of its generator and
contains no real personal data. Here: every Hungarian document and a sample of the English
ones (``en_uk`` and ``en_us`` both become ``en``, the variant kept in ``meta.variant``).

Its account, policy and contract references, ABA routing numbers and health conditions have
no pii-guard type (references identify a contract, not a person): ignore regions. ``employer``
is ``ORGANIZATION`` (a ``keep`` type).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from pathlib import Path

from pii_guard.eval.datasets._common import LabelMap, Row
from pii_guard.eval.datasets.spec import Dataset, SourceFile
from pii_guard.types import EntityType

__all__ = ["DATASET", "LABELS", "rows"]

REPO = "flowxai/cee-pii-bench"
REVISION = "84ee883574624e6fde2f81932da187f59b3253e4"
LANGUAGES = {"hu": "hu", "en_uk": "en", "en_us": "en"}

_E = EntityType
LABELS = LabelMap(
    types={
        "person_name": _E.PERSON,
        "first_name": _E.PERSON,
        "surname": _E.PERSON,
        "address": _E.ADDRESS,
        "postal": _E.ADDRESS,
        "email": _E.EMAIL,
        "phone": _E.PHONE,
        "dob": _E.DATE_OF_BIRTH,
        "taj": _E.NATIONAL_ID_HU_TAJ,
        "card": _E.BANK_ACCOUNT,
        "plate": _E.VEHICLE_PLATE,
        "employer": _E.ORGANIZATION,
        "utr": _E.ID_DOCUMENT,
        "nhs": _E.ID_DOCUMENT,
        "ssn": _E.ID_DOCUMENT,
        "nino": _E.ID_DOCUMENT,
        "itin": _E.ID_DOCUMENT,
        "szemelyi": _E.ID_DOCUMENT,
        "uk_account_number": _E.BANK_ACCOUNT,
        "account_ref": None,
        "policy_ref": None,
        "contract_ref": None,
        "aba": None,
        "health_condition": None,
        "ein": None,
    },
    part_only=frozenset({"postal"}),
    notes={
        "postal": "ADDRESS inside an address; a postcode on its own is policy-excluded",
        "employer": "ORGANIZATION is a keep type: scored for recall, never a leak",
        "utr": "UK tax and health numbers are ID_DOCUMENT",
        "account_ref": "a customer, policy or contract reference identifies a contract",
        "aba": "a routing number identifies a bank, not a person",
        "ein": "an employer identification number identifies a business",
    },
)


def _uid(raw: dict[str, object]) -> str:
    # The bench has no row id; its generator seed is unique per row.
    seed = raw.get("seed")
    if seed is not None:
        return str(seed)
    return hashlib.sha256(str(raw["text"]).encode()).hexdigest()[:16]  # pragma: no cover


def rows(paths: Sequence[Path]) -> Iterator[Row]:
    with paths[0].open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            raw = json.loads(line)
            variant = str(raw.get("language"))
            language = LANGUAGES.get(variant)
            if language is None:
                continue
            entities = raw.get("entities") or []
            yield Row(
                _uid(raw),
                language,
                str(raw["text"]),
                tuple((int(e["start"]), int(e["end"]), str(e["type"])) for e in entities),
                meta={
                    "variant": variant,
                    "registers": list(raw.get("registers") or []),
                    "has_noise": bool(raw.get("has_noise")),
                    "has_negatives": bool(raw.get("has_negatives")),
                },
                values=tuple(str(e["text"]) for e in entities),
            )


DATASET = Dataset(
    name="cee-pii",
    title="CEE-PII-Bench v0.2",
    homepage=f"https://huggingface.co/datasets/{REPO}",
    revision=REVISION,
    files=(
        SourceFile(
            "ceepii_bench_v0.2.jsonl",
            f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/ceepii_bench_v0.2.jsonl",
            "15b49cf42411d990660d59bee6769a5d5f449746b31f12a79ed9e226ed214acd",
        ),
    ),
    license="Apache-2.0",
    license_url="https://www.apache.org/licenses/LICENSE-2.0",
    attribution="FlowX.AI, flowxai/cee-pii-bench (CEE-PII-Bench v0.2)",
    languages=("hu", "en"),
    source_split="test (the whole v0.2 standard subset)",
    split="test",
    synthetic=True,
    commit_rows=True,
    description="short noisy CEE documents with checksum-valid TAJ, hard negatives, no-entity docs",
    sample={"hu": 251, "en": 200},
    seed=2026,
    labels=LABELS,
    read=rows,
    notes=(
        "Synthetic, from a template generator with deliberate noise (stripped Hungarian "
        "diacritics, OCR confusions); about 14 % of the documents have no entities at all.",
        "Written by another detector's authors as its own benchmark: a fair third-party set "
        "for pii-guard, though not for flowxai/cee-pii.",
    ),
)
