"""Unicode separators, digits, dashes, combining marks and lookalike-only identifiers (LAB-1204).

Word and Office text puts no-break spaces and en dashes inside numbers, macOS file names and
some keyboards produce decomposed (NFD) accents, and other scripts have their own digits. The
detection normaliser folds all of them one for one (or composes them, with an exact end
offset), so every structured identifier is still found, over its exact original span.

All values are fictional (ADR 0005).
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pii_guard.detect import checksums
from pii_guard.detect.normalize import (
    INVISIBLE_CHARS,
    LOOKALIKES,
    _normalize_reference,
    normalize_for_detection,
)
from pii_guard.detect.pipeline import DetectionPipeline
from pii_guard.languages.de import checksums as de_checksums
from pii_guard.types import EntityType, Span
from pii_guard.vault import Vault

E = EntityType
KEY = bytes.fromhex("1e" * 32)
FIXTURES = Path(__file__).resolve().parents[2] / "eval" / "fixtures"
RULE_FIXTURES = ("hu-smoke", "en-smoke", "de-smoke", "hu-synth-sample", "en-synth-sample")

SPACES = {
    "NBSP": "\u00a0",
    "narrow NBSP": "\u202f",
    "thin space": "\u2009",
    "figure space": "\u2007",
    "ideographic space": "\u3000",
}
DASHES = {
    "hyphen": "\u2010",
    "non-breaking hyphen": "\u2011",
    "en dash": "\u2013",
    "minus sign": "\u2212",
    "small hyphen-minus": "\ufe63",
}
DIGITS = {"Arabic-Indic": 0x660, "Devanagari": 0x966, "fullwidth": 0xFF10, "Bengali": 0x9E6}


def rules() -> DetectionPipeline:
    return DetectionPipeline(["rules"])


def found(text: str, language: str) -> list[tuple[E, str]]:
    spans = rules().detect(text, language)
    for s in spans:
        assert s.text == text[s.start : s.end]
    return [(s.entity_type, s.text) for s in spans]


def triples(spans: list[Span]) -> list[tuple[int, int, E]]:
    return [(s.start, s.end, s.entity_type) for s in spans]


# --- the reviewers' probe inputs ---------------------------------------------


@pytest.mark.parametrize("sep", SPACES.values(), ids=SPACES.keys())
def test_unicode_spaces_inside_identifiers(sep: str) -> None:
    taj, phone = f"123{sep}456{sep}788", f"+36{sep}30{sep}123{sep}4567"
    assert found(f"Küldöm: 8123456786 és {taj} meg {phone}", "hu") == [
        (E.NATIONAL_ID_HU_TAX, "8123456786"),
        (E.NATIONAL_ID_HU_TAJ, taj),
        (E.PHONE, phone),
    ]
    card = f"4111{sep}1111{sep}1111{sep}1111"
    iban = f"GB82{sep}WEST{sep}1234{sep}5698{sep}7654{sep}32"
    assert found(f"Paid with {card} thanks; IBAN {iban}", "en") == [
        (E.PAYMENT_CARD, card),
        (E.BANK_ACCOUNT, iban),
    ]
    phone, steuer = f"030{sep}12345678", f"12{sep}345{sep}678{sep}903"
    assert found(f"Rufen Sie {phone} an, Steuer-ID {steuer}", "de") == [
        (E.PHONE, phone),
        (E.ID_DOCUMENT, steuer),
    ]
    assert found(f"Adóazonosító: 812345{sep}6786", "hu") == [
        (E.NATIONAL_ID_HU_TAX, f"812345{sep}6786")
    ]


@pytest.mark.parametrize("dash", DASHES.values(), ids=DASHES.keys())
def test_unicode_dashes_inside_identifiers(dash: str) -> None:
    giro, phone = f"11773016{dash}11111018", f"06{dash}30{dash}123{dash}4567"
    tax, reg = f"12345676{dash}2{dash}41", f"01{dash}09{dash}123456"
    text = f"Számla {giro}, tel {phone}, adószám {tax}, cg {reg}"
    assert found(text, "hu") == [
        (E.BANK_ACCOUNT, giro),
        (E.PHONE, phone),
        (E.COMPANY_ID_HU, tax),
        (E.COMPANY_ID_HU, reg),
    ]
    assert found(f"Hívj: +36{dash}30{dash}123{dash}4567", "hu") == [
        (E.PHONE, f"+36{dash}30{dash}123{dash}4567")
    ]


@pytest.mark.parametrize("brk", ["\n", "\r\n", "\u2028"], ids=["LF", "CRLF", "LS"])
def test_number_wrapped_over_a_line_break(brk: str) -> None:
    assert found(f"Hívj: +36 30 123{brk}4567", "hu") == [(E.PHONE, f"+36 30 123{brk}4567")]
    iban = f"DE89{brk}3704 0044 0532 0130 00"
    assert found(f"IBAN {iban}", "en") == [(E.BANK_ACCOUNT, iban)]


def test_a_column_of_numbers_is_not_joined() -> None:
    # One number per line: joining them would make one long number that matches nothing.
    text = "123 456 788\n8123456786\n+36 30 123 4567"
    assert found(text, "hu") == [
        (E.NATIONAL_ID_HU_TAJ, "123 456 788"),
        (E.NATIONAL_ID_HU_TAX, "8123456786"),
        (E.PHONE, "+36 30 123 4567"),
    ]


def test_chat_lines_starting_with_a_time_are_not_joined() -> None:
    norm = normalize_for_detection("Számla: 11773016-11111018\n18:50 Anna: ok")
    assert norm.text == "Számla: 11773016-11111018\n18:50 Anna: ok"
    assert found("Számla: 11773016-11111018\n18:50 Anna: ok", "hu") == [
        (E.BANK_ACCOUNT, "11773016-11111018")
    ]


def test_lookalike_only_identifiers() -> None:
    plate, card, passport = "\u0410\u0412\u0421-123", "123456\u0410\u0412", "\u0410\u04121234567"
    text = f"Rendszám: {plate}, szig: {card}, útlevél: {passport}"
    assert found(text, "hu") == [
        (E.VEHICLE_PLATE, plate),
        (E.ID_DOCUMENT, card),
        (E.ID_DOCUMENT, passport),
    ]
    iban = "\u0392\u039568 5390 0754 7034"  # Greek Beta and Epsilon
    assert found(f"IBAN {iban}", "en") == [(E.BANK_ACCOUNT, iban)]


def test_genuine_cyrillic_and_greek_with_digits_are_left_alone() -> None:
    text = "\u041c\u043e\u0441\u043a\u0432\u0430 2026, \u0391\u03b8\u03ae\u03bd\u03b1 12"
    assert normalize_for_detection(text).text == text


def test_nfd_email_is_one_whole_span() -> None:
    for value in ("josé.garcía@example.com", "kovács.jános@példa.hu", "jóhn@example.com"):
        nfd = unicodedata.normalize("NFD", value)
        text = f"Írj a {nfd} címre"
        assert found(text, "hu") == [(E.EMAIL, nfd)]


def test_combining_marks_inside_numbers() -> None:
    phone = "+36 30 123 45\u033367"  # combining double low line under a digit
    assert found(f"tel {phone}", "hu") == [(E.PHONE, phone)]
    tax = "812345678\u20e36"  # combining enclosing keycap
    assert found(f"adóaz {tax}", "hu") == [(E.NATIONAL_ID_HU_TAX, tax)]
    trailing = "8123456786\u20e3"  # a mark on the last digit is part of the value
    assert found(f"adóaz {trailing} ok", "hu") == [(E.NATIONAL_ID_HU_TAX, trailing)]


@pytest.mark.parametrize("zero", DIGITS.values(), ids=DIGITS.keys())
def test_other_scripts_digits(zero: int) -> None:
    def digits(s: str) -> str:
        return "".join(chr(zero + int(c)) if c.isdigit() else c for c in s)

    assert found(f"Adóazonosító: {digits('8123456786')}", "hu") == [
        (E.NATIONAL_ID_HU_TAX, digits("8123456786"))
    ]
    assert found(f"TAJ: {digits('123 456 788')}", "hu") == [
        (E.NATIONAL_ID_HU_TAJ, digits("123 456 788"))
    ]


def test_arabic_indic_sv_number_does_not_fail_the_request() -> None:
    # Before LAB-1204 isdigit() let these through to arithmetic that raised: the rules
    # detector failed and the gateway refused the request (fail-closed denial of service).
    for language in ("en", "de", "hu"):
        rules().detect(
            "ref \u0661\u0665\u0660\u0667\u0660\u0666\u0664\u0669C\u0663\u0664\u0662 ok", language
        )
    assert not de_checksums.is_valid_sv_number(
        "\u0661\u0665\u0660\u0667\u0660\u0666\u0664\u0669C\u0663\u0664\u0662"
    )


@pytest.mark.parametrize("dot", ["\u3002", "\uff0e", "\uff61", "\u2024"])
def test_email_with_unicode_dots(dot: str) -> None:
    for value in (f"john{dot}doe@example.com", f"john@example{dot}com"):
        assert found(f"Mail me at {value}", "en") == [(E.EMAIL, value)]


# --- every rule fixture value, rewritten --------------------------------------


def _documents() -> list[tuple[str, str]]:
    docs = []
    for name in RULE_FIXTURES:
        for line in (FIXTURES / f"{name}.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                doc = json.loads(line)
                docs.append((doc["language"], doc["text"]))
    return docs


DOCUMENTS = _documents()


def _one_for_one(name: str) -> dict[str, str]:
    if name in SPACES:
        return {" ": SPACES[name]}
    if name in DASHES:
        return {"-": DASHES[name]}
    zero = DIGITS[name]
    return {str(d): chr(zero + d) for d in range(10)}


@pytest.mark.parametrize("variant", [*SPACES, *DASHES, *DIGITS])
def test_every_fixture_value_survives_one_for_one_rewrites(variant: str) -> None:
    table = str.maketrans(_one_for_one(variant))
    pipeline = rules()
    for language, text in DOCUMENTS:
        expected = triples(pipeline.detect(text, language))
        rewritten = text.translate(table)
        spans = pipeline.detect(rewritten, language)
        assert triples(spans) == expected, (variant, text[:60])
        for s in spans:
            assert s.text == rewritten[s.start : s.end]


def test_every_fixture_value_survives_nfd() -> None:
    pipeline = rules()
    for language, text in DOCUMENTS:
        pieces = [unicodedata.normalize("NFD", c) for c in text]
        offsets = [0]
        for p in pieces:
            offsets.append(offsets[-1] + len(p))
        nfd = "".join(pieces)
        expected = [
            (offsets[a], offsets[b], t) for a, b, t in triples(pipeline.detect(text, language))
        ]
        assert triples(pipeline.detect(nfd, language)) == expected, text[:60]


@pytest.mark.parametrize("variant", ["NBSP", "en dash", "Arabic-Indic"])
def test_vault_round_trip_of_rewritten_fixtures_is_exact(variant: str) -> None:
    table = str.maketrans(_one_for_one(variant))
    pipeline = rules()
    for language, text in DOCUMENTS[:20]:
        rewritten = text.translate(table)
        spans = pipeline.detect(rewritten, language)
        session = Vault(KEY).session()
        masked = session.mask(rewritten, spans, language=language)
        for s in spans:
            assert s.text not in masked
        assert session.unmask(masked) == rewritten


# --- the offset map ----------------------------------------------------------


def test_composed_character_maps_back_over_its_marks() -> None:
    text = "jose\u0301"
    norm = normalize_for_detection(text)
    assert norm.text == "josé"
    assert norm.to_original(0, 4) == (0, 5)
    assert norm.to_original(3, 4) == (3, 5)


def test_marks_on_a_non_latin_base_are_kept() -> None:
    text = "\u0915\u093f\u0924\u093e\u092c"  # Devanagari: vowel signs stay as they are
    assert normalize_for_detection(text).text == text


_ALPHABET = st.sampled_from(
    [
        *"abe5 -.@\n\r",
        "\u0301",
        "\u0333",
        "\u20e3",
        "\ufe0f",
        "\u0430",
        "\u0410",
        "\u0392",
        "\u00a0",
        "\u2013",
        "\u0663",
        "\u3002",
        "\u200b",
        "\u0915",
        "\u093f",
    ]
)


@given(st.lists(_ALPHABET, max_size=40).map("".join))
def test_offset_map_invariants(text: str) -> None:
    norm = normalize_for_detection(text)
    n = len(norm.text)
    assert len(norm.origin) == n
    ends = norm.ends or tuple(o + 1 for o in norm.origin)
    assert len(ends) == n
    for i in range(n):
        assert norm.origin[i] < ends[i] <= len(text)
        if i + 1 < n:
            assert ends[i] <= norm.origin[i + 1]
    # What no output character stands for was dropped on purpose.
    covered = {k for o, e in zip(norm.origin, ends, strict=True) for k in range(o, e)}
    for k, c in enumerate(text):
        if k not in covered:
            assert c in INVISIBLE_CHARS or c == "\r", (k, c)
    for start in range(n):
        for end in range(start + 1, n + 1):
            o_start, o_end = norm.to_original(start, end)
            assert 0 <= o_start < o_end <= len(text)


# --- checksum helpers never raise ---------------------------------------------

_VALIDATORS = [
    checksums.is_valid_giro,
    checksums.is_valid_hu_personal_id,
    checksums.is_valid_hu_tax_id,
    checksums.is_valid_iban,
    checksums.is_valid_taj,
    de_checksums.is_valid_steuer_id,
    de_checksums.is_valid_sv_number,
]
_DIGITISH = st.text(
    alphabet=st.sampled_from(
        [*"0123456789AZC <", "\u0661", "\u0966", "\uff11", "\u00b2", "\u2460"]
    ),
    min_size=0,
    max_size=30,
)


@given(_DIGITISH)
def test_validators_never_raise(value: str) -> None:
    for validate in _VALIDATORS:
        assert validate(value) in (True, False)
    assert checksums.is_valid_hu_tax_number(value[:8], value[8:9], value[9:11]) in (True, False)
    assert checksums.is_valid_mrz_td3(value, value) in (True, False)
    assert checksums.is_valid_mrz_td1(value, value, value) in (True, False)


@given(_DIGITISH)
def test_validators_reject_non_ascii_digits(value: str) -> None:
    if value.isascii():
        return
    for validate in _VALIDATORS:
        assert validate(value) is False


# --- the one-for-one fast path (LAB-1280) ------------------------------------
# Text with no invisible character and no combining mark is folded with ``str.translate``
# instead of character by character. It must give exactly what the full path gives.


def _assert_same_as_reference(text: str) -> None:
    fast, slow = normalize_for_detection(text), _normalize_reference(text)
    assert fast.text == slow.text, text[:60]
    assert tuple(fast.origin) == tuple(slow.origin), text[:60]
    assert fast.ends == slow.ends, text[:60]
    assert fast.changed == slow.changed, text[:60]


_EQUIVALENCE_FILES = sorted(FIXTURES.glob("*.jsonl")) + sorted(
    (FIXTURES / "public").glob("*-ai4privacy.jsonl")
)


@pytest.mark.parametrize("path", _EQUIVALENCE_FILES, ids=lambda p: p.name)
def test_fast_path_matches_reference_on_fixtures(path: Path) -> None:
    texts = [
        json.loads(line)["text"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert texts
    for text in texts:
        _assert_same_as_reference(text)


@pytest.mark.parametrize(
    "text",
    [
        "Teszt Elek, 1051 Budapest",
        "Árvíztűrő tükörfúrógép, Kovács Éva",
        "T\u0435szt Elek",  # Cyrillic lookalike inside a Latin word
        "\u0410\u0412\u0421-123",  # lookalike-only plate
        "\u041c\u043e\u0441\u043a\u0432\u0430 2024",  # genuine Cyrillic
        "\U0001d6a8\U0001d6a9 12",  # mathematical Greek folds (NFKC) to a lookalike
        "\uff34\uff45\uff53\uff5a\uff54 \U0001d400",  # fullwidth and mathematical Latin
        "+36\u00a030\u2009123\u20134567",  # no-break and thin spaces, en dash
        "\u0661\u0662\u0663 \u0967\u0968",  # Arabic-Indic and Devanagari digits
        "".join(chr(0x660 + d) for d in range(10)),  # a table too big for str.replace
        "teszt\u3002elek@example\uff61com",  # ideographic and halfwidth dots
        "[[PERSON_Teszt Elek]] és [[PERSON_3fa2c1]] é",  # spoofed and real placeholders
        "Tel.: +36 30 123\n4567 é",  # a number wrapped over a line break
        "jose\u0301 \u0430",  # combining mark: full path
        "Te\u200bszt\u200bElek \u0435",  # invisible characters: full path
        "\u0915\u093f\u0924\u093e\u092c",  # Devanagari vowel signs (marks)
        "é",
        "\u00a0",
    ],
)
def test_fast_path_matches_reference_on_unicode_inputs(text: str) -> None:
    _assert_same_as_reference(text)


@given(
    st.lists(
        st.sampled_from(
            [
                *"abe5Tz -.@[]_\n\r",
                *sorted(INVISIBLE_CHARS),
                *list(LOOKALIKES),
                *SPACES.values(),
                *DASHES.values(),
                "\u0301",
                "\u20e3",
                "é",
                "\u0436",
                "\u0663",
                "\u3002",
                "\uff21",
                "\U0001d6a8",
                "\u0915",
                "\u093f",
            ]
        ),
        max_size=40,
    ).map("".join)
)
def test_fast_path_matches_reference_property(text: str) -> None:
    _assert_same_as_reference(text)
