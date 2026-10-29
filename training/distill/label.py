"""Teacher labels for the distillation corpus: planted gold + rules + Muse Glimmer.

Fictional data only. For every corpus document the teacher (the ``llm`` detector pointed at
Muse Glimmer, ``reasoning_strength`` low, see ``deploy/modal/glimmer.py``) and the rule
detector run once; their spans are merged with the generator's planted gold spans into the
student's training labels (:func:`merge`):

- **Planted gold always wins.** Gold spans keep their type and boundaries.
- A teacher span (``PERSON``, ``ORGANIZATION``, ``ADDRESS``, ``DATE_OF_BIRTH``) that overlaps
  gold but runs past it (``Dr.`` before a name, a town after an address) or has another type
  is a **disagreement**: the characters it covers outside gold are excluded from the loss
  (``meta.loss_ignore``), not guessed.
- A teacher span that overlaps no gold is new: ``PERSON`` / ``ORGANIZATION`` become labels
  (names the writing model added on its own), unless a rule found a structured identifier
  there or the document is a hard negative (``negative-*`` kinds), where they are excluded
  instead. ``ADDRESS`` / ``DATE_OF_BIRTH`` are excluded: the generator supplies every address
  and birth date, so a new one is a town in prose or an ordinary date.

Teacher outputs are cached per document (``teacher-cache.jsonl``: id, text hash, spans), so a
rerun reproduces the labels without calling the model.

::

    PII_GUARD_LLM_DETECTOR_URL=... PII_GUARD_LLM_DETECTOR_API_KEY=... \\
    uv run python training/distill/label.py --corpus eval/generated/distill-s11 --workers 64
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pii_guard.eval.fixtures import Document, GoldSpan, load_fixtures, write_fixtures
from pii_guard.types import EntityType

NER_TYPES = frozenset(
    {
        EntityType.PERSON,
        EntityType.ORGANIZATION,
        EntityType.ADDRESS,
        EntityType.DATE_OF_BIRTH,
    }
)
ADOPT_TYPES = frozenset({EntityType.PERSON, EntityType.ORGANIZATION})
TEACHER_MODEL = "muse-glimmer"
TEACHER_STRENGTH = "low"


@dataclass(frozen=True, slots=True)
class Hit:
    start: int
    end: int
    entity_type: EntityType


@dataclass(slots=True)
class Merged:
    spans: list[GoldSpan]
    ignore: list[tuple[int, int]]
    counts: Counter[str] = field(default_factory=Counter)


def _overlaps(a: Any, b: Any) -> bool:
    return a.start < b.end and b.start < a.end


def _outside(hit: Hit, covers: Iterable[Any]) -> list[tuple[int, int]]:
    """The parts of ``hit`` not covered by any of ``covers``."""
    pieces = [(hit.start, hit.end)]
    for c in covers:
        nxt = []
        for s, e in pieces:
            if c.end <= s or e <= c.start:
                nxt.append((s, e))
                continue
            if s < c.start:
                nxt.append((s, c.start))
            if c.end < e:
                nxt.append((c.end, e))
        pieces = nxt
    return pieces


def _trim(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and not text[start].isalnum():
        start += 1
    while end > start and not text[end - 1].isalnum():
        end -= 1
    return (start, end) if start < end else None


def merge(
    doc: Document,
    teacher: Sequence[Hit],
    rules: Sequence[Hit],
    *,
    negative: bool = False,
) -> Merged:
    """Training labels for ``doc`` from gold, teacher and rule spans (see module docstring)."""
    gold = list(doc.spans)
    counts: Counter[str] = Counter()
    ignore: list[tuple[int, int]] = []
    adopted: list[Hit] = []
    for g in gold:
        if g.entity_type in NER_TYPES:
            found = any(_overlaps(t, g) for t in teacher if t.entity_type in NER_TYPES)
            counts["gold_found_by_teacher" if found else "gold_missed_by_teacher"] += 1
    for t in sorted(set(teacher), key=lambda h: (-(h.end - h.start), h.start)):
        if t.entity_type not in NER_TYPES:
            continue
        hits = [g for g in gold if _overlaps(g, t)]
        if hits:
            same = any(
                g.entity_type == t.entity_type and g.start <= t.start and t.end <= g.end
                for g in hits
            )
            rest = [p for p in (_trim(doc.text, s, e) for s, e in _outside(t, hits)) if p]
            if same or not rest:
                counts["agree"] += 1
            else:
                counts["disagree"] += 1
                ignore.extend(rest)
            continue
        if any(_overlaps(r, t) for r in rules):
            counts["rule_conflict"] += 1
            ignore.append((t.start, t.end))
        elif negative:
            counts["negative_ignored"] += 1
            ignore.append((t.start, t.end))
        elif t.entity_type not in ADOPT_TYPES:
            counts[f"new_{t.entity_type.value.lower()}_ignored"] += 1
            ignore.append((t.start, t.end))
        elif any(_overlaps(a, t) for a in adopted):
            counts["teacher_overlap_ignored"] += 1
            ignore.append((t.start, t.end))
        else:
            counts[f"adopted_{t.entity_type.value.lower()}"] += 1
            adopted.append(t)
    spans = gold + [
        GoldSpan(a.start, a.end, a.entity_type, doc.text[a.start : a.end]) for a in adopted
    ]
    spans.sort(key=lambda s: (s.start, s.end))
    return Merged(spans, sorted(set(ignore)), counts)


def labelled_document(doc: Document, merged: Merged, model: str = TEACHER_MODEL) -> Document:
    meta = dict(doc.meta)
    meta["loss_ignore"] = [list(r) for r in merged.ignore]
    meta["teacher"] = {"model": model, "reasoning_strength": TEACHER_STRENGTH}
    return Document(doc.id, doc.language, doc.text, tuple(merged.spans), meta)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class TeacherCache:
    """Append-only JSONL of teacher spans per document (id + text hash)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.entries: dict[tuple[str, str], list[Hit]] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.entries[(row["id"], row["sha"])] = [
                        Hit(s, e, EntityType(t)) for s, e, t in row["spans"]
                    ]

    def get(self, doc: Document) -> list[Hit] | None:
        return self.entries.get((doc.id, text_hash(doc.text)))

    def put(self, doc: Document, hits: Sequence[Hit]) -> None:
        row = {
            "id": doc.id,
            "sha": text_hash(doc.text),
            "spans": [[h.start, h.end, h.entity_type.value] for h in hits],
        }
        with self._lock:
            self.entries[(doc.id, row["sha"])] = list(hits)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")


