"""Corpus generator with a mocked model: planning, span location, discards, cache, CLI.

All data is fictional (ADR 0005). The one ``live`` test calls the Meta Model API with a
fictional prompt and is skipped without ``META_API_KEY``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from pii_guard import cli
from pii_guard.eval import generate as gen
from pii_guard.eval.fixtures import load_fixtures
from pii_guard.eval.generate import (
    ChatClient,
    DocumentPlan,
    ModelError,
    ResponseCache,
    assign_splits,
    clean_output,
    generate_corpus,
    generate_document,
    load_language,
    locate_values,
    parse_split,
    plan_document,
)
from pii_guard.eval.identities import _HU_TOWNS, Value
from pii_guard.types import EntityType as E

LIVE_KEY = os.environ.get("META_API_KEY")

Handler = Callable[[httpx.Request], httpx.Response]


def completion(content: str, finish_reason: str = "stop") -> dict[str, object]:
    return {
        "model": "muse-test",
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "completion_tokens_details": {"reasoning_tokens": 30},
        },
    }


def prompt_values(request: httpx.Request) -> list[str]:
    """The values listed in the user prompt (``- label: value`` lines)."""
    user = json.loads(request.content)["messages"][1]["content"]
    block = user.split("Values:", 1)[1]
    return [line.split(": ", 1)[1] for line in block.splitlines() if line.startswith("- ")]


def echo_writer(request: httpx.Request) -> httpx.Response:
    """A 'model' that writes every supplied value into a document, one per line."""
    lines = [f"Adat: {value} ." for value in prompt_values(request)]
    return httpx.Response(200, json=completion("\n".join(lines)))


def make_client(handler: Handler, calls: list[httpx.Request] | None = None, **kw) -> ChatClient:
    def wrapped(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return handler(request)

    kw.setdefault("sleep", lambda _s: None)
    return ChatClient(
        base_url="https://model.test/v1",
        api_key="test-key",
        model="muse-test",
        transport=httpx.MockTransport(wrapped),
        **kw,
    )


def pairs(doc) -> list[tuple[str, str]]:
    return [(s.entity_type.value, s.text) for s in doc.spans]


# --- Templates and planning ---------------------------------------------------------------


@pytest.mark.parametrize("language", ["hu", "en"])
def test_every_template_plans(language: str) -> None:
    pack = load_language(language)
    assert len(pack.kinds) >= 8
    kinds = {k.id for k in pack.kinds}
    assert {"sale-contract", "lease", "power-of-attorney", "court-notice", "invoice"} <= kinds
    assert {"letter", "email", "chat"} <= kinds
    for template in pack.kinds:
        plan = plan_document(language, 7, 0, kind=template.id)
        assert plan.kind == template.id
        assert plan.required, template.id
        user = plan.messages[1]["content"]
        for value in plan.required:
            assert value.text in user
        system = plan.messages[0]["content"]
        assert pack.language_name in system and "{" not in system + user


def test_hungarian_templates_include_a_land_registry_extract() -> None:
    plan = plan_document("hu", 1, 0, kind="land-registry")
    types = {v.entity_type for v in plan.required}
    assert {E.PARCEL_NUMBER_HU, E.PERSON, E.ADDRESS, E.ORGANIZATION} <= types


@pytest.mark.parametrize("kind", ["land-registry", "power-of-attorney"])
def test_land_registry_office_is_in_the_property_town(kind: str) -> None:
    """The office that registers a property sits in the property's own town (LAB-1105)."""
    for seed in range(30):
        plan = plan_document("hu", seed, 0, kind=kind)
        office = next(v.text for v in plan.values if v.field == "org_name" and "Hivatal" in v.text)
        parcel = next(i for i, v in enumerate(plan.values) if v.field == "parcel")
        prop = plan.values[parcel + 1].text  # the property's fields: parcel, address
        town = prop.split(",")[0].split(" ", 1)[1]
        assert any(
            t == town and office.startswith(adjective.split()[0]) for t, adjective, _ in _HU_TOWNS
        ), seed


def test_unknown_language_or_kind() -> None:
    with pytest.raises(gen.GenerationError, match="no document templates"):
        load_language("xx")
    with pytest.raises(KeyError):
        plan_document("hu", 1, 0, kind="haiku")


def test_plan_is_deterministic_per_seed_and_index() -> None:
    a = plan_document("hu", 42, 3)
    assert a == plan_document("hu", 42, 3)
    assert a.doc_id == "hu-synth-s42-00003"
    assert a.messages != plan_document("hu", 42, 4).messages
    assert a.messages != plan_document("hu", 43, 3).messages
    assert "values=" in repr(a) and a.required[0].text not in repr(a)


