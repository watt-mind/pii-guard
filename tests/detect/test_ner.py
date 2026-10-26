"""NER detector: decoding, thresholds, offsets and fail-closed behaviour, with mocked models.

Nothing here downloads a model. Tests that need torch/transformers (the ``ner`` extra) build a
tiny word-level tokenizer and a model stub in ``tmp_path`` and are skipped without the extra.
All text is fictional.
"""

from __future__ import annotations

import pytest

from pii_guard.detect import ner
from pii_guard.detect.ner import (
    NerDetector,
    RawEntity,
    decode_tokens,
    dependencies_available,
    merge_entities,
)
from pii_guard.detect.pipeline import DetectionPipeline
from pii_guard.registry import resolve_detector
from pii_guard.types import DetectionError, EntityType, Span


class FakeBackend:
    def __init__(self, entities: list[RawEntity] | None = None, error: Exception | None = None):
        self.entities = entities or []
        self.error = error
        self.calls = 0

    def predict(self, text: str) -> list[RawEntity]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.entities)


def at(text: str, value: str, label: str, score: float = 0.9, nth: int = 0) -> RawEntity:
    start = -1
    for _ in range(nth + 1):
        start = text.index(value, start + 1)
    return RawEntity(label, start, start + len(value), score)


# -- decode_tokens --


def test_decode_first_aggregation_spans_whole_words() -> None:
    # "Teszt Eleknek" -> tokens: <s> ▁Teszt ▁Elek nek </s>
    offsets = [(0, 0), (0, 5), (6, 10), (10, 13), (0, 0)]
    word_ids = [None, 0, 1, 1, None]
    labels = ["O", "B-PER", "I-PER", "O", "O"]
    scores = [1.0, 0.9, 0.7, 0.2, 1.0]
    assert decode_tokens(offsets, word_ids, labels, scores) == [RawEntity("PER", 0, 13, 0.8)]


def test_decode_token_aggregation_leaves_suffix_out() -> None:
    offsets = [(0, 5), (6, 11), (11, 12)]  # "Kiss Pétert": ▁Kiss ▁Péter t
    word_ids = [0, 1, 1]
    labels = ["B-PERSON", "I-PERSON", "O"]
    out = decode_tokens(offsets, word_ids, labels, [0.9, 0.9, 0.9], aggregation="token")
    assert out == [RawEntity("PERSON", 0, 11, pytest.approx(0.9))]


def test_decode_token_aggregation_joins_subwords_after_b() -> None:
    # A stray B- on a continuation sub-token does not split a word.
    out = decode_tokens(
        [(0, 3), (3, 6)], [0, 0], ["B-ORG", "B-ORG"], [0.8, 0.6], aggregation="token"
    )
    assert out == [RawEntity("ORG", 0, 6, pytest.approx(0.7))]


def test_decode_consecutive_b_tags_are_separate_entities() -> None:
    offsets = [(0, 4), (5, 9)]
    out = decode_tokens(offsets, [0, 1], ["B-PER", "B-PER"], [0.9, 0.8])
    assert [(e.start, e.end) for e in out] == [(0, 4), (5, 9)]


def test_decode_type_change_and_bioes_prefixes() -> None:
    offsets = [(0, 4), (5, 9), (10, 14), (15, 19)]
    labels = ["S-PER", "B-LOC", "E-LOC", "I-ORG"]
    out = decode_tokens(offsets, [0, 1, 2, 3], labels, [1.0] * 4)
    assert [(e.label, e.start, e.end) for e in out] == [
        ("PER", 0, 4),
        ("LOC", 5, 14),
        ("ORG", 15, 19),
    ]


def test_decode_validates_arguments() -> None:
    with pytest.raises(ValueError, match="same length"):
        decode_tokens([(0, 1)], [0], [], [])
    with pytest.raises(ValueError, match="aggregation"):
        decode_tokens([], [], [], [], aggregation="max")


