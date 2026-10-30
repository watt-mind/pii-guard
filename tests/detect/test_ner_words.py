"""NER spans of the text types snap to whole words (LAB-1338).

All names are fictional (ADR 0005).
"""

from __future__ import annotations

import pytest

from pii_guard.detect.ner import NerDetector, RawEntity
from pii_guard.detect.ner_words import snap_to_tokens, snap_to_words
from pii_guard.detect.pipeline import DetectionPipeline
from pii_guard.detect.rules import RuleDetector
from pii_guard.types import EntityType, Span
from pii_guard.vault import PLACEHOLDER_RE, Vault

E = EntityType
KEY = b"k" * 32


class FakeBackend:
    def __init__(self, raw: list[RawEntity]) -> None:
        self.raw = raw

    def predict(self, text: str) -> list[RawEntity]:
        return list(self.raw)


def fragment(text: str, value: str, label: str = "PERSON", nth: int = 0) -> RawEntity:
    start = -1
    for _ in range(nth + 1):
        start = text.index(value, start + 1)
    return RawEntity(label, start, start + len(value), 0.95)


def ner_spans(text: str, *raw: RawEntity) -> list[str]:
    return [s.text for s in NerDetector(backend=FakeBackend(list(raw))).detect(text, "hu")]


@pytest.mark.parametrize(
    ("text", "value", "expected"),
    [
        # The fragments the ticket reports (start and/or end inside a word).
        ("A számlát Teszt Eleknek adtuk át.", "szt", "Teszt"),
        ("A levelet Próba Piroskáról kaptuk.", "osk", "Piroskáról"),
        ("Holnap Próba Tihamérért jön.", "hamér", "Tihamér"),
        ("A levelet Teszt Piroskáról kaptuk.", "szt Pirosk", "Teszt Piroskáról"),
        ("Egyeztettünk Gyakorló Jakabbal.", "ló Jakab", "Gyakorló Jakab"),
        ("Holnap Teszt Kelemen jön.", "szt", "Teszt"),
        ("Kérem, hívja vissza Teszt Piroska a héten.", "o", "Piroska"),
        # An end inside a word off any stem the pack reads goes to the word's end, also
        # when a weak reading (Kelem + en) exists: no stem is guessed.
        ("Holnap Teszt Kelemen jön.", "Teszt Kel", "Teszt Kelemen"),
        ("Holnap Teszt Kelemen jön.", "Teszt Kelem", "Teszt Kelem"),
    ],
)
def test_fragments_snap_to_words(text: str, value: str, expected: str) -> None:
    assert ner_spans(text, fragment(text, value)) == [expected]


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Holnap Minta Pétert hívjuk.", "Minta Péter"),  # stem before -t
        ("A választ Gyakorló Tihamérnak küldtük.", "Gyakorló Tihamér"),
        ("Minta Hajnának írtunk.", "Minta Hajná"),  # lengthened stem as written
        ("Teszt Elek írt nekünk.", "Teszt Elek"),
    ],
)
def test_word_and_stem_boundaries_are_kept(text: str, value: str) -> None:
    assert ner_spans(text, fragment(text, value)) == [value]


def test_other_types_keep_model_boundaries() -> None:
    text = "Azonosító: AB123456CD, köszönöm."
    raw = fragment(text, "123456", "ID_DOCUMENT")
    spans = snap_to_words(text, [Span(raw.start, raw.end, E.ID_DOCUMENT, "123456", 0.9, "ner")])
    assert [s.text for s in spans] == ["123456"]


def test_overlapping_fragments_merge() -> None:
    text = "Holnap Gyakorló Gergellyel egyeztetünk."
    spans = ner_spans(text, fragment(text, "Gy"), fragment(text, "ló Gergel"))
    assert spans == ["Gyakorló Gergellyel"]


def test_snap_runs_before_suffix_trim_and_vault() -> None:
    """A fragment snapped to the whole inflected name is trimmed to its stem; nothing leaks."""
    text = "A számlát Teszt Eleknek adtuk át. Teszt Elek holnap jön."
    raw = [fragment(text, "szt Elek"), fragment(text, "Teszt Elek", nth=1)]
    pipeline = DetectionPipeline([RuleDetector(), NerDetector(backend=FakeBackend(raw))])
    spans = pipeline.detect(text, "hu")
    session = Vault(KEY).session()
    out = session.mask(text, spans, language="hu")
    assert "Teszt" not in out and "Elek" not in out
    placeholders = {m.group(0) for m in PLACEHOLDER_RE.finditer(out)}
    assert len(placeholders) == 1
    assert {session.unmask(p) for p in placeholders} == {"Teszt Elek"}
    assert session.unmask(out) == text