def test_informal_parties_offer_the_given_name() -> None:
    plan = plan_document("en", 5, 0, kind="chat")
    assert "given name, for informal address" in plan.messages[1]["content"]
    assert "typos" in plan.messages[1]["content"]
    formal = plan_document("en", 5, 0, kind="invoice")
    assert "given name" not in formal.messages[1]["content"]


# --- Locating values ------------------------------------------------------------------------


def V(field: str, t: E, text: str, required: bool = True, cap: bool = False) -> Value:
    return Value(field, t, text, required=required, capitalized=cap)


def test_locate_values_finds_all_occurrences_and_hungarian_inflections() -> None:
    values = [
        V("name", E.PERSON, "Kovács Anna"),
        V("given", E.PERSON, "Anna", required=False, cap=True),
        V("family", E.PERSON, "Kovács", required=False, cap=True),
        V("phone", E.PHONE, "+36 30 123 4567"),
        V("org_name", E.ORGANIZATION, "Napfény Ingatlan Kft."),
    ]
    text = (
        "Kovács Annának a Napfény Ingatlan Kft.-vel kötött szerződése szerint Kovács Anna "
        "a 06 30 123 4567-es számon érhető el. Annával és Kováccsal megbeszéltük. "
        "A kovács műhelye zárva."
    )
    spans, missing = locate_values(text, values, "hu")
    assert missing == []
    found = [(s.entity_type.value, s.text) for s in spans]
    assert found == [
        ("PERSON", "Kovács Annának"),  # stem-changing form: the whole word (forms.py)
        ("ORGANIZATION", "Napfény Ingatlan Kft."),
        ("PERSON", "Kovács Anna"),
        ("PHONE", "06 30 123 4567"),
        ("PERSON", "Annával"),
        ("PERSON", "Kováccsal"),
    ]  # lower-case "kovács" (a smith) is not a name


def test_locate_values_reports_missing_required_values_only() -> None:
    values = [
        V("name", E.PERSON, "Amelia Carter"),
        V("given", E.PERSON, "Amelia", required=False, cap=True),
        V("iban", E.BANK_ACCOUNT, "GB33 BUKB 2020 1555 5555 55"),
    ]
    spans, missing = locate_values("Dear Ms Carter's friend Amelia,", values, "en")
    assert [v.field for v in missing] == ["name", "iban"]
    assert [(s.entity_type.value, s.text) for s in spans] == [("PERSON", "Amelia")]


def test_clean_output_strips_fences_and_reasoning() -> None:
    assert clean_output("```text\nHello\nWorld\n```") == "Hello\nWorld"
    assert clean_output("<think>plan</think>\r\nDoc\r\n") == "Doc"
    assert clean_output("   ") == ""


# --- One document ------------------------------------------------------------------------------


def test_generate_document_labels_every_supplied_value() -> None:
    plan = plan_document("hu", 1, 0, kind="sale-contract")
    outcome = generate_document(plan, make_client(echo_writer), split="train")
    assert outcome.accepted and outcome.reason is None
    doc = outcome.document
    assert doc is not None and doc.id == plan.doc_id and doc.language == "hu"
    labelled = {s.text for s in doc.spans}
    assert {v.text for v in plan.required} <= labelled
    assert doc.meta["kind"] == "sale-contract" and doc.meta["split"] == "train"
    assert doc.meta["source"] == "synthetic" and doc.meta["model"] == "muse-test"
    assert outcome.completion is not None and outcome.completion.usage["reasoning_tokens"] == 30


def test_document_with_a_missing_value_is_discarded() -> None:
    plan = plan_document("hu", 1, 0, kind="invoice")
    dropped = next(v for v in plan.required if v.entity_type is E.BANK_ACCOUNT)

    def forgetful(request: httpx.Request) -> httpx.Response:
        values = [v for v in prompt_values(request) if v != dropped.text]
        return httpx.Response(200, json=completion("\n".join(f"- {v} ." for v in values)))

    outcome = generate_document(plan, make_client(forgetful))
    assert not outcome.accepted
    assert outcome.reason == "missing_value" and outcome.missing == (E.BANK_ACCOUNT,)


def test_document_with_an_invented_identifier_is_discarded() -> None:
    plan = plan_document("hu", 1, 0, kind="court-notice")

    def inventive(request: httpx.Request) -> httpx.Response:
        body = "\n".join(f"{v} ." for v in prompt_values(request))
        return httpx.Response(200, json=completion(body + "\nÍrjon: titkarsag@example.net"))

    outcome = generate_document(plan, make_client(inventive))
    assert outcome.reason == "unsupplied_value" and outcome.unsupplied == (E.EMAIL,)


@pytest.mark.parametrize(
    ("content", "finish", "reason"),
    [("half a docu", "length", "truncated"), ("```\n\n```", "stop", "empty_output")],
)
def test_truncated_or_empty_output_is_discarded(content: str, finish: str, reason: str) -> None:
    client = make_client(lambda r: httpx.Response(200, json=completion(content, finish)))
    assert generate_document(plan_document("en", 1, 0), client).reason == reason


