"""The tabularisai/eu-pii-safeguard label adapter (LAB-1386). No model is loaded."""

from __future__ import annotations

from pii_guard.detect.ner import RawEntity
from pii_guard.eval.baselines import eu_pii_safeguard as eu
from pii_guard.registry import resolve_detector
from pii_guard.types import EntityType

#: The checkpoint's 42 labels (config.json id2label at the pinned revision, without B-/I-).
MODEL_LABELS = {
    "ACCOUNT_NUMBER", "ADDRESS", "AGE", "AMOUNT", "BUILDING_NUMBER", "CITY", "COMPANY_NAME",
    "COUNTRY", "CREDIT_CARD_NUMBER", "CURRENCY", "DEVICE_ID", "DOB", "DRIVER_LICENSE", "EMAIL",
    "ETHNICITY", "FIRSTNAME", "GENDER", "HEALTH_CONDITION", "HEALTH_INSURANCE_ID", "IBAN",
    "IP_ADDRESS", "JOB_TITLE", "LASTNAME", "LATITUDE", "LONGITUDE", "MAC_ADDRESS", "MIDDLENAME",
    "NATIONAL_ID", "PASSPORT_NUMBER", "PASSWORD", "PHONE_NUMBER", "POLITICAL_OPINION",
    "POSTAL_CODE", "PREFIX", "RELIGION", "SALARY", "SEXUAL_ORIENTATION", "STATE", "STREET",
    "TAX_ID", "URL", "USERNAME",
}  # fmt: skip


def _raw(text: str, *parts: tuple[str, str]) -> list[RawEntity]:
    out, pos = [], 0
    for label, value in parts:
        start = text.index(value, pos)
        out.append(RawEntity(label, start, start + len(value), 0.9))
        pos = start + len(value)
    return out


def test_every_model_label_has_an_explicit_decision() -> None:
    assert set(eu.LABEL_MAP) == MODEL_LABELS
    assert len(MODEL_LABELS) == 42


def test_name_parts_merge_into_one_person() -> None:
    text = "Dear Mr. Anna Maria Példa, hello"
    raw = _raw(text, ("PREFIX", "Mr."), ("FIRSTNAME", "Anna"), ("MIDDLENAME", "Maria"),
               ("LASTNAME", "Példa"))  # fmt: skip
    out, dropped = eu.adapt(text, raw, "en")
    assert [(e.label, text[e.start : e.end]) for e in out] == [("PERSON", "Anna Maria Példa")]
    assert dropped == {"PREFIX": 1}


def test_address_parts_merge_and_a_lone_city_is_dropped() -> None:
    text = "Fiktív utca 12, 1011 Példaváros. Later in Példaváros again."
    raw = _raw(text, ("STREET", "Fiktív utca"), ("BUILDING_NUMBER", "12"),
               ("POSTAL_CODE", "1011"), ("CITY", "Példaváros"), ("CITY", "Példaváros"))  # fmt: skip
    out, dropped = eu.adapt(text, raw, "hu")
    assert [(e.label, text[e.start : e.end]) for e in out] == [
        ("ADDRESS", "Fiktív utca 12, 1011 Példaváros")
    ]
    assert dropped == {"ADDRESS_PART_ALONE": 1}


def test_parts_of_different_types_or_far_apart_do_not_merge() -> None:
    text = "Anna and Példa; Anna Példa Kft."
    raw = _raw(text, ("FIRSTNAME", "Anna"), ("LASTNAME", "Példa"), ("FIRSTNAME", "Anna"),
               ("COMPANY_NAME", "Példa Kft."))  # fmt: skip
    out, _ = eu.adapt(text, raw, "hu")
    assert [e.label for e in out] == ["PERSON", "PERSON", "PERSON", "ORGANIZATION"]


def test_hungarian_tax_and_taj_numbers_get_their_own_types() -> None:
    text = "x 8000000000 y 000000000"
    raw = _raw(text, ("TAX_ID", "8000000000"), ("HEALTH_INSURANCE_ID", "000000000"))
    hu, _ = eu.adapt(text, raw, "hu")
    en, _ = eu.adapt(text, raw, "en")
    assert [e.label for e in hu] == ["NATIONAL_ID_HU_TAX", "NATIONAL_ID_HU_TAJ"]
    assert [e.label for e in en] == ["ID_DOCUMENT", "ID_DOCUMENT"]


def test_unmapped_labels_are_counted_not_returned() -> None:
    text = "age 42, nurse, 3000 EUR"
    raw = _raw(text, ("AGE", "42"), ("JOB_TITLE", "nurse"), ("SALARY", "3000 EUR"))
    out, dropped = eu.adapt(text, raw, "en")
    assert out == []
    assert dropped == {"AGE": 1, "JOB_TITLE": 1, "SALARY": 1}


class _Backend:
    def __init__(self, raw: list[RawEntity]) -> None:
        self.raw = raw

    def predict(self, text: str) -> list[RawEntity]:
        return list(self.raw)


def test_detector_runs_the_adapter_through_the_ner_post_processing() -> None:
    text = "Write to Anna Példa, she is 42."
    detector = eu.EuPiiSafeguardDetector(
        backend=_Backend(_raw(text, ("FIRSTNAME", "Anna"), ("LASTNAME", "Példa,"), ("AGE", "42")))
    )
    spans = detector.detect(text, "en")
    assert [(s.entity_type, s.text, s.detector) for s in spans] == [
        (EntityType.PERSON, "Anna Példa", "ner")
    ]
    assert detector.unmapped == {"AGE": 1}


def test_register_makes_the_name_resolvable() -> None:
    eu.register()
    assert resolve_detector(eu.DETECTOR_NAME) is eu.EuPiiSafeguardDetector


def test_the_model_is_pinned() -> None:
    assert len(eu.MODEL.revision) == 40
    assert len(eu.MODEL.weights_sha256) == 64
    assert eu.MODEL.licence == "Apache-2.0"
