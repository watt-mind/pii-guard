"""LLM detector. HTTP is mocked with ``httpx.MockTransport``; recorded responses come from the
Meta Model API (``muse-spark-1.3``) on fictional text only (ADR 0005). The ``live`` test calls
the real API and is skipped without ``META_API_KEY``."""

from __future__ import annotations

import itertools
import json
import os
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from pii_guard import registry
from pii_guard.config import Settings
from pii_guard.detect import llm
from pii_guard.detect.llm import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    LlmDetector,
    LlmEntity,
    chunk_text,
    find_occurrences,
    language_profile,
    parse_entities,
)
from pii_guard.types import DetectionError, Detector, EntityType

E = EntityType
FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "muse_spark_recorded.json").read_text("utf-8")
)
# Read at import time: the autouse ``clean_env`` fixture removes it from the environment.
LIVE_KEY = os.environ.get("META_API_KEY")


def completion(content: str, finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content},
            }
        ],
    }


def entities_json(*items: tuple[str, str]) -> str:
    return json.dumps({"entities": [{"type": t, "text": v} for t, v in items]})


class Recorder:
    """A MockTransport handler that replays responses in order and records requests."""

    def __init__(self, *responses: httpx.Response | dict[str, Any] | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        if isinstance(item, httpx.Response):
            return item
        return httpx.Response(200, json=item)

    def payloads(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]


def make(handler: Callable[[httpx.Request], httpx.Response], **kwargs: Any) -> LlmDetector:
    kwargs.setdefault("base_url", "https://llm.test/v1")
    kwargs.setdefault("api_key", "test-key")
    return LlmDetector(transport=httpx.MockTransport(handler), settings=Settings(), **kwargs)


def pairs(text: str, spans: list[Any]) -> list[tuple[str, str]]:
    for s in spans:
        assert text[s.start : s.end] == s.text
        assert s.detector == "llm"
    return [(s.entity_type.value, s.text) for s in spans]


# --- Recorded responses -------------------------------------------------------


def test_recorded_contract_maps_every_occurrence() -> None:
    fx = FIXTURES["contract_hu"]
    text = fx["text"]
    rec = Recorder(fx["response"])
    spans = make(rec).detect(text)

    found = pairs(text, spans)
    assert found.count(("PERSON", "Teszt Elek")) == 3
    assert ("PERSON", "Teszt Eleknek") in found
    assert ("PERSON", "Példa Ágnesnek") in found
    assert found.count(("PERSON", "Példa Ágnes")) == 2
    assert ("DATE_OF_BIRTH", "1985. április 12.") in found
    assert ("ADDRESS", "6720 Szeged, Kárász utca 7. szám") in found
    assert ("BANK_ACCOUNT", "HU42 1177 3016 1111 1018 0000 0000") in found
    assert ("PARCEL_NUMBER_HU", "12345/6") in found
    assert len(rec.requests) == 1


def test_recorded_prose_finds_inflected_stem_change() -> None:
    fx = FIXTURES["prose_hu"]
    text = fx["text"]
    found = pairs(text, make(Recorder(fx["response"])).detect(text))
    # "Zsuzsanna" -> "Zsuzsannának": the stem changes, so the surface form must be listed.
    assert ("PERSON", "Próba Zsuzsannának") in found
    assert ("PERSON", "Kovácsné Próba Zsuzsanna") in found
    assert ("ID_DOCUMENT", "123456AB") in found
    assert ("VEHICLE_PLATE", "ABC-123") in found
    assert ("ORGANIZATION", "Próba Zsuzsanna e.v.") in found


def test_recorded_english_letter() -> None:
    fx = FIXTURES["letter_en"]
    text = fx["text"]
    rec = Recorder(fx["response"])
    found = pairs(text, make(rec).detect(text, language="en"))
    # Titles are left out; "Jonathan's" yields "Jonathan" (the apostrophe ends the word).
    assert ("PERSON", "Jonathan Fakename") in found
    assert found.count(("PERSON", "Jonathan")) == 2
    assert ("PERSON", "Riley") in found
    assert ("DATE_OF_BIRTH", "14 March 1979") in found
    assert ("ADDRESS", "Flat 3, 27 Example Road, Testington TE5 7XY") in found
    assert ("ID_DOCUMENT", "123456789") in found
    assert ("EMAIL", "j.fakename@example.org") in found
    system = rec.payloads()[0]["messages"][0]["content"]
    assert "English" in system
    assert "_HU" not in system


# --- Languages -------------------------------------------------------------------


def test_language_selects_notes_and_entity_types() -> None:
    hu_system, hu_user = llm.build_messages("szöveg", "hu")
    en_system, en_user = llm.build_messages("text", "en-GB")
    assert "Zsuzsannának" in hu_system["content"]
    assert "PARCEL_NUMBER_HU" in hu_system["content"]
    assert "NATIONAL_ID_HU_TAX" in hu_system["content"]
    assert "possessive" in en_system["content"]
    assert "_HU" not in en_system["content"]
    assert "Language: hu" in hu_user["content"]
    assert "Language: en" in en_user["content"]
    for content in (hu_system["content"], en_system["content"]):
        assert "{" + "language_notes}" not in content
        assert "PERSON" in content


@pytest.mark.parametrize("language", ["de", "pl-PL", "", "xx"])
def test_unknown_language_falls_back(language: str) -> None:
    system, _ = llm.build_messages("Text", language)
    assert "any language" in system["content"]
    assert "_HU" not in system["content"]
    rec = Recorder(completion(entities_json(("PERSON", "Anna Beispiel"))))
    text = "Brief an Anna Beispiels Adresse"  # German genitive -s: suffix tolerated
    assert pairs(text, make(rec).detect(text, language=language)) == [("PERSON", "Anna Beispiel")]


def test_language_profiles() -> None:
    assert language_profile("HU").code == "hu"
    assert language_profile("en_US").code == "en"
    assert language_profile("en").allow_suffix is False
    assert language_profile("hu").allow_suffix is True
    assert language_profile("fr").allow_suffix is False
    assert language_profile("fi").allow_suffix is True
    assert language_profile("ja").word_boundary is False
    assert language_profile("").code == "und"


def test_english_alignment_needs_a_word_end() -> None:
    text = "Ann met Anne and Ann's sister."
    rec = Recorder(completion(entities_json(("PERSON", "Ann"))))
    spans = make(rec).detect(text, language="en")
    assert [(s.start, s.end) for s in spans] == [(0, 3), (17, 20)]
    # The same answer for Hungarian tolerates suffixes ("Annnak"), so "Anne" matches too.
    rec = Recorder(completion(entities_json(("PERSON", "Ann"))))
    assert len(make(rec).detect(text, language="hu")) == 3


def test_scripts_without_word_spaces_match_inside_runs() -> None:
    text = "请联系山田太郎先生。"
    rec = Recorder(completion(entities_json(("PERSON", "山田太郎"))))
    spans = make(rec).detect(text, language="ja")
    assert pairs(text, spans) == [("PERSON", "山田太郎")]
    rec = Recorder(completion(entities_json(("PERSON", "山田太郎"))))
    assert make(rec).detect(text, language="hu") == []  # word-boundary languages do not


# --- Request shape -------------------------------------------------------------


def test_request_payload_and_headers() -> None:
    rec = Recorder(completion(entities_json()))
    det = make(rec, model="muse-spark-1.3", reasoning_effort="minimal")
    det.detect("Teszt Elek {braces} írt.", language="hu")

    (request,) = rec.requests
    assert str(request.url) == "https://llm.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["model"] == "muse-spark-1.3"
    assert body["temperature"] == 0
    assert body["stream"] is False
    assert body["reasoning_effort"] == "minimal"
    assert body["response_format"] == {"type": "json_object"}
    system, user = body["messages"]
    assert system["role"] == "system" and user["role"] == "user"
    for entity_type in llm.ENTITY_DESCRIPTIONS:
        assert entity_type.value in system["content"]
    assert "{entity_types}" not in system["content"]
    assert "Teszt Elek {braces} írt." in user["content"]
    assert "Language: hu" in user["content"]


def test_optional_fields_are_omitted() -> None:
    rec = Recorder(completion(entities_json()))
    make(rec, api_key="", json_mode=False, max_tokens=None).detect("Szia!")
    body = rec.payloads()[0]
    assert "reasoning_effort" not in body
    assert "response_format" not in body
    assert "max_tokens" not in body
    assert "authorization" not in rec.requests[0].headers


def test_full_completions_url_is_accepted() -> None:
    rec = Recorder(completion(entities_json()))
    make(rec, base_url="http://localhost:8000/v1/chat/completions/").detect("Szia!")
    assert str(rec.requests[0].url) == "http://localhost:8000/v1/chat/completions"


def test_defaults_target_muse_spark_open_on_baseten() -> None:
    det = LlmDetector(settings=Settings())
    assert det.model == DEFAULT_MODEL == "meta-models/muse-spark-open-1026"
    assert det.url == DEFAULT_BASE_URL + "/chat/completions"


def test_settings_and_env_configure_the_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_LLM_DETECTOR_URL", "https://vllm.internal/v1")
    monkeypatch.setenv("PII_GUARD_LLM_DETECTOR_API_KEY", "from-env")
    monkeypatch.setenv("PII_GUARD_LLM_DETECTOR_MODEL", "my-org/muse-spark-open-ft")
    rec = Recorder(completion(entities_json()))
    det = LlmDetector(transport=httpx.MockTransport(rec), settings=Settings())
    det.detect("Szia!")
    assert str(rec.requests[0].url) == "https://vllm.internal/v1/chat/completions"
    assert rec.requests[0].headers["authorization"] == "Bearer from-env"
    assert rec.payloads()[0]["model"] == "my-org/muse-spark-open-ft"
    assert "from-env" not in repr(det)


def test_empty_text_makes_no_request() -> None:
    rec = Recorder(completion(entities_json()))
    assert make(rec).detect("  \n ") == []
    assert rec.requests == []


def test_registered_as_llm() -> None:
    assert registry.resolve_detector("llm") is LlmDetector
    det = registry.create_detector("llm", settings=Settings())
    assert isinstance(det, Detector)
    assert det.name == "llm"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_retries": -1},
        {"score": 1.5},
        {"chunk_size": 0},
        {"chunk_size": 100, "chunk_overlap": 100},
    ],
)
def test_invalid_constructor_arguments(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        LlmDetector(settings=Settings(), **kwargs)


# --- Parsing ---------------------------------------------------------------------


def test_hallucinated_and_unknown_values_are_dropped() -> None:
    text = "Teszt Elek lakik itt."
    content = json.dumps(
        {
            "entities": [
                {"type": "PERSON", "text": "Teszt Elek"},
                {"type": "PERSON", "text": "Minta Mária"},  # not in the text
                {"type": "PERSON", "text": "teszt elek"},  # case changed: not verbatim
                {"type": "SECRET_SAUCE", "text": "lakik"},  # unknown type
                {"type": "FACE", "text": "itt"},  # visual type
                {"type": "PERSON", "text": ""},
                {"type": "PERSON"},
                "Teszt Elek",
            ]
        }
    )
    spans = make(Recorder(completion(content))).detect(text)
    assert pairs(text, spans) == [("PERSON", "Teszt Elek")]


@pytest.mark.parametrize(
    "content",
    [
        '<think>The user wants PII. "Teszt Elek" is a name.</think>'
        + entities_json(("PERSON", "Teszt Elek")),
        "Reasoning about it...</think>\n" + entities_json(("PERSON", "Teszt Elek")),
        "```json\n" + entities_json(("PERSON", "Teszt Elek")) + "\n```",
        "Here you go: " + entities_json(("PERSON", "Teszt Elek")) + " Done.",
        json.dumps([{"entity_type": "person", "value": "Teszt Elek"}]),
        json.dumps({"entities": [{"type": "NAME", "text": "Teszt Elek", "occurrence": 2}]}),
    ],
    ids=["think-block", "unterminated-think", "code-fence", "prose", "bare-list", "alias"],
)
def test_tolerant_parsing(content: str) -> None:
    text = "Teszt Elek és Teszt Elek."
    spans = make(Recorder(completion(content))).detect(text)
    # The occurrence hint never narrows masking: every copy is masked.
    assert pairs(text, spans) == [("PERSON", "Teszt Elek"), ("PERSON", "Teszt Elek")]


def test_content_parts_are_joined() -> None:
    body = completion("")
    body["choices"][0]["message"]["content"] = [
        {"type": "text", "text": '{"entities": [{"type": "EMAIL", '},
        {"type": "text", "text": '"text": "teszt@example.com"}]}'},
    ]
    text = "Írj ide: teszt@example.com"
    assert pairs(text, make(Recorder(body)).detect(text)) == [("EMAIL", "teszt@example.com")]


def test_parse_entities_rejects_non_entity_json() -> None:
    with pytest.raises(llm._InvalidOutput):
        parse_entities('{"answer": "no"}')
    with pytest.raises(llm._InvalidOutput):
        parse_entities("I could not find anything.")
    assert parse_entities('{"entities": []}') == []
    (entity,) = parse_entities('{"entities": [{"type": "PERSON", "text": " Teszt Elek "}]}')
    assert entity == LlmEntity(E.PERSON, "Teszt Elek")
    assert "Teszt" not in repr(entity)


# --- Fail closed --------------------------------------------------------------------


def test_invalid_json_is_retried_once_then_succeeds() -> None:
    rec = Recorder(completion("not json at all"), completion(entities_json(("PERSON", "Ede"))))
    text = "Szia Ede!"
    assert pairs(text, make(rec).detect(text)) == [("PERSON", "Ede")]
    assert len(rec.requests) == 2


def test_invalid_json_twice_raises() -> None:
    rec = Recorder(completion('{"entities": [{"type": "PERSON", "text": "Teszt'))
    with pytest.raises(DetectionError) as excinfo:
        make(rec).detect("Teszt Elek írt.")
    assert len(rec.requests) == 2
    assert "Teszt" not in excinfo.value.message


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(503, text="Teszt Elek overloaded"),
        httpx.Response(429, json={"error": "rate limited"}),
        httpx.ReadTimeout("timed out"),
        httpx.ConnectError("refused"),
        completion(entities_json(("PERSON", "Teszt Elek")), finish_reason="length"),
        httpx.Response(200, text="<html>gateway</html>"),
        {"choices": []},
        completion(""),
    ],
    ids=["503", "429", "timeout", "connect", "truncated", "not-json", "no-choices", "empty"],
)
def test_retryable_failures_raise_after_retry(failure: Any) -> None:
    rec = Recorder(failure)
    with pytest.raises(DetectionError) as excinfo:
        make(rec).detect("Teszt Elek írt.")
    assert len(rec.requests) == 2
    assert excinfo.value.code == "detection_failed"
    assert "Teszt" not in excinfo.value.message