def test_transient_errors_are_retried_then_discarded() -> None:
    calls: list[httpx.Request] = []
    responses = iter([httpx.Response(503), httpx.Response(200, json={"nope": 1})])

    def flaky(request: httpx.Request) -> httpx.Response:
        try:
            return next(responses)
        except StopIteration:
            return echo_writer(request)

    plan = plan_document("en", 2, 0)
    assert generate_document(plan, make_client(flaky, calls)).accepted
    assert len(calls) == 3

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    outcome = generate_document(plan, make_client(down, max_retries=1))
    assert outcome.reason == "model_error" and outcome.completion is None


def test_configuration_errors_abort_the_run() -> None:
    client = make_client(lambda r: httpx.Response(401, json={"error": "bad key"}))
    with pytest.raises(ModelError, match="HTTP 401") as info:
        generate_document(plan_document("hu", 1, 0), client)
    assert not info.value.retryable
    assert "test-key" not in repr(client)
    with pytest.raises(ValueError, match="always reason"):
        ChatClient(reasoning_effort="none")


def test_payload_sends_reasoning_effort_and_model() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer test-key"
        assert str(request.url) == "https://model.test/v1/chat/completions"
        return echo_writer(request)

    generate_document(plan_document("hu", 1, 0), make_client(handler, reasoning_effort="minimal"))
    assert seen[0]["model"] == "muse-test" and seen[0]["reasoning_effort"] == "minimal"
    assert seen[0]["temperature"] == 0.8 and seen[0]["max_tokens"] == 8192
    bare = ChatClient(reasoning_effort=None, temperature=None, max_tokens=None)
    assert set(bare.payload([])) == {"model", "messages"}
    assert gen.DEFAULT_MODEL == "muse-spark-1.3-contributor"


# --- Corpus, cache, splits ---------------------------------------------------------------------