def test_merge_entities_unions_window_overlaps() -> None:
    merged = merge_entities(
        [
            RawEntity("PER", 10, 20, 0.6),
            RawEntity("PER", 15, 25, 0.8),
            RawEntity("ORG", 15, 25, 0.9),
            RawEntity("PER", 30, 35, 0.7),
        ]
    )
    assert merged == [
        RawEntity("PER", 10, 25, 0.8),
        RawEntity("ORG", 15, 25, 0.9),
        RawEntity("PER", 30, 35, 0.7),
    ]


# -- NerDetector with a fake backend --

TEXT = (
    "Teszt Elek, a Kitalált Ingatlan Kft. ügyvezetője, 1051 Budapest, Minta utca 12. alatt lakik."
)


def test_detector_maps_labels_and_trims() -> None:
    raw = [
        at(TEXT, "Teszt Elek,", "PER"),
        at(TEXT, "Kitalált Ingatlan Kft.", "ORG"),
        at(TEXT, "1051 Budapest, Minta utca 12.", "LOC"),
        at(TEXT, "alatt", "DATE"),  # unmapped labels are ignored
    ]
    detector = NerDetector(backend=FakeBackend(raw))
    spans = detector.detect(TEXT, "hu")
    assert [(s.entity_type, s.text) for s in spans] == [
        (EntityType.PERSON, "Teszt Elek"),
        (EntityType.ORGANIZATION, "Kitalált Ingatlan Kft."),
        (EntityType.ADDRESS, "1051 Budapest, Minta utca 12."),
    ]
    assert all(TEXT[s.start : s.end] == s.text and s.detector == "ner" for s in spans)


def test_person_loses_trailing_dot_but_org_keeps_it() -> None:
    text = "Signed by Mia Fairbanks. Acme Ltd."
    raw = [at(text, "Mia Fairbanks.", "PERSON"), at(text, "Acme Ltd.", "ORGANIZATION")]
    spans = NerDetector(backend=FakeBackend(raw)).detect(text, "en")
    assert [s.text for s in spans] == ["Mia Fairbanks", "Acme Ltd."]


def test_punctuation_only_entities_are_dropped() -> None:
    text = "Hello, (world)"
    spans = NerDetector(backend=FakeBackend([RawEntity("PER", 5, 7, 0.99)])).detect(text)
    assert spans == []


def test_thresholds_per_language_with_default_fallback() -> None:
    text = "Anna Smith met Kovács Anna."
    raw = [at(text, "Anna Smith", "PER", 0.7), at(text, "Kovács Anna", "PER", 0.7)]
    detector = NerDetector(
        backend=FakeBackend(raw),
        thresholds={"en": {"PERSON": 0.8}, "default": {EntityType.PERSON: 0.6}},
    )
    assert detector.detect(text, "en-GB") == []
    assert len(detector.detect(text, "hu")) == 2  # no "hu" table: the default applies
    assert detector.threshold("de", EntityType.PERSON) == 0.6
    assert detector.threshold("en", EntityType.ADDRESS) == 0.5


def test_threshold_values_are_validated() -> None:
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        NerDetector(backend=FakeBackend(), thresholds={"hu": {"PERSON": 1.5}})


def test_entity_types_filter_and_validation() -> None:
    text = "Teszt Elek, Minta Kft."
    raw = [at(text, "Teszt Elek", "PER"), at(text, "Minta Kft.", "ORG")]
    detector = NerDetector(backend=FakeBackend(raw), entity_types=["PERSON"])
    assert [s.entity_type for s in detector.detect(text)] == [EntityType.PERSON]
    with pytest.raises(ValueError, match="subset"):
        NerDetector(backend=FakeBackend(), entity_types=["EMAIL"])


def test_custom_label_map() -> None:
    text = "Teszt Elek"
    detector = NerDetector(
        backend=FakeBackend([RawEntity("NAME", 0, 10, 0.9)]), label_map={"NAME": "PERSON"}
    )
    assert detector.detect(text)[0].entity_type is EntityType.PERSON


def test_unicode_offsets_are_code_points() -> None:
    text = "🙂 Ügyfél: Őri Zsuzsannának írtunk."
    raw = [at(text, "Őri Zsuzsannának", "PER")]
    span = NerDetector(backend=FakeBackend(raw)).detect(text)[0]
    assert text[span.start : span.end] == "Őri Zsuzsannának"


