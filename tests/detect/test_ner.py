"""NER detector: decoding, thresholds, offsets and fail-closed behaviour, with mocked models.

Nothing here downloads a model. Tests that need torch/transformers (the ``ner`` extra) build a
tiny word-level tokenizer and a model stub in ``tmp_path`` and are skipped without the extra.
All text is fictional.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

from pii_guard.detect import ner, ner_resolve
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
        NerDetector(backend=FakeBackend(), entity_types=["VEHICLE_PLATE"])


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
    monkeypatch.setenv("PII_GUARD_NER_FALLBACK", "download")
    default = NerDetector(backend=FakeBackend())
    # Unset: the published checkpoint (LAB-1306), from its pinned directory in the model cache.
    published = ner_resolve.PUBLISHED
    assert (default.model, default.revision) == (str(published.local_dir()), None)
    assert default.choice is not None and default.choice.source == "published"
    assert "custom" not in repr(default)
    # Without the published step, the public fallback, likewise from its pinned directory.
    monkeypatch.setenv("PII_GUARD_NER_PUBLISHED_MODEL", "fictional/unpublished-ner")
    fallback = ner_resolve.PUBLIC_FALLBACK
    without = NerDetector(backend=FakeBackend())
    assert (without.model, without.revision) == (str(fallback.local_dir()), None)
    assert fallback.repo_id == ner.DEFAULT_MODEL
    assert without.choice is not None and without.choice.source == "fallback"
    # Pinned hub id given explicitly: the pinned revision applies.
    hub = NerDetector(model=ner.DEFAULT_MODEL, backend=FakeBackend())
    assert hub.revision == ner.DEFAULT_REVISION


def test_unresolved_model_refuses_to_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_NER_FALLBACK", "off")
    monkeypatch.setattr(ner, "dependencies_available", lambda: True)
    with pytest.raises(DetectionError, match="PII_GUARD_NER_FALLBACK=off"):
        NerDetector()
    assert NerDetector(backend=FakeBackend()).detect("Teszt Elek ír.") is not None


def test_missing_fallback_is_downloaded_on_first_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_NER_FALLBACK", "download")
    monkeypatch.setenv("PII_GUARD_NER_PUBLISHED_MODEL", "fictional/unpublished-ner")  # skip step 2
    monkeypatch.setattr(ner, "dependencies_available", lambda: True)
    fetched: list[str] = []

    def fake_ensure(choice: ner_resolve.NerChoice) -> str:
        fetched.append(choice.source)
        return "/models/fetched"

    built: list[str] = []
    monkeypatch.setattr(ner_resolve, "ensure", fake_ensure)
    monkeypatch.setattr(
        ner, "TransformersBackend", lambda model, **_: built.append(model) or FakeBackend()
    )
    detector = NerDetector(preload=False)
    assert fetched == [] and built == []
    detector.load()
    assert (fetched, built) == (["fallback"], ["/models/fetched"])


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
    # The case ending stays outside the name (LAB-1174).
    assert by_type[EntityType.PERSON].text == "Teszt Elek"
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


def test_transformers_backend_refuses_pickled_weights(tiny_model_dir, tmp_path) -> None:
    """Only ``model.safetensors`` is loaded: a pickled ``pytorch_model.bin`` can run code."""
    import shutil

    import torch
    from transformers import AutoModelForTokenClassification

    path, _ = tiny_model_dir
    pickled = tmp_path / "pickled"
    shutil.copytree(path, pickled, ignore=shutil.ignore_patterns("*.safetensors"))
    model = AutoModelForTokenClassification.from_pretrained(path)
    torch.save(model.state_dict(), pickled / "pytorch_model.bin")
    with pytest.raises(OSError, match="safetensors"):
        ner.TransformersBackend(str(pickled), device="cpu")


def test_detector_loads_a_local_model(tiny_model_dir, monkeypatch: pytest.MonkeyPatch) -> None:
    path, _ = tiny_model_dir
    monkeypatch.setenv(ner.DEVICE_ENV_VAR, "cpu")
    detector = NerDetector(model=str(path))
    assert isinstance(detector.load(), ner.TransformersBackend)
    assert detector.load().aggregation == "first"
    assert isinstance(detector.detect("Teszt Elek lakik", "hu"), list)


# -- batching (LAB-1279) --


class FakeBatchBackend:
    """Entities chosen per text by ``finder``; ``predict_batch`` records each batch."""

    def __init__(self, finder, error: Exception | None = None, wrong_count: bool = False):
        self.finder = finder
        self.error = error
        self.wrong_count = wrong_count
        self.batches: list[list[str]] = []
        self.calls = 0

    def predict(self, text: str) -> list[RawEntity]:
        self.calls += 1
        return self.finder(text)

    def predict_batch(self, texts):
        self.batches.append(list(texts))
        if self.error is not None:
            raise self.error
        out = [self.finder(t) for t in texts]
        return out[:-1] if self.wrong_count else out


def _find_test_names(text: str) -> list[RawEntity]:
    found = []
    for name in ("Teszt Elek", "Minta Mária"):
        start = text.find(name)
        if start >= 0:
            found.append(RawEntity("PER", start, start + len(name), 0.91))
    start = text.find("Minta Kft.")
    if start >= 0:
        found.append(RawEntity("ORG", start, start + len("Minta Kft."), 0.4))  # below threshold
    return found


BATCH_TEXTS = [
    "Teszt Elek lakik Budapesten.",
    "   ",
    "Nincs itt senki.",
    "Minta Mária a Minta Kft. ügyvezetője, Teszt Elek a helyettese.",
    "",
]


def test_detect_batch_equals_detect_per_text() -> None:
    backend = FakeBatchBackend(_find_test_names)
    detector = NerDetector(backend=backend)
    batched = detector.detect_batch(BATCH_TEXTS, "hu")
    assert backend.batches == [[t for t in BATCH_TEXTS if t.strip()]]  # one call, blanks skipped
    assert batched == [detector.detect(t, "hu") for t in BATCH_TEXTS]
    assert [len(s) for s in batched] == [1, 0, 0, 2, 0]


def test_detect_batch_loops_predict_without_predict_batch() -> None:
    raw = [RawEntity("PER", 0, 10, 0.9)]
    backend = FakeBackend(raw)
    detector = NerDetector(backend=backend)
    texts = ["Teszt Elek lakik itt", "Teszt Elek dolgozik"]
    assert detector.detect_batch(texts, "hu") == [detector.detect(t, "hu") for t in texts]
    assert backend.calls == 4
    assert detector.detect_batch(["", " "]) == [[], []]
    assert backend.calls == 4  # nothing to run, the model is not called


@pytest.mark.parametrize(
    ("backend", "match"),
    [
        (FakeBatchBackend(_find_test_names, error=RuntimeError("Teszt Elek")), "RuntimeError"),
        (FakeBatchBackend(_find_test_names, error=DetectionError("boom")), "boom"),
        (FakeBatchBackend(_find_test_names, wrong_count=True), "number of batch results"),
    ],
)
def test_detect_batch_fails_closed(backend, match: str) -> None:
    detector = NerDetector(backend=backend)
    with pytest.raises(DetectionError, match=match) as info:
        detector.detect_batch(BATCH_TEXTS, "hu")
    assert "Teszt" not in info.value.message


def test_detect_batch_rejects_offsets_outside_a_text() -> None:
    detector = NerDetector(backend=FakeBatchBackend(lambda t: [RawEntity("PER", 0, 999, 0.9)]))
    with pytest.raises(DetectionError, match="offsets outside"):
        detector.detect_batch(["Teszt Elek"], "hu")


def _counting(forward):
    shapes: list[tuple[int, ...]] = []

    def wrapped(**inputs):
        shapes.append(tuple(inputs["input_ids"].shape))
        return forward(**inputs)

    return wrapped, shapes


def _batch_texts() -> list[str]:
    long = "Teszt Elek lakik Budapesten és a Minta Kft. dolgozik " * 3 + "Teszt  Elek"
    return [
        "Teszt Elek lakik Budapesten",
        long,
        "a Minta Kft. dolgozik",
        "",
        "Elek",
        "Teszt Elek és Teszt Elek",
        long[:60],
    ]


def test_predict_batch_equals_predict_per_text(tiny_model_dir) -> None:
    path, vocab = tiny_model_dir
    backend = ner.TransformersBackend(str(path), device="cpu", max_length=12, stride=2)
    backend.model, shapes = _counting(_stub_forward(vocab))
    texts = _batch_texts()
    singles = [backend.predict(t) for t in texts]
    shapes.clear()
    assert backend.predict_batch(texts) == singles
    # The long text needs several windows; all windows of all texts in ceil(n / 8) forwards.
    windows = sum(
        len(
            backend.tokenizer(
                t, return_overflowing_tokens=True, truncation=True, max_length=12, stride=2
            )["input_ids"]
        )
        for t in texts
    )
    assert windows > len(texts)
    assert sum(rows for rows, _ in shapes) == windows
    assert len(shapes) < windows and all(rows <= 8 for rows, _ in shapes)
    # Longest windows first: the padded width never grows from one micro-batch to the next.
    assert [s[1] for s in shapes] == sorted((s[1] for s in shapes), reverse=True)
    detector = NerDetector(backend=backend)
    assert detector.detect_batch(texts, "hu") == [detector.detect(t, "hu") for t in texts]
    assert backend.predict_batch([]) == []


def test_predict_batch_respects_the_token_cap(tiny_model_dir) -> None:
    path, vocab = tiny_model_dir
    backend = ner.TransformersBackend(
        str(path), device="cpu", max_length=12, stride=2, batch_size=8, max_batch_tokens=24
    )
    backend.model, shapes = _counting(_stub_forward(vocab))
    texts = _batch_texts()
    singles = [backend.predict(t) for t in texts]
    shapes.clear()
    assert backend.predict_batch(texts) == singles
    assert shapes and all(rows * width <= 24 or rows == 1 for rows, width in shapes)
    with pytest.raises(ValueError, match="positive"):
        ner.TransformersBackend(str(path), device="cpu", batch_size=0)


def test_micro_batches_bound_count_tokens_and_padding(tiny_model_dir) -> None:
    path, _ = tiny_model_dir
    backend = ner.TransformersBackend(str(path), device="cpu")
    # A long system prompt is not batched with short tool texts (padding over 2x).
    lengths = [282, 24, 23, 24, 5, 5, 5, 5, 5, 5, 5, 5, 5, 3]
    batches = backend._micro_batches(lengths)
    assert sorted(w for b in batches for w in b) == list(range(len(lengths)))
    assert batches[0][0] == 0 and len(batches[0]) <= 2
    for batch in batches:
        width = lengths[batch[0]]
        assert all(lengths[w] <= width for w in batch)
        assert len(batch) <= 8
        assert len(batch) * width <= 2 * sum(lengths[w] for w in batch)
    # Equal lengths: full batches of 8 up to the token cap.
    assert [len(b) for b in backend._micro_batches([512] * 20)] == [8, 8, 4]
    backend.max_batch_tokens = 1024
    assert [len(b) for b in backend._micro_batches([512] * 5)] == [2, 2, 1]


def test_padded_batch_matches_unpadded_forward(tiny_model_dir) -> None:
    """With the real (random) tiny model: right padding + attention mask leave scores as is."""
    path, _ = tiny_model_dir
    backend = ner.TransformersBackend(str(path), device="cpu", max_length=12, stride=2)
    texts = [t for t in _batch_texts() if t]
    singles = [backend.predict(t) for t in texts]
    batched = backend.predict_batch(texts)

    def rounded(entities):
        return [(e.label, e.start, e.end, round(e.score, 4)) for e in entities]

    assert [rounded(b) for b in batched] == [rounded(s) for s in singles]


def test_predict_batch_softmax_runs_on_cpu(tiny_model_dir) -> None:
    """Logits leave the device once per micro-batch; softmax and argmax run on the CPU."""
    path, vocab = tiny_model_dir
    backend = ner.TransformersBackend(str(path), device="cpu", max_length=12, stride=2)
    forward = _stub_forward(vocab)
    moved: list[str] = []

    class Logits:
        def __init__(self, inner):
            self.inner = inner

        def float(self):
            return self

        def cpu(self):
            moved.append("cpu")
            return self.inner.float()

    class Out:
        def __init__(self, logits):
            self.logits = Logits(logits)

    forwards: list[int] = []

    def model(**inputs):
        forwards.append(1)
        return Out(forward(**inputs).logits)

    backend.model = model
    backend.predict_batch(_batch_texts())
    assert len(forwards) > 1
    assert len(moved) == len(forwards)  # one device-to-CPU copy per micro-batch


# -- concurrent callers share runs (LAB-1177) --


def _gated(backend):
    """Hold the first ``_predict_now`` run until ``release`` is set; record every run's texts."""
    inner = backend._predict_now
    started, release = threading.Event(), threading.Event()
    runs: list[list[str]] = []
    active: list[int] = []

    def run(texts):
        active.append(1)
        try:
            assert len(active) == 1, "two runs at once"
            runs.append(list(texts))
            if len(runs) == 1:
                started.set()
                assert release.wait(10)
            return inner(texts)
        finally:
            active.pop()

    backend._predict_now = run
    return started, release, runs


