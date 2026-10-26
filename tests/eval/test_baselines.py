"""Comparison baselines: label mapping, scoring, the worker protocol, the CLI hook.

These run without the ``baselines`` extra: the tools are replaced by fakes. The real tools are
exercised in ``test_baselines_live.py``, which skips when they aren't installed. All values
are fictional (ADR 0005).
"""

from __future__ import annotations

import json
import re
import sys
import textwrap
from collections import Counter
from pathlib import Path

import pytest

from pii_guard.eval import cli as eval_cli
from pii_guard.eval import from_markup, label, load_fixtures
from pii_guard.eval.baselines import (
    BASELINES,
    LABEL_MAP,
    BaselineOutput,
    BaselineUnavailable,
    baseline_section,
    create_baseline,
    map_label,
    render_comparison,
    run_baseline,
    run_baselines,
    to_spans,
)
from pii_guard.eval.baselines import compare as compare_mod
from pii_guard.eval.baselines.worker import WORKERS_DIR, WorkerBaseline, worker_env
from pii_guard.types import DetectionError, EntityType, Span

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "eval" / "fixtures"
EN = FIXTURES / "en-smoke.jsonl"

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


class FakeBaseline:
    """Finds emails (as EMAIL_ADDRESS) and the word "Acme" (as an unmapped URL label)."""

    name = "fake"
    reversible = True
    placeholder_re = re.compile(r"<[A-Z_]+_\d+>")

    def __init__(self, *, fail: bool = False) -> None:
        self.info = {"tool": "fake", "versions": {"fake": "1.0"}, "models": ["none"]}
        self.closed = False
        self.fail = fail

    def process(self, text: str, language: str) -> BaselineOutput:
        if self.fail:
            raise DetectionError("fake baseline failed")
        raw = [(m.start(), m.end(), "EMAIL_ADDRESS", 0.9) for m in _EMAIL.finditer(text)]
        raw += [(m.start(), m.end(), "URL", 0.5) for m in re.finditer("Acme", text)]
        spans, unmapped = to_spans(text, raw, self.name)
        masked = _EMAIL.sub("<EMAIL_ADDRESS_1>", text)
        return BaselineOutput(tuple(spans), masked, masked, 1.0, 0.5, unmapped)

    def close(self) -> None:
        self.closed = True


def _doc():
    return from_markup(
        "t-1",
        f"Write to {label('EMAIL', 'kis.anna@example.com')} or call "
        f"{label('PERSON', 'Kis Anna')} at Acme.",
        language="hu",
    )


# --- Label mapping -----------------------------------------------------------------------


def test_label_map_covers_presidio_vocabulary() -> None:
    assert map_label("PERSON") is EntityType.PERSON
    assert map_label("EMAIL_ADDRESS") is EntityType.EMAIL
    assert map_label("LOCATION") is EntityType.ADDRESS
    assert map_label("DATE_TIME") is EntityType.DATE_OF_BIRTH
    assert map_label("CREDIT_CARD") is EntityType.BANK_ACCOUNT
    assert map_label("FINANCIAL") is EntityType.BANK_ACCOUNT
    assert map_label("US_SSN") is EntityType.ID_DOCUMENT
    # LLM Guard's regex variants map like the base label.
    assert map_label("EMAIL_ADDRESS_RE") is EntityType.EMAIL
    assert map_label("US_SSN_RE") is EntityType.ID_DOCUMENT
    # Unmapped: explicit None and unknown labels.
    assert map_label("URL") is None
    assert map_label("SECRET") is None
    assert map_label("SOMETHING_NEW") is None
    assert map_label("SOMETHING_RE") is None
    assert all(v is None or isinstance(v, EntityType) for v in LABEL_MAP.values())


def test_label_map_is_documented() -> None:
    doc = (REPO_ROOT / "docs" / "evaluation.md").read_text(encoding="utf-8")
    for tool_label in LABEL_MAP:
        assert f"`{tool_label}`" in doc, tool_label


