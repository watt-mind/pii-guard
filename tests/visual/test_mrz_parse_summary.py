"""MRZ field parsing and the image document summary (LAB-1156).

The zones are the fictional Utopia (``UTO``) specimens of ``eval/fixtures/visual/generation.json``.
"""

from __future__ import annotations

import datetime as dt

import pytest

from pii_guard.types import EntityType
from pii_guard.visual.captions import CaptionValue
from pii_guard.visual.mrz import check_digit, parse_mrz
from pii_guard.visual.ocr import OcrWord
from pii_guard.visual.regions import Box
from pii_guard.visual.summary import SummaryField, build_summary, document_type, field_name

TD1 = (
    "I<UTO664444HM<325901027499<<<<",
    "5901021F3106305UTO<<<<<<<<<<<2",
    "FIKTIV<<MARIA<<<<<<<<<<<<<<<<<",
)
TD3 = (
    "P<UTOPELDA<<GABOR<<<<<<<<<<<<<<<<<<<<<<<<<<<",
    "KK74063024UTO8504168M310630518504163255<<<26",
)


def test_check_digit_follows_icao_9303() -> None:
    assert check_digit("590102") == "1"
    assert check_digit("310630") == "5"
    assert check_digit("<<<") == "0"


def test_td1_fields() -> None:
    data = parse_mrz(TD1)
    assert data is not None and data.valid
    assert (data.format, data.document_code, data.issuing_state) == ("TD1", "I", "UTO")
    assert (data.birth, data.expiry, data.nationality) == ("590102", "310630", "UTO")
    assert (data.surname, data.given, data.name) == ("FIKTIV", "MARIA", "FIKTIV MARIA")
    assert "MARIA" not in repr(data)


def test_td3_fields() -> None:
    data = parse_mrz(TD3)
    assert data is not None and data.valid
    assert data.format == "TD3" and data.document_number == "KK7406302"
    assert data.name == "PELDA GABOR"


def test_a_misread_check_digit_makes_the_zone_invalid_not_absent() -> None:
    broken = (TD3[0], TD3[1].replace("8504168", "8504169"))
    data = parse_mrz(broken)
    assert data is not None and not data.valid


@pytest.mark.parametrize("lines", [(), ("not an mrz",)])
def test_not_a_zone(lines: tuple[str, ...]) -> None:
    assert parse_mrz(lines) is None


def test_a_zone_missing_a_line_is_never_valid() -> None:
    data = parse_mrz(TD1[:2])
    assert data is None or not data.valid


def test_field_names_from_captions() -> None:
    assert field_name("Surname / Nachname") == "surname"
    assert field_name("Utónév") == "given_names"
    assert field_name("Date of expiry") == "expiry"
    assert field_name(None, EntityType.PERSON) == "name"
    assert field_name("Something else") is None


def test_document_type_from_title_or_mrz() -> None:
    assert document_type("REPUBLIC OF UTOPIA  PASSPORT") == "passport"
    assert document_type("no title", parse_mrz(TD1)) == "id_card"
    assert document_type("no title") is None


def expiry_field(text: str) -> CaptionValue:
    box = Box(0, 0, 10, 10)
    words = tuple(OcrWord(w, box, (0,)) for w in text.split())
    return CaptionValue("Date of expiry", "en", None, box, box, words)


def test_summary_reduces_expiry_to_expired_by_default() -> None:
    summary = build_summary(
        text="IDENTITY CARD",
        fields=[SummaryField("surname", "[[PERSON_a]]", "exact")],
        caption_fields=[expiry_field("31.03.2025")],
        mrz=None,
        holder=SummaryField("holder", "[[PERSON_a]]", "fuzzy"),
        holder_confidence=0.93,
        today=dt.date(2026, 10, 27),
    )
    assert summary["document_type"] == "id_card"
    assert summary["expired"] is True and summary["expiry"] is None
    assert summary["holder"] == "[[PERSON_a]]" and summary["holder_match"] == "fuzzy"
    assert summary["fields_found"] == {"surname": "[[PERSON_a]]"}
    assert "2025" not in repr(summary)


def test_summary_keeps_expiry_when_asked_and_reads_mrz() -> None:
    summary = build_summary(
        text="",
        fields=[],
        caption_fields=[],
        mrz=parse_mrz(TD1),
        holder=None,
        expiry="keep",
        today=dt.date(2026, 10, 27),
    )
    assert summary["expiry"] == "2031-06-30" and summary["expired"] is False
    assert summary["mrz_present"] and summary["mrz_valid"]
    assert summary["issuing_country"] == "UTO"


def test_uncertain_fields_are_listed() -> None:
    summary = build_summary(
        text="",
        fields=[SummaryField("date_of_birth", "[[DATE_OF_BIRTH_b]]", "uncertain")],
        caption_fields=[],
        mrz=None,
        holder=SummaryField("holder", "[[PERSON_a]]", "uncertain"),
    )
    assert summary["fields_uncertain"] == ["holder", "date_of_birth"]


TENANT_KEY = "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0"


def test_garbled_document_number_is_fixed_by_its_check_digit() -> None:
    # LAB-1197: Tesseract reads J for I in the de-id_card-back zone; the digit says which
    # read is right. The garbled number alone only matches uncertainly (LAB-1211 keeps
    # letter-apart numbers apart), the digit-gated fix recovers the printed number.
    from pii_guard.vault import Vault
    from pii_guard.visual.labels import VaultMatcher, mrz_number_fixes
    from pii_guard.visual.mrz import MrzData

    garbled = MrzData(
        "TD1",
        "I",
        "UTO",
        "XIXK86KV4",
        "UTO",
        "900722",
        "310630",
        "MUSTERMANN",
        "ERIKA",
        False,
        "8",
    )
    assert mrz_number_fixes(garbled) == ["XJXK86KV4"]

    session = Vault(bytes.fromhex(TENANT_KEY)).session()
    matcher = VaultMatcher(session, "de")
    true_placeholder = matcher.assign("XJXK86KV4", EntityType.ID_DOCUMENT).placeholder
    near = matcher.assign("XJXK86KU4", EntityType.ID_DOCUMENT).placeholder
    assert near != true_placeholder
    # As read the garbled number is uncertain (a real letter changed), never a merge.
    assert matcher.match("XIXK86KV4", EntityType.ID_DOCUMENT).status == "uncertain"
    # The digit-gated fix matches the printed number exactly, not the near-namesake.
    fixed = matcher.match("XJXK86KV4", EntityType.ID_DOCUMENT)
    assert fixed.status == "exact" and fixed.candidate is not None
    assert fixed.candidate.placeholder == true_placeholder


def test_number_check_defaults_to_empty() -> None:
    from pii_guard.visual.mrz import MrzData

    data = MrzData(
        "TD3", "P", "UTO", "KK7406302", "UTO", "850416", "310630", "PELDA", "GABOR", True
    )
    assert data.number_check == ""
    assert "KK7406302" not in repr(data)
