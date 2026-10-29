"""LLM detector: answers that are right but not verbatim (LAB-1215).

A model reports a value in a "corrected" surface form (letter case, apostrophe style, phone
separators), or writes other JSON before its answer. Both used to drop the value silently.
HTTP is mocked; the completions are shaped like recorded Muse Spark answers. All values are
fictional.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from pii_guard.config import Settings
from pii_guard.detect import llm
from pii_guard.detect.llm import LlmDetector, LlmEntity, parse_entities
from pii_guard.types import DetectionError, EntityType

E = EntityType
RSQUO = "\N{RIGHT SINGLE QUOTATION MARK}"
NDASH = "\N{EN DASH}"


def completion(content: str) -> dict[str, Any]:
    return {
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def answer(*items: tuple[str, str]) -> str:
    return json.dumps({"entities": [{"type": t, "text": v} for t, v in items]}, ensure_ascii=False)


class Replay:
    """Replays completions in order (the last one repeats) and counts requests."""

    def __init__(self, *contents: str) -> None:
        self.contents = list(contents)
        self.requests = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        content = self.contents.pop(0) if len(self.contents) > 1 else self.contents[0]
        return httpx.Response(200, json=completion(content))


def make(handler: Replay, **kwargs: Any) -> LlmDetector:
    return LlmDetector(
        base_url="https://llm.test/v1",
        api_key="test-key",
        transport=httpx.MockTransport(handler),
        settings=Settings(),
        **kwargs,
    )


def aligned(text: str, value: str, entity_type: EntityType, language: str) -> list[str]:
    det = LlmDetector(api_key="test-key", base_url="https://llm.test/v1", settings=Settings())
    spans = det.align(text, [LlmEntity(entity_type, value)], language)
    for s in spans:
        assert text[s.start : s.end] == s.text
    return [s.text for s in spans]


# --- Alignment ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value", "entity_type", "language", "expected"),
    [
        # Letter case: the model title-cases a name written in capitals.
        ("Ügyfél: KOVÁCS JÁNOS, Budapest", "Kovács János", E.PERSON, "hu", ["KOVÁCS JÁNOS"]),
        ("Patient: JOHN SMITH, ward 4", "John Smith", E.PERSON, "en", ["JOHN SMITH"]),
        ("kedves teszt elek, köszönjük", "Teszt Elek", E.PERSON, "hu", ["teszt elek"]),
        # ... and a Hungarian suffix still runs on.
        ("Átadtuk TESZT ELEKNEK a kulcsot.", "Teszt Elek", E.PERSON, "hu", ["TESZT ELEK"]),
        ("Antwort an MAX MUSTERMANN.", "Max Mustermann", E.PERSON, "de", ["MAX MUSTERMANN"]),
        # Apostrophes and dashes: typographic in the text, ASCII in the answer (and back).
        (
            f"Patient: Patrick O{RSQUO}Brien",
            "Patrick O'Brien",
            E.PERSON,
            "en",
            [f"Patrick O{RSQUO}Brien"],
        ),
        ("Patient: Patrick O'Brien", f"Patrick O{RSQUO}Brien", E.PERSON, "en", ["Patrick O'Brien"]),
        (
            f"Név: Nagy{NDASH}Példa Anna",
            "Nagy-Példa Anna",
            E.PERSON,
            "hu",
            [f"Nagy{NDASH}Példa Anna"],
        ),
        # Number separators.
        ("Tel: +36-30-123-4567.", "+36 30 123 4567", E.PHONE, "hu", ["+36-30-123-4567"]),
        ("Tel: +36 (30) 123 4567", "+36301234567", E.PHONE, "hu", ["+36 (30) 123 4567"]),
        ("Call 020 7946 0958 today", "02079460958", E.PHONE, "en", ["020 7946 0958"]),
        ("Született: 1985.04.12.", "1985-04-12", E.DATE_OF_BIRTH, "hu", ["1985.04.12"]),
        (
            "IBAN: hu42117730161111101800000000",
            "HU42 1177 3016 1111 1018 0000 0000",
            E.BANK_ACCOUNT,
            "hu",
            ["hu42117730161111101800000000"],
        ),
    ],
)
def test_value_in_another_surface_form_is_aligned(
    text: str, value: str, entity_type: EntityType, language: str, expected: list[str]
) -> None:
    assert aligned(text, value, entity_type, language) == expected


def test_verbatim_match_wins_over_the_fallback() -> None:
    # "Rose" is in the text verbatim, so the lowercase flower is not masked as well.
    text = "Rose bought a rose and a ROSE-shaped cake."
    assert aligned(text, "Rose", E.PERSON, "en") == ["Rose"]


@pytest.mark.parametrize(
    ("text", "value", "entity_type", "language"),
    [
        # Never inside a longer number, whatever the separators.
        ("Tel: +36-30-123-45678", "+36 30 123 4567", E.PHONE, "hu"),
        ("Ref 9020-7946-0958", "020 7946 0958", E.PHONE, "en"),
        # English names end at a word boundary, also case-insensitively.
        ("Contact JOHNSONVILLE office", "John", E.PERSON, "en"),
        # Still dropped when the value is not there in any form.
        ("Ügyfél: Teszt Elek", "Példa Ágnes", E.PERSON, "hu"),
        ("Tel: +36 30 123 4567", "+36 30 765 4321", E.PHONE, "hu"),
    ],
)
def test_fallback_does_not_overreach(
    text: str, value: str, entity_type: EntityType, language: str
) -> None:
    assert aligned(text, value, entity_type, language) == []


def test_number_separators_need_four_digits() -> None:
    # "A1-B2" vs "A1 B2": too short to drop separators; the case fallback alone finds nothing.
    assert aligned("code A1-B2 here", "A1 B2", E.ID_DOCUMENT, "en") == []
    assert aligned("doc AB-123456 here", "AB 123456", E.ID_DOCUMENT, "en") == ["AB-123456"]


# --- Parsing ------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        'Types I checked: ["PERSON", "EMAIL"]\n' + answer(("PERSON", "Kovács János")),
        "Found [1] person.\n" + answer(("PERSON", "Kovács János")),
        '{"note": "one name"}\n' + answer(("PERSON", "Kovács János")),
        # A bare list of entity objects after a list of strings.
        'Types: ["PERSON"]\n[{"type": "PERSON", "text": "Kovács János"}]',
        "```json\n" + answer(("PERSON", "Kovács János")) + "\n```",
    ],
)
def test_entities_answer_preferred_over_earlier_json(content: str) -> None:
    (entity,) = parse_entities(content)
    assert (entity.entity_type, entity.text) == (E.PERSON, "Kovács János")


def test_nested_values_are_not_taken_for_the_answer() -> None:
    # The objects inside the entities list are not candidates of their own.
    content = answer(("PERSON", "Kovács János"), ("EMAIL", "kj@example.com"))
    assert len(parse_entities(content)) == 2


@pytest.mark.parametrize(
    "content",
    [
        '["PERSON", "EMAIL"]',
        '{"entities": ["Kovács János"]}',
        '{"entities": [{"type": "PERSON"}, {"text": "Kovács János"}]}',
        '{"entities": [{"type": 7, "text": "Kovács János"}]}',
    ],
)
def test_nothing_usable_is_invalid_output(content: str) -> None:
    with pytest.raises(llm._InvalidOutput):
        parse_entities(content)


def test_only_unknown_types_is_a_valid_empty_answer() -> None:
    assert parse_entities('{"entities": [{"type": "URL", "text": "example.com"}]}') == []
    assert parse_entities("[]") == []
    assert parse_entities('{"entities": []}') == []


def test_one_usable_item_is_kept_among_malformed_ones() -> None:
    content = '{"entities": ["junk", {"type": "PERSON", "text": "Teszt Elek"}]}'
    (entity,) = parse_entities(content)
    assert entity.text == "Teszt Elek"


# --- End to end (mock transport) ----------------------------------------------


def test_preamble_list_no_longer_hides_the_answer() -> None:
    text = "Ügyfél neve Kovács János, kérem."
    content = 'Types I checked: ["PERSON", "EMAIL"]\n' + answer(("PERSON", "Kovács János"))
    replay = Replay(content)
    spans = make(replay).detect(text, "hu")
    assert [(s.entity_type, s.text) for s in spans] == [(E.PERSON, "Kovács János")]
    assert replay.requests == 1


def test_capitals_and_reformatted_phone_end_to_end() -> None:
    text = "ÜGYFÉL: KOVÁCS JÁNOS\nTel: +36-30-123-4567"
    replay = Replay(answer(("PERSON", "Kovács János"), ("PHONE", "+36 30 123 4567")))
    spans = make(replay).detect(text, "hu")
    assert [(s.entity_type, s.text) for s in spans] == [
        (E.PERSON, "KOVÁCS JÁNOS"),
        (E.PHONE, "+36-30-123-4567"),
    ]


def test_malformed_answer_is_retried() -> None:
    text = "Ügyfél neve Kovács János."
    replay = Replay('["PERSON"]', answer(("PERSON", "Kovács János")))
    det = make(replay)
    spans = det.detect(text, "hu")
    assert [s.text for s in spans] == ["Kovács János"]
    assert replay.requests == 2
    assert det.usage["invalid_outputs"] == 1


def test_malformed_answers_fail_closed() -> None:
    replay = Replay('["PERSON"]')
    det = make(replay, max_retries=1)
    with pytest.raises(DetectionError):
        det.detect("Ügyfél neve Kovács János.", "hu")
    assert replay.requests == 2
