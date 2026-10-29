"""Fictional court-style documents and error-pattern variants for NER v4.1 (LAB-1539).

Fictional data only (ADR 0005). Nothing here quotes, adapts or is derived from MAPA, TAB or
any other court text: the briefs below are written from scratch and every party is planted
from ``court_eu_names.py`` (common given names and surnames combined at random, invented
company words). As ``eu_corpus.py`` (LAB-1525), Muse Spark writes each document around the
planted values with the generator's prompt files (``system.md`` / ``user.md``) and response
cache, the planted values are the gold, and ``training/ner/modal_eu_label.py`` then adds the
Glimmer teacher pass.

Two corpora:

- ``court`` (part 1): judgment and opinion-style text in 24 languages (the 21 MAPA languages,
  hr, sl, pl). Formal register, long sentences, numbered paragraphs, parties introduced once
  in full and then referred to by surname alone (``Mr X`` ... ``X``), next to role words and,
  in the case-rich languages, in whatever grammatical case the sentence needs.
- ``variants`` (part 2): short fictional documents per v2.0 error pattern mined on
  development splits (``training/ner/mine_v41.py``; patterns in :data:`VARIANTS`).

**Gold.** A planted person is found as the full name, the surname alone or the given name
alone, in any form :func:`court_eu_names.person_regex` allows; an honorific is never part of
the span. Every other value must appear exactly as given (separators aside). Discards (counted,
never values): truncated or empty output, a value missing (each person at least once in full),
an identifier nobody planted, a given name of the pack outside every planted person.

::

    set -a; source .env; set +a      # META_API_KEY (Meta Model API, contributor tier)
    uv run --no-sync python training/ner/court_eu.py court --n 170 --seed 1539 \\
        --out <data>/court --cache <data>/cache --budget-usd 3.5 --workers 10

Writes ``<lang>-distill-{train,dev}.jsonl`` (the names ``training/distill/label.py`` expects)
and ``stats.json`` (counts, discard reasons, tokens, cost; never values). 90 / 10 split by a
seeded shuffle.
"""

# Seeded synthetic data: the standard PRNG is the point.
# ruff: noqa: S311

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import threading
import time
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from court_eu_names import COMPANY_WORDS, LANGUAGES, PACKS, Pack, given_name_regex, person_regex

from pii_guard.eval.fixtures import Document, GoldSpan, write_fixtures
from pii_guard.eval.forms import find_surface_forms
from pii_guard.eval.generate import (
    DEFAULT_BASE_URL,
    ChatClient,
    Completion,
    ModelError,
    ResponseCache,
    _template_text,
    clean_output,
    unsupplied_types,
)
from pii_guard.types import EntityType

CORPUS_VERSION = 1
DEFAULT_MODEL = "muse-spark-1.3-contributor"
PRICE_PER_M = {"prompt": 0.10, "completion": 0.20}
NO_VALUES = "(none: this document contains no personal data at all)"


@dataclass(frozen=True, slots=True)
class Planted:
    field: str
    entity_type: EntityType
    text: str
    required: bool = True
    given: str = ""
    family: str = ""
    gender: str = ""

    def __repr__(self) -> str:  # never the value
        return f"Planted({self.field!r}, {self.entity_type.value})"


@dataclass(frozen=True, slots=True)
class Party:
    label: str
    kind: str  # person | company | property
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Kind:
    id: str
    title: str
    brief: str
    length: str
    parties: tuple[Party, ...]
    register: str = "formal judicial"
    weight: int = 1
    #: For variants: the mined pattern this kind targets.
    pattern: str = ""


def _p(label: str, kind: str, *fields: str) -> Party:
    return Party(label, kind, fields)


_COURT_STYLE = (
    " Write it as courts do: numbered paragraphs, long sentences with subordinate clauses, "
    "formal vocabulary. Introduce each person once with their full name (an honorific is "
    "fine), then refer to them mostly by surname alone, sometimes with an honorific (Mr X, "
    "then X), and often right next to their procedural role (the claimant X, witness X), in "
    "whatever grammatical case each sentence needs. Name the court only generically, without "
    "a town or a judge's name unless given."
)

