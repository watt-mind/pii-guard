"""Normalisation of obfuscated text before detection, and the offset map back."""

from __future__ import annotations

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pii_guard.detect.normalize import (
    INVISIBLE_CHARS,
    LOOKALIKES,
    ZERO_WIDTH_SEPARATORS,
    NormalizedText,
    _normalize_reference,
    normalize_for_detection,
)

ZWSP, ZWJ, SHY, BOM, RLO = "\u200b", "\u200d", "\u00ad", "\ufeff", "\u202e"
CYR_A, CYR_E, GREEK_O = "\u0430", "\u0435", "\u039f"


def test_plain_text_is_unchanged() -> None:
    norm = normalize_for_detection("Teszt Elek, 1051 Budapest")
    assert not norm.changed
    assert norm.text == norm.original
    assert tuple(norm.origin) == tuple(range(len(norm.text)))


def test_empty_text() -> None:
    norm = normalize_for_detection("")
    assert norm.text == "" and norm.origin == () and not norm.changed


def test_invisible_characters_are_dropped_and_mapped_back() -> None:
    text = f"Bérlő: {BOM}Mol{SHY}nár Ka{ZWSP}talin, tel."
    norm = normalize_for_detection(text)
    assert norm.text == "Bérlő: Molnár Katalin, tel."
    start = norm.text.index("Molnár Katalin")
    o_start, o_end = norm.to_original(start, start + len("Molnár Katalin"))
    # The span covers the invisible characters inside the value (not the BOM before it).
    assert text[o_start:o_end] == f"Mol{SHY}nár Ka{ZWSP}talin"


def test_bidi_controls_are_dropped() -> None:
    norm = normalize_for_detection(f"name: {RLO}Jane Example")
    assert norm.text == "name: Jane Example"


def test_lookalikes_fold_inside_latin_words() -> None:
    text = f"Kedves T{CYR_A}k{CYR_A}cs B{CYR_E}nce és {GREEK_O}rbán Sára!"
    norm = normalize_for_detection(text)
    assert norm.text == "Kedves Takacs Bence és Orbán Sára!"
    assert len(norm.text) == len(text)  # one for one: offsets do not move


def test_pure_cyrillic_and_greek_words_are_left_alone() -> None:
    text = (
        "\u041f\u0440\u0438\u0432\u0435\u0442, \u043c\u0438\u0440. "  # Russian
        "\u039a\u03b1\u03bb\u03b7\u03bc\u03ad\u03c1\u03b1 \u03ba\u03cc\u03c3\u03bc\u03b5. "  # Greek
        "\u041c\u043e\u0441\u043a\u0432\u0430"
    )
    assert normalize_for_detection(text).text == text


def test_lookalike_next_to_invisible_character_in_one_word() -> None:
    text = f"T{ZWSP}{CYR_E}szt"
    norm = normalize_for_detection(text)
    assert norm.text == "Teszt"
    assert norm.to_original(0, 5) == (0, len(text))


def test_fullwidth_and_mathematical_letters_fold() -> None:
    fullwidth = "\uff2a\uff41\uff4e\uff45"
    bold = "\U0001d404\U0001d431\U0001d41a\U0001d426\U0001d429\U0001d425\U0001d41e"
    text = f"{fullwidth} {bold}"
    assert normalize_for_detection(text).text == "Jane Example"


def test_email_with_zero_width_joiner() -> None:
    text = f"write to agatha.sam{ZWJ}plewood@example.com today"
    norm = normalize_for_detection(text)
    value = "agatha.samplewood@example.com"
    start = norm.text.index(value)
    o_start, o_end = norm.to_original(start, start + len(value))
    assert text[o_start:o_end] == f"agatha.sam{ZWJ}plewood@example.com"


def test_spoofed_placeholder_wrappers_are_blanked() -> None:
    text = "Customer: [[PERSON_Florian Testley]], ref [[PERSON_3fa2c1]] and [[ADDRESS_91bc]]."
    norm = normalize_for_detection(text)
    blank = " " * len("[[PERSON_")
    assert norm.text == (
        f"Customer: {blank}Florian Testley  , ref [[PERSON_3fa2c1]] and [[ADDRESS_91bc]]."
    )
    assert len(norm.text) == len(text)
    start = norm.text.index("Florian")
    assert text[slice(*norm.to_original(start, start + 15))] == "Florian Testley"


