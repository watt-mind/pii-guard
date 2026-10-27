"""Distillation corpus: the generator's documents plus extra genres, under a hard cost cap.

Fictional data only (ADR 0005). Every document is planned deterministically from
``(seed, language, index)`` like ``pii-guard eval generate`` does, but from a wider set of
document kinds: the generator's own templates (``src/pii_guard/eval/templates/<lang>.toml``)
plus ``training/distill/templates/<lang>.toml`` (tool output, forms, logs, CSV, support chat,
SMS, meeting notes, messages full of look-alike words, and hard negatives without any personal
data). Writing, labelling of the planted values and the discard rules are the generator's
(:func:`pii_guard.eval.generate.generate_document`), and model outputs go through its response
cache, so a rerun with the same seed reproduces the corpus byte for byte without model calls.

::

    uv run python training/distill/corpus.py --language hu --n 2500 --seed 11 \\
        --out eval/generated/distill-s11 --budget-usd 1.5 --workers 24

Writes ``<lang>-distill-{train,dev}.jsonl`` and ``<lang>-distill-stats.json`` (counts, discard
reasons, token usage and cost: never values). The cost cap counts uncached calls only; once it
is reached the remaining documents are skipped (reason ``budget``), not sent.
"""

# Seeded, reproducible synthetic data: the standard PRNG is the point, not a weakness.
# ruff: noqa: S311

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import random
import sys
import threading
import tomllib
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any

from pii_guard.eval.fixtures import write_fixtures
from pii_guard.eval.generate import (
    DEFAULT_BASE_URL,
    ChatClient,
    Completion,
    CorpusResult,
    DocumentPlan,
    DocumentTemplate,
    LanguagePack,
    Outcome,
    PartySpec,
    ResponseCache,
    assign_splits,
    generate_document,
    load_language,
)
from pii_guard.eval.identities import Value, identity_generator

TEMPLATES = Path(__file__).resolve().parent / "templates"
CORPUS_VERSION = 1
DEFAULT_MODEL = "muse-spark-1.3-contributor"
#: USD per million tokens, Meta Model API contributor tier (dev.meta.ai pricing, 2026-10-27).
PRICE_PER_M = {"prompt": 0.10, "completion": 0.20}
NO_VALUES = "(none: this document contains no personal data at all)"
#: Subject hints for kinds without planted values. Without them every such document of a kind
#: would get the same prompt, hence the same cache key and the same text.
NEGATIVE_TOPICS = (
    "a software release",
    "a weather report",
    "a recipe",
    "a train timetable change",
    "a football match",
    "a museum exhibition",
    "a database migration",
    "a library opening hours",
    "a city park renovation",
    "a product review",
    "a server outage",
    "a school curriculum",
    "a cooking class",
    "a tax rule explained in general terms",
    "a hiking trail",
    "a board game",
    "a car maintenance checklist",
    "a gardening tip",
    "a concert programme",
    "a network config",
    "a historical event",
    "a science article",
    "a budget spreadsheet summary",
    "a style guide",
)


def _kinds(raw: dict[str, Any]) -> tuple[DocumentTemplate, ...]:
    return tuple(
        DocumentTemplate(
            id=k["id"],
            title=k["title"],
            brief=k["brief"],
            register=k["register"],
            length=k["length"],
            weight=float(k.get("weight", 1)),
            typos=bool(k.get("typos", False)),
            parties=tuple(
                PartySpec(
                    role=p["role"],
                    label=p["label"],
                    kind=p["kind"],
                    fields=tuple(p["fields"]),
                    informal=bool(p.get("informal", False)),
                )
                for p in k.get("parties", [])
            ),
        )
        for k in raw["kinds"]
    )


@cache
def language_pack(language: str, extra: bool = True) -> LanguagePack:
    """The generator's pack for ``language`` with the distillation kinds appended."""
    pack = load_language(language)
    if not extra:
        return pack
    raw = tomllib.loads((TEMPLATES / f"{pack.language}.toml").read_text(encoding="utf-8"))
    added = _kinds(raw)
    clash = {k.id for k in added} & {k.id for k in pack.kinds}
    if clash:
        raise ValueError(f"distill templates redefine generator kinds: {sorted(clash)}")
    return dataclasses.replace(pack, kinds=pack.kinds + added)


def _prompt(name: str) -> str:
    return files("pii_guard.eval").joinpath("templates", name).read_text(encoding="utf-8")


def plan(language: str, seed: int, index: int, pack: LanguagePack | None = None) -> DocumentPlan:
    """Kind, fictional identities and prompt for document ``index`` (deterministic)."""
    pack = pack or language_pack(language)
    rng = random.Random(f"pii-guard-distill/{CORPUS_VERSION}/{seed}/{pack.language}/{index}")
    template = rng.choices(pack.kinds, weights=[k.weight for k in pack.kinds])[0]
    identities = identity_generator(pack.language, rng)
    values: list[Value] = []
    blocks: list[str] = []
    for party in template.parties:
        record = identities.make(party.kind)
        party_values = record.values(party.fields)
        lines = [f"{party.label}:"]
        for value in party_values:
            if value.required:
                lines.append(f"- {pack.field_labels.get(value.field, value.field)}: {value.text}")
            elif party.informal and value.field == "given":
                lines.append(f"- {pack.field_labels.get('given', 'given name')}: {value.text}")
        blocks.append("\n".join(lines))
        values.extend(party_values)
    system = (
        _prompt("system.md")
        .replace("{language_name}", pack.language_name)
        .replace("{inflection_rule}", pack.inflection_rule)
    )
    user = (
        _prompt("user.md")
        .replace("{title}", template.title)
        .replace("{brief}", template.brief)
        .replace("{register}", template.register)
        .replace("{length}", template.length)
        .replace("{typos}", pack.typos if template.typos else "")
        .replace("{values}", "\n\n".join(blocks) if blocks else NO_VALUES)
    )
    if not blocks:
        topic = rng.choice(NEGATIVE_TOPICS)
        user += (
            f"\n\nSubject: {topic}. Variant {rng.randrange(10**6)}: make it distinct from others."
        )
    return DocumentPlan(
        doc_id=f"{pack.language}-distill-s{seed}-{index:05d}",
        language=pack.language,
        seed=seed,
        index=index,
        kind=template.id,
        values=tuple(values),
        messages=(
            {"role": "system", "content": system.strip()},
            {"role": "user", "content": user.strip()},
        ),
    )


