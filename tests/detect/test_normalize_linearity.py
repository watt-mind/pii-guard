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