COURT_KINDS: tuple[Kind, ...] = (
    Kind(
        "court-loan", "Reasons of a first-instance civil judgment (excerpt)",
        "An excerpt from the reasons of a first-instance judgment in a dispute between two "
        "private persons about the repayment of a private loan: the facts as established, "
        "the claimant's and the defendant's arguments, the testimony of a witness, the "
        "court's assessment of the evidence and the operative part." + _COURT_STYLE,
        "450-650",
        (_p("Claimant", "person", "name", "address"),
         _p("Defendant", "person", "name", "address", "date_of_birth"),
         _p("Witness", "person", "name")),
        weight=2,
    ),
    Kind(
        "court-tenancy", "Judgment in a tenancy dispute (reasons)",
        "The reasons of a judgment in which a property company sued a private tenant for "
        "rent arrears and the return of a flat: the lease, the payment history, the tenant's "
        "defence about defects, the evidence of the company's property manager, and the "
        "court's findings." + _COURT_STYLE,
        "450-650",
        (_p("Claimant company", "company", "org_name"),
         _p("the company's property manager (a witness)", "person", "name"),
         _p("Defendant (the tenant)", "person", "name", "date_of_birth"),
         _p("the flat", "property", "address")),
        weight=2,
    ),
    Kind(
        "court-employment", "Judgment of a labour court on a dismissal (reasons)",
        "The reasons of a labour court judgment on an employee's claim that her or his "
        "dismissal by a company was unlawful: the employment history, the reasons the "
        "employer gave, the hearing of the employee's former manager, the parties' "
        "submissions and the court's legal assessment." + _COURT_STYLE,
        "450-650",
        (_p("Claimant (the employee)", "person", "name", "address"),
         _p("Defendant employer", "company", "org_name"),
         _p("the former manager (a witness)", "person", "name")),
        weight=2,
    ),
    Kind(
        "court-traffic", "Judgment on damages after a road accident (reasons)",
        "The reasons of a judgment on a claim for damages after a collision at a junction: "
        "the claimant, the defendant driver, the defendant's insurer, two accounts of the "
        "accident, an eyewitness, an expert's opinion (the expert by role only) and the "
        "apportionment of liability." + _COURT_STYLE,
        "450-650",
        (_p("Claimant", "person", "name", "address"),
         _p("Defendant driver", "person", "name"),
         _p("Defendant insurer", "company", "org_name"),
         _p("Eyewitness", "person", "name")),
    ),
    Kind(
        "court-appeal", "Appellate court decision (reasons)",
        "The reasons of an appellate court's decision on an appeal against a first-instance "
        "judgment between two private persons about a defective renovation of a house: the "
        "first-instance findings summarized, the grounds of appeal, the respondent's reply, "
        "and the appellate court's reasoning, partly allowing the appeal." + _COURT_STYLE,
        "450-650",
        (_p("Appellant (first-instance defendant)", "person", "name", "address"),
         _p("Respondent (first-instance claimant)", "person", "name"),
         _p("the house", "property", "address")),
    ),
    Kind(
        "court-administrative", "Administrative court judgment on a building permit",
        "The reasons of an administrative court judgment on a neighbour's action against a "
        "building permit granted to a private applicant: the permit, the neighbour's "
        "objections, the authority's position (the authority by role only), the applicant "
        "joining as an interested party, and the court's review." + _COURT_STYLE,
        "450-650",
        (_p("Applicant for the permit (interested party)", "person", "name", "address"),
         _p("Claimant (the neighbour)", "person", "name", "date_of_birth"),
         _p("the plot", "property", "address")),
    ),
    Kind(
        "court-opinion", "Opinion of an advocate general (excerpt)",
        "An excerpt of an advocate general's opinion in a preliminary reference that arose "
        "from a dispute between a private consumer and a company over a cancelled package "
        "holiday: the facts of the main proceedings, the questions referred, and the "
        "analysis, referring back to the parties of the main proceedings by surname or name. "
        "The advocate general writes in the first person ('In my view ...')." + _COURT_STYLE,
        "500-700",
        (_p("Applicant in the main proceedings", "person", "name"),
         _p("Defendant company in the main proceedings", "company", "org_name"),
         _p("the applicant's travel companion", "person", "name")),
    ),
    Kind(
        "court-succession", "Judgment in a succession dispute (reasons)",
        "The reasons of a judgment in a dispute between two siblings about the division of "
        "their late parent's estate (a flat and savings): the will, each sibling's claims, the "
        "evidence of a family friend, and the court's division. The late parent is named "
        "too." + _COURT_STYLE,
        "450-650",
        (_p("Claimant (sibling)", "person", "name", "address"),
         _p("Defendant (sibling)", "person", "name"),
         _p("the late parent", "person", "name", "date_of_birth"),
         _p("Family friend (a witness)", "person", "name"),
         _p("the flat", "property", "address")),
    ),
)  # fmt: skip


