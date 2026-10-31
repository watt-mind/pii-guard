"""Three newer public PII encoders as comparison NER models (LAB-1391). Evaluation only.

All four checkpoints are mmBERT (ModernBERT) token classifiers, decoded word by word
(:class:`~pii_guard.eval.baselines.encoders.WordLevelBackend`); ModernBERT is in the ``ner``
extra's ``transformers`` (``>=5.21``), so no extra environment is needed. Each is pinned to a hub
revision and the SHA-256 of its weights, and its licence is the one read from the files at that
revision (see each spec). Results: ``eval/results/2026-10-28-new-encoders/``.

- ``bardsai-v3``: ``bardsai/eu-pii-anonimization-multilang-v3`` (successor of the public
  fallback), 37 types, 24 EU languages.
- ``horizon-base`` / ``horizon-small``: ``Horizon-Labs/pii-redactor-base`` (308M) and
  ``-small`` (141M), 29 types. Trained on OpenPII-1.5M with no split stated: its ai4privacy
  numbers may be contaminated and are left out of any ranking.
- ``wismut-nym``: ``Wismut/nym-pii-multilingual``, 40 types, 22 languages, **no Hungarian**.

Download (about 4.3 GB in all, once, into the pii-guard model cache, checked against the pins)::

    uv run python -m pii_guard.eval.baselines.new_encoders download
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from pii_guard.detect import ner_resolve
from pii_guard.eval.baselines.encoders import ComparisonDetector, EncoderSpec, LabelAdapter
from pii_guard.eval.baselines.encoders import download as _download
from pii_guard.types import EntityType

__all__ = [
    "BARDSAI_V3",
    "HORIZON_BASE",
    "HORIZON_SMALL",
    "SPECS",
    "WISMUT_NYM",
    "download",
    "register",
]

_E = EntityType
_FILES = (
    "config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
)

_OPENPII_1M_TRAIN = (
    "in distribution: trained on the OpenPII-1M train split, our fixtures are its validation rows"
)
_NEMOTRON_TRAIN = "in distribution: trained on the Nemotron-PII train split (fixtures: test)"

# -- bardsai/eu-pii-anonimization-multilang-v3 --

BARDSAI_V3 = EncoderSpec(
    name="bardsai-v3",
    model=ner_resolve.PinnedModel(
        repo_id="bardsai/eu-pii-anonimization-multilang-v3",
        revision="091984b5fbce4c161abc4776ed0f4e3206e1b374",
        licence=(
            "apache-2.0 per card metadata; the repository has no LICENSE file at this revision"
        ),
        size_mb=1230,
        weights_sha256="cf02c106f39889d85638be4a3c0024628a9cf5e5a979986b54af26c485631294",
        files=_FILES,
    ),
    adapter=LabelAdapter(
        label_map={
            "PERSON_NAME": _E.PERSON,
            "PERSON_ALIAS": None,  # nicknames and handles: not a pii-guard type
            "PERSON_IDENTIFIER": _E.ID_DOCUMENT,  # as the v1 fallback (detect/ner.py LABEL_MAP)
            "PERSON_ATTRIBUTE": None,
            "PERSON_ROLE_OR_TITLE": None,
            "DATE_OF_BIRTH": _E.DATE_OF_BIRTH,
            "DATE_TIME": None,
            "EMAIL_ADDRESS": _E.EMAIL,
            "PHONE_NUMBER": _E.PHONE,
            "CONTACT_HANDLE": None,
            "POSTAL_ADDRESS": _E.ADDRESS,
            "LOCATION": _E.ADDRESS,  # only inside an address (part_only)
            "GEO_LOCATION": None,
            "IP_ADDRESS": None,
            "DEVICE_IDENTIFIER": None,
            "IDENTIFYING_LINK": None,
            "URL": None,
            "ACCOUNT_IDENTIFIER": None,  # user and customer accounts, not bank accounts
            "AUTH_SECRET": _E.SECRET,
            "BANK_ACCOUNT_IDENTIFIER": _E.BANK_ACCOUNT,
            "PAYMENT_CARD": _E.BANK_ACCOUNT,
            "PAYMENT_CARD_SECURITY": None,
            "FINANCIAL_AMOUNT": None,
            "DOCUMENT_IDENTIFIER": _E.ID_DOCUMENT,
            "DOCUMENT_REFERENCE": None,
            "VEHICLE_IDENTIFIER": None,  # plates are a rules type
            "ORGANIZATION_NAME": _E.ORGANIZATION,
            "ORGANIZATION_IDENTIFIER": None,  # company and VAT numbers: COMPANY_ID_HU is rules
            "PROPER_NAME": None,
            # GDPR Art. 9 special categories: pii-guard's taxonomy has no type for them.
            "HEALTH_DATA": None,
            "BIOMETRIC_DATA": None,
            "ETHNIC_ORIGIN": None,
            "POLITICAL_OPINION": None,
            "RELIGION_OR_BELIEF": None,
            "SEXUAL_ORIENTATION": None,
            "TRADE_UNION_MEMBERSHIP": None,
            "CRIMINAL_OFFENCE_DATA": None,
        },
        part_only=frozenset({"LOCATION"}),
    ),
    decoder="word",
    summary="mmBERT base (ModernBERT), 307M, 37 types, 24 EU languages",
    contamination={
        "ai4privacy": _OPENPII_1M_TRAIN,
        "nemotron-pii": _NEMOTRON_TRAIN,
    },
)

# -- Horizon-Labs/pii-redactor-base and -small (same label set) --

_HORIZON_ADAPTER = LabelAdapter(
    label_map={
        "PERSON": _E.PERSON,
        "ORGANIZATION": _E.ORGANIZATION,
        "EMAIL": _E.EMAIL,
        "PHONE": _E.PHONE,
        "STREET_ADDRESS": _E.ADDRESS,
        "POSTCODE": _E.ADDRESS,
        "LOCATION": _E.ADDRESS,  # only inside an address (part_only)
        "DATE_OF_BIRTH": _E.DATE_OF_BIRTH,
        "BANK_ACCOUNT": _E.BANK_ACCOUNT,
        "CREDIT_CARD": _E.BANK_ACCOUNT,
        "NATIONAL_ID": _E.ID_DOCUMENT,
        "PASSPORT": _E.ID_DOCUMENT,
        "DRIVER_LICENSE": _E.ID_DOCUMENT,
        "TAX_ID": _E.ID_DOCUMENT,
        "MEDICAL_ID": _E.ID_DOCUMENT,
        "PASSWORD": _E.SECRET,
        "SECRET": _E.SECRET,
        # No pii-guard type.
        "ACCOUNT_ID": None,
        "AGE": None,
        "COORDINATE": None,
        "CREDIT_CARD_CVV": None,
        "DATE": None,
        "DEVICE_ID": None,
        "IP_ADDRESS": None,
        "LICENSE_NUMBER": None,  # professional licences: policy-excluded in the gold
        "MAC_ADDRESS": None,
        "URL": None,
        "USERNAME": None,
        "VEHICLE_ID": None,
    },
    language_label_map={
        "hu": {"TAX_ID": _E.NATIONAL_ID_HU_TAX, "MEDICAL_ID": _E.NATIONAL_ID_HU_TAJ},
    },
    part_only=frozenset({"LOCATION"}),
)
_HORIZON_LICENCE = (
    "Apache-2.0: card metadata, LICENSE (Apache 2.0 text) and NOTICE (mmBERT, MIT) agree"
)
_HORIZON_CONTAMINATION = {
    "ai4privacy": (
        "possibly contaminated: trained on OpenPII-1.5M (a 256k sample), split not stated; "
        "our fixtures are OpenPII-1M validation rows. Excluded from any ranking"
    ),
    "nemotron-pii": (
        "in distribution: trained on Nemotron-PII (card reports its test set as held out)"
    ),
}

HORIZON_BASE = EncoderSpec(
    name="horizon-base",
    model=ner_resolve.PinnedModel(
        repo_id="Horizon-Labs/pii-redactor-base",
        revision="42dfb0dccb0864c889c99300265567ace9fa6e6d",
        licence=_HORIZON_LICENCE,
        size_mb=1230,
        weights_sha256="29d33d68c288407c02098758dbfea87750663782bbd8b2e1ff5aa40a15a5cb46",
        files=_FILES,
    ),
    adapter=_HORIZON_ADAPTER,
    decoder="word",
    summary="mmBERT base (ModernBERT), 308M, 29 types, v1.0",
    contamination=_HORIZON_CONTAMINATION,
)

HORIZON_SMALL = EncoderSpec(
    name="horizon-small",
    model=ner_resolve.PinnedModel(
        repo_id="Horizon-Labs/pii-redactor-small",
        revision="3f6a99b9906378f3faed3e6eeb3b396b0b8257c2",
        licence=_HORIZON_LICENCE,
        size_mb=563,
        weights_sha256="026ba83dfd0a7f656d92451fd19d3ce5dcc2c0b27f21fb72c23e4c3f6b37766e",
        files=_FILES,
    ),
    adapter=_HORIZON_ADAPTER,
    decoder="word",
    summary="mmBERT small (ModernBERT), 141M, 29 types, v1.1",
    contamination=_HORIZON_CONTAMINATION,
)

# -- Wismut/nym-pii-multilingual --

WISMUT_NYM = EncoderSpec(
    name="wismut-nym",
    model=ner_resolve.PinnedModel(
        repo_id="Wismut/nym-pii-multilingual",
        revision="0ed0242d67a30ca6a83e5f118506ff1e1daf83ca",
        licence=(
            "MIT per card metadata and card text; the repository has no LICENSE file at this "
            "revision; part of its training labels come from an LLM teacher on CC-BY-SA text"
        ),
        size_mb=1230,
        weights_sha256="a98a7ec3d7b45eaeab52acfa2c520d35a89698b1d3e1ea5635830b34bd21fa55",
        files=_FILES,
    ),
    adapter=LabelAdapter(
        label_map={
            "GIVEN_NAME": _E.PERSON,
            "SURNAME": _E.PERSON,
            "COMPANY_NAME": _E.ORGANIZATION,
            "EMAIL": _E.EMAIL,
            "PHONE": _E.PHONE,
            "FAX_NUMBER": _E.PHONE,
            "STREET_ADDRESS": _E.ADDRESS,
            "STREET_NAME": _E.ADDRESS,
            "BUILDING_NUMBER": _E.ADDRESS,
            "SECONDARY_ADDRESS": _E.ADDRESS,
            "ZIP_CODE": _E.ADDRESS,
            "CITY": _E.ADDRESS,  # only inside an address (part_only), as below
            "STATE": _E.ADDRESS,
            "COUNTRY": _E.ADDRESS,
            "DATE_OF_BIRTH": _E.DATE_OF_BIRTH,
            "IBAN": _E.BANK_ACCOUNT,
            "ACCOUNT_NUMBER": _E.BANK_ACCOUNT,
            "CREDIT_DEBIT_CARD": _E.BANK_ACCOUNT,
            "GOVERNMENT_ID": _E.ID_DOCUMENT,
            "SSN": _E.ID_DOCUMENT,
            "PASSPORT": _E.ID_DOCUMENT,
            "DRIVERS_LICENSE": _E.ID_DOCUMENT,
            "TAX_ID": _E.ID_DOCUMENT,
            "API_KEY": _E.SECRET,
            "PASSWORD": _E.SECRET,
            # No pii-guard type.
            "AGE": None,
            "CUSTOMER_ID": None,
            "CVV": None,
            "DATE": None,
            "EMPLOYEE_ID": None,
            "GENDER": None,
            "LICENSE_PLATE": None,
            "MAC_ADDRESS": None,
            "MEDICAL_RECORD_NUMBER": None,
            "PIN": None,
            "ROUTING_NUMBER": None,
            "SWIFT_BIC": None,
            "TIME": None,
            "URL": None,
            "USERNAME": None,
        },
        language_label_map={"hu": {"TAX_ID": _E.NATIONAL_ID_HU_TAX}},
        part_only=frozenset({"CITY", "STATE", "COUNTRY"}),
    ),
    decoder="word",
    summary="mmBERT base (ModernBERT), 308M, 40 types, 22 languages (no Hungarian)",
    languages=("en", "de"),
    contamination={
        "ai4privacy": "clean per card (ai4privacy reported as out of distribution)",
    },
)

SPECS: dict[str, EncoderSpec] = {
    s.name: s for s in (BARDSAI_V3, HORIZON_BASE, HORIZON_SMALL, WISMUT_NYM)
}


class BardsaiV3Detector(ComparisonDetector):
    spec = BARDSAI_V3


class HorizonBaseDetector(ComparisonDetector):
    spec = HORIZON_BASE


class HorizonSmallDetector(ComparisonDetector):
    spec = HORIZON_SMALL


class WismutNymDetector(ComparisonDetector):
    spec = WISMUT_NYM


DETECTORS: dict[str, type[ComparisonDetector]] = {
    d.spec.name: d
    for d in (BardsaiV3Detector, HorizonBaseDetector, HorizonSmallDetector, WismutNymDetector)
}


def download(name: str) -> str:
    """The verified local directory of one model, fetched first if it isn't cached."""
    return _download(SPECS[name])


def register() -> None:
    """Make the four names resolvable in the detector registry (evaluation only)."""
    from pii_guard.registry import register_detector

    for name, cls in DETECTORS.items():
        register_detector(name, f"{__name__}:{cls.__name__}", replace=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    dl = sub.add_parser("download", help="fetch and verify the pinned checkpoints")
    dl.add_argument("names", nargs="*", default=list(SPECS))
    args = parser.parse_args(argv)
    if args.command == "download":
        for name in args.names or SPECS:
            print(download(name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