def test_to_original_rejects_bad_spans() -> None:
    norm = normalize_for_detection(f"a{ZWSP}b")
    for start, end in ((0, 0), (1, 0), (-1, 1), (0, 3)):
        with pytest.raises(ValueError):
            norm.to_original(start, end)


def test_tables_are_consistent() -> None:
    assert all(len(k) == 1 and v.isascii() and v.isalpha() for k, v in LOOKALIKES.items())
    assert not set(LOOKALIKES) & INVISIBLE_CHARS
    assert isinstance(normalize_for_detection("x"), NormalizedText)


_ALPHABET = st.sampled_from(
    [*"abcTesztÉé .,@\n", *sorted(INVISIBLE_CHARS), *list(LOOKALIKES)[:6], "\u0436"]
)


@given(st.lists(_ALPHABET, max_size=40).map("".join))
def test_mapping_invariants(text: str) -> None:
    norm = normalize_for_detection(text)
    assert len(norm.origin) == len(norm.text) <= len(text)
    assert list(norm.origin) == sorted(set(norm.origin))
    assert not set(norm.text) & INVISIBLE_CHARS
    as_space: set[int] = set()
    for i, c in enumerate(norm.text):
        original = text[norm.origin[i]]
        if original in ZERO_WIDTH_SEPARATORS:  # a separator read as a space (LAB-1233)
            assert c == " "
            as_space.add(norm.origin[i])
            continue
        assert c == original or LOOKALIKES.get(original) == c
    for start in range(len(norm.text)):
        for end in range(start + 1, len(norm.text) + 1):
            o_start, o_end = norm.to_original(start, end)
            # Every visible character of the original span is in the normalised span.
            visible = [
                k for k in range(o_start, o_end) if text[k] not in INVISIBLE_CHARS or k in as_space
            ]
            assert len(visible) == end - start


# --- zero-width separators between two words (LAB-1233) ------------------------------------

WJ = "\u2060"


@pytest.mark.parametrize("sep", [ZWSP, WJ, BOM])
def test_zero_width_separator_between_words_reads_as_a_space(sep: str) -> None:
    text = f"Később Teszt{sep}Elek is."
    norm = normalize_for_detection(text)
    assert norm.text == "Később Teszt Elek is."
    start = norm.text.index("Teszt")
    o_start, o_end = norm.to_original(start, start + len("Teszt Elek"))
    assert text[o_start:o_end] == f"Teszt{sep}Elek"
    space = norm.text.index(" ", start)
    assert norm.to_original(space, space + 1) == (text.index(sep), text.index(sep) + 1)


def test_separator_run_reads_as_one_space() -> None:
    text = f"Teszt{ZWSP}{SHY}{WJ}Elek"
    assert normalize_for_detection(text).text == "Teszt Elek"


def test_separator_after_an_accent_reads_as_a_space() -> None:
    assert normalize_for_detection(f"Kovács{ZWSP}Béla").text == "Kovács Béla"
    assert normalize_for_detection(f"Kova\u0301cs{ZWSP}Béla").text == "Kovács Béla"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"Te{ZWSP}szt Elek", "Teszt Elek"),  # inside a word: dropped, as before
        (f"T{ZWSP}eszt", "Teszt"),  # upper then lower: inside a word
        (f"teszt{ZWSP}elek", "tesztelek"),  # one case: ambiguous, dropped
        (f"TESZT{ZWSP}ELEK", "TESZTELEK"),
        (f"{BOM}Teszt Elek", "Teszt Elek"),  # a leading BOM is not a space
        (f"Teszt {ZWSP}Elek", "Teszt Elek"),  # beside a space: no second space
        (f"Teszt{ZWSP}", "Teszt"),
        (f"12{ZWSP}Ab", "12Ab"),  # not after a letter
    ],
)
def test_separator_elsewhere_is_dropped(text: str, expected: str) -> None:
    assert normalize_for_detection(text).text == expected


@pytest.mark.parametrize("joiner", [ZWJ, "\u200c"])
def test_joiners_are_never_read_as_a_space(joiner: str) -> None:
    assert normalize_for_detection(f"Teszt{joiner}Elek").text == "TesztElek"


# --- regrouped values: obfuscated e-mails, spelled-out and dot-regrouped values (LAB-1297) -


