"""A zero-width separator between the words of a value does not hide it (LAB-1233).

Found while fixing LAB-1208: the normaliser dropped U+200B, so ``Teszt\\u200bElek`` read as
``TesztElek`` and the occurrence pattern (``teszt\\s+elek``) missed it. All values are
fictional (ADR 0005).
"""

from __future__ import annotations

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from vault_helpers import TEST_KEY, span_of

from pii_guard.detect.known import merge_known
from pii_guard.types import EntityType
from pii_guard.vault import PLACEHOLDER_RE, Vault, VaultSession
from pii_guard.vault.fold import fold_text, fold_views
from pii_guard.vault.known import known_values_from

P = EntityType.PERSON
ZWSP, WJ, BOM, ZWNJ, ZWJ = "​", "⁠", "﻿", "‌", "‍"
SEPARATORS = [ZWSP, WJ, BOM]


def session() -> VaultSession:
    return Vault(TEST_KEY).session()


def placeholders(masked: str) -> set[str]:
    return {m.group(0) for m in PLACEHOLDER_RE.finditer(masked)}


def test_repro_zero_width_space_between_the_words() -> None:
    text = f"Teszt Elek írt. Később Teszt{ZWSP}Elek is."
    s = session()
    masked = s.mask(text, [span_of(text, "Teszt Elek", P)], language="hu")
    assert "Elek" not in masked and ZWSP not in masked
    assert len(placeholders(masked)) == 1
    assert masked.count("[[PERSON_") == 2


@pytest.mark.parametrize("sep", SEPARATORS)
@pytest.mark.parametrize(
    "written", ["Teszt{0}Elek", "teszt{0}elek", "TESZT{0}ELEK", "Teszt{0}{0}Elek", "Teszt{0} Elek"]
)
def test_separator_in_any_casing_does_not_hide_an_occurrence(sep: str, written: str) -> None:
    text = f"Teszt Elek írt. Később {written.format(sep)} is."
    s = session()
    masked = s.mask(text, [span_of(text, "Teszt Elek", P)], language="hu")
    assert "elek" not in fold_text(masked).text
    assert sep not in masked


def test_separator_inside_a_word_is_still_masked() -> None:
    # The LAB-1208 case keeps working alongside the new reading.
    text = f"Teszt Elek írt. Később Te{ZWSP}szt El{ZWSP}ek és Teszt{ZWSP}Elek is."
    s = session()
    masked = s.mask(text, [span_of(text, "Teszt Elek", P)], language="hu")
    assert "El" not in masked and "szt" not in masked
    assert masked.count("[[PERSON_") == 3


def test_suffix_after_a_separated_occurrence() -> None:
    text = f"Teszt Elek írt. Később teszt{ZWSP}eleknek is."
    s = session()
    masked = s.mask(text, [span_of(text, "Teszt Elek", P)], language="hu")
    assert "elek" not in fold_text(masked).text


@pytest.mark.parametrize("joiner", [ZWNJ, ZWJ])
def test_joiners_are_not_read_as_a_space(joiner: str) -> None:
    views = fold_views(f"Teszt{joiner}Elek")
    assert [v.text for v in views] == ["tesztelek"]


def test_views_map_back_to_the_original() -> None:
    text = f"Kovács béla és teszt{ZWSP}elek, Te{ZWSP}szt."
    views = fold_views(text)
    assert [v.text for v in views] == [
        "kovács béla és tesztelek, teszt.",
        "kovács béla és teszt elek, te szt.",
    ]
    spaced = views[1]
    start = spaced.text.index("teszt elek")
    assert text[slice(*spaced.to_original(start, start + len("teszt elek")))] == (
        f"teszt{ZWSP}elek"
    )


def test_no_second_view_without_a_separator_between_letters() -> None:
    assert len(fold_views("Teszt Elek")) == 1
    assert len(fold_views(f"{BOM}Teszt Elek")) == 1
    assert len(fold_views(f"Teszt {ZWSP}Elek")) == 1


def test_known_value_found_across_a_separator() -> None:
    text = f"Üzenet: teszt{ZWSP}elek írt."
    s = session()
    s.known_values.add(known_values_from([{"value": "Teszt Elek", "entity_type": "PERSON"}]))
    spans = merge_known(text, [], s.known_values, "hu")
    assert [sp.text for sp in spans] == [f"teszt{ZWSP}elek"]
    masked = s.mask(text, spans, language="hu")
    assert "elek" not in fold_text(masked).text