# --- Part 2: variants per mined v2.0 error pattern --------------------------------------------

VARIANTS: tuple[Kind, ...] = (
    Kind(
        "variant-dates-not-birth", "Letter with several dates, one of them a birth date",
        "An official letter or form confirmation that gives one person's date of birth "
        "exactly as given, and also at least four other dates that are NOT birth dates, "
        "written in varied formats: a deadline ('no later than ...'), an appointment, the "
        "date the application was received, a validity period, and an ISO timestamp such as "
        "2019-03-14T09:30:00. Never call any other date a date of birth.",
        "150-250",
        (_p("Applicant", "person", "name", "date_of_birth"),),
        register="formal administrative",
        pattern="overmask:date_of_birth (ordinary dates masked as a birth date)",
        weight=3,
    ),
    Kind(
        "variant-honorific", "Letters and messages that address people with honorifics",
        "A short letter or e-mail that addresses its recipient with the language's formal "
        "honorific or title (Mr, Mrs, Miss, Dear Sir/Madam forms, 'Kungs', 'Signorina', "
        "'Domnișoara', 'Ponia', 'Δεσποινίς', 'Herr', 'Fru' ... whatever this language uses), "
        "mentions a second person with an honorific in another grammatical case, and uses the "
        "honorifics alone too ('Dear Madam', 'the gentleman'). The honorifics are not names.",
        "100-200",
        (_p("Recipient", "person", "name"), _p("Second person", "person", "name")),
        register="polite, semi-formal",
        pattern="overmask:person (an honorific masked as a name)",
        weight=2,
    ),
    Kind(
        "variant-standalone-declined", "Contract or report naming parties by surname alone",
        "A contract clause, lease clause, employment certificate or incident report in which "
        "each person is introduced once in full and then referred to only by surname or only "
        "by given name, in as many different grammatical cases as the language has (genitive "
        "'through X's fault', dative, instrumental, locative, possessive), at least six "
        "standalone mentions in total.",
        "180-280",
        (_p("First party", "person", "name"), _p("Second party", "person", "name")),
        register="formal legal",
        pattern="leak:person:single-token-case-rich (declined surname or given name alone)",
        weight=3,
    ),
    Kind(
        "variant-reference-numbers", "Order or support chat with many reference numbers",
        "A customer support chat, delivery notice or log excerpt that mentions the customer "
        "by name and is full of numbers that are NOT personal data: order numbers, invoice "
        "numbers, ticket IDs, tracking numbers, SKUs, room numbers, distances in km, "
        "quantities and amounts, in varied formats (8841, SO-4471203, ORD-2026-118734, "
        "GT-81215).",
        "120-220",
        (_p("Customer", "person", "name"),),
        register="conversational or terse business",
        pattern="overmask:id_document / address (reference numbers masked as IDs or addresses)",
        weight=2,
    ),
    Kind(
        "variant-person-like-company", "Invoice or log naming a company that looks like a person",
        "An invoice, purchase log or delivery record in which a supplier and a carrier are "
        "companies whose names are built from a surname (given exactly as listed) and a "
        "private person (the buyer) is also named. Use the company names in fields such as "
        "'vendor:', 'carrier=', 'supplier' and in prose; they are organizations, not people.",
        "120-220",
        (_p("Supplier", "company", "org_name"), _p("Carrier", "company", "org_name"),
         _p("Buyer", "person", "name")),
        register="business, terse",
        pattern="overmask:person:multi-word (a person-like company name masked as a person)",
        weight=2,
    ),
    Kind(
        "negative-capitalized-words", "Text full of capitalized non-names",
        "An everyday text without any personal data in which many capitalized words are NOT "
        "names of people: greetings at the start of a line ('Hi', 'Bok', 'Hej'), product and "
        "app names used as common nouns (a chat channel, a spreadsheet tool), month and day "
        "names, words capitalized at the start of a sentence or in a heading, and the names "
        "of districts or neighbourhoods in prose. No people, no companies.",
        "120-200",
        (),
        register="neutral",
        pattern="overmask:person:single-capitalized-word / sentence-initial-word",
        weight=2,
    ),
)  # fmt: skip


# --- Identities -------------------------------------------------------------------------------