def _call_in_threads(backend, calls):
    """Start one thread per call while the first run is held; results or exceptions, in order."""
    out: list[object] = [None] * len(calls)

    def work(i):
        try:
            out[i] = backend.predict_batch(calls[i])
        except Exception as exc:
            out[i] = exc

    threads = [threading.Thread(target=work, args=(i,)) for i in range(len(calls))]
    return threads, out


def _wait_queued(backend, n):
    deadline = time.monotonic() + 10
    while len(backend._queue) < n:
        assert time.monotonic() < deadline, "callers did not queue"
        time.sleep(0.005)


def test_concurrent_calls_share_one_run_and_get_their_own_results(tiny_model_dir) -> None:
    path, vocab = tiny_model_dir
    backend = ner.TransformersBackend(str(path), device="cpu", max_length=12, stride=2)
    backend.model = _stub_forward(vocab)
    texts = _batch_texts()
    calls = [["Elek lakik"], texts[:3], texts[3:5], [texts[5]], texts[5:], ["a Minta Kft."]]
    expected = [[backend.predict(t) for t in call] for call in calls]
    started, release, runs = _gated(backend)
    threads, out = _call_in_threads(backend, calls)
    threads[0].start()
    assert started.wait(10)  # the first caller runs at once, alone
    for t in threads[1:]:
        t.start()
    _wait_queued(backend, len(calls) - 1)
    release.set()
    for t in threads:
        t.join(10)
    assert out == expected
    # The five callers that queued behind the first run share the second run.
    assert runs == [calls[0], [t for call in calls[1:] for t in call]]
    assert not backend._running and not backend._queue
    assert backend.predict_batch(calls[1]) == expected[1]  # idle again: runs at once, alone
    assert runs[-1] == calls[1] and len(runs) == 3