def test_retry_recovers_from_a_transient_error() -> None:
    rec = Recorder(httpx.Response(502), completion(entities_json(("PERSON", "Ede"))))
    assert len(make(rec).detect("Szia Ede!")) == 1
    assert len(rec.requests) == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_client_errors_are_not_retried(status: int) -> None:
    rec = Recorder(httpx.Response(status, text="echo: Teszt Elek"))
    with pytest.raises(DetectionError) as excinfo:
        make(rec).detect("Teszt Elek írt.")
    assert len(rec.requests) == 1
    assert str(status) in excinfo.value.message
    assert "Teszt" not in excinfo.value.message


def test_max_retries_zero() -> None:
    rec = Recorder(httpx.Response(500))
    with pytest.raises(DetectionError):
        make(rec, max_retries=0).detect("Szia!")
    assert len(rec.requests) == 1


# --- Offset mapping -------------------------------------------------------------------


def test_find_occurrences_accented_and_boundaries() -> None:
    text = "Őry Ödön, Kőry Ödön és Őry Ödönnek írt; Őry  Ödön."
    hits = find_occurrences(text, "Őry Ödön")
    assert [text[s:e] for s, e in hits] == ["Őry Ödön", "Őry Ödön", "Őry  Ödön"]
    # Not inside a longer word ("Kőry"), but a following suffix ("Ödönnek") is fine.
    assert hits[0][0] == 0
    assert all(text[s - 1] in " " for s, _ in hits[1:])