class Identities:
    def __init__(self, pack: Pack, rng: random.Random) -> None:
        self.pack, self.rng = pack, rng
        self._used: set[str] = set()

    def address(self) -> str:
        town, post = self.rng.choice(self.pack.towns)
        num = str(self.rng.randint(1, 160))
        if self.rng.random() < 0.25:
            num += "/" + str(self.rng.randint(1, 40))
        return self.pack.address_format.format(
            street=self.rng.choice(self.pack.streets), num=num, town=town, post=post
        )

    def birth(self) -> str:
        y = self.rng.randint(1945, 2004)
        m = self.rng.randint(1, 12)
        d = self.rng.randint(1, 28)
        return self.pack.date_format.format(d=f"{d:02d}", m=f"{m:02d}", y=y)

    def person(self, fields: Sequence[str]) -> list[Planted]:
        gender = self.rng.choice("fm")
        for _ in range(60):
            given = self.rng.choice(self.pack.given_f if gender == "f" else self.pack.given_m)
            male, female = self.rng.choice(self.pack.surnames)
            family = female if gender == "f" else male
            if given not in self._used and male not in self._used:
                break
        self._used |= {given, male, female}
        values = {
            "name": f"{given} {family}",
            "address": self.address(),
            "date_of_birth": self.birth(),
        }
        types = {
            "name": EntityType.PERSON,
            "address": EntityType.ADDRESS,
            "date_of_birth": EntityType.DATE_OF_BIRTH,
        }
        return [
            Planted(
                f, types[f], values[f],
                given=given if f == "name" else "", family=family if f == "name" else "",
                gender=gender if f == "name" else "",
            )
            for f in fields
        ]  # fmt: skip

    def company(self, kind: Kind) -> list[Planted]:
        if kind.id == "variant-person-like-company":
            male, _ = self.rng.choice([s for s in self.pack.surnames if s[0] not in self._used])
            self._used.add(male)
            short = male
        else:
            short = self.rng.choice([w for w in COMPANY_WORDS if w not in self._used])
            self._used.add(short)
        name = f"{short} {self.rng.choice(self.pack.company_forms)}"
        return [
            Planted("org_name", EntityType.ORGANIZATION, name),
            Planted("short_name", EntityType.ORGANIZATION, short, required=False),
        ]

    def make(self, party: Party, kind: Kind) -> list[Planted]:
        if party.kind == "person":
            return self.person(party.fields)
        if party.kind == "company":
            return self.company(kind)
        return [Planted("address", EntityType.ADDRESS, self.address())]


# --- Plans ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Plan:
    doc_id: str
    language: str
    index: int
    kind: Kind
    values: tuple[Planted, ...]
    messages: tuple[dict[str, str], ...]


def inflection_rule(pack: Pack) -> str:
    decline = (
        "Decline the names of people as natural " + pack.name + " requires. "
        if pack.inflects
        else ""
    )
    return (
        f"{decline}Courts and offices writing in {pack.name} refer to parties like this: "
        f"{pack.honorifics}. Give every person's full name at least once exactly as given "
        "(in the nominative where the language has cases, for example where the parties "
        "are introduced); after that you may use the surname or the given name alone, with "
        "or without an honorific, in any grammatical case. Write company names, addresses "
        "and dates exactly as given."
    )


NEGATIVE_TOPICS = (
    "a team's weekly status update", "a train timetable change", "a city district's festival",
    "a software release note", "a library's new opening hours", "a hiking trail in two "
    "neighbourhoods", "a school's sports day", "a recipe blog post", "a museum's new wing",
    "an office move checklist", "a cycling route through three districts", "a product FAQ",
)  # fmt: skip


