"""Fictional Muse-written documents for the multilingual NER phase 1 (LAB-1525): lv, lt, hr, sl;
phase 1b (LAB-1534): fr, es, it, nl, ro, ga, mt.

Fictional data only (ADR 0005). The v2.0 distillation corpus (``training/distill/corpus.py``)
plans each document from ``(seed, language, index)``, has Muse write it around planted
fictional values, and labels the planted values (gold); ``training/distill/label.py`` then adds
Muse Glimmer's teacher spans. The generator's identity and template packs exist only for hu
and en, so this script brings its own for the phase-1 languages (``eu_identities.py``) and
document kinds (:data:`KINDS`, prompts in English, the document in the target language). It
reuses the generator's prompt files (``system.md`` / ``user.md``), chat client and response
cache, so a rerun with the same seed reproduces the corpus without model calls.

**Gold.** These languages decline names (``Jānis Bērziņš`` -> ``Jāņa Bērziņa``), so a planted
name is located in every declined form :func:`eu_identities.name_forms` lists, as a whole word
(the way ``hu-inflection.jsonl`` labels Hungarian stem-changing forms): a given name followed by
a surname is one ``PERSON``, either alone is a ``PERSON`` too. Every other value (addresses,
organisations, numbers, e-mails, birth dates) must appear exactly as given, separators aside
(:func:`pii_guard.eval.forms.find_surface_forms`).

**Discards** (counted in the stats, never values): truncated or empty output, a required value
missing (a person counts as present in any declined form), an identifier the rules find outside
every planted value (an invented one), or a capitalised given name of the language's list that
is not part of a planted person (an invented person: without a teacher pass it would be taught
as ``O``).

**Teacher pass.** The output files are named ``<lang>-distill-{train,dev}.jsonl`` so
``training/distill/label.py`` runs on them unchanged once a Glimmer endpoint is up (it adopts
names Muse added and excludes disagreements from the loss)::

    set -a; source .env; set +a      # META_API_KEY (Meta Model API, contributor tier)
    uv run --no-sync python training/ner/eu_corpus.py --languages lv,lt,hr,sl --n 1200 \\
        --seed 1525 --out eval/generated/distill-eu-s1525 --budget-usd 3 --workers 16
    uv run --no-sync python training/ner/eu_corpus.py --languages fr,es,it,nl,ro,ga,mt \\
        --n 1200 --seed 1525 --out eval/generated/distill-eu-1b-s1525 --budget-usd 4.8 --workers 32

Writes ``<lang>-distill-{train,dev}.jsonl`` and ``stats.json`` (counts, discard reasons, token
usage, cost; never values). Split: 90 % train, 10 % dev, by a seeded shuffle of the indices.
"""

# Seeded synthetic data: the standard PRNG is the point.
# ruff: noqa: S311

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import threading
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eu_identities import LANGS, Identities, Lang, Planted, name_forms

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
#: USD per million tokens, Meta Model API contributor tier (as training/distill/corpus.py).
PRICE_PER_M = {"prompt": 0.10, "completion": 0.20}
NO_VALUES = "(none: this document contains no personal data at all)"


@dataclass(frozen=True, slots=True)
class Party:
    label: str
    kind: str  # person, company, property, court, office
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Kind:
    id: str
    title: str
    brief: str
    register: str
    length: str
    weight: int
    parties: tuple[Party, ...]
    typos: bool = False


def _p(label: str, kind: str, *fields: str) -> Party:
    return Party(label, kind, fields)


