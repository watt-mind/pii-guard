"""Cue and format checks for NER numbers (LAB-1293).

No model is loaded: the backend is a fake that tags the given values. Every value is
fictional: order numbers, ids, phone numbers and amounts are made up (ADR 0005).
"""

from __future__ import annotations

import time

import pytest

from pii_guard.detect.ner import NerDetector, RawEntity, model_view
from pii_guard.detect.ner_numbers import check_numbers, cue_before, number_verdict
from pii_guard.types import EntityType, Span

E = EntityType


class TagBackend:
    """Tags every occurrence of each ``(value, label)`` pair.

    The model sees glued cell delimiters as spaces (LAB-1258), so values are looked up as the
    model sees them.
    """

    def __init__(self, tags: list[tuple[str, str]]) -> None:
        self.tags = tags

    def predict(self, text: str) -> list[RawEntity]:
        out = []
        for value, label in self.tags:
            value = model_view(value)[0]
            start = text.find(value)
            while start >= 0:
                out.append(RawEntity(label, start, start + len(value), 0.9))
                start = text.find(value, start + 1)
        return out


def detect(text: str, *tags: tuple[str, str], checks: bool = True) -> list[tuple[EntityType, str]]:
    det = NerDetector(backend=TagBackend(list(tags)), number_checks=checks)
    return [(s.entity_type, s.text) for s in det.detect(text, "en")]


CARD = "5117 3778 4464 2943"  # made up, Luhn fails


# --- cues ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ('{"order": "858761608507", "amount": "1 Ft"}', "858761608507"),
        ("ticket: SO1737204\ncreated: 2026-01-01", "SO1737204"),
        ("Subject: Re: Rendelés módosítása SO1904022", "SO1904022"),
        ("Subject: AW: Änderung Ihrer Bestellung SO9353081", "SO9353081"),
        ("  - sku: KH-61026\n    qty: 6", "KH-61026"),
        ('"""Order 623728311818 escalation; owner: x."""', "623728311818"),
        ("Tracking number 9400111899223344556677 ships today", "9400111899223344556677"),
        ("payment approved order=586666414270 amount=1", "586666414270"),
        ("Ihre Bestellnummer bleibt SO9353081.", "SO9353081"),  # one word between
        ("  sku: AD-61026", "61026"),  # the value's own prefix is no word between
        ("see ORD-2024-398890 today", "398890"),  # an order prefix on the value
    ],
)
def test_a_negative_label_drops_the_number(text: str, value: str) -> None:
    assert detect(text, (value, "ID_DOCUMENT")) == []
    # Without the checks the span still covers its whole digit run (LAB-1367).
    whole = "2024-398890" if value == "398890" else value
    assert detect(text, (value, "ID_DOCUMENT"), checks=False) == [(E.ID_DOCUMENT, whole)]


@pytest.mark.parametrize(
    "text",
    [
        "For my order last week the clerk took number 858761608507 down",  # too far back
        "order SO1, then 858761608507 arrived",  # another number between
        "Your order was sent; card 858761608507",  # a positive cue is nearer
        "Payment reference: 858761608507",  # reference and amount words are no negative cue
        "Betrag 858761608507",
        "Ihre Bestellung wurde heute 858761608507",  # two words between
    ],
)
def test_a_reference_word_earlier_in_the_sentence_is_no_label(text: str) -> None:
    assert detect(text, ("858761608507", "ID_DOCUMENT")) == [(E.ID_DOCUMENT, "858761608507")]


@pytest.mark.parametrize(
    ("text", "value", "label"),
    [
        ('"ids": {"national": "8432525405"}', "8432525405", "ID_DOCUMENT"),
        ("Passport no. SO8631416, issued 2020", "SO8631416", "ID_DOCUMENT"),
        ("Refund the order to card 5117 3778 4464 2943, not cash", CARD, "BANK_ACCOUNT"),
        ("order=642325122634 iban=123456789012", "123456789012", "BANK_ACCOUNT"),
        ("A bankszámlaszámom 153809370379666", "153809370379666", "BANK_ACCOUNT"),
        ("Steuer-ID 123456789012345", "123456789012345", "ID_DOCUMENT"),
        ('"phone": "447700900614"', "447700900614", "ID_DOCUMENT"),
    ],
)
def test_a_positive_cue_keeps_any_shape(text: str, value: str, label: str) -> None:
    assert detect(text, (value, label)) == [(E(label), value)]