def test_to_spans_maps_resolves_and_counts_unmapped() -> None:
    text = "Kis Anna, Budapest, https://example.com"
    raw = [
        (0, 8, "PERSON", 0.85),
        (0, 3, "LOCATION", 0.9),  # shorter overlap loses
        (10, 18, "LOCATION", 1.7),  # score clamped to 1
        (20, 39, "URL", 0.5),  # unmapped
        (5, 5, "PERSON", 1.0),  # empty: dropped
        (30, 99, "PERSON", 0.5),  # clipped to the text
    ]
    spans, unmapped = to_spans(text, raw, "fake")
    assert [(s.start, s.end, s.entity_type) for s in spans] == [
        (0, 8, EntityType.PERSON),
        (10, 18, EntityType.ADDRESS),
        (30, 39, EntityType.PERSON),
    ]
    assert spans[1].score == 1.0
    assert all(s.text == text[s.start : s.end] and s.detector == "fake" for s in spans)
    assert unmapped == Counter({"URL": 1})


# --- Runner and scorecard section --------------------------------------------------------


def test_run_baseline_scores_the_tools_own_masking() -> None:
    doc = _doc()
    baseline = FakeBaseline()
    results, unmapped = run_baseline([doc], baseline)
    (result,) = results
    assert [s.entity_type for s in result.predicted] == [EntityType.EMAIL]
    assert result.masked_spans == result.predicted
    assert "kis.anna@example.com" not in result.masked_text
    assert "<EMAIL_ADDRESS_1>" not in result.masked_text  # placeholder blanked like ours
    assert result.roundtrip is False  # the fake "restores" to the masked text
    assert unmapped == Counter({"URL": 1})

    section = baseline_section(baseline, results, unmapped)
    assert section["name"] == "fake"
    assert section["unmapped_labels"] == {"URL": 1}
    assert set(section["languages"]) == {"hu"}
    leak = section["overall"]["leak"]
    assert leak["values"] == 2 and leak["leaked"] == 1  # the email masked, the name not
    assert section["overall"]["detection"]["overlap"]["micro"]["precision"] == 1.0


def test_placeholder_tokens_never_count_as_partial_leaks() -> None:
    doc = from_markup("t-2", f"Mail {label('EMAIL', 'secret@example.com')}.", language="en")

    class Redacting(FakeBaseline):
        placeholder_re = re.compile(r"\[SECRET\]")

        def process(self, text: str, language: str) -> BaselineOutput:
            masked = _EMAIL.sub("[SECRET]", text)
            return BaselineOutput((), masked, None, 1.0, 0.5)

    class Unblanked(Redacting):
        placeholder_re = re.compile(r"(?!)")  # matches nothing

    def partial(baseline: FakeBaseline) -> int:
        results, unmapped = run_baseline([doc], baseline)
        return baseline_section(baseline, results, unmapped)["overall"]["leak"]["partial"]

    assert partial(Unblanked()) == 1  # "SECRET" in the placeholder looks like the value
    assert partial(Redacting()) == 0


def test_run_baselines_skips_unavailable_and_always_closes() -> None:
    made: list[FakeBaseline] = []

    def ok() -> FakeBaseline:
        made.append(FakeBaseline())
        return made[-1]

    def missing() -> FakeBaseline:
        raise BaselineUnavailable("not installed")

    sections, skipped = run_baselines(
        [_doc()], ["ok", "missing"], factories={"ok": ok, "missing": missing}
    )
    assert list(sections) == ["ok"]
    assert sections["ok"]["info"]["host"]["cpu_count"]
    assert skipped == [("missing", "not installed")]
    assert made[0].closed

    failing = FakeBaseline(fail=True)
    with pytest.raises(DetectionError):
        run_baselines([_doc()], ["bad"], factories={"bad": lambda: failing})
    assert failing.closed


def test_create_baseline_rejects_unknown_names() -> None:
    assert set(BASELINES) == {"presidio", "llm-guard", "privaite"}
    with pytest.raises(BaselineUnavailable, match="unknown baseline"):
        create_baseline("nope")


def test_presidio_reports_missing_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "presidio_analyzer", None)  # import fails
    with pytest.raises(BaselineUnavailable, match="extra"):
        create_baseline("presidio")


# --- Worker protocol ---------------------------------------------------------------------

