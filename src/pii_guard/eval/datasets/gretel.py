"""Gretel ``synthetic_pii_finance_multilingual``: synthetic financial documents, en and de.

`gretelai/synthetic_pii_finance_multilingual
<https://huggingface.co/datasets/gretelai/synthetic_pii_finance_multilingual>`_ (Apache-2.0):
55,940 full-length synthetic financial documents (EDI messages, loan agreements, statements,
e-mails) in seven languages, generated with Gretel Navigator; spans were labelled during
generation and checked with GLiNER, so some labels are missing or wrong (per the card). The
``test`` split is the held-out sample here; pii-guard never trained on any of it.

Labels pii-guard has no type for (dates and times, IP addresses, customer and employee ids,
PINs, passwords, API keys, user names, SWIFT and routing codes, card security codes,
coordinates) are ignore regions. ``company`` is ``ORGANIZATION`` (a ``keep`` type).
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from pathlib import Path

from pii_guard.eval.datasets._common import LabelMap, Row, read_parquet
from pii_guard.eval.datasets.spec import Dataset, SourceFile
from pii_guard.types import EntityType

__all__ = ["DATASET", "LABELS", "rows"]

REPO = "gretelai/synthetic_pii_finance_multilingual"
REVISION = "7b844d16738527a04264f50214cb426a4cea0897"
LANGUAGES = {"English": "en", "German": "de"}

_E = EntityType
LABELS = LabelMap(
    types={
        "name": _E.PERSON,
        "first_name": _E.PERSON,
        "last_name": _E.PERSON,
        "company": _E.ORGANIZATION,
        "street_address": _E.ADDRESS,
        "email": _E.EMAIL,
        "phone_number": _E.PHONE,
        "date_of_birth": _E.DATE_OF_BIRTH,
        "iban": _E.BANK_ACCOUNT,
        "bban": _E.BANK_ACCOUNT,
        "credit_card_number": _E.BANK_ACCOUNT,
        "ssn": _E.ID_DOCUMENT,
        "passport_number": _E.ID_DOCUMENT,
        "driver_license_number": _E.ID_DOCUMENT,
        "date": None,
        "time": None,
        "date_time": None,
        "customer_id": None,
        "employee_id": None,
        "ipv4": None,
        "ipv6": None,
        "credit_card_security_code": None,
        "bank_routing_number": None,
        "swift_bic_code": None,
        "account_pin": None,
        "password": None,
        "api_key": None,
        "user_name": None,
        "local_latlng": None,
    },
    notes={
        "name": "first and last names next to each other are merged into one PERSON span",
        "company": "ORGANIZATION is a keep type: scored for recall, never a leak",
        "credit_card_number": "cards are BANK_ACCOUNT in pii-guard's taxonomy",
        "ssn": "national identifiers are ID_DOCUMENT",
        "date": "any date, not only birth dates: policy-excluded",
        "api_key": "secrets are out of scope for the text policy: policy-excluded",
        "customer_id": "account and customer references aren't a pii-guard type",
    },
)


def rows(paths: Sequence[Path]) -> Iterator[Row]:
    for raw in read_parquet(paths[0], ["index", "language", "generated_text", "pii_spans"]):
        language = LANGUAGES.get(str(raw["language"]))
        if language is None:
            continue
        spans = tuple(
            (int(s["start"]), int(s["end"]), str(s["label"])) for s in json.loads(raw["pii_spans"])
        )
        yield Row(str(raw["index"]), language, str(raw["generated_text"]), spans)


DATASET = Dataset(
    name="gretel-finance",
    title="Gretel synthetic PII finance (multilingual)",
    homepage=f"https://huggingface.co/datasets/{REPO}",
    revision=REVISION,
    files=(
        SourceFile(
            "data/test-00000-of-00001.parquet",
            f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/data/test-00000-of-00001.parquet",
            "014e1057978f030fce4f4cad7c93b9e3377fd0ded713d2bf4c7de00e3e3c8c72",
        ),
    ),
    license="Apache-2.0",
    license_url="https://www.apache.org/licenses/LICENSE-2.0",
    attribution="Gretel.ai, gretelai/synthetic_pii_finance_multilingual",
    languages=("en", "de"),
    source_split="test",
    split="test",
    synthetic=True,
    commit_rows=True,
    description="long synthetic financial documents (EDI, contracts, statements, e-mail)",
    sample={"en": 200, "de": 200},
    seed=2026,
    labels=LABELS,
    read=rows,
    notes=(
        "Spans were labelled during generation and validated with GLiNER (dataset card): some "
        "labels are missing or wrong, which shows up as over-masking or leaks for every system.",
    ),
)