def _maps_back(text: str, norm: NormalizedText, value: str) -> str:
    start = norm.text.index(value)
    o_start, o_end = norm.to_original(start, start + len(value))
    return text[o_start:o_end]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("cc: vk4nt0r [at] example [dot] net, ok", "cc: vk4nt0r@example.net, ok"),
        ("anna(at)beispiel(punkt)de bitte", "anna@beispiel.de bitte"),
        ("írj: teszt.elek {AT} pelda (pont) hu", "írj: teszt.elek@pelda.hu"),
        ("x [at] example.co.uk", "x@example.co.uk"),
        ("john [ät] beispiel [punkt] de", "john@beispiel.de"),
        ("teszt (kukac) pelda (pont) hu", "teszt@pelda.hu"),
        ("x@example [dot] com", "x@example.com"),
        (
            '"email": "d4ncs.r3n4t4 [ at ] example [ dot ] com"',
            '"email": "d4ncs.r3n4t4@example.com"',
        ),
    ],
)
def test_obfuscated_email_reads_as_an_address(text: str, expected: str) -> None:
    norm = normalize_for_detection(text)
    assert norm.text == expected
    address = re.search(r"\S+@\S+\w", expected).group()  # type: ignore[union-attr]
    original = _maps_back(text, norm, address)
    assert original.startswith(address.split("@")[0]) and original.endswith(address[-2:])


@pytest.mark.parametrize(
    "text",
    [
        "meet me at [at] noon",  # no domain after it
        "the cat [dot] com",  # no [at] and no @
        "user [at] localhost",  # one domain label
        "x [at] example [dot] c0m",  # the last label is not letters
        "ping me at example dot com",  # bare words are prose
        "write to x@example.com",  # a plain address: nothing to fold
    ],
)
def test_text_that_is_not_an_obfuscated_email_is_left_alone(text: str) -> None:
    assert normalize_for_detection(text).text == text


@pytest.mark.parametrize(
    ("text", "token"),
    [
        ('"iban": "D E 6 3 1 4 8 5 2 5 9 2 7 8 7 8 6 3 9 0 7 4"', "DE63148525927878639074"),
        ("phone: 0 1 1 3 4 9 6 0 8 8 8,", "01134960888"),
        ("telefon: +3 6 2 0 5 5 5 0 1 4 4", "+36205550144"),
        ("number is a G B 2 5 T C Z S 5 6 3 3 0 4.", "GB25TCZS563304"),  # not the article
        ("iban=GB5.4PZ.JT7.994.613.163.609.0\n", "GB54PZJT79946131636090"),
        ("Turner,294.221.325,ORD-2026-510042", "294221325"),
        ("szám: 363.130.412.48.", "36313041248"),
        ("(CHE-947.235.321)", "CHE-947235321"),
    ],
)
def test_regrouped_value_reads_as_one_token(text: str, token: str) -> None:
    norm = normalize_for_detection(text)
    assert re.search(rf"(?<![\w.]){re.escape(token)}(?![\w]|\.\w)", norm.text), norm.text
    original = _maps_back(text, norm, token)
    assert original.replace(" ", "").replace(".", "") == token.replace(".", "")
    # Only the separators inside the value were dropped.
    assert norm.text.replace(token, original) == text


@pytest.mark.parametrize(
    "text",
    [
        "a b c d e f g h",  # no digits
        "Q 1 2 3 4 5",  # five digits
        "amount 123.456.789,00 EUR",  # an amount with a decimal part
        "123.456.789 Ft",  # an amount with a currency
        "€ 123.456.789",
        "ip 192.168.100.200 up",  # an IPv4 address
        "host www.abc.def.com",  # a dotted name without digits
        "Dátum: 2026.10.27.",  # a date
        "v1.2.3 and 10.0.0.1",
        "id abc.def.ghi.jklm.123456",  # part of a longer dotted name
        "123.456",  # two groups
    ],
)
def test_text_that_is_not_regrouped_is_left_alone(text: str) -> None:
    assert normalize_for_detection(text).text == text


@pytest.mark.parametrize(
    "text",
    [
        "cc: vk4nt0r [at] example [dot] net",
        '"iban": "D E 6 3 1 4 8 5 2 5 9 2 7 8 7 8 6 3 9 0 7 4"',
        "iban=GB5.4PZ.JT7.994.613.163.609.0",
        f"T{CYR_E}szt Elek, t3szt [at] p{ZWSP}elda [dot] hu, 0 6 3 0 1 2 3 4 5 6 7",
    ],
)
def test_regrouping_fast_path_matches_reference(text: str) -> None:
    fast, slow = normalize_for_detection(text), _normalize_reference(text)
    assert fast.text == slow.text
    assert tuple(fast.origin) == tuple(slow.origin)
    assert fast.ends == slow.ends