_FAKE_WORKER = """
import re, sys, time
sys.path.insert(0, WORKERS)
from _protocol import ms_since, protocol_stdout, quiet_logging, serve

out = protocol_stdout()
quiet_logging()
print("library chatter that must not reach the protocol")
EMAIL = re.compile(r"[\\w.+-]+@[\\w-]+\\.[\\w.]+")

def handle(text, language):
    if "BOOM" in text:
        raise ValueError(text)  # the message carries the text; the reply must not
    started = time.perf_counter()
    spans = [[m.start(), m.end(), "EMAIL_ADDRESS", 1.0] for m in EMAIL.finditer(text)]
    masked = EMAIL.sub("<EMAIL_ADDRESS_1>", text)
    return spans, masked, text, ms_since(started), 0.1

raise SystemExit(serve(out, {"tool": "fake-worker"}, handle))
"""


def _fake_worker(tmp_path: Path, body: str = _FAKE_WORKER) -> list[str]:
    script = tmp_path / "fake_worker.py"
    body = textwrap.dedent(body).replace("WORKERS", repr(str(WORKERS_DIR)))
    script.write_text(body, encoding="utf-8")
    return [sys.executable, str(script)]


def test_worker_round_trip(tmp_path: Path) -> None:
    worker = WorkerBaseline(
        "fake-worker", _fake_worker(tmp_path), placeholder_re=re.compile(r"<[A-Z_]+_\d+>")
    )
    try:
        assert worker.info == {"tool": "fake-worker"}
        out = worker.process("Mail kis.anna@example.com now", "hu")
        assert [(s.start, s.end, s.entity_type) for s in out.spans] == [(5, 25, EntityType.EMAIL)]
        assert out.masked_text == "Mail <EMAIL_ADDRESS_1> now"
        assert out.restored_text == "Mail kis.anna@example.com now"
        with pytest.raises(DetectionError) as excinfo:
            worker.process("BOOM kis.anna@example.com", "hu")
        assert "ValueError" in excinfo.value.message
        assert "kis.anna" not in excinfo.value.message
        # The worker survives a failed document.
        assert worker.process("nothing here", "en").spans == ()
    finally:
        worker.close()


def test_worker_that_dies_at_startup_is_unavailable(tmp_path: Path) -> None:
    command = _fake_worker(tmp_path, "raise SystemExit(3)\n")
    with pytest.raises(BaselineUnavailable, match="code 3"):
        WorkerBaseline("dead", command, placeholder_re=re.compile("(?!)"))


def test_worker_that_cannot_start_is_unavailable(tmp_path: Path) -> None:
    with pytest.raises(BaselineUnavailable, match="could not start"):
        WorkerBaseline("ghost", [str(tmp_path / "missing")], placeholder_re=re.compile("(?!)"))


def test_worker_gone_mid_run_fails_closed(tmp_path: Path) -> None:
    body = "import sys\nsys.stdout.write('{\"ready\": true}\\n')\n"
    worker = WorkerBaseline(
        "flaky", _fake_worker(tmp_path, body), placeholder_re=re.compile("(?!)")
    )
    try:
        with pytest.raises(DetectionError):
            worker.process("hello", "en")
    finally:
        worker.close()


def test_worker_env_drops_credentials() -> None:
    env = worker_env(
        {
            "PATH": "/bin",
            "HOME": "/home/x",
            "META_API_KEY": "k",
            "HF_TOKEN": "t",
            "PII_GUARD_TENANT_KEY": "x",
            "DB_PASSWORD": "p",
            "AWS_SECRET_ACCESS_KEY": "s",
        }
    )
    assert env["PATH"] == "/bin" and env["HOME"] == "/home/x"
    assert not {"META_API_KEY", "HF_TOKEN", "PII_GUARD_TENANT_KEY", "DB_PASSWORD"} & set(env)
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert env["HF_HUB_DISABLE_TELEMETRY"] == "1"


def test_uv_command_needs_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    from pii_guard.eval.baselines import worker as worker_mod

    monkeypatch.setattr(worker_mod.shutil, "which", lambda _name: None)
    with pytest.raises(BaselineUnavailable, match="uv"):
        create_baseline("llm-guard")
    with pytest.raises(BaselineUnavailable, match="uv"):
        create_baseline("privaite")
    monkeypatch.setattr(worker_mod.shutil, "which", lambda _name: "/usr/bin/uv")
    command = worker_mod.uv_command(Path("r.txt"), Path("w.py"))
    assert command[:2] == ["/usr/bin/uv", "run"] and "--isolated" in command


