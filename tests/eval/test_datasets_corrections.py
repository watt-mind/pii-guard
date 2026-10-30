"""Corrected-label variants (LAB-1497): the rule, and the committed gretel-finance corrections.

The upstream set keeps its labels; ``gretel-finance-corrected`` is rebuilt from the committed
fixture files and ``corrections.json`` and must match its committed manifest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pii_guard.eval.datasets import corrections, get, test_datasets
from pii_guard.eval.fixtures import from_markup, load_fixtures
from pii_guard.types import EntityType

ROOT = Path(__file__).resolve().parents[2]
CORRECTIONS = "eval/datasets/gretel-finance/corrections.json"


def _rules(tmp_path: Path, rules: list[dict[str, object]]) -> corrections.Corrections:
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"dataset": "x", "rules": rules}), encoding="utf-8")
    return corrections.load(path)


def test_a_matched_span_becomes_an_ignore_region_and_nothing_else_changes(tmp_path: Path) -> None:
    rules = _rules(
        tmp_path,
        [{"id": "phrase", "entity_types": ["PERSON"], "rationale": "r", "values": ["Damen"]}],
    )
    doc = from_markup(
        "d1",
        "Sehr geehrte {{PERSON|Damen}} und Herren, Ihr {{PERSON|Teszt Elek}}. {{EMAIL|Damen}}",
        language="de",
    )
    new, counts = corrections.apply(doc, rules)
    assert counts == {"phrase:PERSON": 1}
    assert [s.text for s in new.spans] == ["Teszt Elek", "Damen"]
    assert new.spans[1].entity_type is EntityType.EMAIL  # another type is not matched
    assert new.text == doc.text and new.id == doc.id
    (region,) = new.meta["ignore"]
    assert region["label"] == "corrected:phrase"
    assert doc.text[region["start"] : region["end"]] == "Damen"
    # A document no rule touches is returned as it is.
    clean = from_markup("d2", "{{PERSON|Teszt Elek}}", language="en")
    assert corrections.apply(clean, rules) == (clean, {})


def test_values_must_be_normalised_and_listed_once(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="normalised"):
        _rules(
            tmp_path, [{"id": "a", "entity_types": ["PERSON"], "rationale": "", "values": ["a  b"]}]
        )
    with pytest.raises(ValueError, match="twice"):
        _rules(
            tmp_path,
            [
                {"id": "a", "entity_types": ["PERSON"], "rationale": "", "values": ["x"]},
                {"id": "b", "entity_types": ["PERSON"], "rationale": "", "values": ["x"]},
            ],
        )


def test_every_rule_has_a_rationale_and_every_value_matches_a_gold_span() -> None:
    rules = corrections.load(ROOT / CORRECTIONS)
    assert rules.dataset == "gretel-finance"
    seen = set()
    for doc in load_fixtures([ROOT / p for p in get("gretel-finance").fixture_paths()]):
        for span in doc.spans:
            if rules.match(span.entity_type.value, span.text):
                seen.add(" ".join(span.text.split()))
    for rule in rules.rules:
        assert len(rule.rationale) > 40, rule.id
        assert set(rule.values) <= seen, rule.id  # no value that corrects nothing


def test_the_corrected_set_is_a_variant_not_a_new_held_out_set() -> None:
    ds = get("gretel-finance-corrected")
    assert ds.derived_from == "gretel-finance" and ds.corrections == CORRECTIONS
    assert not ds.commit_rows and all(str(p).startswith("data/") for p in ds.fixture_paths())
    assert ds.name not in {d.name for d in test_datasets()}
    assert "gretel-finance" in {d.name for d in test_datasets()}


def test_the_committed_manifest_matches_a_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    ds = get("gretel-finance-corrected")
    assert corrections.check(ds) == []
    manifest = json.loads(ds.manifest_path.read_text(encoding="utf-8"))
    assert manifest["unused_rules"] == []
    assert sum(manifest["corrected"].values()) == sum(
        r["spans_corrected"] for r in manifest["rules"]
    )
    assert "text" not in json.dumps(manifest["languages"]).replace("sha256", "")


def test_the_cli_checks_a_corrected_set(monkeypatch: pytest.MonkeyPatch) -> None:
    from pii_guard.eval.datasets import cli

    monkeypatch.chdir(ROOT)
    assert cli.main(["check", "gretel-finance-corrected"]) == 0


def test_a_dataset_run_records_the_published_ner_by_its_hub_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pii_guard.detect import ner_resolve
    from pii_guard.eval.datasets import run

    monkeypatch.delenv(ner_resolve.MODEL_ENV_VAR, raising=False)
    monkeypatch.setattr(
        ner_resolve, "resolve", lambda **_: ner_resolve.NerChoice("published", "x", None)
    )
    det = run._ner_detector()
    release = ner_resolve.PUBLISHED_RELEASE
    assert det["model"] == f"xlmr-base-{release}"  # one system key per published release
    assert det["model_ref"].startswith(
        f"{ner_resolve.PUBLISHED_REPO} {release}, revision {ner_resolve.PUBLISHED.revision[:12]}"
    )
    assert det["revision"] == f"sha256:{ner_resolve.PUBLISHED.weights_sha256}"
