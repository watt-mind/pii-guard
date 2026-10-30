"""Synthetic corpus generator: fictional identities + a Meta Muse model writing the documents.

For every document index the generator, deterministically from ``(seed, language, index)``:

1. picks a document template from the language pack's ``corpus_templates`` (ADR 0010;
   ``templates/<language>.toml`` for Hungarian and English: sale contract, lease, power of
   attorney, land registry extract, court notice, invoice, letter, informal e-mail, chat);
2. draws fictional identities for its parties (the pack's ``identity_generator``, see
   :mod:`pii_guard.eval.identities`: names and
   places sampled from the language pack's lexicons, :mod:`pii_guard.lang`) and a few
   **hard negatives**, ordinary phrases that look like personal data but aren't (a surname
   that is a common word, used as the word; a town outside an address; "Eladó lakás"), which
   the prompt asks for and which are never labelled;
3. asks a Muse model (any OpenAI-compatible Chat Completions endpoint; by default the Meta
   Model API) to write the document using exactly those values;
4. **locates every value** in the output, all occurrences and inflected forms
   (:func:`pii_guard.eval.find_surface_forms`), plus name parts used alone, and records the
   spans as gold labels;
5. **discards** the document if any required value can't be located, if the rule detector
   finds a structured identifier that wasn't supplied (the model invented one), or if the
   output is empty or truncated. Discards are counted by reason and entity type, never
   hand-fixed, and never logged with values.

Model outputs are cached on disk by a hash of the request (``--cache``), so a rerun with the
same seed reproduces the corpus byte for byte without calling the model. Only fictional data
is ever sent to the model (ADR 0005, ``docs/models.md``).

Command line (also ``python -m pii_guard.eval.generate``)::

    pii-guard eval generate --language hu --n 200 --seed 42 --out eval/generated/
    pii-guard eval generate --language en --n 10 --seed 1 --out eval/fixtures/en-synth.jsonl

A directory ``--out`` gets ``<lang>-synth-{train,dev,test}.jsonl`` (``--split 70/15/15``) and
``<lang>-synth-stats.json``; a ``.jsonl`` path gets every document in one file (the split is
still recorded in each record's ``meta``).

Endpoint configuration (flags override the environment):

- ``PII_GUARD_CORPUS_URL`` (default ``https://api.meta.ai/v1``),
- ``PII_GUARD_CORPUS_API_KEY`` (falls back to ``META_API_KEY``),
- ``PII_GUARD_CORPUS_MODEL`` (default ``muse-spark-1.3-contributor``: contributor-tier
  traffic may be used by Meta to improve its products, acceptable here only because every
  value sent is fictional).

Muse Spark Open on Baseten works the same way:
``--base-url https://inference.baseten.co/v1 --model meta-models/muse-spark-open-1026``.
"""

# Seeded, reproducible synthetic data: the standard PRNG is the point, not a weakness.
# ruff: noqa: S311

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import re
import statistics
import sys
import time
import tomllib
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any

import httpx

from pii_guard.eval.fixtures import Document, FixtureError, GoldSpan, parse_document, write_fixtures
from pii_guard.eval.forms import find_surface_forms
from pii_guard.eval.identities import Value, identity_generator
from pii_guard.lang import LexiconUnavailable, available_kinds, lexicon, lexicon_digest
from pii_guard.languages import get_pack, on_change
from pii_guard.types import EntityType

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "GENERATOR_VERSION",
    "UNSUPPLIED_CHECK_TYPES",
    "ChatClient",
    "Completion",
    "CorpusResult",
    "DocumentPlan",
    "DocumentTemplate",
    "GenerationError",
    "HardNegatives",
    "LanguagePack",
    "ModelError",
    "Outcome",
    "PartySpec",
    "ResponseCache",
    "assign_splits",
    "build_parser",
    "clean_output",
    "generate_corpus",
    "generate_document",
    "load_language",
    "locate_values",
    "main",
    "parse_split",
    "plan_document",
    "unsupplied_types",
]

logger = logging.getLogger(__name__)