def test_the_csv_column_header_is_the_cue() -> None:
    text = (
        "name,email,phone,national_id,order,amount\n"
        "Ann Smith,ann@example.org,447700900464,SO1234567,SO7654321,63684.78\n"
    )
    tags = [("447700900464", "BANK_ACCOUNT"), ("SO1234567", "ID_DOCUMENT")]
    found = detect(text, *tags, ("SO7654321", "ID_DOCUMENT"))
    assert found == [(E.BANK_ACCOUNT, "447700900464"), (E.ID_DOCUMENT, "SO1234567")]
    assert cue_before(text, text.index("SO1234567")) is True
    assert cue_before(text, text.index("SO7654321")) is False


def test_csv_without_a_header_falls_back_to_the_line() -> None:
    text = "Ann Smith,ann@example.org,SO1234567,63684.78"
    assert cue_before(text, text.index("SO1234567")) is None


def test_a_cue_on_another_line_does_not_count() -> None:
    text = "order:\n  SO1234567"
    assert cue_before(text, text.index("SO")) is None


@pytest.mark.parametrize(
    "header",
    [
        '"note,order",passport,memo',  # a quoted comma: "order" is not the passport column
        '"say ""hi"", order",passport,memo',  # escaped quotes inside the quoted field
        ' "note, order" , passport , memo',  # spaces around the fields and separators
    ],
)
def test_a_quoted_comma_in_the_csv_header_does_not_shift_the_columns(header: str) -> None:
    # LAB-1352: the header was split on every comma, the row only on unquoted ones.
    text = f"{header}\nAnn Smith,SO1234567,x\n"
    assert cue_before(text, text.index("SO1234567")) is True
    assert detect(text, ("SO1234567", "ID_DOCUMENT")) == [(E.ID_DOCUMENT, "SO1234567")]


def test_a_quoted_comma_in_the_row_does_not_shift_the_columns() -> None:
    text = 'memo,order,passport\n"Smith, Ann",SO7654321,SO1234567\n'
    assert cue_before(text, text.index("SO7654321")) is False
    assert cue_before(text, text.index("SO1234567")) is True


def test_each_csv_block_has_its_own_header() -> None:
    text = (
        "name,passport,memo\nAnn,SO1234567,x\n\n"
        "name,order,memo\nBob,SO7654321,y\n"
        "id,name\n17,Cy\n"  # one comma: not a row
    )
    assert cue_before(text, text.index("SO1234567")) is True
    assert cue_before(text, text.index("SO7654321")) is False
    assert cue_before(text, text.index("17,")) is None


def test_a_large_csv_is_checked_in_linear_time() -> None:
    # LAB-1352: every value walked back over the rows above it to find the header again;
    # 4,000 rows took 8-17 s, now a few hundredths. The bound leaves room for a loaded runner.
    rows = ["name,passport,memo", *(f"Ann {i},AB{i:07d},note {i}" for i in range(4000))]
    text = "\n".join(rows) + "\n"
    spans = []
    for i in range(4000):
        start = text.index(f",AB{i:07d},") + 1
        spans.append(Span(start, start + 9, E.ID_DOCUMENT, text[start : start + 9], 0.9, "ner"))
    t0 = time.perf_counter()
    kept = check_numbers(text, spans)
    elapsed = time.perf_counter() - t0
    assert kept == spans
    assert elapsed < 2.0, f"check_numbers took {elapsed:.2f}s on 4,000 rows"


