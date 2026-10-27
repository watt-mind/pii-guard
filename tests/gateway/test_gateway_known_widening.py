"""A name found whole somewhere repairs the same name found in part (LAB-1284).

NER sometimes returns only part of a name (``Placeholder`` in the CSV row ``1,Jane
Placeholder``). Without widening the gateway forwarded ``1,Jane [[PERSON_x]]``: the second-pass
sweep can't find ``Jane Placeholder`` once its surname is a placeholder. All values are
fictional (ADR 0005); the upstream is a mock.
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient
from gateway_helpers import MockUpstream, make_app

from pii_guard.types import EntityType, Span
from pii_guard.vault import PLACEHOLDER_RE

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

LETTER = "Dear Jane Placeholder, your contract is attached."
CSV = "id,name,email\n1,Jane Placeholder,jane.placeholder@example.net\n2,John Sample,x@example.org"


class PartialNer:
    """A detector that finds the full name in prose, only parts of it elsewhere."""

    name = "llm"
    model = "partial-ner"

    def __init__(self, found: dict[str, list[str]]) -> None:
        # text marker -> the values it reports in a text containing that marker
        self.found = found

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        spans: list[Span] = []
        for marker, values in self.found.items():
            if marker not in text:
                continue
            for value in values:
                for m in re.finditer(rf"(?<!\w){re.escape(value)}(?!\w)", text):
                    if any(s.start < m.end() and m.start() < s.end for s in spans):
                        continue
                    spans.append(Span(m.start(), m.end(), EntityType.PERSON, value, 0.9, "llm"))
        return spans


def post(http: TestClient, messages: list[dict[str, str]], **headers: str):
    return http.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": messages},
        headers={"X-PII-Guard-Mode": "audit", **headers},
    )


def upstream_text(upstream: MockUpstream, index: int = -1) -> str:
    return json.dumps(upstream.bodies[index]["messages"], ensure_ascii=False)


def test_full_name_in_one_message_repairs_a_partial_csv_row() -> None:
    llm = PartialNer({"Dear": ["Jane Placeholder"], "id,name": ["Placeholder", "Sample"]})
    upstream = MockUpstream()
    with TestClient(make_app(upstream, llm=llm)) as http:
        response = post(
            http,
            [
                {"role": "user", "content": CSV},
                {"role": "user", "content": LETTER},
            ],
        )
    assert response.status_code == 200
    sent = upstream_text(upstream)
    assert "Jane" not in sent
    assert "Placeholder" not in sent
    rows = upstream.bodies[-1]["messages"][0]["content"]
    letter = upstream.bodies[-1]["messages"][1]["content"]
    # One placeholder for the name, the same in the CSV row and in the letter.
    row_token = PLACEHOLDER_RE.search(rows.splitlines()[1]).group(0)
    assert row_token in letter
    assert rows.splitlines()[1].startswith(f"1,{row_token},")
    # A name nobody found whole elsewhere is left to the detector: "John" is not invented.
    assert "John [[PERSON_" in rows


def test_value_from_an_earlier_turn_repairs_a_partial_span() -> None:
    llm = PartialNer({"Client:": ["John Sample"], "- John": ["John"]})
    upstream = MockUpstream()
    with TestClient(make_app(upstream, llm=llm)) as http:
        first = post(http, [{"role": "user", "content": "Client: John Sample."}])
        session = first.headers["x-pii-guard-session"]
        second = post(
            http,
            [{"role": "user", "content": "Attendees:\n- John Sample\n- someone else"}],
            **{"X-PII-Guard-Session": session},
        )
    assert second.status_code == 200
    sent = upstream_text(upstream)
    assert "Sample" not in sent
    first_token = PLACEHOLDER_RE.search(upstream_text(upstream, 0)).group(0)
    assert f"- {first_token}\n" in upstream.bodies[-1]["messages"][0]["content"]