def test_combined_runs_respect_the_text_cap(tiny_model_dir) -> None:
    path, vocab = tiny_model_dir
    backend = ner.TransformersBackend(
        str(path), device="cpu", max_length=12, stride=2, max_combined_texts=3
    )
    backend.model = _stub_forward(vocab)
    calls = [
        ["Teszt Elek"],
        ["Elek"],
        ["Minta Kft.", "Elek lakik"],
        ["Teszt"],
        ["a", "b", "c", "d"],
    ]
    expected = [[backend.predict(t) for t in call] for call in calls]
    started, release, runs = _gated(backend)
    threads, out = _call_in_threads(backend, calls)
    threads[0].start()
    assert started.wait(10)
    for i, t in enumerate(threads[1:], start=1):
        t.start()
        _wait_queued(backend, i)  # queue in a known order
    release.set()
    for t in threads:
        t.join(10)
    assert out == expected
    # Oldest first, up to 3 texts per run; a caller with more texts than the cap runs alone.
    assert [len(r) for r in runs] == [1, 3, 1, 4]
    with pytest.raises(ValueError, match="positive"):
        ner.TransformersBackend(str(path), device="cpu", max_combined_texts=0)


def test_a_failing_caller_does_not_fail_the_others(tiny_model_dir) -> None:
    path, vocab = tiny_model_dir
    backend = ner.TransformersBackend(str(path), device="cpu", max_length=12, stride=2)
    forward = _stub_forward(vocab)
    poison = vocab["Kft."]

    def model(input_ids, **inputs):
        if (input_ids == poison).any():
            raise RuntimeError("fictional device error")
        return forward(input_ids, **inputs)

    backend.model = model
    calls = [["Teszt Elek"], ["Elek lakik"], ["a Minta Kft. dolgozik"], ["Teszt Elek és Teszt"]]
    expected = [[backend.predict(t) for t in call] for call in (calls[0], calls[1], calls[3])]
    started, release, runs = _gated(backend)
    threads, out = _call_in_threads(backend, calls)
    threads[0].start()
    assert started.wait(10)
    for t in threads[1:]:
        t.start()
    _wait_queued(backend, 3)
    release.set()
    for t in threads:
        t.join(10)
    assert [out[0], out[1], out[3]] == expected
    assert isinstance(out[2], RuntimeError)
    # The combined run failed, then its three callers ran one at a time.
    assert [len(r) for r in runs] == [1, 3, 1, 1, 1]
    assert not backend._running and not backend._queue