def plan_document(corpus: str, code: str, seed: int, index: int) -> Plan:
    pack = PACKS[code]
    rng = random.Random(f"pii-guard-court-eu/{CORPUS_VERSION}/{corpus}/{seed}/{code}/{index}")
    kinds = COURT_KINDS if corpus == "court" else VARIANTS
    kind = rng.choices(kinds, weights=[k.weight for k in kinds])[0]
    ids = Identities(pack, rng)
    values: list[Planted] = []
    blocks: list[str] = []
    for party in kind.parties:
        pv = ids.make(party, kind)
        lines = [f"{party.label}:"]
        lines += [f"- {v.field.replace('_', ' ')}: {v.text}" for v in pv if v.required]
        blocks.append("\n".join(lines))
        values.extend(pv)
    system = (
        _template_text("system.md")
        .replace("{language_name}", pack.name)
        .replace("{inflection_rule}", inflection_rule(pack))
    )
    user = (
        _template_text("user.md")
        .replace("{title}", kind.title)
        .replace("{brief}", kind.brief)
        .replace("{register}", kind.register)
        .replace("{length}", kind.length)
        .replace("{typos}", "")
        .replace("{hard_negatives}", "")
        .replace("{values}", "\n\n".join(blocks) if blocks else NO_VALUES)
    )
    user += f"\n\nVariant {rng.randrange(10**6)}: make the facts and wording distinct."
    if not kind.parties:
        user += f" Subject: {rng.choice(NEGATIVE_TOPICS)}."
    prefix = "court" if corpus == "court" else "v41var"
    return Plan(
        f"{code}-{prefix}-s{seed}-{index:05d}", code, index, kind, tuple(values),
        ({"role": "system", "content": system.strip()},
         {"role": "user", "content": user.strip()}),
    )  # fmt: skip


# --- Gold -------------------------------------------------------------------------------------


def locate(text: str, plan: Plan) -> tuple[list[GoldSpan], list[Planted]]:
    candidates: list[tuple[int, int, EntityType, bool]] = []
    missing: list[Planted] = []
    for v in plan.values:
        if v.entity_type is EntityType.PERSON and v.given:
            hits = [
                m.span()
                for m in person_regex(plan.language, v.given, v.family, v.gender).finditer(text)
            ]
            full_tokens = len(v.text.split())
            if not any(len(text[s:e].split()) >= full_tokens for s, e in hits):
                missing.append(v)
        else:
            hits = find_surface_forms(text, v.text, v.entity_type, plan.language)
            if v.field == "short_name":
                hits = [(s, e) for s, e in hits if text[s].isupper()]
            if v.required and not hits:
                missing.append(v)
        candidates.extend((s, e, v.entity_type, v.required) for s, e in hits)
    candidates.sort(key=lambda c: (-(c[1] - c[0]), not c[3], c[0]))
    taken: list[tuple[int, int, EntityType]] = []
    for s, e, t, _ in candidates:
        if not any(s < te and ts < e for ts, te, _ in taken):
            taken.append((s, e, t))
    taken.sort()
    return [GoldSpan(s, e, t, text[s:e]) for s, e, t in taken], missing


_GIVEN: dict[str, Any] = {}


def invented_people(text: str, spans: Sequence[GoldSpan], code: str) -> int:
    pattern = _GIVEN.setdefault(code, given_name_regex(code))
    return sum(
        1
        for m in pattern.finditer(text)
        if not any(m.start() < s.end and s.start < m.end() for s in spans)
    )


# --- Generation -------------------------------------------------------------------------------


class Budget:
    def __init__(self, usd: float) -> None:
        self.usd, self.spent = usd, 0.0
        self.tokens: Counter[str] = Counter()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            return self.spent < self.usd

    def spend(self, c: Completion) -> None:
        with self._lock:
            p = int(c.usage.get("prompt_tokens", 0))
            q = int(c.usage.get("completion_tokens", 0))
            self.tokens["prompt"] += p
            self.tokens["completion"] += q
            self.spent += (p * PRICE_PER_M["prompt"] + q * PRICE_PER_M["completion"]) / 1e6


@dataclass(frozen=True, slots=True)
class Outcome:
    plan: Plan
    document: Document | None
    reason: str | None = None


def generate(
    plan: Plan, client: ChatClient, cache: ResponseCache, budget: Budget, split: str, seed: int
) -> Outcome:
    key = ResponseCache.key(client.payload(plan.messages))
    completion = cache.get(key)
    if completion is None:
        if not budget.allow():
            return Outcome(plan, None, "budget")
        try:
            completion = client.complete(plan.messages)
        except ModelError as exc:
            if not exc.retryable:
                return Outcome(plan, None, "model_error_final")
            return Outcome(plan, None, "model_error")
        budget.spend(completion)
        cache.put(key, completion)
    if completion.finish_reason == "length":
        return Outcome(plan, None, "truncated")
    text = clean_output(completion.content)
    if not text:
        return Outcome(plan, None, "empty_output")
    spans, missing = locate(text, plan)
    if missing:
        return Outcome(plan, None, "missing_value")
    try:
        invented = unsupplied_types(text, spans, plan.language)
    except Exception:
        invented = []
    if invented:
        return Outcome(plan, None, "unsupplied_value")
    if invented_people(text, spans, plan.language):
        return Outcome(plan, None, "invented_person")
    kind = plan.kind
    meta: dict[str, Any] = {
        "kind": kind.id,
        "source": "synthetic",
        "synthetic": True,
        "generator": f"training/ner/court_eu.py/{CORPUS_VERSION}",
        "seed": seed,
        "index": plan.index,
        "model": completion.model or client.model,
        "prompt_sha256": key[:16],
        "gold": "planted values; names in any form (court_eu_names.person_regex)",
        "split": split,
    }
    if kind.pattern:
        meta["pattern"] = kind.pattern
    return Outcome(plan, Document(plan.doc_id, plan.language, text, tuple(spans), meta))