#: Document kinds. ``{country}`` is the language's country adjective-free placeholder: the
#: writing model is told the language, and the values carry the local formats.
KINDS: tuple[Kind, ...] = (
    Kind(
        "sale-contract",
        "Agreement for the sale of a used car",
        "A private sale agreement for a used car between a seller and a buyer: the parties' "
        "details, the vehicle with its registration plate, the price in euros, payment by bank "
        "transfer to the seller's account, the condition clause and signature lines with dates.",
        "formal legal",
        "250-400",
        2,
        (
            _p(
                "Seller",
                "person",
                "name",
                "date_of_birth",
                "address",
                "id_document",
                "bank_account",
                "plate",
            ),
            _p("Buyer", "person", "name", "address", "id_document"),
        ),
    ),
    Kind(
        "lease",
        "Residential lease agreement",
        "A residential lease between a company landlord and a private tenant: the parties, the "
        "flat, the term, monthly rent paid to the landlord's account, the deposit, the tenant's "
        "obligations and signature lines. The landlord's manager signs for the company.",
        "formal legal",
        "300-450",
        2,
        (
            _p("Landlord", "company", "org_name", "address", "bank_account"),
            _p("the landlord's manager", "person", "name"),
            _p("Tenant", "person", "name", "date_of_birth", "phone", "email"),
            _p("the flat", "property", "address"),
        ),
    ),
    Kind(
        "power-of-attorney",
        "Power of attorney",
        "A power of attorney under which a principal authorises an attorney to deal with their "
        "bank and with the tax office on their behalf: both parties' details, the scope, the "
        "duration, and the signature block (any witness only by role).",
        "formal legal",
        "180-300",
        1,
        (
            _p(
                "Principal",
                "person",
                "name",
                "date_of_birth",
                "address",
                "id_document",
                "bank_account",
            ),
            _p("Attorney", "person", "name", "address"),
        ),
    ),
    Kind(
        "court-notice",
        "Summons to a hearing in a civil case",
        "A court summons for a hearing in a small civil claim: case number, date, time and "
        "room, addressed to the defendant, naming the claimant, what to bring, what happens if "
        "the defendant does not attend, and the court's contact details.",
        "formal official",
        "180-300",
        1,
        (
            _p("the court", "court", "org_name", "address", "phone"),
            _p("Defendant (the addressee)", "person", "name", "address"),
            _p("Claimant", "person", "name"),
        ),
    ),
    Kind(
        "court-judgment",
        "Reasons of a first-instance civil judgment (excerpt)",
        "An excerpt from the reasons of a first-instance civil judgment about an unpaid loan "
        "between two private persons: the facts, each party's arguments, the evidence and the "
        "court's assessment. After the first mention, refer to the parties mostly by surname "
        "alone (as courts do), in whatever grammatical case each sentence needs, and sometimes "
        "by procedural role.",
        "formal judicial",
        "300-450",
        2,
        (
            _p("the court", "court", "org_name"),
            _p("Claimant", "person", "name", "address"),
            _p("Defendant", "person", "name", "address", "date_of_birth"),
        ),
    ),
    Kind(
        "invoice",
        "Invoice",
        "A plain-text invoice from a small business to a private customer: supplier block, "
        "customer block, invoice number and dates, three or four line items with amounts in "
        "euros and VAT, the total and payment details with the supplier's account.",
        "business, terse",
        "120-220",
        1,
        (
            _p("Supplier", "company", "org_name", "address", "bank_account", "email"),
            _p("Customer", "person", "name", "address"),
        ),
    ),
    Kind(
        "email",
        "E-mail between colleagues",
        "An informal work e-mail from one colleague to another about rescheduling a client "
        "meeting and a shared document, addressing the recipient by given name (in the "
        "vocative where the language has one) and mentioning a third colleague by name in a "
        "declined form. Signed with the sender's name and phone.",
        "informal, friendly",
        "100-200",
        2,
        (
            _p("Sender", "person", "name", "phone", "email"),
            _p("Recipient", "person", "name"),
            _p("Third colleague", "person", "name"),
        ),
        True,
    ),
    Kind(
        "employment-certificate",
        "Employment certificate",
        "A certificate from an employer confirming that an employee has worked there since a "
        "given date in a given position, with a monthly salary, issued at the employee's "
        "request for a bank, signed by the HR manager.",
        "formal administrative",
        "120-220",
        1,
        (
            _p("Employer", "company", "org_name", "address"),
            _p("Employee", "person", "name", "date_of_birth", "id_document"),
            _p("HR manager", "person", "name"),
        ),
    ),
    Kind(
        "bank-complaint",
        "Complaint to a bank",
        "A customer's written complaint to their bank about a card payment charged twice: the "
        "customer's details and account, the dates and amounts, what they want, and how to "
        "reach them.",
        "polite, semi-formal",
        "150-250",
        1,
        (
            _p("Customer", "person", "name", "address", "phone", "bank_account"),
            _p("the bank", "company", "org_name"),
        ),
        True,
    ),
    Kind(
        "support-chat",
        "Customer support chat transcript",
        "A support chat between a customer and a support agent of an internet provider about a "
        "broken router: the customer confirms their identity, the agent books a technician "
        "visit. Speaker names before each line; the agent addresses the customer by name, in "
        "declined forms where natural.",
        "conversational",
        "150-260",
        1,
        (
            _p("Customer", "person", "name", "email", "phone", "address"),
            _p("Agent", "person", "name"),
            _p("the provider", "company", "org_name"),
        ),
        True,
    ),
    Kind(
        "meeting-minutes",
        "Minutes of a residents' association meeting",
        "Minutes of a meeting of a block of flats' residents' association: those present, the "
        "agenda, who said what (names in declined forms as the sentences need), the decisions "
        "and the management company that will carry out the repairs.",
        "neutral, minutes style",
        "200-320",
        1,
        (
            _p("Chair", "person", "name"),
            _p("Resident", "person", "name"),
            _p("Resident", "person", "name"),
            _p("Management company", "company", "org_name", "phone"),
            _p("the building", "property", "address"),
        ),
    ),
    Kind(
        "negative-prose",
        "Text without personal data",
        "A short everyday text without any personal data at all: no names of people, no "
        "companies, no addresses, no contact details, no identifiers.",
        "neutral",
        "100-200",
        2,
        (),
    ),
)