# --- CLI hook and comparison -------------------------------------------------------------


def test_cli_adds_baselines_to_the_scorecard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(BASELINES, "fake", FakeBaseline)

    def missing() -> FakeBaseline:
        raise BaselineUnavailable("not installed here")

    monkeypatch.setitem(BASELINES, "missing", missing)
    out = tmp_path / "card.json"
    code = eval_cli.main(
        ["--fixtures", str(EN), "--detectors", "rules", "--baselines", "fake,missing",
         "--json", str(out)]
    )  # fmt: skip
    assert code == 0
    captured = capsys.readouterr()
    assert "skipping baseline 'missing': not installed here" in captured.err
    assert "# pii-guard vs open-source baselines" in captured.out
    assert "| pii-guard rules |" in captured.out and "| fake |" in captured.out
    card = json.loads(out.read_text(encoding="utf-8"))
    assert set(card["baselines"]) == {"fake"}
    assert card["meta"]["skipped_baselines"] == [
        {"name": "missing", "reason": "not installed here"}
    ]
    assert card["baselines"]["fake"]["languages"]["en"]["documents"] == 10
    blob = out.read_text(encoding="utf-8")
    for doc in load_fixtures(EN):
        for span in doc.spans:
            if len(span.text) >= 6:
                assert span.text not in blob


def test_cli_baseline_failure_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(BASELINES, "bad", lambda: FakeBaseline(fail=True))
    assert eval_cli.main(["--fixtures", str(EN), "--baselines", "bad"]) == 1
    assert "baseline failed: detection_failed" in capsys.readouterr().err


def test_comparison_groups_by_fixture_set_and_merges_cards(tmp_path: Path) -> None:
    card = _card_with_fake(tmp_path, ["rules"])
    other = _card_with_fake(tmp_path, ["rules", "llm"], with_baseline=False)
    presidio_like = json.loads(json.dumps(card))
    presidio_like["baselines"]["fake"]["reversible"] = False
    md = render_comparison([presidio_like, other])
    assert md.count("## Fixtures:") == 1
    subset = json.loads(json.dumps(other))
    subset["meta"]["detectors"] = ["llm"]
    subset["meta"]["fixtures"] = []  # a subset of every group's files
    assert "| pii-guard llm |" in render_comparison([subset, presidio_like])
    assert render_comparison([subset, presidio_like]).count("## Fixtures:") == 1
    # Two one-language cards for the same system both contribute their language.
    hu_only = json.loads(json.dumps(subset))
    hu_only["languages"] = {"hu": hu_only["languages"]["en"]}
    merged = render_comparison([presidio_like, hu_only, subset])
    rows = [line for line in merged.splitlines() if line.startswith("| pii-guard llm |")]
    assert len(rows) == 2  # one summary row per language
    assert "| pii-guard rules |" in md and "| pii-guard rules+llm |" in md
    assert "n/a" in md  # irreversible baseline: no round trip
    assert "### Baseline configurations" in md and "- **fake**: fake 1.0" in md

    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(presidio_like), encoding="utf-8")
    b.write_text(json.dumps(other), encoding="utf-8")
    target = tmp_path / "cmp" / "comparison.md"
    assert compare_mod.main([str(a), str(b), "--out", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == md


def _card_with_fake(tmp_path: Path, detectors: list[str], *, with_baseline: bool = True) -> dict:
    from pii_guard.eval import DetectorAnalyzer, build_scorecard, run_documents

    docs = load_fixtures(EN)
    card = build_scorecard(
        run_documents(docs, DetectorAnalyzer(["rules"])),
        detectors=detectors,
        fixture_paths=[EN],
        commit=("0" * 40, False),
    )
    if with_baseline:
        card["baselines"], _ = run_baselines(docs, ["fake"], factories={"fake": FakeBaseline})
    return card


def test_span_type_contract_for_baseline_output() -> None:
    out = FakeBaseline().process("x kis.anna@example.com", "hu")
    assert all(isinstance(s, Span) for s in out.spans)
    assert "kis.anna" not in repr(out)
