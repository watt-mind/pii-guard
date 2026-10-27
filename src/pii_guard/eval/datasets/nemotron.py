"""NVIDIA Nemotron-PII: persona-grounded synthetic documents in English, 55+ labels.

`nvidia/Nemotron-PII <https://huggingface.co/datasets/nvidia/Nemotron-PII>`_ (CC-BY-4.0):
synthetic documents (forms, invoices, e-mails, notes) across 50+ industries, generated with
NeMo Data Designer from synthetic personas, with span labels produced during generation. The
``test`` split is sampled here; pii-guard never trained on any of it. Rows whose span text
doesn't match the offsets (about one in eight in the test split) are skipped.

pii-guard has no type for most of the health, demographic and technical labels (medical
record numbers, blood types, occupations, cookies, MAC addresses …): they are ignore regions,
so they are neither leaks nor recall for any system. A city, state, county or postcode counts
only inside an address; on its own it is an ignore region (pii-guard keeps a town on its own).
"""

from __future__ import annotations

import ast
from collections.abc import Iterator, Sequence
from pathlib import Path

from pii_guard.eval.datasets._common import LabelMap, Row, read_parquet
from pii_guard.eval.datasets.spec import Dataset, SourceFile
from pii_guard.types import EntityType

__all__ = ["DATASET", "LABELS", "rows"]

REPO = "nvidia/Nemotron-PII"
REVISION = "b70ffaf5ff39e079776134c5bf4381f00a9fd1ed"

_E = EntityType
_EXCLUDED = (
    "date",
    "time",
    "date_time",
    "url",
    "occupation",
    "country",
    "customer_id",
    "user_name",
    "biometric_identifier",
    "medical_record_number",
    "employment_status",
    "health_plan_beneficiary_number",
    "education_level",
    "race_ethnicity",
    "employee_id",
    "language",
    "bank_routing_number",
    "coordinate",
    "gender",
    "age",
    "password",
    "pin",
    "political_view",
    "religious_belief",
    "ipv4",
    "ipv6",
    "swift_bic",
    "blood_type",
    "http_cookie",
    "cvv",
    "api_key",
    "vehicle_identifier",
    "mac_address",
    "sexuality",
    "certificate_license_number",
    "device_identifier",
    "unique_id",
)
LABELS = LabelMap(
    types={
        "first_name": _E.PERSON,
        "last_name": _E.PERSON,
        "company_name": _E.ORGANIZATION,
        "email": _E.EMAIL,
        "phone_number": _E.PHONE,
        "fax_number": _E.PHONE,
        "street_address": _E.ADDRESS,
        "city": _E.ADDRESS,
        "state": _E.ADDRESS,
        "county": _E.ADDRESS,
        "postcode": _E.ADDRESS,
        "date_of_birth": _E.DATE_OF_BIRTH,
        "account_number": _E.BANK_ACCOUNT,
        "credit_debit_card": _E.BANK_ACCOUNT,
        "ssn": _E.ID_DOCUMENT,
        "national_id": _E.ID_DOCUMENT,
        "tax_id": _E.ID_DOCUMENT,
        "license_plate": _E.VEHICLE_PLATE,
        **dict.fromkeys(_EXCLUDED),
    },
    part_only=frozenset({"city", "state", "county", "postcode"}),
    notes={
        "first_name": "merged with an adjacent last_name into one PERSON span",
        "city": "ADDRESS inside an address; on its own policy-excluded",
        "company_name": "ORGANIZATION is a keep type: scored for recall, never a leak",
        "credit_debit_card": "cards are BANK_ACCOUNT in pii-guard's taxonomy",
        "medical_record_number": "health and demographic labels have no pii-guard type",
        "date": "any date, not only birth dates: policy-excluded",
    },
)


def rows(paths: Sequence[Path]) -> Iterator[Row]:
    for raw in read_parquet(paths[0], ["uid", "text", "spans", "locale", "document_format"]):
        spans = ast.literal_eval(raw["spans"]) if isinstance(raw["spans"], str) else raw["spans"]
        yield Row(
            f"{raw['uid']}-{raw['locale']}",  # a uid appears once per locale
            "en",
            str(raw["text"]),
            tuple((int(s["start"]), int(s["end"]), str(s["label"])) for s in spans),
            meta={"locale": raw["locale"], "format": raw["document_format"]},
            values=tuple(str(s["text"]) for s in spans),
        )


DATASET = Dataset(
    name="nemotron-pii",
    title="NVIDIA Nemotron-PII",
    homepage=f"https://huggingface.co/datasets/{REPO}",
    revision=REVISION,
    files=(
        SourceFile(
            "data/test-00000-of-00001.parquet",
            f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/data/test-00000-of-00001.parquet",
            "1a4b0512ecb5370f0992d29d0f9c07351e6de13f0d7ea33bb18cecb984780247",
        ),
    ),
    license="CC-BY-4.0",
    license_url="https://creativecommons.org/licenses/by/4.0/",
    attribution="NVIDIA Corporation, nvidia/Nemotron-PII",
    languages=("en",),
    source_split="test",
    split="test",
    synthetic=True,
    commit_rows=True,
    description="synthetic structured and unstructured documents across 50+ industries (US/intl)",
    sample={"en": 300},
    seed=2026,
    labels=LABELS,
    read=rows,
    notes=(
        "English only; about half the rows use US conventions (SSNs, US phone numbers).",
        "Rows whose span text doesn't match the offsets are skipped (counted in the manifest).",
    ),
)
