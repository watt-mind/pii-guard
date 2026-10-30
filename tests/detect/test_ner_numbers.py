"""Cue and format checks for NER numbers (LAB-1293).

No model is loaded: the backend is a fake that tags the given values. Every value is
fictional: order numbers, ids, phone numbers and amounts are made up (ADR 0005).
"""

from __future__ import annotations

import time

import pytest

from pii_guard.detect.ner import NerDetector, RawEntity
from pii_guard.detect.ner_numbers import check_numbers, cue_before, number_verdict
from pii_guard.types import EntityType, Span

E = EntityType


class TagBackend:
    """Tags every occurrence of each ``(value, label)`` pair."""

    def __init__(self, tags: list[tuple[str, str]]) -> None:
        self.tags = tags

    def predict(self, text: str) -> list[RawEntity]:
        out = []
        for value, label in self.tags:
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


# --- reference and tracking shapes (LAB-1344, tuned on the cee-dev split) -------------------


def _cnp(head: str) -> str:
    """A Romanian personal number (CNP) with a valid check digit: 13 digits, may start 17/18."""
    total = sum(int(d) * int(w) for d, w in zip(head, "279146358279", strict=True))
    return head + str(1 if total % 11 == 10 else total % 11)


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("BESZEDES ref 1761734400123 519 200 Ft", "1761734400123"),  # epoch milliseconds
        ("reference: 20261029141749\n", "20261029141749"),  # yyyymmddhhmmss
        ("tranzakció TR20261029141749 kész", "TR20261029141749"),
        ("ID: PAY20251020130750", "PAY20251020130750"),
        ("ref K-20260612013631 |", "20260612013631"),
        ("ref 2O261029141749 x", "2O261029141749"),  # an OCR O for a 0
        ("TRANSFER UA222O53650HU 5576", "UA222O53650HU"),  # S10 with an OCR O
        ("ref EE459378323AT", "EE459378323AT"),
        ("ID: 2025/098820\n", "2025/098820"),  # year / serial
        ("invoice VSZ 2024/09146, x", "2024/09146"),
        ("FV 2026/06039, ok", "FV 2026/06039"),
        ("ID: 448-1813374-1068055 |", "448-1813374-1068055"),  # 3-7-7 order number
    ],
)
def test_reference_and_tracking_shapes_are_dropped(text: str, value: str) -> None:
    assert detect(text, (value, "BANK_ACCOUNT")) == []
    assert detect(text, (value, "ID_DOCUMENT")) == []


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("card 5247 1154 0172 4326, ID: 1ZTBVH129952639626.", "1ZTBVH129952639626"),
        ("kártya 4699 7028 7967 2896, TR20260117040802.", "TR20260117040802"),
        ("DIRECT DEBIT 2026-10-17 ref 1ZEF83LC8611052895 £19,647.3", "1ZEF83LC8611052895"),
        ("Account: GB12 KQZF 9822 0076 6235 99 | reference: 1817380329666", "1817380329666"),
    ],
)
def test_a_positive_cue_does_not_reach_over_another_number(text: str, value: str) -> None:
    assert detect(text, (value, "BANK_ACCOUNT")) == []


def test_a_span_is_cut_at_newlines_and_around_tracking_tokens() -> None:
    iban = "GB64 DQLG 1272 1511 3909 60"
    text = f"Account: {iban}\n1ZSB6LZX5311962777\nref x"
    assert detect(text, (f"{iban}\n1ZSB6LZX5311962777", "BANK_ACCOUNT")) == [(E.BANK_ACCOUNT, iban)]
    text = f"TRANSFER CP279078509AT {CARD}\n"
    assert detect(text, (f"CP279078509AT {CARD}", "BANK_ACCOUNT")) == [(E.BANK_ACCOUNT, CARD)]


@pytest.mark.parametrize(
    ("text", "value"),
    [
        (f"Hello {_cnp('175031512345')} bye", _cnp("175031512345")),  # a valid CNP
        ("Hello 3761734400123 bye", "3761734400123"),  # 13 digits, no epoch
        ("Hello 1464872278652 bye", "1464872278652"),  # 2016: too old for a fresh reference
        ("Hello 20261399141749 bye", "20261399141749"),  # month 13: no stamp
        ("Hello 20261029141799 bye", "20261029141799"),  # second 99: no stamp
        ("Hello 2025/0988201234 bye", "2025/0988201234"),  # serial too long
        ("Passport TR20261029141749", "TR20261029141749"),  # a positive label still wins
        (f"card {_cnp('175031512345')}", _cnp("175031512345")),
    ],
)
def test_near_misses_of_the_reference_shapes_are_kept(text: str, value: str) -> None:
    assert detect(text, (value, "ID_DOCUMENT")) == [(E.ID_DOCUMENT, value)]
