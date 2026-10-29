"""The mock upstream, the demo scenarios (an in-process smoke test) and the latency benchmark.

Nothing leaves the process (or loopback). All values are fictional (ADR 0005).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from pii_guard.api.app import create_app
from pii_guard.bench import cli as bench_cli
from pii_guard.bench.latency import CellResult, build_records, percentiles, run_benchmark
from pii_guard.bench.mock_upstream import create_mock_upstream, last_user_text
from pii_guard.bench.scenarios import (
    NER_LABEL,
    SCENARIOS,
    Outcome,
    check,
    expected_misses,
    gold_values,
    leaks,
    run,
    ui_export,
)
from pii_guard.config import Settings
from pii_guard.eval.record import validate
from pii_guard.observability import ObservabilitySettings

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

TENANT_KEY = "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0"
REPO = Path(__file__).resolve().parents[2]

# --- mock upstream -------------------------------------------------------------------------


def test_mock_echoes_the_last_user_message_and_records_it() -> None:
    app = create_mock_upstream()
    with TestClient(app) as client:
        body = {
            "model": "m",
            "messages": [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "ok"},
                {"role": "user", "content": [{"type": "text", "text": "[[EMAIL_1a2b3c]] hi"}]},
            ],
        }
        r = client.post("/v1/chat/completions", json=body)
        assert r.json()["choices"][0]["message"]["content"] == "Echo: [[EMAIL_1a2b3c]] hi"
        assert r.json()["usage"]["total_tokens"] > 0
        received = client.get("/_mock/received").json()
        assert received["count"] == 1 and "[[EMAIL_1a2b3c]]" in received["requests"][0]
        assert client.delete("/_mock/received").json() == {"count": 0}
        assert client.get("/healthz").json()["status"] == "ok"
        assert client.get("/v1/models").json()["data"][0]["id"] == "pii-guard-mock"
        assert client.post("/v1/chat/completions", content=b"{").status_code == 400


def test_mock_calls_the_first_tool_and_streams_in_small_chunks() -> None:
    app = create_mock_upstream(chunk_chars=3)
    tools = [{"type": "function", "function": {"name": "send_email", "parameters": {}}}]
    with TestClient(app) as client:
        body = {"model": "m", "messages": [{"role": "user", "content": "abc defg"}]}
        r = client.post("/v1/chat/completions", json={**body, "tools": tools})
        call = r.json()["choices"][0]["message"]["tool_calls"][0]
        assert call["function"] == {"name": "send_email", "arguments": '{"text": "abc defg"}'}
        r = client.post(
            "/v1/chat/completions",
            json={**body, "stream": True, "stream_options": {"include_usage": True}},
        )
        pieces = [
            json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: {")
        ]
        content = "".join(
            c["choices"][0]["delta"].get("content") or "" for c in pieces if c["choices"]
        )
        assert content == "Echo: abc defg"
        assert pieces[-1]["usage"]["total_tokens"] > 0 and r.text.endswith("data: [DONE]\n\n")
        r = client.post("/v1/chat/completions", json={**body, "stream": True, "tools": tools})
        args = "".join(
            (call.get("function") or {}).get("arguments") or ""
            for line in r.text.splitlines()
            if line.startswith("data: {")
            for call in json.loads(line[6:])["choices"][0]["delta"].get("tool_calls") or []
        )
        assert json.loads(args) == {"text": "abc defg"}


def test_last_user_text_without_user_messages() -> None:
    assert last_user_text({"messages": [{"role": "system", "content": "x"}]}) == ""


# --- scenarios: the smoke test in-process ---------------------------------------------------


def gateway_with_mock() -> tuple[TestClient, TestClient]:
    mock_app = create_mock_upstream()
    settings = Settings(
        tenant_key=TENANT_KEY,
        upstream_base_url="http://mock.test/v1",
        upstream_api_key="sk-test-upstream-key-0000",
    )
    app = create_app(settings, ObservabilitySettings(traffic_log="masked"))
    app.state.gateway_transport = httpx.ASGITransport(app=mock_app)
    return TestClient(app), TestClient(mock_app)


def test_scenarios_restore_exactly_and_leak_nothing() -> None:
    gateway, mock = gateway_with_mock()
    with gateway, mock:
        outcomes = run("http://testserver", client=gateway)
        received = mock.get("/_mock/received?limit=1000").json()["requests"]
        traffic = gateway.get("/v1/traffic").json()["events"]
    assert check(outcomes, received) == []
    names = {o.scenario.name for o in outcomes}
    assert names == {s.name for s in SCENARIOS}
    assert sum(o.turn == 2 for o in outcomes) == 1
    image = next(o for o in outcomes if o.scenario.image)
    assert image.status >= 400  # no SAM configured: fail closed, nothing forwarded
    assert len(received) == len(outcomes) - 1
    assert len(traffic) == len(outcomes)
    assert {o.request_id for o in outcomes if o.status < 400} <= {e["id"] for e in traffic}
    assert [e["outcome"] for e in traffic].count("refused") == 1
    assert "sk-test-upstream-key-0000" not in json.dumps(traffic)
    # Rules only: the labelled NER-only scenario's free-text name is the one expected miss.
    assert [(s.name, found) for s, found in expected_misses(outcomes, received)] == [
        ("hu-needs-ner", ["Gipsz Jakab"])
    ]
    assert check(outcomes, received, detectors={"ner"}) == [
        "gold value reached the upstream: Gipsz Jakab"
    ]
    # Every other name is masked (pre-loaded known values), inflected forms included.
    by_id = {e["id"]: e for e in traffic}
    for o in outcomes:
        if o.scenario.known_values and o.request_id:
            assert "known" in by_id[o.request_id]["detectors"]
    upstream = "\n".join(received)
    for name in ("Teszt Elek", "Jane Placeholder", "Erika Mustermann", "Minta Mári"):
        assert name not in upstream
    assert "]]nak a [[ORGANIZATION_" in upstream and "]]-vel" in upstream and "]]kel." in upstream
    restored = next(o for o in outcomes if o.scenario.name == "hu-known-values").content or ""
    assert "Minta Máriának a Placeholder Kft.-vel" in restored and "Teszt Elekkel" in restored


def test_names_are_known_values_and_only_the_labelled_scenario_needs_the_ner() -> None:
    labelled = [s for s in SCENARIOS if s.requires]
    assert [(s.name, s.requires, s.label) for s in labelled] == [
        ("hu-needs-ner", ("ner",), NER_LABEL)
    ]
    assert not labelled[0].known_values
    assert "Gipsz Jakab" not in gold_values() and "Gipsz Jakab" in gold_values(detectors={"ner"})
    known = {v for s in SCENARIOS for v, _ in s.known_values}
    assert {"Teszt Elek", "Jane Placeholder", "Erika Mustermann", "Minta Mária"} <= known


def test_checksum_valid_identifiers() -> None:
    from pii_guard.detect.checksums import is_valid_hu_tax_id, is_valid_iban, is_valid_taj
    from pii_guard.detect.rules.common import is_valid_card_number

    gold = gold_values()
    assert is_valid_hu_tax_id("8456789011") and "8456789011" in gold
    assert is_valid_taj("123456788") and "123 456 788" in gold
    assert is_valid_card_number("4111111111111111") and "4111 1111 1111 1111" in gold
    ibans = [g for g in gold if g[:2] in {"HU", "GB", "DE"} and g[2:4].isdigit()]
    assert len(ibans) == 3 and all(is_valid_iban(i.replace(" ", "")) for i in ibans)


def test_ui_mirror_is_in_sync() -> None:
    """ui/src/content/demoScenarios.json is what "Send demo traffic" sends in the browser."""
    path = REPO / "ui/src/content/demoScenarios.json"
    assert json.loads(path.read_text(encoding="utf-8")) == ui_export(), (
        "run: uv run python scripts/demo_traffic.py --export-ui"
    )


def test_check_reports_leaks_and_wrong_answers() -> None:
    scenario = SCENARIOS[0]
    good = Outcome(
        scenario, 200, content=f"Echo: {scenario.text}", expected=f"Echo: {scenario.text}"
    )
    wrong = Outcome(scenario, 200, content="Echo: something else", expected=good.expected)
    failed = Outcome(scenario, 502, error="upstream_unavailable", expected=good.expected)
    leaked = json.dumps({"messages": [{"content": "mail teszt.elek@example.com"}]})
    compact = json.dumps({"messages": [{"content": "HU42117730161111101800000000"}]})
    assert check([good], []) == []
    assert any("not restored exactly" in f for f in check([wrong], []))
    assert any("HTTP 502" in f for f in check([failed], []))
    assert check([good], [leaked]) == ["gold value reached the upstream: teszt.elek@example.com"]
    assert leaks([compact], gold_values()) == [
        "HU42 1177 3016 1111 1018 0000 0000 (without spaces)"
    ]


# --- latency benchmark ---------------------------------------------------------------------


def test_percentiles() -> None:
    assert percentiles([]) is None
    p = percentiles([float(v) for v in range(1, 101)])
    assert p == {"p50": 50.5, "p95": 95.05, "p99": 99.01, "mean": 50.5}


def test_benchmark_runs_and_writes_valid_records(tmp_path: Path) -> None:
    cells = run_benchmark(modes=["fast"], concurrency=[1, 2], requests=4, warmup=1, delay_ms=5.0)
    assert len(cells) == 4 and all(c.errors == 0 for c in cells)
    for cell in cells:
        s = cell.summary()
        assert s["requests"] == 4 and s["overhead_ms"]["p50"] >= 0
        assert s["upstream_ms"]["p50"] >= 5.0
        assert set(s["stages_ms"]) >= {"parse", "detect", "mask", "forward", "upstream"}
        assert s["detectors_ms"]["rules"]["p50"] > 0
        assert (s["added_ttft_ms"] is not None) == cell.stream
    (record,) = build_records(cells, slug="test", delay_ms=5.0, day="2026-10-27")
    assert record["run_id"] == "2026-10-27-test-fast" and record["kind"] == "latency"
    assert record["system"]["key"] == "gateway-latency:fast:rules"
    schema = json.loads((REPO / "eval/results/schema/run.schema.json").read_text("utf-8"))
    assert validate(record, schema) == []
    broken = {**record, "metrics": {"upstream_delay_ms": 5.0}}
    assert validate(broken, schema)


def test_bench_cli_records(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runs = tmp_path / "runs"
    out = tmp_path / "cells.json"
    code = bench_cli.main(
        [
            "latency",
            "--concurrency", "1", "--stream", "off", "--requests", "2", "--warmup", "0",
            "--upstream-delay-ms", "1", "--record", "cli", "--runs-dir", str(runs),
            "--json", str(out), "--note", "test run",
        ]
    )  # fmt: skip
    assert code == 0
    printed = capsys.readouterr().out
    assert "overhead p50=" in printed and "wrote" in printed
    (path,) = runs.glob("*-cli-fast.json")
    record = json.loads(path.read_text("utf-8"))
    assert "test run" in record["notes"]
    assert json.loads(out.read_text("utf-8"))[0]["requests"] == 2
    assert bench_cli.main(["latency", "--modes", "slow"]) == 2


def test_cell_summary_counts_errors() -> None:
    cell = CellResult("fast", 1, False, 2, 2, 1.0, [])
    s = cell.summary()
    assert s["errors"] == 2 and s["overhead_ms"] is None
