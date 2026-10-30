"""Hungarian pack: which detector name spans are trimmed to their stem (LAB-1174).

All names are fictional (ADR 0005).
"""

from __future__ import annotations

import pytest

from pii_guard.detect.suffix_trim import trim_name_suffixes
from pii_guard.languages.hu.inflection import HungarianSuffixMatcher
from pii_guard.types import EntityType, Span
from pii_guard.vault import PLACEHOLDER_RE, Vault

E = EntityType
M = HungarianSuffixMatcher()
#: A stand-in for the pack's lexicons, so the cases don't depend on the lists' contents.
NAMES = frozenset(
    n.casefold()
    for n in (
        "Ottó", "Béla", "Zoltán", "Kornél", "Márton", "Simon", "Kelemen", "Gellért", "Klára",
        "Jakab", "Judit", "Kis", "Kiss", "Kovács", "Bálint", "Donát", "Máté",
    )
)  # fmt: skip


def is_name(word: str) -> bool:
    return word.casefold() in NAMES


@pytest.mark.parametrize(
    ("surface", "stem", "lemma", "suffix"),
    [
        # The ablative of the demo sample (LAB-1174), both vowel harmonies.
        ("Kerekes Ottótól", "Kerekes Ottó", "Kerekes Ottó", "tól"),
        ("KEREKES OTTÓTÓL", "KEREKES OTTÓ", "KEREKES OTTÓ", "TÓL"),
        ("Gyakorló Tihamértől", "Gyakorló Tihamér", "Gyakorló Tihamér", "től"),
        # A long case ending after an unknown name: no name ends in it.
        ("Gyakorló Tihamérnak", "Gyakorló Tihamér", "Gyakorló Tihamér", "nak"),
        ("Minta Ödönhöz", "Minta Ödön", "Minta Ödön", "höz"),
        ("Teszt Eleknek", "Teszt Elek", "Teszt Elek", "nek"),
        # A stem change: the vowel lengthens (strong) or the digraph doubles.
        ("Minta Hajnának", "Minta Hajná", "Minta Hajna", "nak"),
        ("Próba Szabolccsal", "Próba Szabolccs", "Próba Szabolcs", "al"),
        ("Minta Gergellyel", "Minta Gergelly", "Minta Gergely", "el"),
        # Short or ambiguous endings, applied because the lemma is a lexicon name.
        ("Minta Bélát", "Minta Bélá", "Minta Béla", "t"),
        ("Teszt Zoltánt", "Teszt Zoltán", "Teszt Zoltán", "t"),
        ("Próba Jakabbal", "Próba Jakab", "Próba Jakab", "bal"),
        ("Próba Kornélnak", "Próba Kornél", "Próba Kornél", "nak"),
        ("Kovácsnál", "Kovács", "Kovács", "nál"),
        # Stacked: -ék/-é/-éi, then a case ending (LAB-1337).
        ("Kerekes Ottóéknál", "Kerekes Ottó", "Kerekes Ottó", "éknál"),
        ("Minta Béláéknak", "Minta Bélá", "Minta Béla", "éknak"),
        ("Teszt Zoltánéit", "Teszt Zoltán", "Teszt Zoltán", "éit"),
    ],
)
def test_inflected_names_split_at_the_stem(
    surface: str, stem: str, lemma: str, suffix: str
) -> None:
    split = M.confident_split(surface, E.PERSON, is_name)
    assert split is not None
    assert (split.stem, split.lemma, split.suffix) == (stem, lemma, suffix)
    assert split.stem + split.suffix == surface


@pytest.mark.parametrize(
    "surface",
    [
        # Names that only look inflected: the last word is a name itself.
        "Próba Márton",  # -on
        "Próba Kornél",  # -nél
        "Teszt Simon",  # -on
        "Minta Kelemen",  # -en
        "Teszt Gellért",  # -ért
        "Minta Klára",  # -ra
        "Teszt Bálint",  # -t
        "Minta Judit",  # -t
        "Teszt Máté",  # -é
        "Minta Donát",  # lengthened a + t
        # Unknown names with an ambiguous ending: left to the vault (a confirmed lemma).
        "Minta Petra",
        "Teszt Zsolt",
        "Teszt Tihamérért",
        "Minta Dórát",
        # Two lexicon readings (Kis + sel, Kiss + el): no guess.
        "Teszt Kissel",
        # Not a name ending: nothing to split.
        "Kerekes Ottó",
        "Gyakorló Tihamér",
    ],
)
def test_names_that_only_look_inflected_stay_whole(surface: str) -> None:
    assert M.confident_split(surface, E.PERSON, is_name) is None


@pytest.mark.parametrize(
    ("value", "entity_type"),
    [("anna.minta@example.com", E.EMAIL), ("Minta Kft-nek", E.ORGANIZATION)],
)
def test_only_person_values_are_trimmed(value: str, entity_type: EntityType) -> None:
    assert M.confident_split(value, entity_type, is_name) is None


# --- a detector span that ends inside an -é/-ék/-éi chain (LAB-1384) -------------------------


def _span_ending(text: str, value: str) -> Span:
    start = text.index(value)
    return Span(start, start + len(value), E.PERSON, value, 0.9, "ner")


