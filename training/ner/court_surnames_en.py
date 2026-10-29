"""Fictional English court-style text with standalone surnames (LAB-1525).

The MAPA baseline (LAB-1516) found v2.0's clearest English miss: judgments refer to people by
surname alone after the first mention (``Hughes accepted that ...``, ``in Carter's evidence``,
``the claim against Mr Doyle``), and the model, trained on letters and forms that name people
in full, leaves many of those surnames unmasked. This script writes short, seeded, template
documents in that register. Every template sentence is written for this script (no court text
is used or adapted: MAPA and TAB never leave the machine, policy LAB-1419), and every person
is a random given name + surname pair, so nobody here is a real person.

Labels: each person is introduced once in full (``PERSON``: given name + surname); later
mentions are the surname alone, sometimes with an honorific. The honorific (``Mr``, ``Mrs``,
``Ms``, ``Dr``) is not part of the span: OpenPII and the eval policy exclude titles, so its
characters go into ``meta.loss_ignore`` (taught neither as PERSON nor as O). A possessive
``'s`` stays outside the span. Many surnames are also common English words (Baker, Hope,
Wood), the hard case: they are capitalised names in these sentences. Role words (the
claimant, the appellant, the judge, the respondent authority) stay unlabelled::

    uv run --no-sync python training/ner/court_surnames_en.py --n 1500 --seed 1525 \\
        --out eval/generated/court-en
"""

# Seeded synthetic data: the standard PRNG is the point.
# ruff: noqa: S311

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from pii_guard.eval.fixtures import Document, GoldSpan, write_fixtures
from pii_guard.eval.identities import _EN_FAMILY, _EN_GIVEN_F, _EN_GIVEN_M
from pii_guard.types import EntityType

#: Surnames that are also ordinary English words, plus more common surnames (combined at random
#: with a given name, as the generator does).
SURNAMES = (
    *_EN_FAMILY,
    "Baker", "Mason", "Hope", "Wood", "Rose", "Young", "Little", "Long", "Ward", "Hill",
    "Marsh", "Brook", "Stone", "Fox", "King", "Bishop", "Price", "Bell", "Hunt", "Lamb",
    "Moss", "Field", "Shepherd", "Cook", "Walker", "Wright", "Hall", "Green", "Lane", "Booth",
    "Archer", "Bird", "Banks", "Chapman", "Dawson", "Ellis", "Foster", "Gibson", "Harper",
    "Jarvis", "Knowles", "Lloyd", "Marshall", "Nash", "Osborne", "Parry", "Reid", "Sutton",
    "Thorne", "Vaughan", "Webb", "Yates", "Ahmed", "Begum", "Kaur", "Singh", "O'Neill",
    "McAllister", "Fitzgerald", "Kowalczyk", "Rossi", "Dimitrov", "Haddad", "Mensah",
)  # fmt: skip
GIVEN = {"f": (*_EN_GIVEN_F, "Rachel", "Joanne", "Karen", "Fiona", "Bethany", "Nadia"),
         "m": (*_EN_GIVEN_M, "Mark", "Paul", "Stephen", "Gareth", "Kieran", "Imran")}  # fmt: skip
TITLES = {"f": ("Mrs", "Ms", "Miss", "Dr"), "m": ("Mr", "Mr", "Mr", "Dr")}
ROLES = (
    ("claimant", "defendant"), ("appellant", "respondent"), ("applicant", "respondent"),
    ("petitioner", "respondent"), ("claimant", "second defendant"),
)  # fmt: skip

# {A}/{B}: full name on first mention; {a}/{b}: surname (maybe titled) later; {a_s}: possessive.
OPENINGS = (
    "The {ra}, {A}, brings this claim against the {rb}, {B}, for the balance of a loan.",
    "This is an appeal by {A} (the {ra}) against an order made in favour of {B}.",
    "{A}, the {ra}, and {B}, the {rb}, were business partners until the spring of {year}.",
    "By a claim form issued in {year}, {A} sought damages from {B} for breach of contract.",
    "The {rb}, {B}, was employed by the {ra}, {A}, as a site manager between {year} and {year2}.",
    "I heard oral evidence from {A} and from {B}, and read the witness statements of both.",
)  # fmt: skip
BODY = (
    "{a} says that the money was a loan; {b} says it was a gift.",
    "In cross-examination {b} accepted that the signature on the agreement was {b_his} own.",
    "I found {a} to be a careful and generally reliable witness.",
    "{b_s} account of the meeting in {month} {year} was, in my judgment, inconsistent.",
    "It is common ground that {a} transferred £{amount} to {b} on that date.",
    "{a} was not cross-examined on that point, and I accept {a_his} evidence about it.",
    "The difficulty for {b} is that the emails do not support {b_his} version of events.",
    "Counsel for {a} submitted that {b} had waived the condition by {b_his} conduct.",
    "{b} denies that any such promise was made to {a}.",
    "I do not accept that {a} knew of the defect before completion.",
    "There is no evidence that {b} ever told {a} about the second invoice.",
    "On {a_s} case, the work was never finished; on {b_s}, it was abandoned for want of payment.",
    "{a} was candid about the gaps in {a_his} records.",
    "When pressed, {b} could not explain why the payment was made in cash.",
    "The judge preferred the evidence of {a} to that of {b}.",
    "Neither {a} nor {b} kept a note of the conversation.",
    "{b} instructed solicitors only after the letter of claim from {a} arrived.",
    "The burden is on {a} to prove the agreement on the balance of probabilities.",
    "It was put to {b} that {b_he} had read the contract; {b_he} said {b_he} had not.",
    "In my view {a_s} contemporaneous messages are the best evidence of what was agreed.",
)  # fmt: skip
CLOSINGS = (
    "For these reasons, the claim by {a} succeeds in part.",
    "The appeal is dismissed and {b} is entitled to {b_his} costs.",
    "I will hear counsel on the form of the order and on costs.",
    "Judgment is entered for {a} in the sum of £{amount}, with interest.",
    "The claim against {b} is dismissed.",
)  # fmt: skip
MONTHS = ("January", "March", "April", "June", "July", "September", "October", "November")