def test_find_occurrences_numbers_do_not_run_on() -> None:
    text = "hrsz. 12345/6, de nem 12345/67."
    assert find_occurrences(text, "12345/6") == [(6, 13)]


def test_find_occurrences_unicode_normalization() -> None:
    text = unicodedata.normalize("NFD", "Kérem, Árvai Éva válaszoljon.")
    hits = find_occurrences(text, "Árvai Éva")  # model answers in NFC
    assert len(hits) == 1
    s, e = hits[0]
    assert unicodedata.normalize("NFC", text[s:e]) == "Árvai Éva"
    assert find_occurrences(text, "   ") == []


def test_find_occurrences_whitespace_and_symbols() -> None:
    text = "Cím:\n6720 Szeged,\nKárász utca 7. (+36 30 123 4567)"
    assert find_occurrences(text, "6720 Szeged, Kárász utca 7.") == [(5, 32)]
    assert find_occurrences(text, "(+36 30 123 4567)") == [(33, 50)]


# --- Chunking -----------------------------------------------------------------------


def test_chunk_text_short_text_is_one_chunk() -> None:
    assert chunk_text("rövid", 100, 10) == [(0, "rövid")]


@given(
    st.text(alphabet="abcőű \n", min_size=1, max_size=400),
    st.integers(min_value=5, max_value=80),
    st.data(),
)
def test_chunk_text_covers_everything(text: str, size: int, data: st.DataObject) -> None:
    overlap = data.draw(st.integers(min_value=0, max_value=size - 1))
    chunks = chunk_text(text, size, overlap)
    assert chunks[0][0] == 0
    assert chunks[-1][0] + len(chunks[-1][1]) == len(text)
    for (start, chunk), (next_start, _) in itertools.pairwise(chunks):
        assert text[start : start + len(chunk)] == chunk
        assert len(chunk) <= size
        assert start < next_start <= start + len(chunk)  # progress, no gaps