@pytest.mark.parametrize(
    ("text", "value", "stem", "lemma"),
    [
        # The NER cut between the family/possessive suffix and the case ending (LAB-1342 run).
        ("Tegnap Teszt Hajnáéknál voltunk.", "Teszt Hajnáék", "Teszt Hajná", "Teszt Hajna"),
        ("Hajnáéktól jött a levél.", "Hajnáék", "Hajná", "Hajna"),
        ("Gyakorló Tihaméréknek írtunk.", "Gyakorló Tihamérék", "Gyakorló Tihamér",
         "Gyakorló Tihamér"),
        ("Minta Hubáéval beszéltünk.", "Minta Hubáé", "Minta Hubá", "Minta Huba"),
        ("Hubáéinak küldtük el.", "Hubáéi", "Hubá", "Huba"),
        ("Teszt Elekékhez megyünk.", "Teszt Elekék", "Teszt Elek", "Teszt Elek"),
        ("TESZT HAJNÁÉKNÁL voltunk.", "TESZT HAJNÁÉK", "TESZT HAJNÁ", "TESZT HAJNA"),
    ],
)  # fmt: skip
def test_span_ending_inside_a_stacked_chain_is_trimmed_to_the_stem(
    text: str, value: str, stem: str, lemma: str
) -> None:
    (trimmed,) = trim_name_suffixes(text, [_span_ending(text, value)], "hu")
    assert trimmed.text == stem
    assert (trimmed.detector, trimmed.score) == ("ner", 0.9)
    session = Vault(b"k" * 32).session()
    masked = session.mask(text, [trimmed], language="hu")
    (placeholder,) = {m.group(0) for m in PLACEHOLDER_RE.finditer(masked)}
    assert session.unmask(placeholder) == lemma
    assert session.unmask(masked) == text
    assert lemma.split()[-1] not in masked  # nothing of the name leaks


def test_chain_cut_and_whole_forms_share_one_placeholder() -> None:
    """The LAB-1342 symptom: one person, several placeholders."""
    text = "Teszt Hajna írt. Tegnap Teszt Hajnáéknál voltunk, Teszt Hajnáéktól jöttünk."
    spans = [
        _span_ending(text, "Teszt Hajna "),
        _span_ending(text, "Teszt Hajnáék"),
        Span(text.rindex("Teszt Hajnáék"), text.rindex("Teszt Hajnáék") + 13, E.PERSON,
             "Teszt Hajnáék", 0.9, "ner"),
    ]  # fmt: skip
    spans[0] = Span(spans[0].start, spans[0].end - 1, E.PERSON, "Teszt Hajna", 0.9, "ner")
    trimmed = trim_name_suffixes(text, spans, "hu")
    session = Vault(b"k" * 32).session()
    masked = session.mask(text, trimmed, language="hu")
    assert len({m.group(0) for m in PLACEHOLDER_RE.finditer(masked)}) == 1
    assert "Hajn" not in masked
    assert session.unmask(masked) == text


@pytest.mark.parametrize(
    ("text", "value"),
    [
        # The span's last word is a name ending in -é itself: the case ending follows it.
        ("Teszt Mátének írtunk.", "Teszt Máté"),
        # Ends inside a word, but not in a chain: the detector chose that stem.
        ("Kerekes Ottótól jött.", "Kerekes Ottó"),
        # A chain-looking tail with nothing that is a case ending after it.
        ("Teszt Hajnáékxyz jött.", "Teszt Hajnáék"),
    ],
)
def test_other_spans_inside_a_word_are_unchanged(text: str, value: str) -> None:
    original = _span_ending(text, value)
    assert trim_name_suffixes(text, [original], "hu") == [original]


@pytest.mark.parametrize(
    ("text", "value", "stem"),
    [
        # Whole-word spans: the case ending is trimmed first, then the chain before it.
        ("Teszt Elekékhez megyünk.", "Teszt Elekékhez", "Teszt Elek"),
        ("Teszt Hajnáéknál voltunk.", "Teszt Hajnáéknál", "Teszt Hajná"),
        ("Gyakorló Tihaméréknek írtunk.", "Gyakorló Tihaméréknek", "Gyakorló Tihamér"),
    ],
)
def test_whole_word_span_with_a_stacked_chain_ends_at_the_name(
    text: str, value: str, stem: str
) -> None:
    (trimmed,) = trim_name_suffixes(text, [_span_ending(text, value)], "hu")
    assert trimmed.text == stem


@pytest.mark.parametrize(
    ("text", "value", "stem"),
    [
        # No confident case ending: the chain is read after a changed stem (Hajná -> Hajna).
        ("Hajnáékat értesítettük.", "Hajnáékat", "Hajná"),
        ("Minta Hubáéit holnap hozzák.", "Minta Hubáéit", "Minta Hubá"),
        ("Ez Minta Hubáé, rendben.", "Minta Hubáé", "Minta Hubá"),
        ("Próba Bencéék fizetnek.", "Próba Bencéék", "Próba Bencé"),
        # A lexicon name before the chain needs no stem change.
        ("Ez Teszt Zoltáné volt.", "Teszt Zoltáné", "Teszt Zoltán"),
    ],
)
def test_whole_word_chain_after_a_changed_stem_is_trimmed(text: str, value: str, stem: str) -> None:
    (trimmed,) = trim_name_suffixes(text, [_span_ending(text, value)], "hu")
    assert trimmed.text == stem


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("A levelet Teszt Máté írta.", "Teszt Máté"),  # a name ending in -é
        ("Ez Gyakorló Tiharéké volt.", "Gyakorló Tiharéké"),  # unknown name, no stem change
    ],
)
def test_whole_word_chain_without_evidence_stays_whole(text: str, value: str) -> None:
    original = _span_ending(text, value)
    assert trim_name_suffixes(text, [original], "hu") == [original]