#: Bumped whenever the same seed would plan different documents (2: names and places drawn from
#: the language-pack lexicons, hard negatives in the prompt; 3: given names unique per
#: document, a property's office or court in the property's town).
GENERATOR_VERSION = 3
DEFAULT_BASE_URL = "https://api.meta.ai/v1"
#: The corpus is entirely fictional, so it may use the contributor tier (cheaper; its traffic
#: may be used by Meta to improve its products). Never use this tier for real or masked data:
#: the detector and gateway defaults stay on non-contributor / open-weights models.
DEFAULT_MODEL = "muse-spark-1.3-contributor"
DEFAULT_REASONING_EFFORT = "low"
DEFAULT_CACHE = "eval/generated/cache"

#: Structured types the rule detector finds reliably (checksums, formats). A hit of one of
#: these that doesn't overlap a supplied value means the model invented an identifier.
UNSUPPLIED_CHECK_TYPES: frozenset[EntityType] = frozenset(
    {
        EntityType.EMAIL,
        EntityType.PHONE,
        EntityType.BANK_ACCOUNT,
        EntityType.PAYMENT_CARD,
        EntityType.NATIONAL_ID_HU_TAX,
        EntityType.NATIONAL_ID_HU_TAJ,
        EntityType.COMPANY_ID_HU,
        EntityType.VEHICLE_PLATE,
    }
)

_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class GenerationError(RuntimeError):
    """A configuration or endpoint problem that stops the whole run."""


class ModelError(GenerationError):
    """The model call failed. ``retryable`` failures discard one document; others abort."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


# --- Templates ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PartySpec:
    role: str
    label: str
    kind: str
    fields: tuple[str, ...]
    informal: bool = False


@dataclass(frozen=True, slots=True)
class DocumentTemplate:
    id: str
    title: str
    brief: str
    register: str
    length: str
    weight: float
    parties: tuple[PartySpec, ...]
    typos: bool = False


@dataclass(frozen=True, slots=True)
class HardNegatives:
    """Ordinary phrases a document must contain that look like personal data but aren't."""

    instruction: str
    phrases: tuple[str, ...] = ()
    settlement_phrases: tuple[str, ...] = ()

    def pick(self, rng: random.Random, language: str, values: Sequence[Value]) -> list[str]:
        """Up to three phrases for one document, none sharing a word with its values.

        A surname used as a common word (``common_word_surnames``), a settlement outside an
        address, and a capitalised phrase; kinds the language pack lacks are skipped.
        """
        used = {w.casefold() for v in values for w in re.findall(r"\w+", v.text)}

        def free(phrase: str) -> bool:
            return not any(w.casefold() in used for w in re.findall(r"\w+", phrase))

        picked: list[str] = []
        try:
            rows = [r for r in lexicon("common_word_surnames", language).rows if len(r) > 2]
            options = [r[2] for r in rows if free(r[2])]
            if options:
                picked.append(rng.choice(options))
        except LexiconUnavailable:
            pass
        if self.settlement_phrases:
            try:
                places = lexicon("settlements", language)
                for _ in range(20):
                    town = places.sample(rng, 0.5)
                    phrase = rng.choice(self.settlement_phrases).replace("{settlement}", town)
                    if free(phrase):
                        picked.append(phrase)
                        break
            except LexiconUnavailable:
                pass
        options = [p for p in self.phrases if free(p)]
        if options and rng.random() < 0.6:
            picked.append(rng.choice(options))
        return picked


@dataclass(frozen=True, slots=True)
class LanguagePack:
    language: str
    language_name: str
    inflection_rule: str
    typos: str
    field_labels: Mapping[str, str]
    kinds: tuple[DocumentTemplate, ...]
    hard_negatives: HardNegatives | None = None

    def kind(self, kind_id: str) -> DocumentTemplate:
        for template in self.kinds:
            if template.id == kind_id:
                return template
        raise KeyError(kind_id)


def _template_text(name: str) -> str:
    return files("pii_guard.eval").joinpath("templates", name).read_text(encoding="utf-8")


