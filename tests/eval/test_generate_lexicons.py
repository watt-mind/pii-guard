"""The corpus generator draws names and places from the lexicons and plans hard negatives."""

# Seeded, reproducible sampling: the standard PRNG is the point.
# ruff: noqa: S311

from __future__ import annotations

import random
import re

from pii_guard.eval import generate as gen
from pii_guard.eval.generate import plan_document
from pii_guard.eval.identities import identity_generator
from pii_guard.lang import lexicon, postcode_index


def _plans(n: int = 50, seed: int = 42) -> list[gen.DocumentPlan]:
    return [plan_document("hu", seed, i) for i in range(n)]


def test_generator_version_was_bumped_for_the_lexicons() -> None:
    assert gen.GENERATOR_VERSION >= 2


def test_people_and_places_come_from_the_lexicons() -> None:
    surnames, given_m, given_f = (
        lexicon("surnames"),
        lexicon("given_names_m"),
        lexicon("given_names_f"),
    )
    settlements, streets = lexicon("settlements"), lexicon("street_names")
    for seed in range(30):
        ids = identity_generator("hu", random.Random(seed))
        person = ids.person()
        assert person.family in surnames
        assert person.given in (given_f if person.gender == "f" else given_m)
        assert person.mother_name is not None
        mother_family, mother_given = person.mother_name.split(" ", 1)
        assert mother_family in surnames and mother_given in given_f
        assert mother_family != person.family
        match = re.match(
            r"(\d{4}) (\w+), (.+?) (?:utca|út|tér|köz|sor|körút|sétány|fasor|rakpart) \d",
            person.address,
        )
        assert match, person.address
        code, town, street = match.groups()
        assert town in settlements and street in streets
        assert postcode_index("hu").consistent(code, town)


def test_a_50_document_sample_is_diverse() -> None:
    """Old lists: 45 distinct surnames in 106 slots, 19 settlements in 78 (seed 42)."""
    surnames: set[str] = set()
    towns: set[str] = set()
    for plan in _plans():
        for value in plan.values:
            if value.field == "family":
                surnames.add(value.text)
            elif value.field == "address":
                towns.add(value.text.split(",", 1)[0].split(" ", 1)[1])
    assert len(surnames) >= 70
    assert len(towns) >= 50
    assert "Budapest" in towns  # still drawn about as often as people live there


def test_no_given_name_hides_inside_a_street_name() -> None:
    for seed in range(40):
        ids = identity_generator("hu", random.Random(f"streets/{seed}"))
        people = [ids.person() for _ in range(4)]
        streets = {w for p in people for w in p.address.split(",", 1)[1].split()}
        assert not streets & {p.given for p in people}


def test_hard_negatives_are_planned_and_never_values() -> None:
    plans = _plans()
    with_negatives = [p for p in plans if p.hard_negatives]
    assert len(with_negatives) == len(plans)
    common_words = {row[2] for row in lexicon("common_word_surnames").rows}
    kinds = {"surname": 0, "settlement": 0}
    for plan in plans:
        prompt = plan.messages[1]["content"]
        words = {w.casefold() for v in plan.values for w in re.findall(r"\w+", v.text)}
        for phrase in plan.hard_negatives:
            assert f'"{phrase}"' in prompt
            assert not {w.casefold() for w in re.findall(r"\w+", phrase)} & words
            kinds["surname"] += phrase in common_words
            kinds["settlement"] += any(
                t in phrase for t in ("felé tartó", "főtere", "környéki", "határában")
            )
    assert kinds["surname"] >= 40 and kinds["settlement"] >= 40


def test_english_has_no_hard_negatives_yet() -> None:
    plan = plan_document("en", 42, 0)
    assert plan.hard_negatives == ()
    assert "{hard_negatives}" not in plan.messages[1]["content"]


def test_hard_negatives_pick_skips_missing_kinds() -> None:
    picker = gen.HardNegatives(instruction="x", phrases=("Eladó lakás",))
    picked = picker.pick(random.Random(0), "en", [])
    assert set(picked) <= {"Eladó lakás"}


def test_plans_are_still_deterministic() -> None:
    a, b = plan_document("hu", 7, 3), plan_document("hu", 7, 3)
    assert a.messages == b.messages and a.hard_negatives == b.hard_negatives


class _EchoClient:
    """Writes every required value and every hard negative, one per line."""

    model = "muse-test"

    def __init__(self, plan: gen.DocumentPlan) -> None:
        self.plan = plan

    def payload(self, messages: object) -> dict[str, object]:
        return {"model": self.model, "messages": messages}

    def complete(self, messages: object) -> gen.Completion:
        lines = [f"- {v.text}" for v in self.plan.required]
        lines += [f"Megjegyzés: {p}." for p in self.plan.hard_negatives]
        return gen.Completion("\n".join(lines), "stop", {}, 0.0, self.model)


def test_documents_record_lexicons_and_unlabelled_hard_negatives() -> None:
    plan = plan_document("hu", 3, 1)
    outcome = gen.generate_document(plan, _EchoClient(plan))  # type: ignore[arg-type]
    doc = outcome.document
    assert doc is not None, outcome.reason
    assert re.fullmatch(r"[0-9a-f]{16}", doc.meta["lexicons"])
    assert doc.meta["hard_negatives"] == list(plan.hard_negatives)
    for phrase in plan.hard_negatives:
        start = doc.text.index(phrase)
        assert not any(s.start < start + len(phrase) and start < s.end for s in doc.spans)