def test_scores_are_clamped() -> None:
    text = "Teszt Elek"
    span = NerDetector(backend=FakeBackend([RawEntity("PER", 0, 10, 1.0000001)])).detect(text)[0]
    assert span.score == 1.0


def test_blank_text_does_not_load_the_model() -> None:
    calls = []
    detector = NerDetector(backend=lambda: calls.append(1) or FakeBackend(), preload=False)
    assert detector.detect("   \n") == []
    assert calls == []


def test_backend_factory_is_called_once() -> None:
    calls = []

    def factory() -> FakeBackend:
        calls.append(1)
        return FakeBackend([RawEntity("PER", 0, 4, 0.9)])

    detector = NerDetector(backend=factory, preload=False)
    assert calls == []
    detector.detect("Anna")
    detector.detect("Anna")
    assert calls == [1]


def test_preload_loads_eagerly() -> None:
    calls = []
    NerDetector(backend=lambda: calls.append(1) or FakeBackend())
    assert calls == [1]


# -- fail closed --


def test_inference_error_fails_closed_without_text() -> None:
    fictional = "Teszt Elek 1985.11.23."
    detector = NerDetector(backend=FakeBackend(error=RuntimeError(fictional)))
    with pytest.raises(DetectionError) as info:
        detector.detect(fictional)
    assert "RuntimeError" in info.value.message
    assert "Teszt" not in info.value.message


def test_load_error_fails_closed() -> None:
    def broken() -> FakeBackend:
        raise OSError("no such model")

    with pytest.raises(DetectionError, match="could not be loaded"):
        NerDetector(backend=broken)
    detector = NerDetector(backend=broken, preload=False)
    with pytest.raises(DetectionError, match="could not be loaded"):
        detector.detect("Teszt Elek")


def test_detection_error_from_backend_propagates() -> None:
    detector = NerDetector(backend=FakeBackend(error=DetectionError("boom")))
    with pytest.raises(DetectionError, match="boom"):
        detector.detect("Teszt Elek")


def test_out_of_range_offsets_fail_closed() -> None:
    detector = NerDetector(backend=FakeBackend([RawEntity("PER", 0, 99, 0.9)]))
    with pytest.raises(DetectionError, match="outside"):
        detector.detect("Teszt Elek")


def test_missing_extra_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ner, "dependencies_available", lambda: False)
    with pytest.raises(DetectionError, match="'ner' extra"):
        NerDetector()
    assert ner.main(["download"]) == 2


def test_model_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ner.MODEL_ENV_VAR, "/models/custom")
    detector = NerDetector(backend=FakeBackend())
    assert detector.model == "/models/custom"
    assert detector.revision is None
    monkeypatch.delenv(ner.MODEL_ENV_VAR)
    default = NerDetector(backend=FakeBackend())
    assert (default.model, default.revision) == (ner.DEFAULT_MODEL, ner.DEFAULT_REVISION)
    assert "custom" not in repr(default)


# -- registry and pipeline --


def test_registry_reflects_the_extra() -> None:
    if dependencies_available():
        assert resolve_detector("ner") is NerDetector
    else:
        with pytest.raises(DetectionError):
            resolve_detector("ner")


def test_pipeline_rules_stay_authoritative() -> None:
    text = "Írjon Teszt Eleknek: teszt.elek@example.com"
    raw = [at(text, "Teszt Eleknek", "PER"), at(text, "teszt.elek@example.com", "ORG", 0.6)]
    pipeline = DetectionPipeline(["rules", NerDetector(backend=FakeBackend(raw))])
    spans = pipeline.detect(text, "hu")
    by_type = {s.entity_type: s for s in spans}
    assert by_type[EntityType.PERSON].text == "Teszt Eleknek"
    assert by_type[EntityType.EMAIL].text == "teszt.elek@example.com"
    assert by_type[EntityType.EMAIL].detector == "rules"
    assert EntityType.ORGANIZATION not in by_type


def test_pipeline_fails_closed_on_ner_error() -> None:
    pipeline = DetectionPipeline(["rules", NerDetector(backend=FakeBackend(error=ValueError()))])
    with pytest.raises(DetectionError):
        pipeline.detect("Teszt Elek", "hu")


