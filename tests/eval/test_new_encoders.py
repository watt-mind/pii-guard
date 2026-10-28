"""The LAB-1391 comparison encoders: label adapters and the word decoder. No model is loaded."""

from __future__ import annotations

import pytest

from pii_guard.detect.ner import RawEntity
from pii_guard.eval.baselines import encoders
from pii_guard.eval.baselines import new_encoders as ne
from pii_guard.registry import resolve_detector
from pii_guard.types import EntityType

#: Each checkpoint's types (config.json id2label at the pinned revision, without B-/I-).
MODEL_LABELS = {
    "bardsai-v3": {
        "ACCOUNT_IDENTIFIER", "AUTH_SECRET", "BANK_ACCOUNT_IDENTIFIER", "BIOMETRIC_DATA",
        "CONTACT_HANDLE", "CRIMINAL_OFFENCE_DATA", "DATE_OF_BIRTH", "DATE_TIME",
        "DEVICE_IDENTIFIER", "DOCUMENT_IDENTIFIER", "DOCUMENT_REFERENCE", "EMAIL_ADDRESS",
        "ETHNIC_ORIGIN", "FINANCIAL_AMOUNT", "GEO_LOCATION", "HEALTH_DATA", "IDENTIFYING_LINK",
        "IP_ADDRESS", "LOCATION", "ORGANIZATION_IDENTIFIER", "ORGANIZATION_NAME", "PAYMENT_CARD",
        "PAYMENT_CARD_SECURITY", "PERSON_ALIAS", "PERSON_ATTRIBUTE", "PERSON_IDENTIFIER",
        "PERSON_NAME", "PERSON_ROLE_OR_TITLE", "PHONE_NUMBER", "POLITICAL_OPINION",
        "POSTAL_ADDRESS", "PROPER_NAME", "RELIGION_OR_BELIEF", "SEXUAL_ORIENTATION",
        "TRADE_UNION_MEMBERSHIP", "URL", "VEHICLE_IDENTIFIER",
    },
    "horizon": {
        "ACCOUNT_ID", "AGE", "BANK_ACCOUNT", "COORDINATE", "CREDIT_CARD", "CREDIT_CARD_CVV",
        "DATE", "DATE_OF_BIRTH", "DEVICE_ID", "DRIVER_LICENSE", "EMAIL", "IP_ADDRESS",
        "LICENSE_NUMBER", "LOCATION", "MAC_ADDRESS", "MEDICAL_ID", "NATIONAL_ID", "ORGANIZATION",
        "PASSPORT", "PASSWORD", "PERSON", "PHONE", "POSTCODE", "SECRET", "STREET_ADDRESS",
        "TAX_ID", "URL", "USERNAME", "VEHICLE_ID",
    },
    "wismut-nym": {
        "ACCOUNT_NUMBER", "AGE", "API_KEY", "BUILDING_NUMBER", "CITY", "COMPANY_NAME", "COUNTRY",
        "CREDIT_DEBIT_CARD", "CUSTOMER_ID", "CVV", "DATE", "DATE_OF_BIRTH", "DRIVERS_LICENSE",
        "EMAIL", "EMPLOYEE_ID", "FAX_NUMBER", "GENDER", "GIVEN_NAME", "GOVERNMENT_ID", "IBAN",
        "LICENSE_PLATE", "MAC_ADDRESS", "MEDICAL_RECORD_NUMBER", "PASSPORT", "PASSWORD", "PHONE",
        "PIN", "ROUTING_NUMBER", "SECONDARY_ADDRESS", "SSN", "STATE", "STREET_ADDRESS",
        "STREET_NAME", "SURNAME", "SWIFT_BIC", "TAX_ID", "TIME", "URL", "USERNAME", "ZIP_CODE",
    },
}  # fmt: skip


def _raw(text: str, *parts: tuple[str, str]) -> list[RawEntity]:
    out, pos = [], 0
    for label, value in parts:
        start = text.index(value, pos)
        out.append(RawEntity(label, start, start + len(value), 0.9))
        pos = start + len(value)
    return out


@pytest.mark.parametrize(
    ("spec", "labels"),
    [
        (ne.BARDSAI_V3, "bardsai-v3"),
        (ne.HORIZON_BASE, "horizon"),
        (ne.HORIZON_SMALL, "horizon"),
        (ne.WISMUT_NYM, "wismut-nym"),
    ],
)
def test_every_model_label_has_an_explicit_decision(spec, labels) -> None:
    assert set(spec.adapter.label_map) == MODEL_LABELS[labels]
    assert spec.adapter.part_only <= set(spec.adapter.label_map)
    assert spec.decoder == "word"


def test_every_model_is_pinned_and_its_licence_recorded() -> None:
    for spec in ne.SPECS.values():
        assert len(spec.model.revision) == 40
        assert len(spec.model.weights_sha256) == 64
        assert spec.model.licence
    assert "no LICENSE file" in ne.BARDSAI_V3.model.licence
    assert "no LICENSE file" in ne.WISMUT_NYM.model.licence
    assert "hu" not in ne.WISMUT_NYM.languages  # no Hungarian in its card
    assert "contaminated" in ne.HORIZON_BASE.contamination["ai4privacy"]


