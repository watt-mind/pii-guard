"""A declared tool name stays as written in identifiers, whatever the vault holds (LAB-1324).

LAB-1299 and LAB-1317 drop the text detections whose whole value is a declared tool name. The
same word can still reach the session another way: an inline image's OCR text read as a
PERSON (then the image remask sweeps every text), or an earlier turn of the session that
declared no tools. The every-occurrence sweep then rewrote the ``muse`` identifier and the
request was refused. Values the operator pre-loaded (``known``) keep failing closed.
All values are fictional (ADR 0005).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gateway_helpers import (
    NAMES,
    TEST_TENANT_KEY,
    UPSTREAM_KEY,
    UPSTREAM_URL,
    FakeLlm,
    MockUpstream,
)
from test_image_parts import Sam, data_url, png
from test_responses import ResponsesUpstream, muse_body

from pii_guard.api.app import create_app
from pii_guard.config import Settings
from pii_guard.gateway import Gateway, GatewayConfig, Mode, build_mode_detectors
from pii_guard.gateway.tool_names import (
    identifier_keeps_tool_names,
    tool_names,
    without_tool_names,
)
from pii_guard.types import EntityType, Span
from pii_guard.vault import Vault
from pii_guard.visual import OcrWord, SamClient
from pii_guard.visual.regions import Box

PERSON = NAMES[0]  # Teszt Elek
LLM_NAMES = (*NAMES, "Muse")


class MuseOcr:
    """The image's text is the product name, which the fake NER reads as a PERSON."""

    name = "fake-ocr"

    def words(self, image: object) -> list[OcrWord]:
        return [OcrWord("Muse", Box(130, 40, 200, 59), (0,))]


def make_app(upstream: MockUpstream) -> FastAPI:
    settings = Settings(
        tenant_key=TEST_TENANT_KEY,
        upstream_base_url=UPSTREAM_URL,
        upstream_api_key=UPSTREAM_KEY,
        image_render="labels",  # image values join the session (LAB-1278)
    )
    config = GatewayConfig(mode=Mode.AUDIT)
    app = create_app(settings)
    app.state.vault = Vault.from_settings(settings)  # shared with /v1/sessions
    app.state.gateway = Gateway(
        settings=settings,
        vault=app.state.vault,
        config=config,
        detectors=build_mode_detectors(settings, config, llm_detector=FakeLlm(LLM_NAMES)),
        transport=upstream.transport(),
        sam=SamClient(api_key="test-key", transport=httpx.MockTransport(Sam()), max_retries=0),
        ocr=MuseOcr(),  # type: ignore[arg-type]
    )
    return app


def chat_tool(name: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": name, "description": "Runs a step.", "parameters": {}},
    }