# --- property: a separator between the words never hides an occurrence ----------------------

_WORD = st.text(alphabet="abcdeéklmnorstuvzáóöőüű", min_size=2, max_size=8)


def _cased(word: str, how: str) -> str:
    return {"upper": word.upper(), "title": word.capitalize()}.get(how, word)


@settings(max_examples=200, deadline=None)
# LAB-1307: "Aaából" reads as the lengthened stem "Aaá" + "-ból", so the value itself masks as
# "[[PERSON_…]]ból"; the separated occurrence must split the same way, not more or less.
@example(words=["aa", "aaából"], how="lower", seps=[ZWSP, ZWSP], replace=False)
@given(
    words=st.lists(_WORD, min_size=2, max_size=3),
    how=st.sampled_from(["lower", "upper", "title"]),
    seps=st.lists(st.sampled_from(SEPARATORS), min_size=2, max_size=2),
    replace=st.booleans(),
)
def test_separator_between_words_never_hides_an_occurrence(
    words: list[str], how: str, seps: list[str], replace: bool
) -> None:
    value = " ".join(w.capitalize() for w in words)
    gaps = [(sep if replace else f"{sep} ") for sep in seps]
    cased = [_cased(w, how) for w in words]
    written = cased[0] + "".join(gap + w for gap, w in zip(gaps, cased[1:], strict=False))
    text = f"{value} írt. Később {written} is."
    s = session()
    masked = s.mask(text, [span_of(text, value, P)], language="hu")
    head, tail = masked.split(" írt. ")
    assert not any(sep in tail for sep in SEPARATORS)
    assert tail.startswith("Később ") and tail.endswith(" is.")
    occurrence = tail[len("Később ") : -len(" is.")]
    # The occurrence is masked exactly like the value's own span. Intended (LAB-1307): when the
    # value itself splits as lemma + Hungarian suffix (``Aaából`` -> ``Aaá`` + ``ból``), the
    # placeholder covers the stem and that suffix stays outside it, in both places, so unmask
    # re-inflects it. Nothing else of the occurrence is left beside the placeholder.
    first, second = PLACEHOLDER_RE.match(head), PLACEHOLDER_RE.match(occurrence)
    assert first is not None and second is not None
    assert first.group(0) == second.group(0)
    suffix = head[first.end() :]
    assert occurrence[second.end() :].casefold() == suffix.casefold()
    assert value.casefold().endswith(suffix.casefold()) and not any(c.isspace() for c in suffix)


# --- a separator at a lower -> upper split inside a confirmed value (LAB-1363) ---------------

S = EntityType.SECRET
_VALUE = "AbCdEfGh1234xY"  # fictional, not secret-shaped


@pytest.mark.parametrize("sep", SEPARATORS)
@pytest.mark.parametrize("split", range(1, len(_VALUE)))
def test_confirmed_secret_with_a_separator_at_any_split_is_remasked(sep: str, split: int) -> None:
    s = session()
    first = f"key {_VALUE}"
    placeholder = s.mask(first, [span_of(first, _VALUE, S)], language="en")[len("key ") :]
    occurrence = _VALUE[:split] + sep + _VALUE[split:]
    masked = s.mask("see " + occurrence, [], language="en")
    assert masked == f"see {placeholder}"


def test_repro_lower_upper_split_of_a_confirmed_secret() -> None:
    s = session()
    first = f"key {_VALUE}"
    s.mask(first, [span_of(first, _VALUE, S)], language="en")
    masked = s.mask(f"see {_VALUE[:6]}{ZWSP}{_VALUE[6:]}", [], language="en")
    assert "AbCdEf" not in masked and "1234" not in masked and ZWSP not in masked


def test_lower_upper_separator_between_words_still_reads_two_words() -> None:
    # The dropped reading is an extra view: the detection fold's own is unchanged.
    views = fold_views(f"Teszt{ZWSP}Elek")
    assert views[0].text == "teszt elek"
    assert "tesztelek" in [v.text for v in views]
