"""Hungarian old orthography (``th``, ``cz``) and model-written long vowels in the vault.

All names are fictional (ADR 0005).
"""

from __future__ import annotations

import pytest
from vault_helpers import TEST_KEY, span_of

from pii_guard.types import EntityType
from pii_guard.vault import PLACEHOLDER_RE, HungarianSuffixMatcher, StreamUnmasker, Vault
from pii_guard.vault.inflection import Split, restore

PERSON = EntityType.PERSON
HU = HungarianSuffixMatcher()


def _session(*, case_sensitive: bool = False):
    if case_sensitive:
        return Vault(TEST_KEY, case_sensitive_placeholders=True).session()
    return Vault(TEST_KEY).session()


def _tokens(masked: str) -> list[str]:
    return [m.group(0) for m in PLACEHOLDER_RE.finditer(masked)]


def _stream(session, text: str, cuts: list[int]) -> str:
    unmasker = StreamUnmasker(session)
    out, last = [], 0
    for cut in [*cuts, len(text)]:
        out.append(unmasker.feed(text[last:cut]))
        last = cut
    out.append(unmasker.flush())
    return "".join(out)


@pytest.mark.parametrize("case_sensitive", [False, True])
@pytest.mark.parametrize(
    ("lemma", "form"),
    [
        ("Kiss Tóth", "Kiss Tóthtal"),
        ("Kiss Tóth", "Kiss Tóthtól"),
        ("Gipsz Kovácz", "Gipsz Kováczcal"),
        ("Gipsz Kovácz", "Gipsz Kovácznak"),
        ("Minta Tóth", "Minta Tóthtá"),
    ],
)
def test_old_digraph_forms_are_masked_and_round_trip(
    lemma: str, form: str, case_sensitive: bool
) -> None:
    session = _session(case_sensitive=case_sensitive)
    text = f"{lemma} jött. {form} beszéltem."
    masked = session.mask(text, [span_of(text, lemma, PERSON)])
    assert lemma.split()[-1] not in masked
    assert len(_tokens(masked)) == 2
    assert len(set(_tokens(masked))) == 1 or case_sensitive
    assert session.unmask(masked) == text


@pytest.mark.parametrize(
    ("lemma", "suffix", "expected"),
    [
        ("Kiss Tóth", "val", "Kiss Tóthtal"),
        ("Kiss Tóth", "al", "Kiss Tóthtal"),
        ("Kiss Tóth", "vel", "Kiss Tóthtel"),
        ("Kiss Tóth", "vá", "Kiss Tóthtá"),
        ("Kiss Tóth", "nak", "Kiss Tóthnak"),
        ("Gipsz Kovácz", "val", "Gipsz Kováczcal"),
        ("Gipsz Kovácz", "vel", "Gipsz Kováczcel"),
        ("Kovács", "val", "Kováccsal"),
        ("Elek", "vel", "Elekkel"),
        ("Próba Zsuzsanna", "ának", "Próba Zsuzsannának"),
        ("Próba Zsuzsanna", "ával", "Próba Zsuzsannával"),
        ("Próba Zsuzsanna", "nak", "Próba Zsuzsannának"),
        ("Próba Kende", "ének", "Próba Kendének"),
        ("Próba Zsuzsanna", "ként", "Próba Zsuzsannaként"),
    ],
)
def test_restore(lemma: str, suffix: str, expected: str) -> None:
    assert HU.restore(lemma, suffix, PERSON) == expected
    assert restore(HU, lemma, suffix, PERSON) == expected


def test_unmask_applies_restore_to_placeholders() -> None:
    session = _session()
    text = "Kiss Tóth jött. Próba Zsuzsanna is."
    masked = session.mask(
        text, [span_of(text, "Kiss Tóth", PERSON), span_of(text, "Próba Zsuzsanna", PERSON)]
    )
    tokens = _tokens(masked)
    assert session.unmask(f"{tokens[0]}val {tokens[1]}ának") == "Kiss Tóthtal Próba Zsuzsannának"
    assert session.unmask(f"{tokens[1]}ával") == "Próba Zsuzsannával"


def test_splits_old_digraphs() -> None:
    assert Split("Tóth", "Tóth", "tal") in HU.splits("Tóthtal", PERSON)
    assert Split("Kovácz", "Kovácz", "cal") in HU.splits("Kováczcal", PERSON)
    assert Split("Tóth", "Tóth", "tel") in HU.splits("Tóthtel", PERSON)


@pytest.mark.parametrize("answer_tail", ["val", "ának", "ával"])
def test_streaming_unmask_matches_at_every_split(answer_tail: str) -> None:
    session = _session()
    text = "Kiss Tóth jött. Próba Zsuzsanna is."
    masked = session.mask(
        text, [span_of(text, "Kiss Tóth", PERSON), span_of(text, "Próba Zsuzsanna", PERSON)]
    )
    tokens = _tokens(masked)
    token = tokens[0] if answer_tail == "val" else tokens[1]
    answer = f"{masked} {token}{answer_tail}"
    expected = session.unmask(answer)
    assert expected.endswith(("Kiss Tóthtal", "Próba Zsuzsannának", "Próba Zsuzsannával"))
    for cut in range(len(answer) + 1):
        assert _stream(session, answer, [cut]) == expected
    assert _stream(session, answer, list(range(1, len(answer)))) == expected