def _corpus_templates(language: str) -> str:
    """The TOML text of ``language``'s pack's ``corpus_templates`` (ADR 0010)."""
    pack = get_pack(language)
    if pack is None or pack.corpus_templates is None or pack.identity_generator is None:
        raise GenerationError(
            f"no document templates for language {language!r}: its language pack has no "
            "corpus_templates and identity_generator (the language is measured on its smoke "
            "set only)"
        )
    try:
        return pack.corpus_templates.read_text(encoding="utf-8")
    except OSError as exc:
        raise GenerationError(
            f"document templates for {language!r} are unreadable: {type(exc).__name__}"
        ) from exc


@cache
def load_language(language: str) -> LanguagePack:
    """Parse the document templates of ``language``'s pack (``"en-GB"`` -> the ``en`` pack)."""
    raw = tomllib.loads(_corpus_templates(language))
    kinds = tuple(
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
                for p in k["parties"]
            ),
        )
        for k in raw["kinds"]
    )
    if not kinds:
        raise GenerationError(f"templates for {language!r} define no document kinds")
    return LanguagePack(
        language=raw["language"],
        language_name=raw["language_name"],
        inflection_rule=" ".join(raw["inflection_rule"].split()),
        typos=raw.get("typos", ""),
        field_labels=dict(raw["field_labels"]),
        kinds=kinds,
        hard_negatives=_hard_negatives(raw.get("hard_negatives")),
    )


on_change(load_language.cache_clear)


def _hard_negatives(raw: Mapping[str, Any] | None) -> HardNegatives | None:
    if not raw:
        return None
    return HardNegatives(
        instruction=" ".join(raw["instruction"].split()),
        phrases=tuple(raw.get("phrases", ())),
        settlement_phrases=tuple(raw.get("settlement_phrases", ())),
    )


# --- Planning (deterministic) ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DocumentPlan:
    """Everything decided before the model call: deterministic given seed and index."""

    doc_id: str
    language: str
    seed: int
    index: int
    kind: str
    values: tuple[Value, ...]
    messages: tuple[Mapping[str, str], ...]
    #: Ordinary phrases the prompt asks for that are *not* personal data (never labelled).
    hard_negatives: tuple[str, ...] = ()

    def __repr__(self) -> str:
        return (
            f"DocumentPlan(doc_id={self.doc_id!r}, kind={self.kind!r}, values={len(self.values)})"
        )

    @property
    def required(self) -> tuple[Value, ...]:
        return tuple(v for v in self.values if v.required)


def _doc_rng(seed: int, language: str, index: int) -> random.Random:
    # A string seed is hashed (SHA-512) by random.Random: stable across runs and platforms.
    return random.Random(f"pii-guard-corpus/{GENERATOR_VERSION}/{seed}/{language}/{index}")


def plan_document(language: str, seed: int, index: int, kind: str | None = None) -> DocumentPlan:
    """Pick a template and fictional identities for document ``index`` and build the prompt."""
    pack = load_language(language)
    rng = _doc_rng(seed, pack.language, index)
    if kind is None:
        template = rng.choices(pack.kinds, weights=[k.weight for k in pack.kinds])[0]
    else:
        template = pack.kind(kind)
    identities = identity_generator(pack.language, rng)
    identities.distinct_given_names = True
    kinds = {party.kind for party in template.parties}
    if "property" in kinds and kinds & {"court", "office"}:
        # The land registry office (or court) handling a property sits in its own town.
        identities.local_town = rng.randrange(identities.town_count)

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

    hard = pack.hard_negatives
    negatives = hard.pick(rng, pack.language, values) if hard else []
    negatives_text = ""
    if hard and negatives:
        quoted = ", ".join(f'"{p}"' for p in negatives)
        negatives_text = f" {hard.instruction} {quoted}."

    system = (
        _template_text("system.md")
        .replace("{language_name}", pack.language_name)
        .replace("{inflection_rule}", pack.inflection_rule)
    )
    user = (
        _template_text("user.md")
        .replace("{title}", template.title)
        .replace("{brief}", template.brief)
        .replace("{register}", template.register)
        .replace("{length}", template.length)
        .replace("{typos}", pack.typos if template.typos else "")
        .replace("{hard_negatives}", negatives_text)
        .replace("{values}", "\n\n".join(blocks))
    )
    return DocumentPlan(
        doc_id=f"{pack.language}-synth-s{seed}-{index:05d}",
        language=pack.language,
        seed=seed,
        index=index,
        kind=template.id,
        values=tuple(values),
        messages=(
            {"role": "system", "content": system.strip()},
            {"role": "user", "content": user.strip()},
        ),
        hard_negatives=tuple(negatives),
    )


