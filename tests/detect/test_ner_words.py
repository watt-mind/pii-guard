"""NER spans of the text types snap to whole words (LAB-1338).

All names are fictional (ADR 0005).
"""

from __future__ import annotations

import pytest

from pii_guard.detect.ner import NerDetector, RawEntity
from pii_guard.detect.ner_words import snap_to_words
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