def test_long_text_is_chunked_and_values_mapped_globally() -> None:
    filler = "Ez egy hosszú, ártalmatlan mondat a szerződésből. " * 6
    text = filler + "Az eladó Teszt Elek. " + filler + "Aláírás: Minta Mária."

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        user = json.loads(request.content)["messages"][1]["content"]
        found = [("PERSON", n) for n in ("Teszt Elek", "Minta Mária") if n in user]
        return httpx.Response(200, json=completion(entities_json(*found)))

    det = make(handler, chunk_size=200, chunk_overlap=40)
    spans = det.detect(text)
    assert len(calls) > 2
    assert pairs(text, spans) == [("PERSON", "Teszt Elek"), ("PERSON", "Minta Mária")]


# --- Live ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.skipif(not LIVE_KEY, reason="META_API_KEY not set")
@pytest.mark.parametrize(
    ("language", "text", "name"),
    [
        (
            "hu",
            "Alulírott Teszt Elek (e-mail: teszt.elek@example.com) 6720 Szeged, Kárász utca 7.",
            "Teszt Elek",
        ),
        (
            "en",
            "Please call Ms Jane Placeholder (teszt.elek@example.com) about 12 Example Road.",
            "Jane Placeholder",
        ),
    ],
)
def test_live_meta_model_api(language: str, text: str, name: str) -> None:
    """Fictional text only: hosted models never see real data (docs/models.md)."""
    det = LlmDetector(
        base_url="https://api.meta.ai/v1",
        api_key=LIVE_KEY,
        model="muse-spark-1.3",
        reasoning_effort="minimal",
        settings=Settings(),
    )
    found = {(s.entity_type, s.text) for s in det.detect(text, language=language)}
    assert (E.PERSON, name) in found
    assert (E.EMAIL, "teszt.elek@example.com") in found