# --- Model client ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Completion:
    content: str
    finish_reason: str | None
    usage: Mapping[str, int]
    latency_s: float
    model: str
    cached: bool = False

    def __repr__(self) -> str:  # never the content
        return (
            f"Completion(model={self.model!r}, chars={len(self.content)}, "
            f"finish_reason={self.finish_reason!r}, cached={self.cached})"
        )

    def to_cache(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "finish_reason": self.finish_reason,
            "usage": dict(self.usage),
            "latency_s": self.latency_s,
            "model": self.model,
        }


def _usage(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    out = {
        k: int(raw[k])
        for k in ("prompt_tokens", "completion_tokens", "total_tokens")
        if isinstance(raw.get(k), int)
    }
    details = raw.get("completion_tokens_details")
    if isinstance(details, dict) and isinstance(details.get("reasoning_tokens"), int):
        out["reasoning_tokens"] = int(details["reasoning_tokens"])
    return out


class ChatClient:
    """Minimal OpenAI-compatible Chat Completions client for document generation.

    ``base_url`` is the API root (``.../v1``) or the full ``.../chat/completions`` URL.
    ``reasoning_effort`` is sent when set (Muse Spark always reasons and rejects ``"none"``).
    ``transport`` is an ``httpx.BaseTransport`` (tests use ``httpx.MockTransport``).
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        reasoning_effort: str | None = DEFAULT_REASONING_EFFORT,
        temperature: float | None = 0.8,
        max_tokens: int | None = 8192,
        timeout: float = 180.0,
        max_retries: int = 2,
        backoff_s: float = 2.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if reasoning_effort == "none":
            raise ValueError("Muse models always reason; use 'minimal' or 'low', not 'none'")
        url = base_url.rstrip("/")
        self.url = url if url.endswith("/chat/completions") else url + "/chat/completions"
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self._sleep = sleep
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout), headers=headers, transport=transport
        )

    def __repr__(self) -> str:  # never the key
        return f"ChatClient(url={self.url!r}, model={self.model!r})"

    def close(self) -> None:
        self._client.close()

    def payload(self, messages: Sequence[Mapping[str, str]]) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.model, "messages": [dict(m) for m in messages]}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.max_tokens is not None:
            body["max_tokens"] = self.max_tokens
        if self.reasoning_effort is not None:
            body["reasoning_effort"] = self.reasoning_effort
        return body

    def complete(self, messages: Sequence[Mapping[str, str]]) -> Completion:
        body = self.payload(messages)
        last = "no attempt"
        for attempt in range(self.max_retries + 1):
            if attempt:
                self._sleep(self.backoff_s * 2 ** (attempt - 1))
            started = time.monotonic()
            try:
                response = self._client.post(self.url, json=body)
            except httpx.TimeoutException:
                last = "timeout"
                continue
            except httpx.HTTPError as exc:
                last = f"transport error ({type(exc).__name__})"
                continue
            latency = time.monotonic() - started
            if response.status_code in _RETRYABLE_STATUS:
                last = f"HTTP {response.status_code}"
                continue
            if response.status_code >= 400:
                raise ModelError(
                    f"model endpoint returned HTTP {response.status_code}", retryable=False
                )
            try:
                data = response.json()
                choice = data["choices"][0]
                content = choice["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError):
                last = "malformed response"
                continue
            if not isinstance(content, str):
                last = "malformed response"
                continue
            return Completion(
                content=content,
                finish_reason=choice.get("finish_reason"),
                usage=_usage(data.get("usage")),
                latency_s=round(latency, 3),
                model=str(data.get("model") or self.model),
            )
        raise ModelError(
            f"model call failed after {self.max_retries + 1} attempts: {last}", retryable=True
        )


class ResponseCache:
    """Raw model outputs on disk, one JSON file per request hash."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    @staticmethod
    def key(payload: Mapping[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.directory / key[:2] / f"{key}.json"

    def get(self, key: str) -> Completion | None:
        path = self._path(key)
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Completion(
            content=raw["content"],
            finish_reason=raw.get("finish_reason"),
            usage=raw.get("usage", {}),
            latency_s=float(raw.get("latency_s", 0.0)),
            model=raw.get("model", ""),
            cached=True,
        )

    def put(self, key: str, completion: Completion) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(completion.to_cache(), ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


# --- Labelling ---------------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```[\w-]*\s*\n(.*?)\n```\s*$", re.DOTALL)
_THINK_RE = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.DOTALL | re.IGNORECASE)


def clean_output(content: str) -> str:
    """Drop reasoning blocks and a wrapping code fence; normalise line endings."""
    text = _THINK_RE.sub("", content).replace("\r\n", "\n").strip()
    fenced = _FENCE_RE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    return text


def locate_values(
    text: str, values: Sequence[Value], language: str
) -> tuple[list[GoldSpan], list[Value]]:
    """Gold spans for every occurrence of every value, and the required values not found.

    Overlapping matches are resolved longest first (a full name beats the given name inside
    it), required values before optional ones, then by position.
    """
    candidates: list[tuple[int, int, Value]] = []
    missing: list[Value] = []
    for value in values:
        hits = find_surface_forms(text, value.text, value.entity_type, language)
        if value.capitalized:
            hits = [(s, e) for s, e in hits if text[s].isupper()]
        if value.required and not hits:
            missing.append(value)
        candidates.extend((s, e, value) for s, e in hits)
    candidates.sort(key=lambda c: (-(c[1] - c[0]), not c[2].required, c[0]))
    taken: list[tuple[int, int, Value]] = []
    for start, end, value in candidates:
        if any(start < t_end and t_start < end for t_start, t_end, _ in taken):
            continue
        taken.append((start, end, value))
    taken.sort(key=lambda c: c[0])
    spans = [GoldSpan(s, e, v.entity_type, text[s:e]) for s, e, v in taken]
    return spans, missing


@cache
def _lexicon_digest(language: str) -> str:
    """Which lexicon contents planned this corpus (empty for a language without a pack)."""
    return lexicon_digest(language) if available_kinds(language) else ""


@cache
def _rules() -> Any:
    from pii_guard.detect.rules import RuleDetector

    return RuleDetector()


def unsupplied_types(text: str, spans: Sequence[GoldSpan], language: str) -> list[EntityType]:
    """Types of structured identifiers in ``text`` that overlap no gold span (invented)."""
    found: list[EntityType] = []
    for hit in _rules().detect(text, language=language):
        if hit.entity_type not in UNSUPPLIED_CHECK_TYPES:
            continue
        if not any(hit.start < s.end and s.start < hit.end for s in spans):
            found.append(hit.entity_type)
    return found


# --- One document ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Outcome:
    """The result for one planned document: a document, or why it was discarded."""

    plan: DocumentPlan
    document: Document | None
    reason: str | None = None
    missing: tuple[EntityType, ...] = ()
    unsupplied: tuple[EntityType, ...] = ()
    completion: Completion | None = None

    @property
    def accepted(self) -> bool:
        return self.document is not None


def generate_document(
    plan: DocumentPlan,
    client: ChatClient,
    cache: ResponseCache | None = None,
    *,
    split: str | None = None,
) -> Outcome:
    """Call the model (or the cache) for ``plan`` and label or discard the result."""
    payload = client.payload(plan.messages)
    key = ResponseCache.key(payload)
    completion = cache.get(key) if cache is not None else None
    if completion is None:
        try:
            completion = client.complete(plan.messages)
        except ModelError as exc:
            if not exc.retryable:
                raise
            logger.warning("corpus: %s discarded: %s", plan.doc_id, exc)
            return Outcome(plan, None, "model_error")
        if cache is not None:
            cache.put(key, completion)

    if completion.finish_reason == "length":
        return Outcome(plan, None, "truncated", completion=completion)
    text = clean_output(completion.content)
    if not text:
        return Outcome(plan, None, "empty_output", completion=completion)

    spans, missing = locate_values(text, plan.values, plan.language)
    if missing:
        return Outcome(
            plan,
            None,
            "missing_value",
            missing=tuple(v.entity_type for v in missing),
            completion=completion,
        )
    invented = unsupplied_types(text, spans, plan.language)
    if invented:
        return Outcome(
            plan, None, "unsupplied_value", unsupplied=tuple(invented), completion=completion
        )

    meta: dict[str, Any] = {
        "kind": plan.kind,
        "source": "synthetic",
        "generator": f"pii_guard.eval.generate/{GENERATOR_VERSION}",
        "seed": plan.seed,
        "index": plan.index,
        "model": completion.model or client.model,
        "prompt_sha256": key[:16],
        "lexicons": _lexicon_digest(plan.language),
    }
    if plan.hard_negatives:
        meta["hard_negatives"] = list(plan.hard_negatives)
    if split:
        meta["split"] = split
    record = {
        "id": plan.doc_id,
        "language": plan.language,
        "text": text,
        "spans": [s.to_dict() for s in spans],
        "meta": meta,
    }
    try:
        document = parse_document(record, where=plan.doc_id)
    except FixtureError:
        return Outcome(plan, None, "invalid_span", completion=completion)
    return Outcome(plan, document, completion=completion)


# --- Corpus ------------------------------------------------------------------------------------

SPLITS = ("train", "dev", "test")


def parse_split(value: str) -> tuple[float, float, float]:
    """``"70/15/15"`` -> ``(0.7, 0.15, 0.15)``."""
    parts = value.replace(",", "/").split("/")
    try:
        numbers = [float(p) for p in parts]
    except ValueError:
        raise ValueError("split must look like 70/15/15") from None
    if len(numbers) != 3 or any(n < 0 for n in numbers) or sum(numbers) <= 0:
        raise ValueError("split must be three non-negative numbers, e.g. 70/15/15")
    total = sum(numbers)
    return (numbers[0] / total, numbers[1] / total, numbers[2] / total)


def assign_splits(n: int, seed: int, ratios: tuple[float, float, float]) -> list[str]:
    """Split label per document index: exact proportions, seeded shuffle, independent of
    which documents end up discarded."""
    counts = [int(n * r) for r in ratios]
    for i in sorted(range(3), key=lambda i: n * ratios[i] - counts[i], reverse=True):
        if sum(counts) >= n:
            break
        counts[i] += 1
    labels = [name for name, count in zip(SPLITS, counts, strict=True) for _ in range(count)]
    random.Random(f"pii-guard-corpus-split/{seed}/{n}").shuffle(labels)
    return labels


@dataclass(slots=True)
class CorpusResult:
    language: str
    seed: int
    outcomes: list[Outcome] = field(default_factory=list)

    @property
    def documents(self) -> list[Document]:
        return [o.document for o in self.outcomes if o.document is not None]

    def by_split(self) -> dict[str, list[Document]]:
        out: dict[str, list[Document]] = {name: [] for name in SPLITS}
        for doc in self.documents:
            out[str(doc.meta.get("split", "test"))].append(doc)
        return out

    def stats(self) -> dict[str, Any]:
        """Counts, discard reasons, token usage and latency. Never any value."""
        outcomes = self.outcomes
        accepted = [o for o in outcomes if o.accepted]
        reasons = Counter(o.reason for o in outcomes if o.reason)
        missing = Counter(t.value for o in outcomes for t in o.missing)
        unsupplied = Counter(t.value for o in outcomes for t in o.unsupplied)
        spans = Counter(s.entity_type.value for d in self.documents for s in d.spans)
        by_kind: dict[str, dict[str, int]] = {}
        for o in outcomes:
            entry = by_kind.setdefault(o.plan.kind, {"accepted": 0, "discarded": 0})
            entry["accepted" if o.accepted else "discarded"] += 1
        completions = [o.completion for o in outcomes if o.completion is not None]
        usage: Counter[str] = Counter()
        for c in completions:
            usage.update(c.usage)
        latencies = [c.latency_s for c in completions]
        return {
            "language": self.language,
            "seed": self.seed,
            "requested": len(outcomes),
            "accepted": len(accepted),
            "discarded": len(outcomes) - len(accepted),
            "discard_rate": round((len(outcomes) - len(accepted)) / len(outcomes), 4)
            if outcomes
            else 0.0,
            "discard_reasons": dict(sorted(reasons.items())),
            "missing_value_types": dict(sorted(missing.items())),
            "unsupplied_value_types": dict(sorted(unsupplied.items())),
            "by_kind": dict(sorted(by_kind.items())),
            "splits": {name: len(docs) for name, docs in self.by_split().items()},
            "spans": sum(spans.values()),
            "spans_by_type": dict(sorted(spans.items())),
            "chars": sum(len(d.text) for d in self.documents),
            "model_calls": sum(1 for c in completions if not c.cached),
            "cache_hits": sum(1 for c in completions if c.cached),
            "usage": dict(sorted(usage.items())),
            "latency_s": {
                "total": round(sum(latencies), 2),
                "mean": round(statistics.fmean(latencies), 2) if latencies else 0.0,
                "median": round(statistics.median(latencies), 2) if latencies else 0.0,
                "max": round(max(latencies), 2) if latencies else 0.0,
            },
        }


def generate_corpus(
    language: str,
    n: int,
    seed: int,
    client: ChatClient,
    cache: ResponseCache | None = None,
    *,
    split: tuple[float, float, float] = (0.7, 0.15, 0.15),
    workers: int = 1,
    start: int = 0,
    kinds: Sequence[str] | None = None,
) -> CorpusResult:
    """Plan, generate and label ``n`` documents. Order and content depend only on the seed
    (and the cached model outputs), not on ``workers``."""
    if n < 1:
        raise ValueError("n must be >= 1")
    pack = load_language(language)
    labels = assign_splits(n, seed, split)
    plans = [
        plan_document(
            pack.language,
            seed,
            start + i,
            kind=kinds[(start + i) % len(kinds)] if kinds else None,
        )
        for i in range(n)
    ]

    def run(i: int) -> Outcome:
        return generate_document(plans[i], client, cache, split=labels[i])

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            outcomes = list(pool.map(run, range(n)))
    else:
        outcomes = [run(i) for i in range(n)]
    return CorpusResult(pack.language, seed, outcomes)


# --- CLI ---------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pii-guard eval generate",
        description="Generate a labelled synthetic corpus with a Meta Muse model "
        "(fictional identities only).",
    )
    parser.add_argument(
        "--language", default="hu", help="a language pack with a corpus: hu, en or de (default: hu)"
    )
    parser.add_argument("--n", type=int, default=20, help="documents to plan (default: 20)")
    parser.add_argument("--seed", type=int, default=42, help="corpus seed (default: 42)")
    parser.add_argument("--start", type=int, default=0, help="first document index")
    parser.add_argument(
        "--out",
        type=Path,
        required=False,
        help="output directory (train/dev/test files) or a single .jsonl file",
    )
    parser.add_argument("--split", default="70/15/15", help="train/dev/test (default 70/15/15)")
    parser.add_argument("--kinds", help="comma-separated template ids to cycle through")
    parser.add_argument("--stats", type=Path, help="write run statistics (JSON) here")
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path(DEFAULT_CACHE),
        help=f"raw model output cache (default: {DEFAULT_CACHE})",
    )
    parser.add_argument("--no-cache", action="store_true", help="don't read or write the cache")
    parser.add_argument("--base-url", help="env PII_GUARD_CORPUS_URL, default the Meta Model API")
    parser.add_argument("--model", help=f"env PII_GUARD_CORPUS_MODEL, default {DEFAULT_MODEL}")
    parser.add_argument(
        "--api-key-env",
        default=None,
        metavar="VAR",
        help="environment variable holding the API key "
        "(default PII_GUARD_CORPUS_API_KEY, then META_API_KEY)",
    )
    parser.add_argument(
        "--reasoning-effort",
        default=DEFAULT_REASONING_EFFORT,
        help="minimal|low|medium|high|xhigh|max, or 'omit' (default: low)",
    )
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--workers", type=int, default=4, help="parallel requests (default: 4)")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the first prompt and exit (no model call)"
    )
    return parser


