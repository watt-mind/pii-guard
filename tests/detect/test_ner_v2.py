"""NER v2 (LAB-1150): identifier labels, the GLiNER backend's windows and label mapping.

No model is downloaded: backends are fakes. All values are fictional.
"""

from __future__ import annotations

import itertools

import pytest

from pii_guard.detect import ner_gliner
from pii_guard.detect.ner import (
    LABEL_MAP,
    NER_ENTITY_TYPES,
    NER_V1_ENTITY_TYPES,
    NerDetector,
    RawEntity,
)
from pii_guard.detect.pipeline import DetectionPipeline
from pii_guard.types import EntityType

V2_TYPES = {
    EntityType.EMAIL,
    EntityType.PHONE,
    EntityType.ID_DOCUMENT,
    EntityType.NATIONAL_ID_HU_TAX,
    EntityType.NATIONAL_ID_HU_TAJ,
    EntityType.BANK_ACCOUNT,
}


class FakeBackend:
    def __init__(self, entities: list[RawEntity]) -> None:
        self.entities = entities

    def predict(self, text: str) -> list[RawEntity]:
        return list(self.entities)


def test_v2_types_are_reported_with_their_own_labels() -> None:
    assert V2_TYPES <= NER_ENTITY_TYPES
    assert NER_V1_ENTITY_TYPES < NER_ENTITY_TYPES
    for t in V2_TYPES:
        assert LABEL_MAP[t.value] is t
    text = "Hívj a +9-559-028.9863 számon, adóazonosító 8123456789."
    raw = [
        RawEntity("PHONE", text.index("+9"), text.index(" számon"), 0.9),
        RawEntity("NATIONAL_ID_HU_TAX", text.index("8123"), text.index("8123") + 10, 0.8),
    ]
    spans = NerDetector(backend=FakeBackend(raw)).detect(text, "hu")
    assert [(s.entity_type, s.text) for s in spans] == [
        (EntityType.PHONE, "+9-559-028.9863"),
        (EntityType.NATIONAL_ID_HU_TAX, "8123456789"),
    ]


def test_validated_rule_span_keeps_its_boundaries_over_a_wider_ner_span() -> None:
    text = "Számlaszám: HU42 1177 3016 1111 1018 0000 0000 köszönöm"
    iban = "HU42 1177 3016 1111 1018 0000 0000"
    start = text.index(iban)
    # The NER runs one word too far; the rules' validated IBAN wins the boundaries.
    raw = [RawEntity("BANK_ACCOUNT", start, len(text), 0.7)]
    pipeline = DetectionPipeline(["rules", NerDetector(backend=FakeBackend(raw))])
    spans = [s for s in pipeline.detect(text, "hu") if s.entity_type is EntityType.BANK_ACCOUNT]
    assert spans and spans[0].text == iban


def test_word_windows_cover_the_text_with_overlap() -> None:
    text = " ".join(f"w{i}" for i in range(25))
    windows = ner_gliner.word_windows(text, size=10, overlap=2)
    assert windows[0][0] == 0 and windows[-1][1] == len(text)
    for (_, prev_end), (start, _) in itertools.pairwise(windows):
        assert start < prev_end  # overlapping
    assert ner_gliner.word_windows("   ") == []
    with pytest.raises(ValueError):
        ner_gliner.word_windows(text, size=4, overlap=4)


def test_gliner_labels_cover_every_ner_type() -> None:
    assert set(ner_gliner.GLINER_LABELS.values()) == NER_ENTITY_TYPES


def test_gliner_backend_shifts_offsets_and_maps_labels() -> None:
    backend = object.__new__(ner_gliner.GlinerBackend)
    backend.labels = dict(ner_gliner.GLINER_LABELS)
    backend.threshold = 0.3
    backend.window_words = 3
    backend.batch_size = 2
    import threading

    backend._lock = threading.Lock()
    text = "a b c Teszt Elek d e"

    class Model:
        def inference(self, chunks, labels, **kwargs):
            out = []
            for chunk in chunks:
                found = []
                if "Teszt" in chunk:
                    i = chunk.index("Teszt")
                    found.append({"start": i, "end": i + 5, "label": "person", "score": 0.9})
                found.append({"start": 0, "end": 1, "label": "unknown label", "score": 0.9})
                out.append(found)
            return out

    backend.model = Model()
    raw = backend.predict(text)
    assert RawEntity("PERSON", text.index("Teszt"), text.index("Teszt") + 5, 0.9) in raw
    assert all(e.label == "PERSON" for e in raw)


def test_gliner_checkpoint_detection(tmp_path) -> None:
    assert not ner_gliner.is_gliner_checkpoint(str(tmp_path))
    (tmp_path / "gliner_config.json").write_text("{}", encoding="utf-8")
    assert ner_gliner.is_gliner_checkpoint(str(tmp_path))


def test_gliner_backend_setting_picks_the_public_zero_shot_model(monkeypatch) -> None:
    from pii_guard.types import DetectionError

    monkeypatch.setenv("PII_GUARD_NER_BACKEND", "gliner")
    monkeypatch.delenv("PII_GUARD_NER_MODEL", raising=False)
    monkeypatch.delenv("PII_GUARD_NER_REVISION", raising=False)
    detector = NerDetector(preload=False)
    assert detector.backend_kind == "gliner"
    assert detector.model == ner_gliner.DEFAULT_MODEL
    assert detector.revision == ner_gliner.DEFAULT_REVISION
    monkeypatch.setattr(ner_gliner, "dependencies_available", lambda: False)
    with pytest.raises(DetectionError, match="gliner"):
        detector.load()


def test_ner_backend_setting_is_validated(monkeypatch) -> None:
    monkeypatch.setenv("PII_GUARD_NER_BACKEND", "spacy")
    with pytest.raises(ValueError, match="backend"):
        NerDetector(preload=False)
    monkeypatch.delenv("PII_GUARD_NER_BACKEND")
    assert NerDetector(preload=False).backend_kind == "transformers"


def test_settings_accept_the_ner_backend(monkeypatch) -> None:
    from pydantic import ValidationError

    from pii_guard.config import Settings

    monkeypatch.setenv("PII_GUARD_NER_BACKEND", "gliner")
    assert Settings().ner_backend == "gliner"
    monkeypatch.setenv("PII_GUARD_NER_BACKEND", "nope")
    with pytest.raises(ValidationError):
        Settings()