NEGATIVE_TOPICS = (
    "a train timetable change", "a weather forecast", "a recipe", "a football match report",
    "a software release note", "a library's opening hours", "a hiking trail description",
    "a school trip plan", "a museum exhibition", "a car maintenance checklist",
    "a city's recycling rules", "a gardening tip", "a board game's rules",
    "a concert programme", "a product's user manual", "a historical event",
)  # fmt: skip

_TYPOS = (
    " Make it feel real: a few typos, missing diacritics or casual abbreviations in the "
    "surrounding text (never inside the values)."
)


@dataclass(frozen=True, slots=True)
class Plan:
    doc_id: str
    language: str
    index: int
    kind: str
    values: tuple[Planted, ...]
    messages: tuple[dict[str, str], ...]


def plan_document(lang: Lang, seed: int, index: int) -> Plan:
    rng = random.Random(f"pii-guard-eu-corpus/{CORPUS_VERSION}/{seed}/{lang.code}/{index}")
    kind = rng.choices(KINDS, weights=[k.weight for k in KINDS])[0]
    ids = Identities(lang, rng)
    values: list[Planted] = []
    blocks: list[str] = []
    for party in kind.parties:
        party_values = ids.make(party.kind, list(party.fields))
        lines = [f"{party.label}:"]
        for v in party_values:
            if v.required:
                label = lang.id_label if v.field == "id_document" else v.field.replace("_", " ")
                lines.append(f"- {label}: {v.text}")
        blocks.append("\n".join(lines))
        values.extend(party_values)
    system = (
        _template_text("system.md")
        .replace("{language_name}", lang.name)
        .replace("{inflection_rule}", lang.inflection_rule)
    )
    user = (
        _template_text("user.md")
        .replace("{title}", kind.title)
        .replace("{brief}", kind.brief)
        .replace("{register}", kind.register)
        .replace("{length}", kind.length)
        .replace("{typos}", _TYPOS if kind.typos else "")
        .replace("{hard_negatives}", "")
        .replace("{values}", "\n\n".join(blocks) if blocks else NO_VALUES)
    )
    if not kind.parties:
        user += (
            f"\n\nSubject: {rng.choice(NEGATIVE_TOPICS)}. "
            f"Variant {rng.randrange(10**6)}: make it distinct from others."
        )
    return Plan(
        doc_id=f"{lang.code}-eu-s{seed}-{index:05d}",
        language=lang.code,
        index=index,
        kind=kind.id,
        values=tuple(values),
        messages=(
            {"role": "system", "content": system.strip()},
            {"role": "user", "content": user.strip()},
        ),
    )