def test_wismut_name_parts_merge_and_a_lone_city_is_dropped() -> None:
    text = "Anna Schmidt, Musterstraße 5, 10115 Berlin. Later Berlin again."
    raw = _raw(text, ("GIVEN_NAME", "Anna"), ("SURNAME", "Schmidt"),
               ("STREET_NAME", "Musterstraße"), ("BUILDING_NUMBER", "5"),
               ("ZIP_CODE", "10115"), ("CITY", "Berlin"), ("CITY", "Berlin"))  # fmt: skip
    out, dropped = ne.WISMUT_NYM.adapter.adapt(text, raw, "de")
    assert [(e.label, text[e.start : e.end]) for e in out] == [
        ("PERSON", "Anna Schmidt"),
        ("ADDRESS", "Musterstraße 5, 10115 Berlin"),
    ]
    assert dropped == {"ADDRESS_PART_ALONE": 1}


def test_horizon_hungarian_tax_and_taj_numbers_get_their_own_types() -> None:
    text = "x 8000000000 y 000000000"
    raw = _raw(text, ("TAX_ID", "8000000000"), ("MEDICAL_ID", "000000000"))
    hu, _ = ne.HORIZON_BASE.adapter.adapt(text, raw, "hu")
    en, _ = ne.HORIZON_BASE.adapter.adapt(text, raw, "en")
    assert [e.label for e in hu] == ["NATIONAL_ID_HU_TAX", "NATIONAL_ID_HU_TAJ"]
    assert [e.label for e in en] == ["ID_DOCUMENT", "ID_DOCUMENT"]


def test_unmapped_labels_are_counted_not_returned() -> None:
    text = "see https://example.org on 2026-10-28 at 10.0.0.1"
    raw = _raw(text, ("URL", "https://example.org"), ("DATE_TIME", "2026-10-28"),
               ("IP_ADDRESS", "10.0.0.1"))  # fmt: skip
    out, dropped = ne.BARDSAI_V3.adapter.adapt(text, raw, "en")
    assert out == []
    assert dropped == {"URL": 1, "DATE_TIME": 1, "IP_ADDRESS": 1}


# -- the word decoder --

_TYPES = ["PERSON", "PHONE"]
_O = [0.0, 0.0, 1.0]
_PER = [0.9, 0.0, 0.1]
_PHONE = [0.0, 0.8, 0.2]


def test_word_spans_trim_edge_punctuation() -> None:
    text = "(«Anna»), call: +36 30."
    assert [text[s:e] for s, e in encoders.word_spans(text)] == ["Anna", "call", "+36", "30"]


def test_decode_words_averages_sub_tokens_and_merges_words() -> None:
    text = "Kovács Pétert hívd: +36 30 123"
    # Anchors: the first non-space character of each token (K, ovács, Pé, tert, hí, vd, +, 3, 0…).
    tokens = [
        (0, _PER, 0.9), (1, [0.4, 0.0, 0.6], 0.0),  # "Kovács": mean favours PERSON
        (7, _PER, 0.1), (9, _PER, 0.0),  # "Pétert": continues the name
        (14, _O, 0.0), (16, _O, 0.0), (18, _O, 0.0),  # "hívd:"
        (20, _PHONE, 0.9), (24, _PHONE, 0.1), (27, _PHONE, 0.2),  # "+36 30 123"
    ]  # fmt: skip
    out = encoders.decode_words(
        text, [a for a, _, _ in tokens], [p for _, p, _ in tokens], [b for *_, b in tokens], _TYPES
    )
    assert [(e.label, text[e.start : e.end]) for e in out] == [
        ("PERSON", "Kovács Pétert"),
        ("PHONE", "+36 30 123"),
    ]
    assert out[0].score == pytest.approx((0.65 + 0.9) / 2)


def test_decode_words_starts_a_new_entity_on_a_begin_token() -> None:
    text = "Anna, Béla"
    out = encoders.decode_words(text, [0, 6], [_PER, _PER], [0.9, 0.8], _TYPES)
    assert [text[e.start : e.end] for e in out] == ["Anna", "Béla"]


def test_decode_words_does_not_merge_across_a_blank_line() -> None:
    text = "Anna\n\nBéla"
    out = encoders.decode_words(text, [0, 6], [_PER, _PER], [0.9, 0.1], _TYPES)
    assert len(out) == 2


def test_decode_words_rejects_mismatched_inputs() -> None:
    with pytest.raises(ValueError):
        encoders.decode_words("a", [0], [], [0.0], _TYPES)


# -- the detector --


class _Backend:
    def __init__(self, raw: list[RawEntity]) -> None:
        self.raw = raw

    def predict(self, text: str) -> list[RawEntity]:
        return list(self.raw)


#: A fictional, low-entropy key shape (built at run time, so no scanner takes it for a secret).
_FAKE_KEY = "sk-" + "proj-" + "x" * 24


def test_detector_runs_the_adapter_through_the_ner_post_processing() -> None:
    text = f"Write to Anna Schmidt, token {_FAKE_KEY}, age 42."
    detector = ne.WismutNymDetector(
        backend=_Backend(_raw(text, ("GIVEN_NAME", "Anna"), ("SURNAME", "Schmidt"),
                              ("API_KEY", _FAKE_KEY), ("AGE", "42")))
    )  # fmt: skip
    spans = detector.detect(text, "en")
    assert [(s.entity_type, s.text, s.detector) for s in spans] == [
        (EntityType.PERSON, "Anna Schmidt", "ner"),
        (EntityType.SECRET, _FAKE_KEY, "ner"),
    ]
    assert detector.unmapped == {"AGE": 1}


def test_register_makes_the_names_resolvable() -> None:
    ne.register()
    for name, cls in ne.DETECTORS.items():
        assert resolve_detector(name) is cls
