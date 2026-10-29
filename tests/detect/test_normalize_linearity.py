"""Exact numeric-line grammar and bounded adversarial normalization (synthetic only)."""

from __future__ import annotations

import itertools
import re
import subprocess
import sys

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pii_guard.detect.normalize import (
    _is_number_continuation,
    _is_number_line,
    normalize_for_detection,
)

# The former grammars are reference oracles on bounded generated strings only. Long
# adversarial inputs below run the production normalizer in a separately bounded process.
_NUMBER_LINE_REFERENCE = re.compile(r"[ \t]*[+(]?[0-9][0-9 ()+\-./]*[ \t]*")
_CONTINUATION_REFERENCE = re.compile(r"[0-9]+(?:[ -][0-9]+)*[ \t]*[.,;:!?)]?[ \t]*")


def test_short_numeric_lines_preserve_exact_accepted_grammar() -> None:
    # Representatives include digit, both padding kinds, every role of punctuation,
    # separators and an invalid character; exhaustive combinations cover ambiguous edges.
    for length in range(6):
        for chars in itertools.product("0 +(-.)\tx", repeat=length):
            text = "".join(chars)
            assert _is_number_line(text) == bool(_NUMBER_LINE_REFERENCE.fullmatch(text))
            assert _is_number_continuation(text) == bool(_CONTINUATION_REFERENCE.fullmatch(text))


@given(st.text(alphabet="0123456789 ()+-./\t,;:!?x\n\r\u00a0\u0661", max_size=64))
def test_generated_numeric_lines_preserve_exact_accepted_grammar(text: str) -> None:
    assert _is_number_line(text) == bool(_NUMBER_LINE_REFERENCE.fullmatch(text))
    assert _is_number_continuation(text) == bool(_CONTINUATION_REFERENCE.fullmatch(text))


@pytest.mark.parametrize("punctuation", ["", ".", ",", ";", ":", "!", "?", ")"])
@pytest.mark.parametrize("padding", ["", " ", "\t", " \t "])
def test_continuation_padding_punctuation_and_offset_mapping(punctuation, padding) -> None:
    original = f"Synthetic phone: +36 30 123\r\n4567{padding}{punctuation}{padding}"
    normalized = normalize_for_detection(original)
    assert normalized.text == original.replace("\r\n", " ")
    start = normalized.text.index("+36")
    end = normalized.text.index("4567") + 4
    assert original[slice(*normalized.to_original(start, end))] == "+36 30 123\r\n4567"


@pytest.mark.parametrize("target", ["number_line", "continuation"])
@pytest.mark.parametrize("padding", [" ", "\t", " \t"])
def test_long_failing_numeric_lines_finish_within_process_deadline(
    target: str, padding: str
) -> None:
    code = """
import sys
from pii_guard.detect.normalize import normalize_for_detection
padding = sys.argv[2] * 100_000
if sys.argv[1] == 'number_line':
    text = '1' + padding + 'x1\\n2'
    expected = text.replace('\\n', ' ')
else:
    text = 'Synthetic number: 1\\n1' + padding + 'x'
    expected = text
normalized = normalize_for_detection(text)
assert normalized.text == expected
assert normalized.changed == (expected != text)
"""
    subprocess.run([sys.executable, "-c", code, target, padding], check=True, timeout=5)  # noqa: S603


_BREAKS = "\n\r\x0b\x0c\x85\u2028\u2029"
_WRAPPED_REFERENCE = re.compile(rf"(?<=[0-9])(\r\n|[{_BREAKS}])(?=[0-9])")
_BREAK_REFERENCE = re.compile(f"[{_BREAKS}]")


def _legacy_join_wrapped_numbers(chars: list[str]) -> list[int]:
    """Original join decisions, on bounded inputs only, independent of the new iterator."""
    joined = "".join(chars)
    drop = []
    for match in _WRAPPED_REFERENCE.finditer(joined):
        start, end = match.span()
        line_start = max(joined.rfind(char, 0, start) for char in _BREAKS) + 1
        following = _BREAK_REFERENCE.search(joined, end)
        before = joined[line_start:start]
        after = joined[end : following.start() if following else len(joined)]
        if _NUMBER_LINE_REFERENCE.fullmatch(before) or not _CONTINUATION_REFERENCE.fullmatch(after):
            continue
        chars[end - 1] = " "
        drop.extend(range(start, end - 1))
    return drop


def _assert_joins_match_legacy(text: str) -> None:
    from pii_guard.detect.normalize import _join_wrapped_numbers

    current, original = list(text), list(text)
    assert _join_wrapped_numbers(current) == _legacy_join_wrapped_numbers(original)
    assert current == original


@pytest.mark.parametrize("first", [*_BREAKS, "\r\n"])
@pytest.mark.parametrize("second", [*_BREAKS, "\r\n"])
def test_mixed_newline_kinds_and_empty_lines_preserve_join_decisions(first, second) -> None:
    for text in (
        f"1{first}2{second}3",
        f"Synthetic number: 1{first}2{second}3",
        f"Synthetic number: 1{first}{second}2",
        f"Synthetic number: 1{first}2\t){second}3",
        f"{first}Synthetic number: 1{second}2",
        f"1{first}Synthetic number: 2{second}3",
    ):
        _assert_joins_match_legacy(text)


@given(st.text(alphabet="01x +()-./\t,;:!?" + _BREAKS, max_size=80))
def test_generated_newline_sequences_match_original_joiner(text: str) -> None:
    _assert_joins_match_legacy(text)


@pytest.mark.parametrize("line_break", [*_BREAKS, "\r\n"])
def test_many_numeric_lines_finish_within_process_deadline(line_break: str) -> None:
    code = """
import sys
from pii_guard.detect.normalize import normalize_for_detection
text = ('1' + sys.argv[1]) * 100_000
normalized = normalize_for_detection(text)
assert normalized.text == text
assert not normalized.changed
"""
    subprocess.run([sys.executable, "-c", code, line_break], check=True, timeout=5)  # noqa: S603