# --- Gold -------------------------------------------------------------------------------------

_W = r"[^\W\d_]"  # a letter


def _alt(forms: set[str]) -> str:
    return "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True))


def person_pattern(language: str, value: Planted) -> re.Pattern[str]:
    """Full name, surname alone or given name alone, each in any listed declined form."""
    given = name_forms(language, value.given, value.gender)
    family = name_forms(language, value.family, value.gender, is_family=True)
    g, f = _alt(given), _alt(family)
    return re.compile(rf"(?<!{_W})(?:(?:{g})\s+(?:{f})|(?:{f})\s+(?:{g})|{f}|{g})(?!{_W})")


def locate(text: str, plan: Plan) -> tuple[list[GoldSpan], list[Planted]]:
    candidates: list[tuple[int, int, EntityType, bool]] = []
    missing: list[Planted] = []
    for value in plan.values:
        if value.entity_type is EntityType.PERSON and value.given:
            hits = [m.span() for m in person_pattern(plan.language, value).finditer(text)]
            full = [(s, e) for s, e in hits if " " in text[s:e].strip() or "\n" in text[s:e]]
            if not full:
                missing.append(value)
        else:
            hits = find_surface_forms(text, value.text, value.entity_type, plan.language)
            if value.field == "short_name":
                hits = [(s, e) for s, e in hits if text[s].isupper()]
            if value.required and not hits:
                missing.append(value)
        candidates.extend((s, e, value.entity_type, value.required) for s, e in hits)
    candidates.sort(key=lambda c: (-(c[1] - c[0]), not c[3], c[0]))
    taken: list[tuple[int, int, EntityType]] = []
    for start, end, etype, _ in candidates:
        if any(start < te and ts < end for ts, te, _ in taken):
            continue
        taken.append((start, end, etype))
    taken.sort()
    return [GoldSpan(s, e, t, text[s:e]) for s, e, t in taken], missing


def _given_name_pattern(lang: Lang) -> re.Pattern[str]:
    forms: set[str] = set()
    for g in (*lang.given_m, *lang.given_f):
        if len(g) >= 4:
            forms |= {f for f in name_forms(lang.code, g, "m") if len(f) >= 4}
    return re.compile(rf"(?<!{_W})(?:{_alt(forms)})(?!{_W})")


_GIVEN_RES: dict[str, re.Pattern[str]] = {}


def invented_people(text: str, spans: Sequence[GoldSpan], lang: Lang) -> int:
    """Capitalised given names of the language's list outside every gold span."""
    pattern = _GIVEN_RES.setdefault(lang.code, _given_name_pattern(lang))
    return sum(
        1
        for m in pattern.finditer(text)
        if not any(m.start() < s.end and s.start < m.end() for s in spans)
    )


# --- One document -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Outcome:
    plan: Plan
    document: Document | None
    reason: str | None = None
    completion: Completion | None = None


