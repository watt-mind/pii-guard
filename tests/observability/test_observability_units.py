"""Units of the observability package: timer, scrubbing, traffic ring buffer, metrics, bind check.

All values are fictional (ADR 0005).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from pii_guard.observability import (
    REDACTED,
    LatencyMetrics,
    Observability,
    ObservabilitySettings,
    RequestTimer,
    TrafficLevel,
    TrafficLog,
    TrafficLogConfigError,
    check_bind,
    is_loopback,
    scrub,
)
from pii_guard.observability.timing import STAGES

# --- timer ---------------------------------------------------------------------------------


def test_overhead_is_total_minus_upstream() -> None:
    timer = RequestTimer(started=100.0)
    timer.add("parse", 0.001)
    timer.add("upstream", 0.200)
    timer.ended = 100.250
    out = timer.breakdown()
    assert out["total_ms"] == pytest.approx(250.0)
    assert out["upstream_ms"] == pytest.approx(200.0)
    assert out["overhead_ms"] == pytest.approx(50.0)
    assert set(out["stages_ms"]) == set(STAGES)
    assert out["added_ttft_ms"] is None


def test_overhead_excludes_time_spent_handing_events_to_the_client() -> None:
    timer = RequestTimer(started=0.0)
    timer.add("detect", 0.004)
    timer.add("unmask", 0.002)
    timer.add("upstream", 0.100)
    timer.add("client", 1.000)  # a slow reader: 20 events x 50 ms (LAB-1212)
    timer.ended = 1.110
    out = timer.breakdown()
    assert out["stages_ms"]["client"] == pytest.approx(1000.0)
    assert out["overhead_ms"] == pytest.approx(10.0)


def test_added_ttft_subtracts_the_upstreams_own_first_byte_time() -> None:
    timer = RequestTimer(started=10.0)
    timer.upstream_sent = 10.004
    timer.upstream_first_data = 10.104  # upstream took 100 ms to its first data
    timer.first_event = 10.110  # client got its first event 110 ms after start
    ttft, upstream, added = timer.ttft()
    assert ttft == pytest.approx(110.0)
    assert upstream == pytest.approx(100.0)
    assert added == pytest.approx(10.0)


def test_server_timing_header_lists_stages_and_overhead() -> None:
    timer = RequestTimer(started=0.0)
    timer.add("detect", 0.002)
    timer.add("upstream", 0.010)
    timer.ended = 0.015
    header = timer.server_timing()
    assert "detect;dur=2.000" in header
    assert "upstream;dur=10.000" in header
    assert "overhead;dur=5.000" in header
    assert "total;dur=15.000" in header
    assert "parse" not in header  # stages that did not run are left out


# --- scrubbing -----------------------------------------------------------------------------


def test_scrub_removes_credentials_known_secrets_and_images() -> None:
    value = {
        "model": "m",
        "Authorization": "Bearer sk-live-should-not-appear",
        "headers": {"x-api-key": "k-123456789", "Cookie": "a=b"},
        "api_key": "sk-other",
        "max_tokens": 10,
        "messages": [
            {"role": "user", "content": "token Bearer abcdefghijklmnop in text"},
            {"role": "user", "content": "the upstream key sk-test-upstream-key-0000 leaked"},
            {"role": "user", "content": "data:image/png;base64," + "A" * 500},
        ],
    }
    out = scrub(value, ["sk-test-upstream-key-0000"])
    dumped = json.dumps(out)
    for secret in ("sk-live", "k-123456789", "a=b", "sk-other", "abcdefghijklmnop", "sk-test-up"):
        assert secret not in dumped
    assert out["Authorization"] == REDACTED
    assert out["headers"]["x-api-key"] == REDACTED
    assert out["max_tokens"] == 10  # "token" in a field name is not a credential
    assert out["messages"][2]["content"].startswith("[inline image/png")
    assert value["api_key"] == "sk-other"  # a copy: the input is untouched


def test_scrub_redacts_credential_synonyms_and_short_secrets() -> None:
    # LAB-1565: keys are matched by meaning (case/separator/camelCase-insensitive),
    # and short known secrets / bearer values are still cut out.
    value = {
        "token": "value-1",
        "auth_token": "value-2",
        "accessToken": "value-3",
        "private_key": "value-4",
        "passwd": "value-5",
        "clientSecret": "value-6",
        "X-Session-Key": "value-7",
        "refreshToken": "value-8",
        "long_form_credential_field": "value-9",
        "prompt_cache_key": "conv-1",
        "max_tokens": 10,
        "author": "Teszt Elek",
        "messages": [{"content": "Bearer x9 and k9z here"}],
    }
    out = scrub(value, ["k9z"])
    dumped = json.dumps(out)
    for marker in (f"value-{i}" for i in range(1, 10)):
        assert marker not in dumped
    assert "x9" not in out["messages"][0]["content"].replace("Bearer [redacted]", "")
    assert "k9z" not in dumped  # a 3-char known secret is still scrubbed
    assert out["prompt_cache_key"] == "conv-1"  # not a credential
    assert out["max_tokens"] == 10 and out["author"] == "Teszt Elek"


@pytest.mark.parametrize("prose", ["a basic idea", "bearer bonds are paper", "Basic setup"])
def test_scrub_keeps_prose_after_bearer_and_basic(prose: str) -> None:
    # LAB-1581: a short plain word after "basic"/"bearer" is English, not a credential.
    assert scrub({"content": prose})["content"] == prose


@pytest.mark.parametrize(
    "token",
    ["abcdefghijklmnop", "part.part.sig0000", "dGVzdDp0ZXN0", "x9", "abc-de"],
)
def test_scrub_still_redacts_token_shaped_values(token: str) -> None:
    for scheme in ("Bearer", "basic"):
        out = scrub({"content": f"auth {scheme} {token} end"})["content"]
        assert out == f"auth {scheme} {REDACTED} end"


def test_scrub_truncates_long_strings() -> None:
    out = scrub({"text": "x" * 50}, max_string=10)
    assert out["text"].startswith("x" * 10) and "truncated, 50 chars" in out["text"]


# --- traffic log ---------------------------------------------------------------------------


def test_session_ref_is_stable_per_process_and_not_the_session_id() -> None:
    log = TrafficLog(TrafficLevel.MASKED)
    sid = "Abc_123-session"
    ref = log.session_ref(sid)
    assert ref == log.session_ref(sid)
    assert ref.startswith("s_") and sid not in ref and len(ref) == 18
    assert log.session_ref("other") != ref
    assert TrafficLog(TrafficLevel.MASKED).session_ref(sid) != ref  # new key per instance


def test_ring_buffer_keeps_the_last_events_in_order() -> None:
    log = TrafficLog(TrafficLevel.MASKED, size=3)
    for i in range(5):
        log.publish({"n": i})
    events = log.recent()
    assert [e["n"] for e in events] == [2, 3, 4]
    assert [e["seq"] for e in events] == [3, 4, 5]
    assert [e["n"] for e in log.recent(2)] == [3, 4]
    assert [e["n"] for e in log.recent(after=4)] == [4]


def test_publish_is_a_no_op_when_off() -> None:
    log = TrafficLog(TrafficLevel.OFF)
    assert log.publish({"n": 1}) is None
    assert log.recent() == []


def test_subscribers_receive_new_events() -> None:
    log = TrafficLog(TrafficLevel.MASKED)

    async def scenario() -> dict:
        async with log.subscribe() as queue:
            assert log.subscribers == 1
            log.publish({"n": 7})
            event = await asyncio.wait_for(queue.get(), timeout=2)
        assert log.subscribers == 0
        return event

    assert asyncio.run(scenario())["n"] == 7


# --- metrics -------------------------------------------------------------------------------


def test_metrics_render_prometheus_histograms() -> None:
    metrics = LatencyMetrics()
    timing = {
        "overhead_ms": 3.0,
        "total_ms": 53.0,
        "upstream_ms": 50.0,
        "added_ttft_ms": None,
        "stages_ms": {"detect": 1.2, "parse": 0.0},
    }
    metrics.observe("fast", "ok", timing)
    metrics.observe("fast", "ok", timing)
    text = metrics.render()
    assert 'pii_guard_gateway_requests_total{mode="fast",outcome="ok"} 2' in text
    assert 'pii_guard_gateway_overhead_ms_bucket{mode="fast",le="5"} 2' in text
    assert 'pii_guard_gateway_overhead_ms_bucket{mode="fast",le="2.5"} 0' in text
    assert 'pii_guard_gateway_stage_ms_count{mode="fast",stage="detect"} 2' in text
    assert 'stage="parse"' not in text  # zero-time stages are not observed
    assert "added_ttft" not in text


def test_metrics_observe_full_gateway_events_and_rest_helpers() -> None:
    metrics = LatencyMetrics()
    timing = {
        "overhead_ms": 4.0,
        "total_ms": 54.0,
        "upstream_ms": 50.0,
        "added_ttft_ms": 2.0,
        "stages_ms": {"detect": 1.5},
        "detectors_ms": {"rules": 0.4, "ner": 1.1, "llm": 0.0},
    }
    ok_event = {
        "mode": "fast",
        "outcome": "ok",
        "timing": timing,
        "entities": {
            "detected": {"EMAIL": 2, "PERSON": 1},
            "masked": {"EMAIL": 2},
            "images": {"count": 1, "masked": {"FACE": 1}, "kept": {"STAMP": 2}, "ocr": True},
        },
        "outbound_check": {"result": "passed", "hits": {}},
        "cache": {"hits": 3, "misses": 1, "seeded": 2},
        "upstream": {"status": 200, "unresolved_placeholders": 1},
        "usage": {"prompt_tokens": 120, "completion_tokens": 45},
    }
    metrics.observe("fast", "ok", timing, ok_event)

    # Outbound block event (Responses-style input_tokens/output_tokens too)
    outbound_block_event = {
        "mode": "fast",
        "outcome": "blocked",
        "timing": timing,
        "error": {"code": "outbound_check_failed", "entity_types": {"EMAIL": 1}},
        "outbound_check": {"result": "blocked", "hits": {"EMAIL": 1}},
        "usage": {"input_tokens": 30, "output_tokens": 10},
    }
    metrics.observe("fast", "blocked", timing, outbound_block_event)

    # Inbound policy block event (no outbound check ran)
    inbound_block_event = {
        "mode": "fast",
        "outcome": "blocked",
        "timing": timing,
        "error": {"code": "blocked_entity", "entity_types": {"SECRET": 2}},
        "outbound_check": None,
    }
    metrics.observe("fast", "blocked", timing, inbound_block_event)

    # Direct REST helpers and live gauges
    metrics.observe_entities(detected={"PHONE": 1}, masked={"PHONE": 1})
    metrics.observe_image_regions(masked={"SIGNATURE": 1}, kept={"STAMP": 1})
    metrics.observe_blocked("inbound", {"IBAN": 1})
    metrics.observe_unresolved(2)
    metrics.observe_http("POST", "/v1/mask", 200, 3.2)

    text = metrics.render(
        active_sessions=4,
        ner_state="ready",
        hosted_stats={
            "owner_runtimes": 2,
            "guest_runtimes": 1,
            "active_streams": 3,
            "sponsored_available": 1,
        },
    )
    assert 'pii_guard_detector_duration_ms_count{mode="fast",detector="ner"} 3' in text
    assert 'pii_guard_detector_duration_ms_count{mode="fast",detector="rules"} 3' in text
    assert 'detector="llm"' not in text
    assert 'pii_guard_entities_detected_total{entity_type="EMAIL"} 2' in text
    assert 'pii_guard_entities_detected_total{entity_type="PERSON"} 1' in text
    assert 'pii_guard_entities_detected_total{entity_type="PHONE"} 1' in text
    assert 'pii_guard_entities_masked_total{entity_type="EMAIL"} 2' in text
    assert 'pii_guard_entities_masked_total{entity_type="PHONE"} 1' in text
    assert 'pii_guard_image_regions_total{entity_type="FACE",action="masked"} 1' in text
    assert 'pii_guard_image_regions_total{entity_type="SIGNATURE",action="masked"} 1' in text
    assert 'pii_guard_image_regions_total{entity_type="STAMP",action="kept"} 3' in text
    assert 'pii_guard_outbound_checks_total{result="passed"} 1' in text
    assert 'pii_guard_outbound_checks_total{result="blocked"} 1' in text
    assert 'pii_guard_blocked_entities_total{stage="outbound",entity_type="EMAIL"} 1' in text
    assert 'pii_guard_blocked_entities_total{stage="inbound",entity_type="SECRET"} 2' in text
    assert 'pii_guard_blocked_entities_total{stage="inbound",entity_type="IBAN"} 1' in text
    assert 'pii_guard_detection_cache_total{result="hit"} 3' in text
    assert 'pii_guard_detection_cache_total{result="miss"} 1' in text
    assert 'pii_guard_detection_cache_total{result="seeded"} 2' in text
    assert 'pii_guard_upstream_tokens_total{direction="input"} 150' in text
    assert 'pii_guard_upstream_tokens_total{direction="output"} 55' in text
    assert "pii_guard_unresolved_placeholders_total 3" in text
    assert 'pii_guard_http_requests_total{method="POST",path="/v1/mask",status="200"} 1' in text
    assert 'pii_guard_http_request_duration_ms_count{method="POST",path="/v1/mask"} 1' in text
    assert "pii_guard_vault_active_sessions 4" in text
    assert 'pii_guard_ner_state{state="ready"} 1' in text
    assert 'pii_guard_ner_state{state="loading"} 0' in text
    assert 'pii_guard_hosted_active_runtimes{kind="owner"} 2' in text
    assert 'pii_guard_hosted_active_runtimes{kind="guest"} 1' in text
    assert "pii_guard_hosted_active_streams 3" in text
    assert "pii_guard_hosted_sponsored_available 1" in text


# --- bind check ----------------------------------------------------------------------------


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "::1", "[::1]", "localhost"])
def test_loopback_hosts(host: str) -> None:
    assert is_loopback(host)
    check_bind(TrafficLevel.FULL, host)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "example.test"])  # noqa: S104
def test_full_is_refused_off_loopback(host: str) -> None:
    assert not is_loopback(host)
    with pytest.raises(TrafficLogConfigError, match="loopback"):
        check_bind(TrafficLevel.FULL, host)
    check_bind(TrafficLevel.MASKED, host)  # masked is fine anywhere


def test_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_GUARD_TRAFFIC_LOG", "masked")
    monkeypatch.setenv("PII_GUARD_TRAFFIC_LOG_SIZE", "5")
    monkeypatch.setenv("PII_GUARD_SERVER_TIMING", "true")
    monkeypatch.setenv("PII_GUARD_METRICS_TOKEN", "synthetic-scrape-token")
    settings = ObservabilitySettings()
    obs = Observability(settings)
    assert obs.traffic.level is TrafficLevel.MASKED and obs.traffic.size == 5
    assert obs.server_timing and obs.metrics is None and obs.recording
    assert settings.metrics_token is not None
    assert settings.metrics_token.get_secret_value() == "synthetic-scrape-token"
    assert "masked" in repr(obs)