def _api_key(var: str | None) -> str | None:
    if var:
        return os.environ.get(var)
    return os.environ.get("PII_GUARD_CORPUS_API_KEY") or os.environ.get("META_API_KEY")


def _write_outputs(result: CorpusResult, out: Path, stats_path: Path | None) -> list[Path]:
    written: list[Path] = []
    stats = result.stats()
    if out.suffix == ".jsonl":
        out.parent.mkdir(parents=True, exist_ok=True)
        write_fixtures(out, result.documents)
        written.append(out)
    else:
        out.mkdir(parents=True, exist_ok=True)
        for name, docs in result.by_split().items():
            if docs:
                path = out / f"{result.language}-synth-{name}.jsonl"
                write_fixtures(path, docs)
                written.append(path)
        stats_path = stats_path or out / f"{result.language}-synth-stats.json"
    if stats_path:
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        stats_path.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
        written.append(stats_path)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        ratios = parse_split(args.split)
        pack = load_language(args.language)
        kinds = [k.strip() for k in args.kinds.split(",") if k.strip()] if args.kinds else None
        for kind in kinds or ():
            pack.kind(kind)
    except (ValueError, GenerationError) as exc:
        print(f"pii-guard eval generate: {exc}", file=sys.stderr)
        return 2
    except KeyError as exc:
        print(f"pii-guard eval generate: unknown template {exc}", file=sys.stderr)
        return 2
    if args.n < 1 or args.workers < 1:
        print("pii-guard eval generate: --n and --workers must be >= 1", file=sys.stderr)
        return 2

    if args.dry_run:
        plan = plan_document(pack.language, args.seed, args.start, kind=kinds[0] if kinds else None)
        for message in plan.messages:
            print(f"--- {message['role']}\n{message['content']}\n")
        return 0
    if args.out is None:
        print("pii-guard eval generate: --out is required", file=sys.stderr)
        return 2

    client = ChatClient(
        base_url=args.base_url or os.environ.get("PII_GUARD_CORPUS_URL") or DEFAULT_BASE_URL,
        api_key=_api_key(args.api_key_env),
        model=args.model or os.environ.get("PII_GUARD_CORPUS_MODEL") or DEFAULT_MODEL,
        reasoning_effort=None if args.reasoning_effort == "omit" else args.reasoning_effort,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )
    cache = None if args.no_cache else ResponseCache(args.cache)
    try:
        result = generate_corpus(
            pack.language,
            args.n,
            args.seed,
            client,
            cache,
            split=ratios,
            workers=args.workers,
            start=args.start,
            kinds=kinds,
        )
    except GenerationError as exc:
        print(f"pii-guard eval generate: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()

    written = _write_outputs(result, args.out, args.stats)
    stats = result.stats()
    print(
        f"pii-guard eval generate: {stats['accepted']}/{stats['requested']} documents accepted "
        f"({stats['discard_rate']:.0%} discarded: {stats['discard_reasons'] or 'none'}), "
        f"{stats['spans']} spans, {stats['model_calls']} model calls, "
        f"{stats['cache_hits']} cached",
        file=sys.stderr,
    )
    for path in written:
        print(f"  wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