def generate(
    plan: Plan, client: ChatClient, cache: ResponseCache, budget: Budget, split: str
) -> Outcome:
    payload = client.payload(plan.messages)
    key = ResponseCache.key(payload)
    completion = cache.get(key)
    if completion is None:
        if not budget.allow():
            return Outcome(plan, None, "budget")
        try:
            completion = client.complete(plan.messages)
        except ModelError as exc:
            if not exc.retryable:
                raise
            return Outcome(plan, None, "model_error")
        budget.spend(completion)
        cache.put(key, completion)
    if completion.finish_reason == "length":
        return Outcome(plan, None, "truncated", completion)
    text = clean_output(completion.content)
    if not text:
        return Outcome(plan, None, "empty_output", completion)
    spans, missing = locate(text, plan)
    if missing:
        return Outcome(plan, None, "missing_value", completion)
    try:
        invented = unsupplied_types(text, spans, plan.language)
    except Exception:
        invented = []
    if invented:
        return Outcome(plan, None, "unsupplied_value", completion)
    if invented_people(text, spans, LANGS[plan.language]):
        return Outcome(plan, None, "invented_person", completion)
    meta: dict[str, Any] = {
        "kind": plan.kind,
        "source": "synthetic",
        "generator": f"training/ner/eu_corpus.py/{CORPUS_VERSION}",
        "seed": int(plan.doc_id.split("-s")[1].split("-")[0]),
        "index": plan.index,
        "model": completion.model or client.model,
        "prompt_sha256": key[:16],
        "gold": "planted values; names in declined forms (eu_identities.name_forms)",
        "split": split,
    }
    return Outcome(
        plan, Document(plan.doc_id, plan.language, text, tuple(spans), meta), None, completion
    )


class Budget:
    def __init__(self, usd: float) -> None:
        self.usd = usd
        self.spent = 0.0
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


def splits(n: int, seed: int, language: str) -> list[str]:
    order = list(range(n))
    random.Random(f"pii-guard-eu-corpus-split/{seed}/{language}").shuffle(order)
    dev = set(order[: max(1, n // 10)])
    return ["dev" if i in dev else "train" for i in range(n)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--languages", default="lv,lt,hr,sl")
    parser.add_argument("--n", type=int, default=1200, help="planned documents per language")
    parser.add_argument("--seed", type=int, default=1525)
    parser.add_argument("--out", type=Path, default=Path("eval/generated/distill-eu-s1525"))
    parser.add_argument("--cache", type=Path, default=Path("eval/generated/cache"))
    parser.add_argument("--budget-usd", type=float, required=True)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument(
        "--base-url", default=os.environ.get("PII_GUARD_CORPUS_URL", DEFAULT_BASE_URL)
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--dry-run", action="store_true", help="print one plan's prompt, no calls")
    args = parser.parse_args(argv)
    languages = args.languages.split(",")
    if args.dry_run:
        plan = plan_document(LANGS[languages[0]], args.seed, 0)
        for m in plan.messages:
            print(f"--- {m['role']}\n{m['content']}")
        return 0
    key = os.environ.get("PII_GUARD_CORPUS_API_KEY") or os.environ.get("META_API_KEY")
    client = ChatClient(
        base_url=args.base_url, api_key=key, model=args.model, reasoning_effort="low"
    )
    cache = ResponseCache(args.cache)
    budget = Budget(args.budget_usd)
    args.out.mkdir(parents=True, exist_ok=True)
    stats: dict[str, Any] = {
        "corpus_version": CORPUS_VERSION, "seed": args.seed, "model": args.model,
        "planned_per_language": args.n, "languages": {},
    }  # fmt: skip
    for code in languages:
        lang = LANGS[code]
        split_of = splits(args.n, args.seed, code)
        plans = [plan_document(lang, args.seed, i) for i in range(args.n)]
        with ThreadPoolExecutor(args.workers) as pool:
            outcomes = list(
                pool.map(
                    lambda p, s=split_of: generate(p, client, cache, budget, s[p.index]), plans
                )
            )
        reasons = Counter(o.reason for o in outcomes if o.reason)
        docs = [o.document for o in outcomes if o.document is not None]
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
            f"eu-corpus: {code}: {len(docs)} accepted, discarded {dict(reasons)}", file=sys.stderr
        )
    stats["tokens_uncached"] = dict(budget.tokens)
    stats["cost_usd_uncached"] = round(budget.spent, 4)
    (args.out / "stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(f"eu-corpus: uncached cost ${budget.spent:.3f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
