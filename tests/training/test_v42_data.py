"""LAB-1625: the NER v4.2 selection split, targeted generators and birth-date treatment."""

from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

from pii_guard.eval.fixtures import load_fixtures

from .conftest import ROOT, load_script

gen = load_script("training/ner/v42_gen.py", "ner_v42_gen")
sel = load_script("training/ner/selection_v42.py", "ner_selection_v42")
v42 = load_script("training/ner/v42_data.py", "ner_v42_data")
decontam = load_script("training/ner/decontam.py", "ner_decontam_v42")
gates = load_script("training/ner/gates_v4.py", "ner_gates_v42")


def _docs(slice_: str, lang: str, pool: str, n: int = 40):
    rng = random.Random(f"test-{slice_}-{lang}-{pool}")  # noqa: S311
    return [
        gen.BUILDERS[slice_](lang, pool, rng, frozenset()).document(f"t-{i}", lang, {})
        for i in range(n)
    ]


def test_pools_split_every_name_list() -> None:
    for names in (gen.DE_GIVEN, gen.DE_FAMILY, gen.HU_GIVEN, gen.HU_WORD_SURNAMES):
        train, held = gen._half(names, "train"), gen._half(names, "sel")
        assert not set(train) & set(held)
        assert set(train) | set(held) == set(names)


def test_spans_match_text_and_pools_share_no_frame() -> None:
    for slice_ in gen.SLICES:
        for lang in gen.SLICE_LANGS[slice_]:
            for pool in gen.POOLS:
                for doc in _docs(slice_, lang, pool):
                    for span in doc.spans:
                        assert doc.text[span.start : span.end] == span.text
    for frames in (gen.DOB_FRAMES, gen.OTHER_DATE_FRAMES, gen.NUMBER_FRAMES, gen.HU_FRAMES):
        for key in frames["sel"]:
            assert not set(frames["sel"][key]) & set(frames["train"][key])
    assert not set(gen.DE_GEN_FRAMES["sel"]) & set(gen.DE_GEN_FRAMES["train"])


def test_german_genitive_ending_stays_outside_the_person_span() -> None:
    endings = Counter()
    for doc in _docs("de-genitive", "de", "train", 80):
        for span in doc.spans:
            if span.entity_type.value == "PERSON":
                assert not span.text.endswith(("'", "s'"))
                after = doc.text[span.end : span.end + 2]
                endings[after[:1]] += 1
    assert endings["s"] and endings["'"]


def test_hungarian_intact_stem_keeps_the_suffix_outside() -> None:
    doc = gen.add_hu_case(gen.Builder(), "Fekete Elek", "dat").document("x", "hu", {})
    assert doc.text == "Fekete Eleknek"
    assert [(s.text, doc.text[s.end :]) for s in doc.spans] == [("Fekete Elek", "nek")]
    doc = gen.add_hu_case(gen.Builder(), "Nagy Géza", "dat").document("y", "hu", {})
    assert [s.text for s in doc.spans] == ["Nagy Gézának"]  # stem change: the whole word


def test_dates_slice_labels_only_birth_dates() -> None:
    docs = _docs("dates", "en", "sel", 60)
    dob = [s for d in docs for s in d.spans if s.entity_type.value == "DATE_OF_BIRTH"]
    assert 0 < len(dob) < len(docs)  # some documents hold no birth date at all
    for d in docs:  # every document has more dates than labelled birth dates
        digits = sum(ch.isdigit() for ch in d.text)
        labelled = sum(ch.isdigit() for s in d.spans for ch in s.text)
        assert digits > labelled


def test_selection_split_is_deterministic_decontaminated_and_avoids_smoke_names() -> None:
    a = sel.build(scale=0.1, blob="")
    assert [d.to_dict() for d in a] == [d.to_dict() for d in sel.build(scale=0.1, blob="")]
    assert {d.meta["slice"] for d in a} == set(sel.SLICES)
    fixtures = ROOT / "eval/fixtures"
    smoke = load_fixtures(
        [*sorted(fixtures.glob("*-smoke.jsonl")), fixtures / "hu-inflection.jsonl"]
    )
    index = decontam.EvalIndex()
    for doc in smoke:
        index.add("smoke", doc)
    assert all(index.match(d) is None for d in a)
    smoke_people = {s.text for d in smoke for s in d.spans if s.entity_type.value == "PERSON"}
    assert not {s.text for d in a for s in d.spans if s.entity_type.value == "PERSON"} & (
        smoke_people
    )


def test_dob_plausibility_and_cue() -> None:
    assert v42.is_plausible("14/02/1987") and v42.is_plausible("1987. március 3.")
    assert not v42.is_plausible("2024-05-24")  # a flight, a contract
    assert not v42.is_plausible("30 de abril")  # no year
    assert not v42.is_plausible("Ljubljani")
    assert v42.is_cued("Name: X, date of birth 2001-01-01", 26, 36)
    assert not v42.is_cued("the contract signed on 15/03/2024", 23, 33)


def _line(text: str, spans: list[tuple[str, str]]) -> str:
    out = []
    for value, kind in spans:
        start = text.index(value)
        out.append({"start": start, "end": start + len(value), "entity_type": kind, "text": value})
    return json.dumps({"id": "x", "language": "en", "text": text, "spans": out})


def test_treat_dob_modes() -> None:
    text = "Ann, born 1980-02-02, signed on 2024-05-24, last seen 1999-01-01 in Ljubljani"
    spans = [("Ann", "PERSON"), ("1980-02-02", "DATE_OF_BIRTH"), ("2024-05-24", "DATE_OF_BIRTH"),
             ("1999-01-01", "DATE_OF_BIRTH"), ("Ljubljani", "DATE_OF_BIRTH")]  # fmt: skip
    line = _line(text, spans)
    (o,), so = v42.treat_dob([line], "o")
    kept = [s["text"] for s in json.loads(o)["spans"]]
    assert kept == ["Ann", "1980-02-02", "1999-01-01"]  # implausible and digitless: O
    assert so == Counter(dob=4, cued=1, uncued_implausible=1, uncued_plausible=1, no_digit=1)
    (i,), _ = v42.treat_dob([line], "ign")
    doc = json.loads(i)
    assert [s["text"] for s in doc["spans"]] == ["Ann", "1980-02-02"]
    ignored = {text[a:b] for a, b in doc["meta"]["loss_ignore"]}
    assert ignored == {"2024-05-24", "1999-01-01", "Ljubljani"}


def test_gates_rank_passers_on_the_selection_split(tmp_path: Path) -> None:
    for cand, leak in (("v20", 0.0), ("b1", 0.3), ("b2", 0.1)):
        block = {"leak": leak, "over": 5.0, "leaked": 1, "values": 9, "over_masked": 1, "masked": 9}
        (tmp_path / f"{cand}.json").write_text(json.dumps({"all": block}), encoding="utf-8")
    assert gates.selection_split(tmp_path, "b2")["leak"] == 0.1
    assert gates.selection_split(tmp_path, "b9") is None