def test_an_interrupted_run_releases_every_waiting_caller(tiny_model_dir) -> None:
    path, vocab = tiny_model_dir
    backend = ner.TransformersBackend(str(path), device="cpu", max_length=12, stride=2)
    backend.model = _stub_forward(vocab)

    def interrupted(texts):
        raise KeyboardInterrupt

    backend._predict_now = interrupted
    with pytest.raises(KeyboardInterrupt):
        backend.predict_batch(["Teszt Elek", "Elek"])
    assert not backend._running and not backend._queue


# -- the shipped checkpoint, where one is available (PII_GUARD_NER_MODEL) --


# Read at import: the autouse ``clean_env`` fixture clears ``PII_GUARD_*`` for every test.
REAL_MODEL = os.environ.get(ner.MODEL_ENV_VAR, "")


def _real_model_path() -> str:
    if not REAL_MODEL or not os.path.isdir(REAL_MODEL):
        pytest.skip(f"{ner.MODEL_ENV_VAR} does not point at a local checkpoint")
    if not dependencies_available():
        pytest.skip("needs the 'ner' extra")
    return REAL_MODEL


def _fixture_docs() -> list[tuple[str, str]]:
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "eval" / "fixtures"
    docs = []
    for path in sorted(root.glob("*-smoke.jsonl")) + sorted(root.glob("public/*-ai4privacy.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                doc = json.loads(line)
                docs.append((doc.get("language", "hu"), doc["text"]))
    return docs


def test_real_model_detect_batch_equals_detect() -> None:
    """Batched and per-text detection agree span for span on the smoke + ai4privacy fixtures."""
    detector = NerDetector(model=_real_model_path(), device="cpu")
    docs = _fixture_docs()
    long_text = " ".join(text for _, text in docs[:40])  # several 512-token windows
    assert len(detector.load().tokenizer(long_text)["input_ids"]) > 1024
    docs.append(("en", long_text))

    def key(spans):
        return [(s.start, s.end, s.entity_type, s.text) for s in spans]

    by_language: dict[str, list[str]] = {}
    for language, text in docs:
        by_language.setdefault(language, []).append(text)
    for language, texts in by_language.items():
        batched = detector.detect_batch(texts, language)
        singles = [detector.detect(t, language) for t in texts]
        assert [key(b) for b in batched] == [key(s) for s in singles]
        # Padding changes the float sums slightly: scores agree to 1e-4, not bit for bit.
        for b, s in zip(batched, singles, strict=True):
            assert all(abs(x.score - y.score) <= 1e-4 for x, y in zip(b, s, strict=True))


def test_bucket_padded_width_buckets_on_mps_only() -> None:
    """LAB-1329: on MPS micro-batches pad to a multiple of 32 (capped at max_length), so
    a new width does not compile a new kernel mid-traffic. No model needed."""
    assert ner.bucket_padded_width(17, 512, None) == 17  # CPU: no bucketing
    assert ner.bucket_padded_width(17, 512, ner.MPS_PAD_BUCKET) == 32
    assert ner.bucket_padded_width(32, 512, ner.MPS_PAD_BUCKET) == 32
    assert ner.bucket_padded_width(33, 512, ner.MPS_PAD_BUCKET) == 64
    assert ner.bucket_padded_width(33, 40, ner.MPS_PAD_BUCKET) == 40  # capped
    assert ner.bucket_padded_width(512, 512, ner.MPS_PAD_BUCKET) == 512
    assert ner.bucket_padded_width(600, 512, ner.MPS_PAD_BUCKET) == 600


def test_bucketed_padding_changes_no_span(tiny_model_dir) -> None:
    """LAB-1329: the extra bucket padding is attention-masked, so spans are identical to
    the unbucketed run and every micro-batch width is a multiple of the bucket."""
    path, vocab = tiny_model_dir
    backend = ner.TransformersBackend(str(path), device="cpu")
    assert backend.pad_bucket is None
    backend.model, shapes = _counting(_stub_forward(vocab))
    texts = _batch_texts()
    plain = backend.predict_batch(texts)
    backend.pad_bucket = ner.MPS_PAD_BUCKET  # as on MPS
    shapes.clear()
    assert backend.predict_batch(texts) == plain
    assert shapes and all(width % ner.MPS_PAD_BUCKET == 0 for _, width in shapes)