def test_corpus_is_deterministic_and_cached(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    cache = ResponseCache(tmp_path / "cache")
    first = generate_corpus("hu", 10, 42, make_client(echo_writer, calls), cache, workers=4)
    assert len(calls) == 10
    again = generate_corpus("hu", 10, 42, make_client(echo_writer, calls), cache, workers=1)
    assert len(calls) == 10, "second run is served from the cache"
    assert [d.to_dict() for d in first.documents] == [d.to_dict() for d in again.documents]
    stats = again.stats()
    assert stats["cache_hits"] == 10 and stats["model_calls"] == 0
    assert stats["accepted"] == 10 and stats["discard_rate"] == 0.0
    assert stats["usage"]["prompt_tokens"] == 1000
    assert sum(stats["splits"].values()) == 10 and stats["splits"]["train"] == 7
    other = generate_corpus("hu", 10, 43, make_client(echo_writer), None)
    assert [d.text for d in other.documents] != [d.text for d in first.documents]


def test_stats_count_discards_without_values() -> None:
    def picky(request: httpx.Request) -> httpx.Response:
        values = prompt_values(request)
        return httpx.Response(200, json=completion("\n".join(values[1:])))  # drops the first

    result = generate_corpus("en", 4, 1, make_client(picky), None, kinds=["invoice"])
    stats = result.stats()
    assert stats["accepted"] == 0 and stats["discard_rate"] == 1.0
    assert stats["discard_reasons"] == {"missing_value": 4}
    assert stats["missing_value_types"] == {"ORGANIZATION": 4}
    assert stats["by_kind"] == {"invoice": {"accepted": 0, "discarded": 4}}
    rendered = json.dumps(stats)
    plan = result.outcomes[0].plan
    assert all(v.text not in rendered for v in plan.values)
    with pytest.raises(ValueError):
        generate_corpus("en", 0, 1, make_client(picky))


def test_splits() -> None:
    assert parse_split("70/15/15") == pytest.approx((0.7, 0.15, 0.15))
    assert parse_split("8,1,1") == pytest.approx((0.8, 0.1, 0.1))
    for bad in ("70/30", "a/b/c", "0/0/0", "-1/1/1"):
        with pytest.raises(ValueError):
            parse_split(bad)
    labels = assign_splits(20, 1, (0.7, 0.15, 0.15))
    assert sorted(labels).count("train") == 14 and labels.count("dev") == 3
    assert labels == assign_splits(20, 1, (0.7, 0.15, 0.15))
    assert len(assign_splits(7, 1, (0.7, 0.15, 0.15))) == 7


# --- CLI ---------------------------------------------------------------------------------------


@pytest.fixture
def mocked_client(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    calls: list[httpx.Request] = []
    real = gen.ChatClient

    def factory(**kwargs) -> ChatClient:
        kwargs["transport"] = httpx.MockTransport(lambda r: calls.append(r) or echo_writer(r))
        return real(**kwargs)

    monkeypatch.setattr(gen, "ChatClient", factory)
    return calls


def test_cli_writes_split_files_and_stats(tmp_path: Path, mocked_client: list) -> None:
    out = tmp_path / "corpus"
    code = cli.main(
        ["eval", "generate", "--language", "en", "--n", "6", "--seed", "3", "--out", str(out),
         "--cache", str(tmp_path / "c"), "--split", "50/25/25"]
    )  # fmt: skip
    assert code == 0 and len(mocked_client) == 6
    files = sorted(p.name for p in out.iterdir())
    assert files == [
        "en-synth-dev.jsonl",
        "en-synth-stats.json",
        "en-synth-test.jsonl",
        "en-synth-train.jsonl",
    ]
    docs = load_fixtures(out)
    assert len(docs) == 6 and {d.meta["split"] for d in docs} == {"train", "dev", "test"}
    stats = json.loads((out / "en-synth-stats.json").read_text())
    assert stats["accepted"] == 6 and stats["language"] == "en"
    # The model URL and model name come from the environment when not given as flags.
    assert str(mocked_client[0].url) == "https://api.meta.ai/v1/chat/completions"
    assert json.loads(mocked_client[0].content)["model"] == "muse-spark-1.3-contributor"


def test_cli_single_file_output_and_env(
    tmp_path: Path, mocked_client: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PII_GUARD_CORPUS_URL", "https://other.test/v1")
    monkeypatch.setenv("PII_GUARD_CORPUS_MODEL", "muse-other")
    monkeypatch.setenv("META_API_KEY", "fallback-key")
    out = tmp_path / "hu-sample.jsonl"
    stats = tmp_path / "stats.json"
    assert gen.main(["--n", "2", "--out", str(out), "--stats", str(stats), "--no-cache"]) == 0
    assert len(load_fixtures(out)) == 2 and json.loads(stats.read_text())["requested"] == 2
    request = mocked_client[0]
    assert str(request.url).startswith("https://other.test/v1")
    assert request.headers["Authorization"] == "Bearer fallback-key"
    assert json.loads(request.content)["model"] == "muse-other"


def test_cli_dry_run_and_bad_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    assert gen.main(["--language", "hu", "--dry-run", "--kinds", "lease"]) == 0
    printed = capsys.readouterr().out
    assert "--- system" in printed and "Lakásbérleti" in printed
    assert gen.main(["--split", "1/2"]) == 2
    assert gen.main(["--language", "xx", "--out", "x.jsonl"]) == 2
    assert gen.main(["--kinds", "haiku", "--out", "x.jsonl"]) == 2
    assert gen.main(["--n", "0", "--out", "x.jsonl"]) == 2
    assert gen.main([]) == 2  # --out required unless --dry-run


def test_cli_aborts_on_configuration_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = gen.ChatClient

    def factory(**kwargs) -> ChatClient:
        kwargs["transport"] = httpx.MockTransport(lambda r: httpx.Response(403))
        return real(**kwargs)

    monkeypatch.setattr(gen, "ChatClient", factory)
    assert gen.main(["--n", "1", "--out", str(tmp_path / "x.jsonl"), "--no-cache"]) == 1
    assert not (tmp_path / "x.jsonl").exists()


def test_committed_samples_are_valid_generator_output() -> None:
    root = Path(__file__).resolve().parents[2] / "eval" / "fixtures"
    for name, language in (("hu-synth-sample.jsonl", "hu"), ("en-synth-sample.jsonl", "en")):
        path = root / name
        if not path.exists():
            pytest.skip("sample not generated yet")
        docs = load_fixtures(path)
        assert docs and all(d.language == language for d in docs)
        assert all(d.meta["source"] == "synthetic" for d in docs)
        assert all(d.meta["generator"].startswith("pii_guard.eval.generate/") for d in docs)
        assert all(d.spans for d in docs)


# --- Live -------------------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.skipif(not LIVE_KEY, reason="META_API_KEY not set")
def test_live_meta_model_api_writes_a_labelled_document() -> None:
    """Fictional values only: hosted models never see real data (docs/models.md)."""
    client = ChatClient(api_key=LIVE_KEY, reasoning_effort="minimal")
    try:
        plan: DocumentPlan = plan_document("hu", 2026, 0, kind="email")
        outcome = generate_document(plan, client)
    finally:
        client.close()
    assert outcome.completion is not None and outcome.completion.content.strip()
    assert outcome.reason in {None, "missing_value", "unsupplied_value"}
    if outcome.document is not None:
        assert {v.text for v in plan.required} <= {s.text for s in outcome.document.spans}