def cost_usd(usage: dict[str, int]) -> float:
    return (
        usage.get("prompt_tokens", 0) * PRICE_PER_M["prompt"]
        + usage.get("completion_tokens", 0) * PRICE_PER_M["completion"]
    ) / 1e6


class Budget:
    """Thread-safe running cost of uncached calls; ``allow()`` is False once ``cap`` is hit."""

    def __init__(self, cap_usd: float) -> None:
        self.cap = cap_usd
        self.spent = 0.0
        self.calls = 0
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            return self.spent < self.cap

    def add(self, completion: Completion | None) -> None:
        if completion is None or completion.cached:
            return
        with self._lock:
            self.spent += cost_usd(dict(completion.usage))
            self.calls += 1


def build_corpus(
    language: str,
    n: int,
    seed: int,
    client: ChatClient,
    cache: ResponseCache | None,
    budget: Budget,
    *,
    split: tuple[float, float, float] = (0.85, 0.15, 0.0),
    workers: int = 1,
    progress: bool = False,
) -> CorpusResult:
    pack = language_pack(language)
    labels = assign_splits(n, seed, split)
    plans = [plan(pack.language, seed, i, pack) for i in range(n)]
    done = [0]
    lock = threading.Lock()

    def run(i: int) -> Outcome:
        payload_key = ResponseCache.key(client.payload(plans[i].messages))
        cached = cache is not None and cache.get(payload_key) is not None
        if not cached and not budget.allow():
            return Outcome(plans[i], None, "budget")
        outcome = generate_document(plans[i], client, cache, split=labels[i])
        budget.add(outcome.completion)
        with lock:
            done[0] += 1
            if progress and done[0] % 100 == 0:
                print(
                    f"{pack.language}: {done[0]}/{n} done, ${budget.spent:.3f} spent",
                    file=sys.stderr,
                    flush=True,
                )
        return outcome

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            outcomes = list(pool.map(run, range(n)))
    else:
        outcomes = [run(i) for i in range(n)]
    return CorpusResult(pack.language, seed, outcomes)


def write(result: CorpusResult, out: Path, budget: Budget, model: str) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    for name, docs in result.by_split().items():
        if docs:
            write_fixtures(out / f"{result.language}-distill-{name}.jsonl", docs)
    stats = result.stats()
    usage = stats["usage"]
    stats.update(
        corpus_version=CORPUS_VERSION,
        model=model,
        cost_usd_uncached=round(budget.spent, 4),
        cost_usd_all_calls=round(cost_usd(usage), 4),
        price_per_m=PRICE_PER_M,
    )
    path = out / f"{result.language}-distill-stats.json"
    path.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    return stats


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--language", required=True, help="hu or en")
    parser.add_argument("--n", type=int, required=True, help="documents to plan")
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument("--cache", type=Path, default=Path("eval/generated/cache"))
    parser.add_argument("--budget-usd", type=float, required=True, help="cap for uncached calls")
    parser.add_argument("--model", default=os.environ.get("PII_GUARD_CORPUS_MODEL", DEFAULT_MODEL))
    parser.add_argument("--base-url", default=os.environ.get("PII_GUARD_CORPUS_URL"))
    parser.add_argument("--reasoning-effort", default="minimal")
    parser.add_argument("--temperature", type=float, default=0.9)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--dry-run", type=int, metavar="INDEX", help="print one prompt and exit")
    args = parser.parse_args(argv)

    if args.dry_run is not None:
        for message in plan(args.language, args.seed, args.dry_run).messages:
            print(f"--- {message['role']}\n{message['content']}\n")
        return 0
    key = os.environ.get("PII_GUARD_CORPUS_API_KEY") or os.environ.get("META_API_KEY")
    client = ChatClient(
        base_url=args.base_url or DEFAULT_BASE_URL,
        api_key=key,
        model=args.model,
        reasoning_effort=None if args.reasoning_effort == "omit" else args.reasoning_effort,
        temperature=args.temperature,
        max_tokens=6144,
    )
    budget = Budget(args.budget_usd)
    try:
        result = build_corpus(
            args.language,
            args.n,
            args.seed,
            client,
            ResponseCache(args.cache),
            budget,
            workers=args.workers,
            progress=True,
        )
    finally:
        client.close()
    stats = write(result, args.out, budget, args.model)
    print(
        f"{stats['language']}: {stats['accepted']}/{stats['requested']} accepted, "
        f"discards {stats['discard_reasons']}, usage {stats['usage']}, "
        f"${stats['cost_usd_uncached']:.3f} this run",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