def chat_body(*, tools: bool = True, image: bool = False) -> dict[str, Any]:
    user: Any = f"Írj levelet {PERSON} nevében."
    if image:
        user = [
            {"type": "text", "text": user},
            {"type": "image_url", "image_url": {"url": data_url(png())}},
        ]
    call = {"id": "call_1", "type": "function", "function": {"name": "muse", "arguments": "{}"}}
    body: dict[str, Any] = {
        "model": "m",
        "messages": [
            {"role": "system", "content": "You are a coding agent."},
            {"role": "user", "content": user},
        ],
    }
    if tools:
        body["messages"] += [
            {"role": "assistant", "content": None, "tool_calls": [call]},
            {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        ]
        body["tools"] = [chat_tool("muse"), chat_tool("write_file")]
        body["tool_choice"] = {"type": "function", "function": {"name": "muse"}}
    return body


def responses_body(*, tools: bool = True, image: bool = False) -> dict[str, Any]:
    body = muse_body()
    if image:
        body["input"][1]["content"] = [
            {"type": "input_text", "text": "Read client-letter.md and reply to Jane Placeholder."},
            {"type": "input_image", "image_url": data_url(png()), "detail": "high"},
        ]
    if not tools:
        body.pop("tools")
        body["input"] = body["input"][:2]
    return body


def assert_chat_kept(response: httpx.Response, upstream: MockUpstream) -> None:
    assert response.status_code == 200, response.text
    forwarded = upstream.bodies[-1]
    assert [t["function"]["name"] for t in forwarded["tools"]] == ["muse", "write_file"]
    assert forwarded["messages"][2]["tool_calls"][0]["function"]["name"] == "muse"
    assert forwarded["tool_choice"]["function"]["name"] == "muse"
    raw = upstream.requests[-1].content.decode()
    assert PERSON not in raw


def assert_responses_kept(response: httpx.Response, upstream: ResponsesUpstream) -> None:
    assert response.status_code == 200, response.text
    forwarded = json.loads(upstream.requests[-1].content)
    assert forwarded["tools"][0]["name"] == "muse"
    assert forwarded["tools"][0]["tools"][0]["name"] == "write_file"
    assert forwarded["input"][4]["name"] == "muse.read_file"
    assert PERSON not in upstream.requests[-1].content.decode()


# --- the word comes from an image's OCR text -----------------------------------------------


def test_chat_image_text_equal_to_a_tool_name_does_not_refuse() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/chat/completions", json=chat_body(image=True))
    assert_chat_kept(response, upstream)


def test_responses_image_text_equal_to_a_tool_name_does_not_refuse() -> None:
    upstream = ResponsesUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/responses", json=responses_body(image=True))
    assert_responses_kept(response, upstream)


# --- the word comes from an earlier turn that declared no tools -----------------------------


def test_chat_value_from_an_earlier_toolless_turn_does_not_refuse() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        first = http.post(
            "/s/c_lab1324_chat_0001/v1/chat/completions",
            json={"model": "m", "messages": [{"role": "user", "content": "Hi Muse."}]},
        )
        assert first.status_code == 200, first.text
        assert "Muse" not in upstream.requests[-1].content.decode()  # learned as a PERSON
        response = http.post("/s/c_lab1324_chat_0001/v1/chat/completions", json=chat_body())
    assert_chat_kept(response, upstream)


def test_responses_value_from_an_earlier_toolless_turn_does_not_refuse() -> None:
    upstream = ResponsesUpstream()
    with TestClient(make_app(upstream)) as http:
        first_body = responses_body(tools=False)
        # ``model`` is identifier-checked (LAB-1563): with no tool declared, a model name
        # containing the detected word would refuse this setup turn itself.
        first_body["model"] = "m"
        first_body["input"][0]["content"] = "Hi Muse."
        first = http.post("/s/c_lab1324_resp_0001/v1/responses", json=first_body)
        assert first.status_code == 200, first.text
        assert "Hi Muse." not in upstream.requests[-1].content.decode()
        response = http.post("/s/c_lab1324_resp_0001/v1/responses", json=responses_body())
    assert_responses_kept(response, upstream)


# --- pre-loaded known values still fail closed ---------------------------------------------


def test_a_preloaded_known_value_still_refuses_with_an_image() -> None:
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        created = http.post(
            "/v1/sessions", json={"known_values": [{"value": "Muse", "entity_type": "PERSON"}]}
        )
        assert created.status_code == 201, created.text
        response = http.post(
            "/v1/chat/completions",
            json=chat_body(image=True),
            headers={"X-PII-Guard-Session": created.json()["session_id"]},
        )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "unsupported_content"
    assert upstream.requests == []


def test_a_preloaded_known_value_still_refuses_on_responses() -> None:
    upstream = ResponsesUpstream()
    with TestClient(make_app(upstream)) as http:
        created = http.post(
            "/v1/sessions", json={"known_values": [{"value": "muse", "entity_type": "PERSON"}]}
        )
        response = http.post(
            "/v1/responses",
            json=responses_body(),
            headers={"X-PII-Guard-Session": created.json()["session_id"]},
        )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "unsupported_content"
    assert upstream.requests == []


# --- other personal data in an identifier still fails closed -------------------------------


def test_a_real_name_in_an_identifier_is_still_refused_after_the_tool_name() -> None:
    """The exemption covers the declared names only: a name the vault holds, glued to a tool
    name in one identifier, still refuses the request."""
    upstream = MockUpstream()
    body = chat_body(image=True)
    body["messages"][2]["tool_calls"][0]["function"]["name"] = f"muse.{PERSON}"
    with TestClient(make_app(upstream)) as http:
        first = http.post(
            "/s/c_lab1324_chat_0002/v1/chat/completions",
            json={"model": "m", "messages": [{"role": "user", "content": f"Mail {PERSON}."}]},
        )
        assert first.status_code == 200, first.text
        response = http.post("/s/c_lab1324_chat_0002/v1/chat/completions", json=body)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "unsupported_content"


def test_identifier_keeps_tool_names() -> None:
    values = {"[[PERSON_aaaa]]": "Muse", "[[PERSON_bbbb]]": "Teszt Elek"}

    def original(placeholder: str) -> str | None:
        return values.get(placeholder)

    names = frozenset({"muse", "write_file"})
    keeps = identifier_keeps_tool_names
    assert keeps("muse", "[[PERSON_aaaa]]", names, original)
    assert keeps("muse.read_file", "[[PERSON_aaaa]].read_file", names, original)
    assert keeps("MUSE", "[[PERSON_aaaa]]", names, original)
    # The rewritten surface or the placeholder's value is not a declared name: refused.
    assert not keeps("Teszt Elek", "[[PERSON_bbbb]]", names, original)
    assert not keeps("muse", "[[PERSON_bbbb]]", names, original)
    # A suffix kept outside the placeholder: still only the declared name was rewritten.
    assert keeps("musenak", "[[PERSON_aaaa]]nak", names, original)
    assert not keeps("muse", "[[PERSON_cccc]]", names, original)  # not this session's
    # Anything else changed: refused.
    assert not keeps("muse.x", "[[PERSON_aaaa]].y", names, original)
    assert not keeps("muse", "[[PERSON_aaaa]]", frozenset(), original)
    # Nothing masked: kept only if nothing changed at all.
    assert keeps("muse", "muse", names, original)
    assert not keeps("muse", "other", names, original)
    # A placeholder of a type found by format or checksum is never a tool word (LAB-1348).
    tax = {"[[NATIONAL_ID_HU_TAX_aaaa]]": "8123456786"}
    assert not keeps("8123456786", "[[NATIONAL_ID_HU_TAX_aaaa]]", TAX_NAMES, tax.get)


# --- the exemption covers word-like types only (LAB-1348) -----------------------------------

TAX_ID = "8123456786"  # fictional, checksum-valid
IBAN_COMPACT = "HU42117730161111101800000000"  # gateway_helpers.IBAN without spaces
TAX_NAMES = frozenset({TAX_ID})


def structured_chat(name: str, value: str) -> dict[str, Any]:
    return {
        "model": "m",
        "messages": [{"role": "user", "content": f"Az azonosítóm {value}, kérlek ellenőrizd."}],
        "tools": [chat_tool(name)],
    }


def structured_responses(name: str, value: str) -> dict[str, Any]:
    return {
        "model": "m",
        "input": [{"role": "user", "content": f"Az azonosítóm {value}, kérlek ellenőrizd."}],
        "tools": [{"type": "function", "name": name, "parameters": {}}],
    }


@pytest.mark.parametrize("value", [TAX_ID, IBAN_COMPACT, "teszt.elek@example.com"])
def test_a_tool_named_after_a_structured_value_fails_closed_on_chat(value: str) -> None:
    """A tool named after a valid tax ID used to keep that ID unmasked in every text, and the
    name went upstream too. The value is personal data whatever the tools are called: the
    identifier can't carry a placeholder, so the request is refused, nothing is forwarded."""
    upstream = MockUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/chat/completions", json=structured_chat(value, value))
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "unsupported_content"
    assert value not in response.text
    assert upstream.requests == []


@pytest.mark.parametrize("value", [TAX_ID, IBAN_COMPACT])
def test_a_tool_named_after_a_structured_value_fails_closed_on_responses(value: str) -> None:
    upstream = ResponsesUpstream()
    with TestClient(make_app(upstream)) as http:
        response = http.post("/v1/responses", json=structured_responses(value, value))
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "unsupported_content"
    assert upstream.requests == []


@pytest.mark.parametrize("value", [TAX_ID, IBAN_COMPACT])
def test_a_structured_value_in_text_is_masked_when_a_tool_is_named_after_it(value: str) -> None:
    """The texts: the value stays a detection, it is never dropped as tool vocabulary."""
    texts = [f"Az azonosítóm {value}."]
    start = texts[0].index(value)
    entity = EntityType.NATIONAL_ID_HU_TAX if value == TAX_ID else EntityType.BANK_ACCOUNT
    found = [[Span(start, start + len(value), entity, value, 0.99, "rules")]]
    names = tool_names(structured_chat(value, value))
    assert names  # identifier-shaped, so declared
    assert without_tool_names(texts, found, names) == found
    # A word-like type of the same name is dropped in an identifier slot only; in prose it
    # is kept and masked (LAB-1299 as restricted by LAB-1563).
    person = [[Span(start, start + len(value), EntityType.PERSON, value, 0.9, "ner")]]
    assert without_tool_names(texts, person, names, ["identifier"]) == [[]]
    assert without_tool_names(texts, person, names, ["content"]) == person
    assert without_tool_names(texts, person, names) == person


# --- a tool named after a person does not unmask prose (LAB-1563) ---------------------------


def test_chat_prose_matching_a_tool_name_is_masked_identifiers_kept() -> None:
    """A client could unmask a real name in every text by naming a tool after it: the
    exemption now covers the tool-name identifiers only, prose is masked as usual."""
    from gateway_helpers import make_app as shared_make_app

    upstream = MockUpstream()
    app = shared_make_app(upstream, llm=FakeLlm((*NAMES, "Kovacs")))
    body: dict[str, Any] = {
        "model": "m",
        "messages": [{"role": "user", "content": "Kovacs called yesterday."}],
        "tools": [chat_tool("Kovacs")],
    }
    with TestClient(app) as http:
        response = http.post("/v1/chat/completions", json=body)
    assert response.status_code == 200, response.text
    forwarded = upstream.bodies[-1]
    assert forwarded["tools"][0]["function"]["name"] == "Kovacs"
    content = forwarded["messages"][-1]["content"]
    assert content.startswith("[[PERSON_") and "called yesterday." in content
    assert "Kovacs called" not in upstream.requests[-1].content.decode()


def test_responses_prose_matching_a_tool_name_is_masked_identifiers_kept() -> None:
    from gateway_helpers import make_app as shared_make_app

    upstream = ResponsesUpstream()
    app = shared_make_app(upstream, llm=FakeLlm((*NAMES, "Kovacs")))
    body: dict[str, Any] = {
        "model": "m",
        "input": [{"role": "user", "content": "Kovacs called yesterday."}],
        "tools": [{"type": "function", "name": "Kovacs", "parameters": {}}],
    }
    with TestClient(app) as http:
        response = http.post("/v1/responses", json=body)
    assert response.status_code == 200, response.text
    forwarded = json.loads(upstream.requests[-1].content)
    assert forwarded["tools"][0]["name"] == "Kovacs"
    content = forwarded["input"][-1]["content"]
    assert content.startswith("[[PERSON_") and "called yesterday." in content
    assert "Kovacs called" not in upstream.requests[-1].content.decode()