# -- the transformers backend with a tiny local tokenizer and a stub model --

WORDS = ["Teszt", "Elek", "lakik", "Budapesten", "és", "Minta", "Kft.", "dolgozik", "a", "-nál"]


@pytest.fixture
def tiny_model_dir(tmp_path):
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    from tokenizers import Tokenizer, models, pre_tokenizers, processors
    from transformers import BertConfig, BertForTokenClassification, PreTrainedTokenizerFast

    special = {
        "unk_token": "[UNK]",
        "pad_token": "[PAD]",
        "cls_token": "[CLS]",
        "sep_token": "[SEP]",
    }
    vocab = {tok: i for i, tok in enumerate(["[PAD]", "[UNK]", "[CLS]", "[SEP]", *WORDS])}
    tok = Tokenizer(models.WordLevel(vocab, special["unk_token"]))
    tok.pre_tokenizer = pre_tokenizers.WhitespaceSplit()
    tok.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]", special_tokens=[("[CLS]", 2), ("[SEP]", 3)]
    )
    fast = PreTrainedTokenizerFast(tokenizer_object=tok, model_max_length=512, **special)
    fast.save_pretrained(tmp_path)
    labels = ["O", "B-PER", "I-PER", "B-ORG", "I-ORG"]
    config = BertConfig(
        vocab_size=len(vocab),
        hidden_size=8,
        num_hidden_layers=1,
        num_attention_heads=1,
        intermediate_size=8,
        max_position_embeddings=64,
        num_labels=len(labels),
        id2label=dict(enumerate(labels)),
        label2id={label: i for i, label in enumerate(labels)},
    )
    BertForTokenClassification(config).save_pretrained(tmp_path)
    return tmp_path, vocab


def _stub_forward(vocab):
    import torch

    tags = {vocab["Teszt"]: 1, vocab["Elek"]: 2, vocab["Minta"]: 3, vocab["Kft."]: 4}

    class Out:
        def __init__(self, logits):
            self.logits = logits

    def forward(input_ids, attention_mask=None, **_):
        logits = torch.full((*input_ids.shape, 5), -5.0)
        logits[..., 0] = 5.0
        for token_id, label in tags.items():
            mask = input_ids == token_id
            logits[mask] = -5.0
            logits[..., label][mask] = 5.0
        return Out(logits)

    return forward


def test_transformers_backend_offsets_and_windows(tiny_model_dir) -> None:
    path, vocab = tiny_model_dir
    backend = ner.TransformersBackend(str(path), device="cpu", max_length=12, stride=2)
    backend.model = _stub_forward(vocab)
    text = "Teszt Elek lakik Budapesten és a Minta Kft. dolgozik " * 3 + "Teszt  Elek"
    detector = NerDetector(backend=backend)
    spans = detector.detect(text, "hu")
    persons = [s for s in spans if s.entity_type is EntityType.PERSON]
    orgs = [s for s in spans if s.entity_type is EntityType.ORGANIZATION]
    assert [s.text for s in persons] == ["Teszt Elek"] * 3 + ["Teszt  Elek"]
    assert [s.text for s in orgs] == ["Minta Kft."] * 3
    assert all(isinstance(s, Span) and text[s.start : s.end] == s.text for s in spans)


def test_transformers_backend_rejects_bad_settings(tiny_model_dir) -> None:
    path, _ = tiny_model_dir
    with pytest.raises(ValueError, match="stride"):
        ner.TransformersBackend(str(path), device="cpu", max_length=16, stride=8)
    with pytest.raises(DetectionError, match="not available"):
        ner.TransformersBackend(str(path), device="cuda:7")


def test_detector_loads_a_local_model(tiny_model_dir, monkeypatch: pytest.MonkeyPatch) -> None:
    path, _ = tiny_model_dir
    monkeypatch.setenv(ner.DEVICE_ENV_VAR, "cpu")
    detector = NerDetector(model=str(path))
    assert isinstance(detector.load(), ner.TransformersBackend)
    assert detector.load().aggregation == "first"
    assert isinstance(detector.detect("Teszt Elek lakik", "hu"), list)