_SLOT = re.compile(r"\{(\w+)\}")


class _Person:
    def __init__(self, rng: random.Random, used: set[str]) -> None:
        self.gender = rng.choice("fm")
        while True:
            self.family = rng.choice(SURNAMES)
            if self.family not in used:
                used.add(self.family)
                break
        self.given = rng.choice(GIVEN[self.gender])
        self.rng = rng

    def pronouns(self) -> dict[str, str]:
        return {"his": "her" if self.gender == "f" else "his",
                "he": "she" if self.gender == "f" else "he"}  # fmt: skip


def document(seed: int, index: int) -> Document:
    rng = random.Random(f"pii-guard-court-en/{seed}/{index}")
    used: set[str] = set()
    people = {"a": _Person(rng, used), "b": _Person(rng, used)}
    ra, rb = rng.choice(ROLES)
    year = rng.randint(2012, 2024)
    sentences = [rng.choice(OPENINGS)]
    sentences += rng.sample(BODY, rng.randint(3, 6))
    if rng.random() < 0.7:
        sentences.append(rng.choice(CLOSINGS))
    template = " ".join(sentences)
    # Paragraph breaks as judgments number them.
    if rng.random() < 0.5:
        parts = template.split(". ")
        template = ".\n\n".join(f"{i + 1}. {p}" for i, p in enumerate(parts))

    text: list[str] = []
    spans: list[GoldSpan] = []
    ignore: list[list[int]] = []
    pos = 0
    cursor = 0
    for m in _SLOT.finditer(template):
        literal = template[cursor : m.start()]
        text.append(literal)
        pos += len(literal)
        cursor = m.end()
        slot = m.group(1)
        key = slot[0].lower()
        if slot in {"A", "B"}:
            p = people[key]
            full = f"{p.given} {p.family}"
            if rng.random() < 0.3:  # "Mr Oliver Hughes"
                title = rng.choice(TITLES[p.gender]) + " "
                ignore.append([pos, pos + len(title) - 1])
                text.append(title)
                pos += len(title)
            spans.append(GoldSpan(pos, pos + len(full), EntityType.PERSON, full))
            text.append(full)
            pos += len(full)
        elif slot in {"a", "b", "a_s", "b_s"}:
            p = people[key]
            if rng.random() < 0.35:
                title = rng.choice(TITLES[p.gender]) + " "
                ignore.append([pos, pos + len(title) - 1])
                text.append(title)
                pos += len(title)
            spans.append(GoldSpan(pos, pos + len(p.family), EntityType.PERSON, p.family))
            text.append(p.family)
            pos += len(p.family)
            if slot.endswith("_s"):
                suffix = "'" if p.family.endswith("s") else "'s"
                text.append(suffix)
                pos += len(suffix)
        elif slot in {"a_his", "b_his", "a_he", "b_he"}:
            word = people[key].pronouns()[slot[2:]]
            text.append(word)
            pos += len(word)
        else:
            word = {
                "ra": ra, "rb": rb, "year": str(year), "year2": str(year + rng.randint(1, 6)),
                "month": rng.choice(MONTHS), "amount": f"{rng.randint(2, 480) * 250:,}",
            }[slot]  # fmt: skip
            text.append(word)
            pos += len(word)
    tail = template[cursor:]
    text.append(tail)
    body = "".join(text)
    # Sentence-initial role words read better capitalised.
    body = re.sub(r"(^|\. |\n\n\d+\. )(the )", lambda m: m.group(1) + "The ", body)
    if len(body) != pos + len(tail):  # pragma: no cover - a template bug
        raise RuntimeError(f"offset drift in document {index}")
    meta = {
        "kind": "court-style-surnames",
        "split": "train",
        "source": "synthetic",
        "seed": seed,
        "loss_ignore": ignore,
    }
    return Document(f"en-court-s{seed}-{index:05d}", "en", body, tuple(spans), meta)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--n", type=int, default=1500)
    parser.add_argument("--dev", type=int, default=100)
    parser.add_argument("--seed", type=int, default=1525)
    parser.add_argument("--out", type=Path, default=Path("eval/generated/court-en"))
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    docs = [document(args.seed, i) for i in range(args.n + args.dev)]
    for d in docs:
        for s in d.spans:
            if d.text[s.start : s.end] != s.text:  # pragma: no cover - a template bug
                raise RuntimeError(f"span drift in {d.id}")
    stats = {}
    for name, part in (("dev", docs[: args.dev]), ("train", docs[args.dev :])):
        for d in part:
            d.meta["split"] = name
        path = args.out / f"en-court-{name}.jsonl"
        write_fixtures(path, part)
        stats[name] = {
            "documents": len(part),
            "person_spans": sum(len(d.spans) for d in part),
            "standalone_surnames": sum(1 for d in part for s in d.spans if " " not in s.text),
            "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        print(f"court-en: {len(part)} {name} documents -> {path}", file=sys.stderr)
    stats["kinds"] = dict(Counter(d.meta["kind"] for d in docs))
    (args.out / "stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