def run_teacher(docs: Sequence[Document], detector: Any, cache: TeacherCache, workers: int):
    """Teacher spans for every document (cached ones first); failures map to ``None``."""
    results: dict[str, list[Hit] | None] = {}
    todo = []
    for doc in docs:
        cached = cache.get(doc)
        if cached is None:
            todo.append(doc)
        else:
            results[doc.id] = cached
    done = [0]
    lock = threading.Lock()
    started = time.monotonic()

    def one(doc: Document) -> None:
        try:
            spans = detector.detect(doc.text, doc.language)
        except Exception as exc:  # fail closed per document: it is left out of training
            print(f"teacher failed on {doc.id}: {type(exc).__name__}", file=sys.stderr)
            results[doc.id] = None
            return
        hits = [Hit(s.start, s.end, s.entity_type) for s in spans]
        cache.put(doc, hits)
        results[doc.id] = hits
        with lock:
            done[0] += 1
            if done[0] % 200 == 0:
                rate = done[0] / max(time.monotonic() - started, 1e-6) * 60
                print(f"teacher {done[0]}/{len(todo)} ({rate:.0f} docs/min)", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        list(pool.map(one, todo))
    return results


def rule_hits(doc: Document, rules: Any) -> list[Hit]:
    return [
        Hit(s.start, s.end, s.entity_type)
        for s in rules.detect(doc.text, language=doc.language)
        if s.entity_type not in NER_TYPES
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--corpus", type=Path, required=True, help="corpus.py output directory")
    parser.add_argument("--out", type=Path, help="default: <corpus>/labelled")
    parser.add_argument("--workers", type=int, default=64, help="requests in flight")
    parser.add_argument("--limit", type=int, help="label only the first N documents per file")
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--cache-only", action="store_true", help="never call the teacher")
    parser.add_argument(
        "--model",
        default=TEACHER_MODEL,
        help="served model name (a Fireworks deployment: '<model>#<deployment>', LAB-1539)",
    )
    parser.add_argument(
        "--reasoning-effort",
        help="also send reasoning_effort (Fireworks maps it onto Glimmer's template and "
        "ignores chat_template_kwargs; use 'low' there)",
    )
    args = parser.parse_args(argv)

    from pii_guard.detect.llm import LlmDetector
    from pii_guard.detect.rules import RuleDetector

    out = args.out or args.corpus / "labelled"
    out.mkdir(parents=True, exist_ok=True)
    cache = TeacherCache(args.corpus / "teacher-cache.jsonl")
    files = sorted(args.corpus.glob("*-distill-*.jsonl"))
    by_file = {
        p: load_fixtures([p])[: args.limit] if args.limit else load_fixtures([p]) for p in files
    }
    every = [d for docs in by_file.values() for d in docs]
    usage: dict[str, int] = {}
    if args.cache_only:
        teacher = {d.id: cache.get(d) for d in every}
    else:
        detector = LlmDetector(
            model=args.model,
            reasoning_strength=TEACHER_STRENGTH,
            reasoning_effort=args.reasoning_effort,
            timeout=args.timeout,
            max_tokens=8192,
            max_retries=2,
        )
        teacher = run_teacher(every, detector, cache, args.workers)
        usage = dict(detector.usage)
    rules = RuleDetector()
    totals: Counter[str] = Counter()
    for path, docs in by_file.items():
        labelled = []
        for doc in docs:
            hits = teacher.get(doc.id)
            if hits is None:
                totals["documents_without_teacher"] += 1
                continue
            negative = str(doc.meta.get("kind", "")).startswith("negative-")
            merged = merge(doc, hits, rule_hits(doc, rules), negative=negative)
            totals.update(merged.counts)
            totals["documents"] += 1
            labelled.append(labelled_document(doc, merged, args.model))
        target = out / path.name
        write_fixtures(target, labelled)
        print(f"wrote {target} ({len(labelled)} documents)", file=sys.stderr)
    summary = {
        "teacher": {"model": args.model, "reasoning_strength": TEACHER_STRENGTH},
        "counts": dict(sorted(totals.items())),
        "usage": usage,
    }
    (out / "label-stats.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
