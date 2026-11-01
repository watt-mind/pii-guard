"""Hungarian old orthography (``th``, ``cz``), triple-consonant simplification and long vowels.

All names are fictional (ADR 0005).
"""

from __future__ import annotations

import pytest
from vault_helpers import TEST_KEY, span_of

from pii_guard.languages.hu.inflection import HungarianSuffixMatcher
from pii_guard.types import EntityType, Span
from pii_guard.vault import PLACEHOLDER_RE, StreamUnmasker, Vault
from pii_guard.vault.inflection import Split, restore
from pii_guard.vault.known import KnownValue

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
        ("Erika Mustermann", "Erika Mustermannak"),
        ("Erika Mustermann", "Erika Mustermannál"),
        ("Teszt Mariann", "Teszt Mariannak"),
        ("Minta Bernadett", "Minta Bernadettől"),
        ("Minta Bernadett", "Minta Bernadettel"),
    ],
)
def test_old_digraph_and_doubled_consonant_forms_are_masked_and_round_trip(
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
        ("Kiss Tóth", "vel", "Kiss Tóthtal"),  # re-harmonized (LAB-1152)
        ("Kiss Tóth", "vá", "Kiss Tóthtá"),
        ("Kiss Tóth", "nak", "Kiss Tóthnak"),
        ("Gipsz Kovácz", "val", "Gipsz Kováczcal"),
        ("Gipsz Kovácz", "vel", "Gipsz Kováczcal"),  # re-harmonized
        ("Kovács", "val", "Kováccsal"),
        ("Elek", "vel", "Elekkel"),
        ("Próba Zsuzsanna", "ának", "Próba Zsuzsannának"),
        ("Próba Zsuzsanna", "ával", "Próba Zsuzsannával"),
        ("Próba Zsuzsanna", "nak", "Próba Zsuzsannának"),
        ("Próba Kende", "ének", "Próba Kendének"),
        ("Próba Zsuzsanna", "ként", "Próba Zsuzsannaként"),
        ("Erika Mustermann", "nak", "Erika Mustermannak"),
        ("Erika Mustermann", "nál", "Erika Mustermannál"),
        ("Teszt Mariann", "nak", "Teszt Mariannak"),
        ("Minta Bernadett", "től", "Minta Bernadettől"),
        ("Minta Bernadett", "tól", "Minta Bernadettől"),  # re-harmonized + AkH. 62
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


def test_splits_old_digraphs_and_simplified_triple_consonants() -> None:
    assert Split("Tóth", "Tóth", "tal") in HU.splits("Tóthtal", PERSON)
    assert Split("Kovácz", "Kovácz", "cal") in HU.splits("Kováczcal", PERSON)
    assert Split("Tóth", "Tóth", "tel") in HU.splits("Tóthtel", PERSON)
    assert Split("Erika Mustermann", "Erika Mustermann", "ak") in HU.splits(
        "Erika Mustermannak", PERSON
    )
    assert Split("Minta Bernadett", "Minta Bernadett", "ől") in HU.splits(
        "Minta Bernadettől", PERSON
    )
    # Bare -n/-t never attaches directly to n/t, so doubled-consonant names are not split as +n/+t.
    assert Split("Erika Musterman", "Erika Musterman", "n") not in HU.splits(
        "Erika Mustermann", PERSON
    )
    assert Split("Minta Bernadet", "Minta Bernadet", "t") not in HU.splits(
        "Minta Bernadett", PERSON
    )


def test_subword_ner_cut_at_triple_consonant_boundary_widens_to_confirmed_lemma() -> None:
    """When a subword NER tokenizer stops before ``nak`` in ``Erika Mustermannak`` (yielding
    ``Erika Musterman`` with one ``n``), the vault widens the stem to ``Erika Mustermann`` and
    keeps one placeholder without leaving a dangling ``n`` on ``Erika Mustermann``."""
    session = _session()
    session.known_values.add([KnownValue("Erika Mustermann", PERSON)])
    text = "Vevő: Erika Mustermann. Az eladó eladja a vevőnek, Erika Mustermannak az ingóságot."
    cut = text.index("Erika Mustermannak")
    spans = [
        span_of(text, "Erika Mustermann", PERSON),
        Span(cut, cut + len("Erika Musterman"), PERSON, "Erika Musterman", 0.99, "ner"),
    ]
    masked = session.mask(text, spans, language="hu")
    tokens = _tokens(masked)
    assert len(tokens) == 2 and len(set(tokens)) == 1
    assert f"{tokens[0]}." in masked  # no dangling 'n' after the placeholder
    assert f"{tokens[0]}ak " in masked
    assert session.unmask(tokens[0]) == "Erika Mustermann"
    assert session.unmask(masked) == text


@pytest.mark.parametrize(
    ("name", "text", "common_words"),
    [
        ("Ann", "Ann jött. Ez annak a jele, annál jobb.", ["annak", "annál"]),
        ("Finn", "Finn jött. A finnek és a finnél?", ["finnek", "finnél"]),
    ],
)
def test_short_doubled_names_do_not_mask_common_words(
    name: str, text: str, common_words: list[str]
) -> None:
    """``annak``/``finnek`` are everyday words, not ``Ann``/``Finn`` + simplified suffix."""
    session = _session()
    masked = session.mask(text, [span_of(text, name, PERSON)], language="hu")
    for word in common_words:
        assert word in masked
    assert session.unmask(masked) == text


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


# --- restore() changes the stem of names only (found in review of LAB-1194) ----------------


@pytest.mark.parametrize(
    ("value", "entity_type", "suffix", "expected"),
    [
        ("anna@firma.de", EntityType.EMAIL, "re", "anna@firma.dere"),
        ("anna@firma.de", EntityType.EMAIL, "nak", "anna@firma.denak"),
        ("info@bit.ly", EntityType.EMAIL, "val", "info@bit.lyval"),
        ("123456AB", EntityType.ID_DOCUMENT, "vel", "123456ABvel"),
        ("AB123456", EntityType.ID_DOCUMENT, "nak", "AB123456nak"),
        # A word-like value of a non-name type keeps its spelling too.
        ("Próba Zsuzsanna", EntityType.EMAIL, "nak", "Próba Zsuzsannanak"),
        # An e-mail address labelled as a name is still not word-like.
        ("anna@firma.de", PERSON, "re", "anna@firma.dere"),
        # Names keep their stem changes.
        ("Próba Zsuzsanna", PERSON, "nak", "Próba Zsuzsannának"),
        ("Minta utca", EntityType.ADDRESS, "ban", "Minta utcában"),
        ("Kiss Tóth", EntityType.ORGANIZATION, "val", "Kiss Tóthtal"),
    ],
)
def test_restore_changes_the_stem_of_names_only(
    value: str, entity_type: EntityType, suffix: str, expected: str
) -> None:
    assert HU.restore(value, suffix, entity_type) == expected


@pytest.mark.parametrize("case_sensitive", [False, True])
@pytest.mark.parametrize(
    ("value", "entity_type", "suffix"),
    [
        ("anna@firma.de", "EMAIL", "re"),
        ("info@bit.ly", "EMAIL", "val"),
        ("123456AB", "ID_DOCUMENT", "vel"),
    ],
)
def test_unmask_appends_suffix_to_emails_and_ids(
    value: str, entity_type: str, suffix: str, case_sensitive: bool
) -> None:
    session = _session(case_sensitive=case_sensitive)
    text = f"Írj ide: {value} ma."
    masked = session.mask(text, [span_of(text, value, entity_type)])
    (token,) = _tokens(masked)
    answer = f"Írtam {token}{suffix}."
    assert session.unmask(answer) == f"Írtam {value}{suffix}."
    assert _stream(session, answer, list(range(1, len(answer)))) == session.unmask(answer)
