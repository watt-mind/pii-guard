"""LAB-1495: a run record says whose model a system is, not only who ran it.

Every system pii-guard runs has ``family: "pii-guard"``, including someone else's model run
through the pipeline (bardsai, tabularisai, Horizon-Labs, Wismut, Davlan, GLiNER zero-shot).
``system.role`` (``own`` | ``other-model`` | ``tool``) tells them apart; the index carries it
and ``eval rescore`` backfills it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from pii_guard.eval import rescore
from pii_guard.eval.record import (
    SCHEMA_PATH,
    load_schema,
    merge_extra,
    system_role,
    validate,
)
from pii_guard.eval.report_index import build_index

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "eval" / "results" / "runs"
SCHEMA = load_schema(ROOT / SCHEMA_PATH)


def _system(*detectors: tuple[str, str | None], family: str = "pii-guard") -> dict[str, Any]:
    return {
        "family": family,
        "tool": "pii-guard" if family == "pii-guard" else "presidio",
        "detectors": [{"name": n, "model": m} for n, m in detectors],
    }


@pytest.mark.parametrize(
    ("detectors", "role"),
    [
        ([("rules", None)], "own"),
        ([("rules", None), ("ner", "xlmr-base-v2-hn")], "own"),
        ([("rules", None), ("ner", "watt-mind/pii-guard-ner-xlmr-base")], "own"),
        ([("rules", None), ("llm", "muse-spark-open")], "own"),
        ([("rules", None), ("ner_gliner", "gliner-multi-v2-ft")], "own"),
        ([("rules", None), ("ner", None)], "own"),
        # someone else's NER, alone or in place of pii-guard's
        ([("ner", "bardsai-v3")], "other-model"),
        ([("rules", None), ("ner", "eu-pii-safeguard")], "other-model"),
        ([("rules", None), ("ner", "horizon-small")], "other-model"),
        ([("rules", None), ("ner", "wismut-nym")], "other-model"),
        ([("rules", None), ("ner", "xlm-roberta-base-ner-hrl")], "other-model"),
        ([("rules", None), ("ner", "bardsai/eu-pii-anonimization-multilang")], "other-model"),
        ([("rules", None), ("ner_gliner", "gliner-multi-v2.1")], "other-model"),
        # pii-guard's own NER in union with a zero-shot model is still pii-guard's
        ([("rules", None), ("ner", "xlmr-base-v2-hn"), ("ner_gliner", "gliner-multi-v2.1")], "own"),
    ],
)
def test_role_of_a_pii_guard_system(detectors: list[tuple[str, str | None]], role: str) -> None:
    assert system_role(_system(*detectors)) == role


def test_a_comparison_tool_is_a_tool() -> None:
    assert system_role(_system(("presidio", None), family="comparison")) == "tool"


def test_merge_extra_recomputes_the_role_unless_extra_sets_it() -> None:
    rec: dict[str, Any] = {"system": _system(("rules", None), ("ner", None)), "notes": []}
    rec["system"]["role"] = system_role(rec["system"])
    merge_extra(rec, {"system": {"detectors": {"ner": {"model": "wismut-nym"}}}})
    assert rec["system"]["role"] == "other-model"
    merge_extra(rec, {"system": {"role": "own"}})
    assert rec["system"]["role"] == "own"


def test_committed_roles_match_their_detectors() -> None:
    for path in RUNS.glob("*.json"):
        rec = json.loads(path.read_text(encoding="utf-8"))
        if "role" in rec["system"]:  # a record from before LAB-1495 is backfilled by rescore
            assert rec["system"]["role"] == system_role(rec["system"]), path.name


def test_rescore_writes_the_role_but_check_does_not_fail_without_it(tmp_path: Path) -> None:
    rec = json.loads(
        (RUNS / "2026-10-27-comparison-en-ai4privacy-presidio.json").read_text("utf-8")
    )
    del rec["system"]["role"]
    path = tmp_path / f"{rec['run_id']}.json"
    path.write_text(json.dumps(rec), encoding="utf-8")
    assert rescore.main(["--runs-dir", str(tmp_path), "--check"]) == 0
    assert rescore.main(["--runs-dir", str(tmp_path)]) == 0
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["system"]["role"] == "tool"
    assert rescore.rescore_record(written) is None


def test_backfill_adds_role_after_family_without_marking_a_rescore() -> None:
    rec = json.loads(
        (RUNS / "2026-10-27-cued-numbers-after-ai4privacy-fast.json").read_text("utf-8")
    )
    old = copy.deepcopy(rec)
    del old["system"]["role"]
    new = rescore.rescore_record(old)
    assert new is not None
    assert new == rec
    keys = list(new["system"])
    assert keys[keys.index("family") + 1] == "role"
    assert not validate(new, SCHEMA)


def test_schema_rejects_an_unknown_role() -> None:
    rec = json.loads(
        (RUNS / "2026-10-27-cued-numbers-after-ai4privacy-fast.json").read_text("utf-8")
    )
    rec["system"]["role"] = "theirs"
    assert validate(rec, SCHEMA)


def test_index_carries_the_role() -> None:
    records = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RUNS.glob("*.json"))]
    index = build_index(records)
    roles = {k: s["role"] for k, s in index["systems"].items()}
    assert roles["rules"] == "own"
    assert roles["rules+ner:wismut-nym@decoder=word"] == "other-model"
    assert roles["ner:bardsai-v3@decoder=word"] == "other-model"
    assert roles["presidio"] == "tool"
    assert set(roles.values()) == {"own", "other-model", "tool"}
