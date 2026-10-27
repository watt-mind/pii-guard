"""Re-identification red team: targets, matching, the attacker client and the report."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from pii_guard.eval import dump_document, from_markup, label
from pii_guard.eval.cli import main as eval_main
from pii_guard.eval.redteam import (
    CONTEXTS,
    Attacker,
    RedTeamError,
    Target,
    add_redteam_arguments,
    attacker_from_args,
    build_messages,
    build_targets,
    candidate_lists,
    guess_matches,
    parse_guesses,
    redteam_breakdown,
    render_redteam_table,
    run_redteam,
)
from pii_guard.eval.scorer import DetectorAnalyzer, run_documents
from pii_guard.types import EntityType
from pii_guard.vault import PLACEHOLDER_RE

EMAIL_A = "jane.example@example.com"
EMAIL_B = "john.sample@example.org"
IBAN = "GB39 YFKY 4708 0391 7252 97"


def _docs() -> list:
    return [
        # The name survives rules-only masking; the e-mail is masked and spells the name.
        from_markup(
            "en-1",
            f"Dear {label('PERSON', 'Jane Example')}, write to {label('EMAIL', EMAIL_A)}.",
            language="en",
            meta={"kind": "letter"},
        ),
        from_markup(
            "en-2",
            f"Pay {label('BANK_ACCOUNT', IBAN)}, contact {label('EMAIL', EMAIL_B)}.",
            language="en",
            meta={"kind": "invoice"},
        ),
        from_markup("en-3", "Nothing personal here.", language="en"),
    ]


def _results():
    return run_documents(_docs(), DetectorAnalyzer(["rules"]))


def _target(entity_type: EntityType, *forms: str, language: str = "en") -> Target:
    return Target("d", language, "k", entity_type, tuple(forms), ("[[X_0000]]",), False)


# --- Targets and candidates ----------------------------------------------------------------


def test_targets_split_leaked_and_masked_values() -> None:
    results = _results()
    first = build_targets(results[0])
    by_type = {t.entity_type: t for t in first}
    assert by_type[EntityType.PERSON].leaked and not by_type[EntityType.PERSON].masked
    email = by_type[EntityType.EMAIL]
    assert email.masked and len(email.placeholders) == 1
    assert email.placeholders[0] in results[0].masked_text
    assert EMAIL_A not in results[0].masked_text
    assert build_targets(results[2]) == []
    assert "jane" not in repr(email).casefold()


def test_candidate_lists_hold_the_truth_plus_decoys_and_are_deterministic() -> None:
    results = _results()
    by_doc = {r.document.id: build_targets(r) for r in results}
    lists = candidate_lists(by_doc, decoys=4)
    again = candidate_lists(by_doc, decoys=4)
    assert lists == again
    email_ph = next(t for t in by_doc["en-1"] if t.entity_type is EntityType.EMAIL).placeholders[0]
    options = lists[("en-1", email_ph)]
    assert EMAIL_A in options and EMAIL_B in options  # only one other e-mail in the pool
    assert len(options) == len(set(options)) == 2
    # Leaked values get no candidate list.
    assert all(ph.startswith("[[EMAIL") or ph.startswith("[[BANK") for _, ph in lists)


# --- Prompt, answer parsing and matching ---------------------------------------------------


def test_build_messages_lists_placeholders_and_candidates() -> None:
    msgs = build_messages(
        "Hi [[PERSON_abcd12]]", ["[[PERSON_abcd12]]"], {"[[PERSON_abcd12]]": ["A B", "C D"]}
    )
    assert msgs[0]["role"] == "system" and "candidate" in msgs[0]["content"]
    assert '- [[PERSON_abcd12]]: candidates ["A B", "C D"]' in msgs[1]["content"]
    plain = build_messages("Hi [[PERSON_abcd12]]", ["[[PERSON_abcd12]]"])
    assert "best concrete guess" in plain[0]["content"] and "candidates" not in plain[1]["content"]


def test_parse_guesses_accepts_fences_think_tags_and_lists() -> None:
    content = (
        "<think>hmm</think>```json\n"
        '{"guesses": [{"placeholder": "[[PERSON_abcd12]]", "guess": "Jane Example"},'
        ' {"placeholder": "EMAIL_ffff00 [[EMAIL_ffff00]]", "guess": ["a@b.c", " "]},'
        ' {"placeholder": "nope", "guess": "x"},'
        ' {"placeholder": "[[PHONE_1234ab]]", "guess": null}]}'
        "\n```"
    )
    assert parse_guesses(content) == {
        "[[PERSON_abcd12]]": ["Jane Example"],
        "[[EMAIL_ffff00]]": ["a@b.c"],
        "[[PHONE_1234ab]]": [],
    }
    with pytest.raises(ValueError):
        parse_guesses("no json at all")
    with pytest.raises(ValueError):
        parse_guesses('{"answer": 1}')


@pytest.mark.parametrize(
    ("guess", "target", "expected"),
    [
        ("Jane Example", _target(EntityType.PERSON, "Jane Example"), "exact"),
        ("jane  EXAMPLE", _target(EntityType.PERSON, "Jane Example"), "normalized"),
        ("gb39yfky47080391725297", _target(EntityType.BANK_ACCOUNT, IBAN), "normalized"),
        ("+36 30 123 4567", _target(EntityType.PHONE, "+36301234567"), "normalized"),
        ("Minta Anna", _target(EntityType.PERSON, "Minta Annának", language="hu"), "normalized"),
        ("Bob Example", _target(EntityType.PERSON, "Jane Example"), "partial"),
        ("jane.other@example.com", _target(EntityType.EMAIL, EMAIL_A), "partial"),
        ("JANE.EXAMPLE@example.com", _target(EntityType.EMAIL, EMAIL_A), "normalized"),
        ("someone@example.com", _target(EntityType.EMAIL, EMAIL_A), None),
        ("John Doe", _target(EntityType.PERSON, "Jane Example"), None),
        ("GB00 0000", _target(EntityType.BANK_ACCOUNT, IBAN), None),
    ],
)
def test_guess_matches(guess: str, target: Target, expected: str | None) -> None:
    assert guess_matches(guess, target) == expected


# --- Attacker client ----------------------------------------------------------------------


def _answer(content: str, *, status: int = 200, usage: dict | None = None) -> httpx.Response:
    body = {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": usage or {"prompt_tokens": 100, "completion_tokens": 20},
    }
    return httpx.Response(status, json=body)


def _oracle(values: dict[str, str]) -> Callable[[httpx.Request], httpx.Response]:
    """Answers every asked placeholder with ``values[<type prefix>]`` (or null)."""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        asked = PLACEHOLDER_RE.findall(payload["messages"][1]["content"].split(">>>", 1)[1])
        guesses = [
            {"placeholder": f"[[{t}_{i}]]", "guess": values.get(t), "confidence": 0.9}
            for t, i in asked
        ]
        return _answer(json.dumps({"guesses": guesses}))

    return handler


def test_attacker_payload_and_repr_never_show_the_key() -> None:
    attacker = Attacker(api_key="sk-secret", transport=httpx.MockTransport(_oracle({})))
    assert "sk-secret" not in repr(attacker) and "sk-secret" not in json.dumps(attacker.describe())
    payload = attacker.payload([{"role": "user", "content": "x"}])
    assert payload["model"] == "meta-models/muse-spark-open-1026"
    assert payload["reasoning_effort"] == "low"
    assert payload["response_format"] == {"type": "json_object"} and payload["temperature"] == 0
    assert "reasoning_effort" not in Attacker(reasoning_effort="none").payload([])
    assert attacker.url == "https://inference.baseten.co/v1/chat/completions"


def test_attacker_retries_then_fails_closed_without_echoing_the_body() -> None:
    calls = []

    def flaky(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503) if len(calls) == 1 else _answer('{"guesses": []}')

    attacker = Attacker(api_key="k", transport=httpx.MockTransport(flaky))
    assert attacker.complete([{"role": "user", "content": "x"}]) == '{"guesses": []}'
    assert len(calls) == 2 and attacker.usage["requests"] == 1

    bad = Attacker(
        api_key="k", transport=httpx.MockTransport(lambda r: httpx.Response(401, text="echo"))
    )
    with pytest.raises(RedTeamError) as exc:
        bad.complete([{"role": "user", "content": "x"}])
    assert "401" in exc.value.message and "echo" not in exc.value.message


def test_attacker_cache_skips_the_second_request(tmp_path: Path) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _answer('{"guesses": []}')

    for _ in range(2):
        attacker = Attacker(api_key="k", cache_dir=tmp_path, transport=httpx.MockTransport(handler))
        attacker.complete([{"role": "user", "content": "x"}])
    assert len(calls) == 1 and attacker.usage["cache_hits"] == 1
    assert "k" not in json.loads(next(tmp_path.glob("*.json")).read_text())


# --- Whole run and report -----------------------------------------------------------------


def test_run_and_breakdown_score_recovery_exposure_and_chance() -> None:
    results = _results()
    attacker = Attacker(
        api_key="k", transport=httpx.MockTransport(_oracle({"EMAIL": EMAIL_A, "BANK_ACCOUNT": "x"}))
    )
    outcomes = run_redteam(results, attacker, contexts=CONTEXTS, decoys=4, workers=2)
    assert len(outcomes) == 6  # 3 documents x 2 contexts
    # en-3 has no masked target: no request. en-1 and en-2 once per context.
    assert attacker.usage["requests"] == 4
    breakdown = redteam_breakdown(outcomes)
    assert set(breakdown) == set(CONTEXTS)
    total = breakdown["masked-only"]["all"]
    # Values: en-1 PERSON (leaked) + EMAIL; en-2 BANK_ACCOUNT + EMAIL. The oracle names
    # EMAIL_A for every e-mail placeholder: right in en-1, wrong in en-2.
    assert (total["values"], total["leaked"], total["masked"], total["recovered"]) == (4, 1, 3, 1)
    assert total["exact"] == 1 and total["reid_rate"] == pytest.approx(1 / 3)
    assert total["exposure"] == pytest.approx(2 / 4)
    assert total["chance_rate"] is None
    decoys = breakdown["decoys"]["all"]
    # Two e-mails (2 candidates each) and one IBAN with no decoys of its type (1 candidate).
    assert decoys["chance_rate"] == pytest.approx((0.5 + 0.5 + 1.0) / 3)
    assert breakdown["masked-only"]["by_language"]["en"]["values"] == 4
    assert breakdown["masked-only"]["by_entity_type"]["EMAIL"]["recovered"] == 1
    assert breakdown["masked-only"]["by_kind"]["letter"]["recovered"] == 1
    assert breakdown["masked-only"]["recovered_ids"] == ["en-1"]
    table = render_redteam_table(breakdown)
    assert "| `masked-only` | **all** | 4 | 1 | 3 | 1 | 33.3 |" in table
    dumped = json.dumps(breakdown) + table
    for raw in (EMAIL_A, EMAIL_B, IBAN, "Jane Example"):
        assert raw not in dumped


def test_failed_requests_are_counted_and_excluded_from_the_rate() -> None:
    attacker = Attacker(
        api_key="k", transport=httpx.MockTransport(lambda r: httpx.Response(400)), max_retries=0
    )
    outcomes = run_redteam(_results(), attacker, contexts=["masked-only"])
    total = redteam_breakdown(outcomes)["masked-only"]["all"]
    assert total["failed"] == 3 and total["reid_rate"] is None
    assert total["exposure"] == pytest.approx(1.0)  # only the leaked name remains countable
    assert attacker.usage["failures"] == 2

    garbled = Attacker(api_key="k", transport=httpx.MockTransport(lambda r: _answer("not json")))
    outcomes = run_redteam(_results(), garbled, contexts=["masked-only"])
    assert redteam_breakdown(outcomes)["masked-only"]["all"]["failed"] == 3
    with pytest.raises(ValueError):
        run_redteam(_results(), garbled, contexts=["nope"])


# --- CLI ----------------------------------------------------------------------------------


def _fixture(tmp_path: Path) -> Path:
    path = tmp_path / "docs.jsonl"
    path.write_text("\n".join(dump_document(d) for d in _docs()) + "\n", encoding="utf-8")
    return path


def test_cli_needs_an_attacker_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for var in ("PII_GUARD_REDTEAM_API_KEY", "BASETEN_API_KEY", "MY_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert eval_main(["--fixtures", str(_fixture(tmp_path)), "--redteam"]) == 2
    assert "no attacker API key" in capsys.readouterr().err
    args = ["--fixtures", str(_fixture(tmp_path)), "--redteam", "--attacker-key-env", "MY_KEY"]
    assert eval_main(args) == 2
    assert "MY_KEY" in capsys.readouterr().err
    monkeypatch.setenv("MY_KEY", "k")
    assert eval_main([*args, "--redteam-contexts", "bogus"]) == 2


def test_attacker_from_args_reads_the_named_key(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = argparse.ArgumentParser()
    add_redteam_arguments(parser)
    monkeypatch.setenv("META_KEY_FOR_TEST", "secret")
    args = parser.parse_args(
        [
            "--redteam",
            "--attacker-key-env",
            "META_KEY_FOR_TEST",
            "--attacker-url",
            "https://api.meta.ai/v1",
            "--attacker-model",
            "muse-spark-1.3",
        ]
    )
    attacker = attacker_from_args(args)
    assert attacker.configured and attacker.model == "muse-spark-1.3"
    assert attacker.url == "https://api.meta.ai/v1/chat/completions"
    with pytest.raises(RedTeamError):
        attacker_from_args(parser.parse_args(["--redteam-decoys", "0"]))


def test_cli_redteam_writes_the_scorecard_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import pii_guard.eval.redteam as redteam

    mock = Attacker(api_key="k", transport=httpx.MockTransport(_oracle({"EMAIL": EMAIL_A})))
    monkeypatch.setattr(redteam, "attacker_from_args", lambda args: mock)
    out = tmp_path / "card.json"
    code = eval_main(["--fixtures", str(_fixture(tmp_path)), "--redteam", "--json", str(out)])
    assert code == 0
    stdout = capsys.readouterr().out
    assert "## Re-identification red team" in stdout and "`decoys`" in stdout
    card = json.loads(out.read_text())
    block = card["redteam"]
    assert block["attacker"]["model"] == "meta-models/muse-spark-open-1026"
    assert block["results"]["masked-only"]["all"]["recovered"] == 1
    assert block["usage"]["requests"] == 4
    assert block["detector_usage"] == {}  # the rules keep no token counters
    assert EMAIL_A not in out.read_text()


# --- Live --------------------------------------------------------------------------------

LIVE_KEY = os.environ.get("BASETEN_API_KEY") or os.environ.get("PII_GUARD_REDTEAM_API_KEY")


@pytest.mark.live
@pytest.mark.skipif(not LIVE_KEY, reason="BASETEN_API_KEY not set")
def test_live_muse_spark_open_answers_in_the_expected_shape() -> None:
    """One fictional document: the attacker must answer parseable JSON for the placeholders.
    Whether it recovers the value is the measurement, not the test."""
    results = _results()[:1]
    attacker = Attacker()
    outcomes = run_redteam(results, attacker, contexts=["masked-only"])
    total = redteam_breakdown(outcomes)["masked-only"]["all"]
    assert total["failed"] == 0 and total["masked"] == 1
    assert attacker.usage["requests"] == 1 and attacker.usage["completion_tokens"] > 0
