"""NER on delimited rows (LAB-1258): cells glued by ``,``/``;`` are separated for the model.

With a mocked backend: the model sees each glued delimiter as a space (same length, so offsets
hold), and a span the model runs across a cell boundary is cut there. All data is fictional.
"""

from __future__ import annotations

from pii_guard.detect.ner import NerDetector, RawEntity, model_view
from pii_guard.types import EntityType

ROW = "2,Teszt Elek,teszt.elek@example.com,+36 30 123 4567\n"


class RecordingBackend:
    def __init__(self, entities: list[RawEntity] | None = None) -> None:
        self.entities = entities or []
        self.seen: list[str] = []

    def predict(self, text: str) -> list[RawEntity]:
        self.seen.append(text)
        return list(self.entities)

    def predict_batch(self, texts: list[str]) -> list[list[RawEntity]]:
        return [self.predict(t) for t in texts]


def at(text: str, value: str, label: str = "PER", score: float = 0.9) -> RawEntity:
    start = text.index(value)
    return RawEntity(label, start, start + len(value), score)


def test_model_view_spaces_delimiters_glued_to_a_capital() -> None:
    view, cuts = model_view(ROW)
    assert len(view) == len(ROW)
    assert view == "2 Teszt Elek,teszt.elek@example.com,+36 30 123 4567\n"
    assert cuts == (1,)
    assert model_view("id;Ádám Kis") == ("id Ádám Kis", (2,))


def test_model_view_leaves_prose_numbers_and_headers_alone() -> None:
    texts = ("Dear Anna, thanks; see you.", "1,5 millió forint", "a;1;2", "id,name,tax_id", "")
    for text in texts:
        assert model_view(text) == (text, ())


def test_backend_sees_the_spaced_row() -> None:
    backend = RecordingBackend()
    NerDetector(backend=backend).detect(ROW, "hu")
    assert backend.seen == [model_view(ROW)[0]]


def test_batch_backend_sees_the_spaced_rows() -> None:
    backend = RecordingBackend()
    NerDetector(backend=backend).detect_batch([ROW, "Dear Anna,"], "hu")
    assert backend.seen == [model_view(ROW)[0], "Dear Anna,"]


def test_whole_name_in_a_cell_is_found() -> None:
    backend = RecordingBackend([at(ROW, "Teszt Elek")])
    spans = NerDetector(backend=backend).detect(ROW, "hu")
    assert [(s.text, s.entity_type) for s in spans] == [("Teszt Elek", EntityType.PERSON)]


def test_span_across_cells_is_cut_at_the_delimiter() -> None:
    text = "7;Peter Nagy;Szeged;active\n"
    backend = RecordingBackend([at(text, "Peter Nagy;Szeged")])
    spans = NerDetector(backend=backend).detect(text, "en")
    assert sorted(s.text for s in spans) == ["Peter Nagy", "Szeged"]
    assert all(";" not in s.text for s in spans)


def test_model_view_leaves_all_caps_reference_cells_glued() -> None:
    # LAB-1648: spacing ",ORD-…" glued the order number to the ID before it, and the model
    # dropped the ID. Only a capitalised word (a name's start) is a cell boundary to space.
    row = '"Isla Ellison",islaellison@example.net,020 7946 0650,610456508,ORD-2026-481850,26.82\n'
    assert model_view(row) == (row, ())
    assert model_view("x,100000000,SO7466927,1.25") == ("x,100000000,SO7466927,1.25", ())
    assert model_view("1,O'Brien Kate;J. Smith") == ("1 O'Brien Kate J. Smith", (1, 14))
