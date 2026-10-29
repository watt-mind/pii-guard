"""NER v3.3 targeted add-on (LAB-1512): case forms, spans, determinism, eval disjointness.

Every name here is fictional (drawn from the generator's own lists).
"""

from __future__ import annotations

import random
import tomllib
from pathlib import Path

import pytest

from .conftest import load_script

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def t():
    return load_script("training/ner/targeted_v33.py", "ner_targeted_v33")


# Hand-checked Hungarian forms: acc, dat, ins, abl, del, all, ade, poss.
HU_FORMS = {
    "Kovács Béla": ("Bélát", "Bélának", "Bélával", "Bélától", "Béláról", "Bélához", "Bélánál",
                    "Béláé"),
    "Szabó Péter": ("Pétert", "Péternek", "Péterrel", "Pétertől", "Péterről", "Péterhez",
                    "Péternél", "Péteré"),
    "Nagy Ádám": ("Ádámot", "Ádámnak", "Ádámmal", "Ádámtól", "Ádámról", "Ádámhoz", "Ádámnál",
                  "Ádámé"),
    "Tóth Szabolcs": ("Szabolcsot", "Szabolcsnak", "Szabolccsal", "Szabolcstól", "Szabolcsról",
                      "Szabolcshoz", "Szabolcsnál", "Szabolcsé"),
    "Lakatos Ödön": ("Ödönt", "Ödönnek", "Ödönnel", "Ödöntől", "Ödönről", "Ödönhöz", "Ödönnél",
                     "Ödöné"),
    "Gál Gergely": ("Gergelyt", "Gergelynek", "Gergellyel", "Gergelytől", "Gergelyről",
                    "Gergelyhez", "Gergelynél", "Gergelyé"),
    "Papp Judit": ("Juditot", "Juditnak", "Judittal", "Judittól", "Juditról", "Judithoz",
                   "Juditnál", "Judité"),
    "Fekete Bence": ("Bencét", "Bencének", "Bencével", "Bencétől", "Bencéről", "Bencéhez",
                     "Bencénél", "Bencéé"),
}  # fmt: skip
CASES = ("acc", "dat", "ins", "abl", "del", "all", "ade", "poss")


@pytest.mark.parametrize("name", sorted(HU_FORMS))
def test_hungarian_case_forms(t, name):
    surname = name.split()[0]
    assert [t.hu_inflect(name, c) for c in CASES] == [f"{surname} {f}" for f in HU_FORMS[name]]


def test_hungarian_compound_and_married_forms_inflect_the_last_word(t):
    assert t.hu_inflect("Nagy-Kovács Anna Mária", "acc") == "Nagy-Kovács Anna Máriát"
    assert t.hu_inflect("Kiss Béláné", "dat") == "Kiss Bélánénak"
    assert t.hu_inflect("Rácz Péterné", "ins") == "Rácz Péternével"


def test_polish_declension(t):
    assert t.pl_surname("Kowal", "ski", False, "gen") == "Kowalskiego"
    assert t.pl_surname("Kowal", "ski", True, "acc") == "Kowalską"
    assert t.pl_surname("Zawa", "dzki", True, "dat") == "Zawadzkiej"
    assert t.de_genitive("Hans Fuchs") == "Hans Fuchs'"
    assert t.de_genitive("Lena Weber") == "Lena Webers"


PARTS = [
    ("names", "hu"), ("names", "pl"), ("names", "de"), ("payload", "hu"), ("payload", "en"),
    ("agent", "de"), ("agent", "hu"),
]  # fmt: skip


@pytest.mark.parametrize(("part", "lang"), PARTS)
def test_documents_are_valid_and_deterministic(t, part, lang):
    a = t.generate(part, lang, 30, 7, "", "train")
    b = t.generate(part, lang, 30, 7, "", "train")
    assert [d.text for d in a] == [d.text for d in b]
    for doc in a:
        for span in doc.spans:
            assert doc.text[span.start : span.end] == span.text
    if part == "names":
        assert all(d.spans for d in a)
    else:  # hard negatives: most documents carry no gold at all
        assert sum(1 for d in a if not d.spans) >= len(a) // 2


def test_payload_numbers_are_never_gold(t):
    docs = t.generate("payload", "en", 200, 3, "", "train")
    for doc in docs:
        assert all(not s.text.strip().isdigit() for s in doc.spans)
        assert {s.entity_type.value for s in doc.spans} <= {"PERSON", "EMAIL"}


def test_a_name_in_an_eval_text_is_redrawn(t):
    rng = random.Random("7-names-hu")  # noqa: S311 - seeded test data
    first = t.BUILDERS["names"]("hu", rng)
    blob = "\n".join(first.names)
    docs = t.generate("names", "hu", 5, 7, blob, "train")
    assert not any(nm in blob for d in docs for nm in d.meta["names"])


def test_train_and_dev_differ(t):
    train = t.generate("names", "hu", 20, t.SEED, "", "train")
    dev = t.generate("names", "hu", 20, t.DEV_SEED, "", "dev")
    assert not {d.text for d in train} & {d.text for d in dev}


def test_configs_hold_no_eval_or_generator_file(t):
    for name in ("v33-t1", "v33-t2"):
        cfg = tomllib.loads((ROOT / f"training/ner/{name}.toml").read_text(encoding="utf-8"))
        files = [*cfg["train"], *cfg["dev"]]
        assert all(f.startswith("eval/generated/") for f in files)
        assert not any("agent-traffic" in f or "/synthetic/" in f for f in files)
        assert cfg["base_model"].endswith("pii-guard-ner-xlmr-base-v32-s30")
    assert sum(t.REPLAY.values()) == 6800
