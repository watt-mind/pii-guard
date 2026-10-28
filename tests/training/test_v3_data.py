"""NER v3 mix (LAB-1393): converters, ignore regions, teacher audit, configs. Fictional only."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from pii_guard.eval.fixtures import Document, GoldSpan
from pii_guard.types import EntityType

from .conftest import ROOT, load_script


@pytest.fixture(scope="module")
def v3():
    return load_script("training/ner/v3_data.py", "ner_v3_data")


@pytest.fixture(scope="module")
def teachers():
    return load_script("training/ner/v3_teachers.py", "ner_v3_teachers")


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("Please send the invoice to the customer and update the record for this account.", "en"),
        ("Bitte senden Sie die Rechnung an den Kunden und die Adresse für das Konto.", "de"),
        ("Proszę wysłać fakturę do klienta, który nie jest w bazie, oraz zgłoszenie.", "pl"),
        ("Prosím pošlete fakturu zákazníkovi, který je v systému, nebo ji uložte.", "cs"),
        ("Vă rugăm să trimiteți factura la client și să actualizați datele din cont.", "ro"),
        ("Envíe la factura al señor, por favor, y actualice la dirección del cliente.", None),
        ("Отправьте счёт клиенту и обновите данные.", None),
    ],
)
def test_guess_language(v3, text, lang) -> None:
    assert v3.guess_language(text) == lang


def test_privy_text_and_spans_found_by_value(v3, tmp_path: Path) -> None:
    text = '{"name": "Teszt Elek", "email": "teszt.elek@example.com", "id": "x"}'
    rows = [
        {
            "full_text": "b'" + text + "'",
            "spans": [
                {"entity_type": "PERSON", "entity_value": "Teszt Elek", "start_position": 0,
                 "end_position": 3},
                {"entity_type": "O", "entity_value": "teszt.elek@example.com",
                 "start_position": 0, "end_position": 1},
                {"entity_type": "O", "entity_value": "", "start_position": 5, "end_position": 5},
            ],
        }
    ]  # fmt: skip
    path = tmp_path / "privy.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    (row,) = list(v3.privy_rows(path))
    assert row.text == text
    out = v3.convert(row, v3.PRIVY_LABELS, prefix="privy", kind="t", source="privy").document
    assert [(text[s.start : s.end], s.entity_type) for s in out.spans] == [
        ("Teszt Elek", EntityType.PERSON)
    ]
    # Privy's "O" values (here an e-mail) are unknown, so ignored rather than taught as O.
    assert [text[r["start"] : r["end"]] for r in out.meta["ignore"]] == ["teszt.elek@example.com"]


def test_wismut_names_merge_and_city_alone_is_ignored(v3, tmp_path: Path) -> None:
    text = "Please call the patient Teszt Elek at the clinic in Budapest for this appointment."
    first = text.index("Teszt")
    city = text.index("Budapest")
    row = {
        "text": text,
        "entities": [
            {"start": first, "end": first + 5, "label": "GIVEN_NAME"},
            {"start": first + 6, "end": first + 10, "label": "SURNAME"},
            {"start": city, "end": city + 8, "label": "CITY"},
        ],
    }
    path = tmp_path / "w.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    docs, _ = v3._sampled(v3.wismut_rows(path), {"en": 5}, v3.WISMUT_LABELS, "wismut")
    (doc,) = docs["en"]
    assert [(text[s.start : s.end], s.entity_type) for s in doc.spans] == [
        ("Teszt Elek", EntityType.PERSON)
    ]
    assert [city, city + 8] in doc.meta["loss_ignore"]
    assert doc.meta["split"] == "train"


def test_gretel_rows_find_every_occurrence(v3, monkeypatch, tmp_path: Path) -> None:
    text = "Patient Teszt Elek, MRN MED123. Teszt Elek signed."
    monkeypatch.setattr(
        v3,
        "read_parquet",
        lambda path, cols: [
            {
                "uid": "u1",
                "text": text,
                "entities": str(
                    [
                        {"entity": "Teszt Elek", "types": ["name"]},
                        {"entity": "MED123", "types": ["medical_record_number"]},
                    ]
                ),
            }
        ],
    )
    (row,) = list(v3.gretel_rows(tmp_path / "x.parquet"))
    out = v3.convert(row, v3.GRETEL_LABELS, prefix="g", kind="t", source="g").document
    assert [text[s.start : s.end] for s in out.spans] == ["Teszt Elek", "Teszt Elek"]
    assert [r["label"] for r in out.meta["ignore"]] == ["medical_record_number"]


def test_no_special_category_or_rules_label_is_taught(v3) -> None:
    """SECRET / URL / IP and health or demographic labels map to ignore, never to a type."""
    for labels, names in (
        (v3.PRIVY_LABELS, ("URL", "IP_ADDRESS", "PASSWORD", "NRP")),
        (v3.WISMUT_LABELS, ("URL", "API_KEY", "PASSWORD", "MEDICAL_RECORD_NUMBER", "GENDER")),
        (v3.GRETEL_LABELS, ("url", "ipv4", "api_key", "medical_record_number", "cvv")),
    ):
        for name in names:
            assert name in labels.types and labels.types[name] is None


def test_training_document_moves_ignore_into_loss_ignore(v3) -> None:
    doc = Document(
        "d", "en", "Ref 2020-01-01 for Teszt Elek",
        (GoldSpan(19, 29, EntityType.PERSON, "Teszt Elek"),),
        {"ignore": [{"start": 4, "end": 14, "label": "date"}], "loss_ignore": [[0, 3]]},
    )  # fmt: skip
    out = v3.training_document(doc, "v3-x")
    assert out.meta["loss_ignore"] == [[0, 3], [4, 14]]
    assert out.meta["kind"] == "v3-x"


def test_agent_traffic_train_has_its_own_seed_and_ids(v3) -> None:
    docs = v3.agent_traffic_train({"en": 2})["en"]
    assert [d.id for d in docs] == ["en-agent-traffic-train-00000", "en-agent-traffic-train-00001"]
    from pii_guard.eval.datasets import synthetic

    with pytest.raises(ValueError):
        v3.agent_traffic_train({"en": 1}, seed=synthetic.DEV_SEED)


def test_sources_are_pinned_and_licensed(v3) -> None:
    allowed = {"MIT", "Apache-2.0", "CC-BY-4.0"}
    for src in v3.DOWNLOADS:
        assert len(src.revision) == 40 and len(src.sha256) == 64
        assert src.license in allowed, src.name
        assert src.revision in src.url


def test_teacher_regions_and_audit(teachers) -> None:
    assert teachers.label_type("B-PERSON_NAME") == "PERSON_NAME"
    assert teachers.label_type("S-private_email") == "private_email"
    assert teachers.label_type("O") == "O"
    offsets = [(0, 3), (4, 9), (10, 14), (15, 17), (18, 22)]
    types = ["O", "PERSON_NAME", "PERSON_NAME", "DATE_TIME", "EMAIL_ADDRESS"]
    regions = teachers.regions_from_tokens(offsets, types, frozenset({"O", "DATE_TIME"}))
    assert regions == [(4, 14, "PERSON_NAME"), (18, 22, "EMAIL_ADDRESS")]
    doc = Document(
        "d", "en", "Hi Teszt Elek on mail", (GoldSpan(3, 8, EntityType.PERSON, "Teszt"),), {}
    )
    extra = teachers.outside_gold(doc, [(4, 14, "PERSON_NAME"), (17, 21, "EMAIL_ADDRESS")])
    assert extra == [(17, 21, "EMAIL_ADDRESS")]  # overlaps gold: gold wins
    out = teachers.apply(doc, extra)
    assert out.meta["loss_ignore"] == [[17, 21]] and out.meta["teacher_ignored"] == 1
    assert out.spans == doc.spans


def test_teachers_are_apache_and_pinned(teachers) -> None:
    repos = {t.repo for t in teachers.TEACHERS}
    assert "tabularisai/eu-pii-safeguard" not in repos
    assert "flowxai/piiguard" not in repos
    assert "bardsai/eu-pii-anonimization-multilang-v3" not in repos  # LAB-1404
    for t in teachers.TEACHERS:
        assert t.license in {"Apache-2.0", "MIT"} and len(t.revision) == 40


def test_v3_configs_share_data_and_differ_in_base() -> None:
    xlmr = tomllib.loads((ROOT / "training/ner/v3-xlmr-base.toml").read_text())
    mmbert = tomllib.loads((ROOT / "training/ner/v3-mmbert-base.toml").read_text())
    assert xlmr["train"] == mmbert["train"] and xlmr["dev"] == mmbert["dev"]
    assert xlmr["base_model"] != mmbert["base_model"]
    for cfg in (xlmr, mmbert):
        assert len(cfg["base_revision"]) == 40
        assert cfg.get("decontam", True) is True
        assert not any("negatives-v21" in p for p in cfg["train"])