# --- shapes without a cue -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ('{"id": "40aebd349d7fcb76", "contact": {}}', "40aebd349d7fcb76"),
        ('"tool_calls": [{"id": "call_8cfd94241862884f"}]', "94241862"),  # a piece of one
        ("auth  req=38d3494435558894 user logged in", "3494435558894"),
        ("Parcel 1Z999AA10123456784 left the depot", "1Z999AA10123456784"),
        ("Parcel LX123456785GB left the depot", "LX123456785GB"),
        ("Paid 48170.94 today", "48170.94"),
        ("Paid 48170.94 today", "48170"),
        ("Paid 48170.94 today", "94"),
        ("Paid 6334.57 today", "334"),
    ],
)
def test_shapes_that_are_never_personal_data_are_dropped(text: str, value: str) -> None:
    assert detect(text, (value, "ID_DOCUMENT")) == []
    assert detect(text, (value, "BANK_ACCOUNT")) == []


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Hello 858761608507 bye", "858761608507"),  # long digits: kept without a cue
        ("Hello 38520665501 bye", "38520665501"),
        ("Reach them on 447700900614.", "447700900614"),  # a joined phone number
        ("ID AB 123 456 here", "123"),  # a group of a spaced value
        ("x 334 y", "334"),  # short values are not judged by length
        ("Hello AB123456 bye", "AB123456"),
    ],
)
def test_everything_else_is_kept(text: str, value: str) -> None:
    assert detect(text, (value, "BANK_ACCOUNT")) == [(E.BANK_ACCOUNT, value)]


def test_a_piece_of_a_number_is_kept_as_the_whole_number() -> None:
    """LAB-1367: the piece is snapped to its digit run before it is judged."""
    text = "Reach them on 447700900614."
    assert detect(text, ("7700900614", "BANK_ACCOUNT")) == [(E.BANK_ACCOUNT, "447700900614")]


def test_a_span_over_a_field_separator_is_split_into_fields() -> None:
    text = "Ann,+44 7700 900464,853103299,SO7654321,63684.78\n"
    found = detect(text, ("853103299,SO7654321,63684.78", "ID_DOCUMENT"))
    assert found == [(E.ID_DOCUMENT, "853103299"), (E.ID_DOCUMENT, "SO7654321")]
    text = "Ann,06 1 494 9935,SO2354538,94541.22\n"
    assert detect(text, ("SO2354538,94541.22", "ID_DOCUMENT")) == [(E.ID_DOCUMENT, "SO2354538")]


def test_a_phone_span_over_a_field_separator_is_split_into_fields() -> None:
    # LAB-1380 (en-agent-traffic-dev-0084): the NER PHONE span runs over the CSV comma
    # between the phone and the national-id columns; each field is judged by its own header.
    text = 'name,phone,national_id\n"Louise Petit",07700900316,703371441\n'
    found = detect(text, ("07700900316,703", "PHONE"))
    # The tagged span is snapped to whole tokens first, then split at the comma.
    assert found == [(E.PHONE, "07700900316"), (E.PHONE, "703371441")]


def test_a_single_field_phone_span_is_untouched() -> None:
    # No separator runs through it: not even a negative label next to it drops it (LAB-1380).
    text = '{"order": "07700900316"}'
    assert detect(text, ("07700900316", "PHONE")) == [(E.PHONE, "07700900316")]


def test_other_types_are_untouched() -> None:
    text = '{"order": "Ann Smith", "sku": "12"}'
    assert detect(text, ("Ann Smith", "PERSON"), ("12", "PHONE")) == [
        (E.PERSON, "Ann Smith"),
        (E.PHONE, "12"),
    ]


def test_check_numbers_keeps_an_untouched_span_as_is() -> None:
    text = "Passport SO8631416"
    span = Span(9, 18, E.ID_DOCUMENT, "SO8631416", 0.77, "ner")
    assert check_numbers(text, [span]) == [span]
    assert check_numbers(text, [span])[0].score == 0.77


def test_number_verdict_is_fail_closed_on_unknown_shapes() -> None:
    assert number_verdict("Hello AB123456 bye", 6, 14) is True