@pytest.mark.parametrize(
    ("text", "value", "stem"),
    [
        ("Beutaló. Háziorvos: Kerekes Ottótól kaptuk a beutalót.", "rekes Ot", "Kerekes Ottó"),
        ("A levelet Teszt Piroskáról kaptuk.", "szt Pirosk", "Teszt Piroská"),
        ("Holnap Gyakorló Gergellyel egyeztetünk.", "ló Gergel", "Gyakorló Gergelly"),
    ],
)
def test_word_end_extension_then_trimmed_by_suffix_trim(text: str, value: str, stem: str) -> None:
    """A fragment that ends off a stem extends to the word, then LAB-1174 trims it."""
    raw = [fragment(text, value)]
    pipeline = DetectionPipeline([RuleDetector(), NerDetector(backend=FakeBackend(raw))])
    spans = [s for s in pipeline.detect(text, "hu") if s.entity_type is E.PERSON]
    assert [s.text for s in spans] == [stem]


# --- Structured types cover whole tokens (LAB-1367) --------------------------------------

_ROW = (
    "nev,email,telefon,adoazonosito\n"
    "Kozák Gabriella,g.kozak@example.org,06-20-751-6714,8461269321,ORD-1\n"
)


@pytest.mark.parametrize(
    ("text", "value", "label", "expected"),
    [
        (_ROW, "8461269", "NATIONAL_ID_HU_TAX", "8461269321"),  # end inside the run
        (_ROW, "1269321", "NATIONAL_ID_HU_TAX", "8461269321"),  # start inside the run
        (_ROW, "6-20-751", "PHONE", "06-20-751-6714"),  # across "-" between digits
        ("Ausweis 812.754.113.91, danke", "812.754.11", "ID_DOCUMENT", "812.754.113.91"),
        ("Azonosító: AB123456CD, köszönöm.", "123456", "ID_DOCUMENT", "AB123456CD"),
        ("Tel.: +36 30 123 4567.", "30 12", "PHONE", "30 123"),  # a space doesn't join
    ],
)
def test_number_fragments_snap_to_tokens(text: str, value: str, label: str, expected: str) -> None:
    raw = fragment(text, value, label)
    spans = snap_to_tokens(text, [Span(raw.start, raw.end, E(label), value, 0.9, "ner")])
    assert [s.text for s in spans] == [expected]


def test_number_snap_keeps_whole_tokens_and_text_types() -> None:
    text = "Adószám: 8461269321, Kozák Gabriella."
    whole = fragment(text, "8461269321", "NATIONAL_ID_HU_TAX")
    name = fragment(text, "Gabriella")
    spans = [
        Span(whole.start, whole.end, E.NATIONAL_ID_HU_TAX, "8461269321", 0.9, "ner"),
        Span(name.start, name.end, E.PERSON, "Gabriella", 0.9, "ner"),
    ]
    assert snap_to_tokens(text, spans) == spans
    # A date or amount next to the number is not joined through the space or the comma.
    assert [
        s.text
        for s in snap_to_tokens(
            "x 2024-05 8461269321,50",
            [Span(10, 20, E.NATIONAL_ID_HU_TAX, "8461269321", 0.9, "ner")],
        )
    ] == ["8461269321"]


def test_ner_pieces_of_one_number_cover_it_and_mask_it_whole() -> None:
    """Two pieces of a tax number, one labelled PHONE: no digit is left next to the mask."""
    text = "Kozák Gabriella,g.kozak@example.org,+36 1 389 4443,8461269321,ORD-1"
    start = text.index("8461269321")
    raw = [
        RawEntity("PHONE", start, start + 3, 0.9),
        RawEntity("NATIONAL_ID_HU_TAX", start + 3, start + 6, 0.6),
    ]
    ner = NerDetector(backend=FakeBackend(raw), number_checks=False)
    # The lexicon name rule (LAB-1606) also finds the name in the first cell.
    assert {s.text for s in ner.detect(text, "hu")} == {"8461269321", "Kozák Gabriella"}
    pipeline = DetectionPipeline([NerDetector(backend=FakeBackend(raw))])
    session = Vault(KEY).session()
    out = session.mask(text, pipeline.detect(text, "hu"), language="hu")
    cell = out.split(",")[3]
    assert PLACEHOLDER_RE.fullmatch(cell), "the whole cell is one placeholder"
    assert session.unmask(out) == text


def test_pieces_of_different_types_on_one_token_keep_the_majority_type() -> None:
    text = "Adatok: 8461269321, köszönöm."
    start = text.index("8461269321")
    spans = [
        Span(start, start + 3, E.PHONE, "846", 0.98, "ner"),
        Span(start + 3, start + 9, E.NATIONAL_ID_HU_TAX, "126932", 0.6, "ner"),
    ]
    (span,) = snap_to_tokens(text, spans)
    assert (span.text, span.entity_type) == ("8461269321", E.NATIONAL_ID_HU_TAX)


# LAB-1359: the model tags the given name and leaves out the surname before it when the
# surname is also an everyday word (``Fekete [[PERSON]]ért``). A capitalised word from the
# pack's ``surnames`` lexicon directly before a PERSON span joins the span.
@pytest.mark.parametrize(
    ("text", "value", "expected"),
    [
        ("A levelet Fekete Tihamérért kaptuk meg tegnap.", "Tihamér", "Fekete Tihamér"),
        ("Kerekes Elek írta alá a szerződést.", "Elek", "Kerekes Elek"),
        ("Kérem, hívja vissza Kerekes Piroska a héten.", "Piroska", "Kerekes Piroska"),
        # A double surname joins whole, not only its last part.
        ("Holnap Fekete-Kerekes Ottó jön.", "Ottó", "Fekete-Kerekes Ottó"),
        # A sub-word fragment snaps first, then takes the surname.
        ("A levelet Fekete Tihamérért kaptuk meg tegnap.", "hamér", "Fekete Tihamér"),
    ],
)
def test_preceding_lexicon_surname_joins_the_person_span(
    text: str, value: str, expected: str
) -> None:
    assert ner_spans(text, fragment(text, value)) == [expected]


