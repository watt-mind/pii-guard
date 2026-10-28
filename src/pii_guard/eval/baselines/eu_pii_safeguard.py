"""``tabularisai/eu-pii-safeguard`` as a comparison NER model (LAB-1386). Evaluation only.

An open XLM-RoBERTa **large** token classifier (about 560M parameters, Apache-2.0) for 26 EU
languages with 42 BIO entity labels: the closest open alternative to pii-guard's own NER
(``hdkiller/pii-guard-ner-xlmr-base``, XLM-R base). It is never in the product's default path:
nothing outside the evaluation imports this module, and the gateway's fast mode keeps resolving
its NER model through :mod:`pii_guard.detect.ner_resolve`.

:class:`EuPiiSafeguardDetector` is pii-guard's own :class:`~pii_guard.detect.ner.NerDetector`
with the pinned checkpoint and a label adapter, so the model runs through exactly the same
post-processing as ours (thresholds, word and token snapping, number checks, the resolver, the
vault). That gives two configurations scored like pii-guard's own NER, placeholder consistency
included:

- the model alone (``--detectors eu-pii-safeguard``), next to ours alone (``ner``);
- rules + this model in place of ours (``rules,eu-pii-safeguard``), next to fast mode.

The label adapter (:func:`adapt`, documented in ``docs/evaluation.md``):

- labels map to pii-guard types by :data:`LABEL_MAP`; ``TAX_ID`` and ``HEALTH_INSURANCE_ID``
  become the Hungarian tax and TAJ types on Hungarian text (as the Ai4Privacy conversion does);
- the model tags name and address *parts* (``FIRSTNAME`` + ``LASTNAME``, ``STREET`` +
  ``BUILDING_NUMBER`` + ``POSTAL_CODE`` + ``CITY``); neighbouring parts of one type separated
  only by up to three spaces, tabs or commas are merged into one span, the rule the gold
  conversions use, so one name is one placeholder;
- a ``CITY``, ``STATE`` or ``COUNTRY`` on its own is not an address under pii-guard's policy
  (the datasets mark it as an ignore region), so it is kept only when merged into an address;
- labels with no pii-guard type (``AGE``, ``GENDER``, ``JOB_TITLE``, ``AMOUNT``, …, the GDPR
  Art. 9 categories, network identifiers) are dropped before scoring and counted in
  :attr:`EuPiiSafeguardDetector.unmapped`. Gold never has them, so masking them could only be
  scored as over-masking and dropping them can't be scored as a leak: neither way is unfair.

Download (about 2.2 GB, once, into the pii-guard model cache, checked against the pin)::

    uv run --extra ner python -m pii_guard.eval.baselines.eu_pii_safeguard download
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from collections.abc import Sequence
from typing import Any

from pii_guard.detect import ner_resolve
from pii_guard.detect.ner import NER_ENTITY_TYPES, NerDetector, RawEntity
from pii_guard.types import EntityType, Span

__all__ = [
    "DETECTOR_NAME",
    "LABEL_MAP",
    "MODEL",
    "PART_ONLY",
    "EuPiiSafeguardDetector",
    "adapt",
    "download",
    "register",
]

#: The registry name the evaluation uses (``--detectors rules,eu-pii-safeguard``).
DETECTOR_NAME = "eu-pii-safeguard"

#: The checkpoint, pinned to a hub revision and the SHA-256 of its weights.
MODEL = ner_resolve.PinnedModel(
    repo_id="tabularisai/eu-pii-safeguard",
    revision="c928cd51d4f28723289098a4ad59955413afcc05",
    licence="Apache-2.0",
    size_mb=2240,
    weights_sha256="206f8317e5df76b74d66853eea34ccae4313b06822f1c7135e390243b1770e33",
    files=(
        "config.json",
        "model.safetensors",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
    ),
)

_E = EntityType

#: Model label (without ``B-`` / ``I-``) -> pii-guard type; ``None``: no pii-guard type,
#: dropped before scoring (see the module docstring). All 42 labels are listed.
LABEL_MAP: dict[str, EntityType | None] = {
    # Names: parts merged into one PERSON span.
    "FIRSTNAME": _E.PERSON,
    "MIDDLENAME": _E.PERSON,
    "LASTNAME": _E.PERSON,
    "PREFIX": None,  # Mr, Dr: honorifics are not part of a PERSON span in pii-guard's gold
    # Contact details
    "EMAIL": _E.EMAIL,
    "PHONE_NUMBER": _E.PHONE,
    # Address parts, merged into one ADDRESS span.
    "ADDRESS": _E.ADDRESS,
    "STREET": _E.ADDRESS,
    "BUILDING_NUMBER": _E.ADDRESS,
    "POSTAL_CODE": _E.ADDRESS,
    "CITY": _E.ADDRESS,  # only inside an address (PART_ONLY)
    "STATE": _E.ADDRESS,  # as CITY
    "COUNTRY": _E.ADDRESS,  # as CITY
    "DOB": _E.DATE_OF_BIRTH,
    # Money: cards are BANK_ACCOUNT in pii-guard's taxonomy (docs/entities.md).
    "IBAN": _E.BANK_ACCOUNT,
    "ACCOUNT_NUMBER": _E.BANK_ACCOUNT,
    "CREDIT_CARD_NUMBER": _E.BANK_ACCOUNT,
    # Identifiers: national numbers without a type of their own are ID_DOCUMENT; the
    # Hungarian tax and TAJ (health insurance) numbers have their own types on hu text.
    "TAX_ID": _E.ID_DOCUMENT,
    "HEALTH_INSURANCE_ID": _E.ID_DOCUMENT,
    "NATIONAL_ID": _E.ID_DOCUMENT,
    "PASSPORT_NUMBER": _E.ID_DOCUMENT,
    "DRIVER_LICENSE": _E.ID_DOCUMENT,
    "COMPANY_NAME": _E.ORGANIZATION,
    "PASSWORD": _E.SECRET,
    # No pii-guard type.
    "USERNAME": None,
    "URL": None,
    "IP_ADDRESS": None,
    "MAC_ADDRESS": None,
    "DEVICE_ID": None,
    "LATITUDE": None,
    "LONGITUDE": None,
    "AGE": None,
    "GENDER": None,
    "JOB_TITLE": None,
    "AMOUNT": None,
    "CURRENCY": None,
    "SALARY": None,
    # GDPR Art. 9 special categories: pii-guard's taxonomy has no type for them.
    "ETHNICITY": None,
    "RELIGION": None,
    "POLITICAL_OPINION": None,
    "SEXUAL_ORIENTATION": None,
    "HEALTH_CONDITION": None,
}

#: Per-language overrides (the Ai4Privacy conversion's rule for TAXNUM / SOCIALNUM).
LANGUAGE_LABEL_MAP: dict[str, dict[str, EntityType]] = {
    "hu": {"TAX_ID": _E.NATIONAL_ID_HU_TAX, "HEALTH_INSURANCE_ID": _E.NATIONAL_ID_HU_TAJ},
}

#: Labels that are an address only next to another address part.
PART_ONLY: frozenset[str] = frozenset({"CITY", "STATE", "COUNTRY"})

#: What may separate two parts of one name or address: the gold conversions' merge gap.
_MERGE_GAP_RE = re.compile(r"[ \t,]{0,3}")
#: Types whose parts are merged (identifiers and contact details are one token run anyway).
_MERGED_TYPES = frozenset({_E.PERSON, _E.ADDRESS})


def _type_of(label: str, language: str) -> EntityType | None:
    override = LANGUAGE_LABEL_MAP.get(language, {}).get(label)
    return override if override is not None else LABEL_MAP.get(label)


def adapt(
    text: str, raw: Sequence[RawEntity], language: str
) -> tuple[list[RawEntity], Counter[str]]:
    """The model's raw entities as pii-guard-typed ones, plus the count of dropped labels.

    Returns entities labelled with :class:`EntityType` values (``"PERSON"``), ready for
    :meth:`NerDetector.to_spans`. See the module docstring for the rules.
    """
    dropped: Counter[str] = Counter()
    typed: list[tuple[RawEntity, EntityType, bool]] = []  # (entity, type, part-only)
    for e in sorted(raw, key=lambda e: (e.start, e.end)):
        label = e.label.upper()
        entity_type = _type_of(label, language)
        if entity_type is None:
            dropped[label] += 1
            continue
        typed.append((e, entity_type, label in PART_ONLY))
    merged: list[tuple[int, int, EntityType, float, bool]] = []  # start, end, type, score, part
    for e, entity_type, part_only in typed:
        if merged:
            start, end, last_type, score, last_part = merged[-1]
            if (
                last_type is entity_type
                and entity_type in _MERGED_TYPES
                and e.start >= end
                and _MERGE_GAP_RE.fullmatch(text, end, e.start)
            ):
                merged[-1] = (
                    start,
                    e.end,
                    entity_type,
                    max(score, e.score),
                    last_part and part_only,
                )
                continue
        merged.append((e.start, e.end, entity_type, e.score, part_only))
    out: list[RawEntity] = []
    for start, end, entity_type, score, part_only in merged:
        if part_only:  # a city, state or country on its own: not an address (policy)
            dropped["ADDRESS_PART_ALONE"] += 1
            continue
        out.append(RawEntity(entity_type.value, start, end, score))
    return out, dropped


class EuPiiSafeguardDetector(NerDetector):
    """pii-guard's NER detector running ``tabularisai/eu-pii-safeguard`` through :func:`adapt`.

    ``name`` stays ``ner``: it takes the NER detector's place in the pipeline, and its spans
    are resolved exactly like ours. The pinned checkpoint is fetched into the model cache on
    first use (about 2.2 GB) and verified. ``unmapped`` counts the labels dropped so far.
    """

    def __init__(
        self,
        *,
        device: str | None = None,
        preload: bool = True,
        backend: Any = None,
        **kwargs: Any,
    ) -> None:
        # Always the verified copy in the model cache, never a hub id (no unpinned load).
        model = MODEL.repo_id if backend is not None else download()
        super().__init__(model=model, device=device, backend=backend, preload=False, **kwargs)
        self.revision = None  # a local directory, already at the pinned revision
        self.entity_types = NER_ENTITY_TYPES | {_E.SECRET}
        self.label_map = {t.value: t for t in EntityType}
        self.unmapped: Counter[str] = Counter()
        if preload:
            self.load()

    def __repr__(self) -> str:
        return f"EuPiiSafeguardDetector(revision={MODEL.revision[:12]!r})"

    def to_spans(self, text: str, raw: Sequence[RawEntity], language: str = "hu") -> list[Span]:
        adapted, dropped = adapt(text, raw, language)
        self.unmapped.update(dropped)
        return super().to_spans(text, adapted, language)


def download() -> str:
    """The verified local directory of :data:`MODEL`, fetched first if it isn't cached."""
    choice = ner_resolve.NerChoice(
        source="configured",
        model=MODEL.repo_id,
        revision=MODEL.revision,
        pinned=MODEL,
        ready=False,  # let ensure() check the cache marker (weights SHA-256) or download
        may_download=True,
    )
    return ner_resolve.ensure(choice)


def register() -> None:
    """Make ``eu-pii-safeguard`` resolvable in the detector registry (evaluation only)."""
    from pii_guard.registry import register_detector

    register_detector(DETECTOR_NAME, f"{__name__}:EuPiiSafeguardDetector", replace=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("download", help="fetch and verify the pinned checkpoint")
    args = parser.parse_args(argv)
    if args.command == "download":
        print(download())
    return 0


if __name__ == "__main__":
    sys.exit(main())