def splits(n: int, seed: int, code: str) -> list[str]:
    order = list(range(n))
    random.Random(f"pii-guard-court-eu-split/{seed}/{code}").shuffle(order)
    dev = set(order[: max(1, n // 10)])
    return ["dev" if i in dev else "train" for i in range(n)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("corpus", choices=("court", "variants"))
    parser.add_argument("--languages", default=",".join(LANGUAGES))
    parser.add_argument("--n", type=int, default=170, help="planned documents per language")
    parser.add_argument("--seed", type=int, default=1539)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--budget-usd", type=float, required=True)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--retry-rounds", type=int, default=3)
    parser.add_argument(
        "--base-url", default=os.environ.get("PII_GUARD_CORPUS_URL", DEFAULT_BASE_URL)
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    languages = args.languages.split(",")
    if args.dry_run:
        for m in plan_document(args.corpus, languages[0], args.seed, 0).messages:
            print(f"--- {m['role']}\n{m['content']}")
        return 0
    key = os.environ.get("PII_GUARD_CORPUS_API_KEY") or os.environ.get("META_API_KEY")
    client = ChatClient(
        base_url=args.base_url, api_key=key, model=args.model, reasoning_effort="low",
        max_retries=4, backoff_s=4.0,
    )  # fmt: skip
    cache = ResponseCache(args.cache)
    budget = Budget(args.budget_usd)
    args.out.mkdir(parents=True, exist_ok=True)
    stats: dict[str, Any] = {
        "corpus": args.corpus, "corpus_version": CORPUS_VERSION, "seed": args.seed,
        "model": args.model, "planned_per_language": args.n, "languages": {},
    }  # fmt: skip
    for code in languages:
        split_of = splits(args.n, args.seed, code)
        todo = [plan_document(args.corpus, code, args.seed, i) for i in range(args.n)]
        done: dict[int, Outcome] = {}
        for rnd in range(args.retry_rounds + 1):
            with ThreadPoolExecutor(args.workers) as pool:
                outs = list(
                    pool.map(
                        lambda p, s=split_of: generate(
                            p, client, cache, budget, s[p.index], args.seed
                        ),
                        todo,
                    )
                )
            for o in outs:
                done[o.plan.index] = o
            todo = [o.plan for o in outs if o.reason == "model_error"]
            if not todo or rnd == args.retry_rounds:
                break
            print(f"court-eu: {code}: retrying {len(todo)} after model errors", file=sys.stderr)
            time.sleep(30 * (rnd + 1))
        outcomes = list(done.values())
        reasons = Counter(o.reason for o in outcomes if o.reason)
        docs = sorted((o.document for o in outcomes if o.document), key=lambda d: d.id)
        block: dict[str, Any] = {"accepted": len(docs), "discarded": dict(sorted(reasons.items()))}
        for name in ("train", "dev"):
            part = [d for d in docs if d.meta["split"] == name]
            write_fixtures(args.out / f"{code}-distill-{name}.jsonl", part)
            block[name] = {
                "documents": len(part),
                "gold_spans": dict(
                    sorted(Counter(s.entity_type.value for d in part for s in d.spans).items())
                ),
                "kinds": dict(sorted(Counter(str(d.meta["kind"]) for d in part).items())),
            }
        stats["languages"][code] = block
        print(
            f"court-eu: {code}: {len(docs)} accepted, discarded {dict(reasons)}, "
            f"spent ${budget.spent:.3f}",
            file=sys.stderr, flush=True,
        )  # fmt: skip
        stats["tokens_uncached"] = dict(budget.tokens)
        stats["cost_usd_uncached"] = round(budget.spent, 4)
        (args.out / "stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