@pytest.mark.parametrize(
    ("text", "value", "label"),
    [
        # Lowercase: the everyday word, not a surname.
        ("A fekete Tihamér nevű ló nyert.", "Tihamér", "PERSON"),
        # A capitalised word that is not in the surnames lexicon (fictional test surname).
        ("Holnap Teszt Elek jön.", "Elek", "PERSON"),
        # Not directly before the span (punctuation, two spaces, a line break).
        ("Ezt mondta Fekete, Elek pedig hallgatott.", "Elek", "PERSON"),
        ("Holnap Fekete  Elek jön.", "Elek", "PERSON"),
        ("Fekete\nElek jön.", "Elek", "PERSON"),
        # Only PERSON spans take a surname: a company keeps its own boundaries.
        ("A szerződést Fekete Gépész Kft. írta alá.", "Gépész Kft.", "ORGANIZATION"),
    ],
)
def test_surname_join_needs_a_capitalised_lexicon_surname_right_before(
    text: str, value: str, label: str
) -> None:
    assert ner_spans(text, fragment(text, value, label)) == [value]


def test_surname_join_is_hungarian_lexicon_driven_and_round_trips() -> None:
    text = "A levelet Fekete Tihamérért kaptuk meg tegnap."
    raw = [fragment(text, "Tihamér")]
    assert [s.text for s in NerDetector(backend=FakeBackend(raw)).detect(text, "en")] == [
        "Tihamérért"
    ], "no surnames lexicon for English: the span only snaps to the word"
    pipeline = DetectionPipeline([RuleDetector(), NerDetector(backend=FakeBackend(raw))])
    session = Vault(KEY).session()
    out = session.mask(text, pipeline.detect(text, "hu"), language="hu")
    assert "Fekete" not in out and "Tihamér" not in out
    assert session.unmask(out) == text


# LAB-1606: the model emitted no span for a common-word surname + inflected given name
# (``Fekete Piroskáról``), so the join above had nothing to extend. A capitalised lexicon
# surname + a capitalised lexicon given name (bare or inflected) is a PERSON span.
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("A számlát Fekete Piroskáról adtuk át.", "Fekete Piroská"),  # stem as written
        ("A levelet Fekete Bélát kaptuk meg tegnap.", "Fekete Bélá"),
        ("Holnap Kovács Zoltánnal egyeztetünk.", "Kovács Zoltán"),
        ("Molnár Anna Mária írta alá.", "Molnár Anna Mária"),
        ("Holnap Fekete-Szabó Ilonának írunk.", "Fekete-Szabó Iloná"),
    ],
)
def test_lexicon_surname_and_given_name_without_a_model_span(text: str, expected: str) -> None:
    pipeline = DetectionPipeline([RuleDetector(), NerDetector(backend=FakeBackend([]))])
    assert [s.text for s in pipeline.detect(text, "hu")] == [expected]
    session = Vault(KEY).session()
    out = session.mask(text, pipeline.detect(text, "hu"), language="hu")
    assert all(word not in out for word in expected.replace("-", " ").split())
    assert session.unmask(out) == text


@pytest.mark.parametrize(
    "text",
    [
        "A fekete Béla nevű ló nyert.",  # lowercase: the everyday word
        "Holnap Teszt Béla jön.",  # not a lexicon surname (fictional test surname)
        "Holnap Fekete Gépész jön.",  # not a given name
        "Ezt mondta Fekete, Béla pedig hallgatott.",  # punctuation between
        "Holnap Fekete  Béla jön.",  # two spaces
        "Fekete\nBéla jön.",  # line break
        "Holnap Fekete béla jön.",  # lowercase given name
        "A Kovács Lajos utca 3. alatt lakunk.",  # a street name, not a person
        "A Kovács Lajos utcában lakunk.",
    ],
)
def test_lexicon_name_needs_both_capitalised_lexicon_words_side_by_side(text: str) -> None:
    assert ner_spans(text) == []


def test_lexicon_name_keeps_a_model_span_over_it_and_needs_a_hungarian_lexicon() -> None:
    text = "A szerződést Fekete Béla Kft. írta alá."
    assert ner_spans(text, fragment(text, "Fekete Béla Kft.", "ORGANIZATION")) == [
        "Fekete Béla Kft."
    ]
    text = "Holnap Kovács Zoltánnal egyeztetünk."
    assert [s.text for s in NerDetector(backend=FakeBackend([])).detect(text, "en")] == []
    assert ner_spans(text, fragment(text, "Zoltán")) == ["Kovács Zoltán"]
