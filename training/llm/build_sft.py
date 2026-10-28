"""Supervised fine-tuning pairs for an answer-only LLM detector (Muse Glimmer LoRA).

Fictional data only (ADR 0005). Source: the LAB-1128 distillation corpus after teacher
labelling (``training/distill/label.py``), ``<lang>-distill-{train,dev}.jsonl`` under
``<corpus>/labelled/``. Every training example is exactly what the ``llm`` detector would
exchange with the model for that document:

- **system** and **user**: :func:`pii_guard.detect.llm.build_messages` for the document's
  language (language pack prompt notes and requested types), after the detector's own
  normalisation (:func:`~pii_guard.detect.normalize.normalize_for_detection`) and chunking
  (:func:`~pii_guard.detect.llm.chunk_text`, the detector's default 6,000 / 300 code points).
  The random delimiter boundary (LAB-1107) is drawn per example from a seeded generator, so
  the file is reproducible and the model never sees the same boundary twice.
- **assistant**: the answer only, ``{"entities": [{"type": ..., "text": ...}]}`` in the
  detector's schema, no reasoning text. Each distinct ``(type, surface text)`` once, in order
  of first appearance in the chunk. Types the prompt does not request for the language are
  left out (the rules own them).

Targets are the labels the NER student was trained on: planted gold plus the names the
teacher found and the merge adopted. A document where the teacher disagreed with gold
(``meta.loss_ignore`` not empty) is left out entirely: an LLM target can't mask part of the
loss, and guessing those characters is what the NER merge avoids too. Hard negatives
(``negative-*`` kinds) stay in with an empty list.

Only the ``train`` split is written. The distillation ``dev`` split is the held-out test set
for this model, and every document in it and in ``eval/fixtures/**`` is checked by text hash
to be absent from the output (the build fails otherwise).

::

    uv run python training/llm/build_sft.py \\
        --corpus eval/generated/distill-s11 --out eval/generated/llm-sft

Writes ``<out>/train.jsonl`` (chat format: ``{"messages": [...]}`` per line) and
``<out>/manifest.json`` (counts per language, kind and type, exclusions, sha256 of every input
and of the output, source commit; never values). ``training/llm/data-manifest.json`` is the
committed copy of the manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any

from pii_guard.detect.llm import build_messages, chunk_text, language_profile
from pii_guard.detect.normalize import normalize_for_detection

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "eval" / "fixtures"
BUILD_VERSION = 1
#: The detector's defaults (``LlmDetector(chunk_size=..., chunk_overlap=...)``).
CHUNK_SIZE = 6000
CHUNK_OVERLAP = 300
LANGUAGES = ("hu", "en")


def text_hash(text: str) -> str:
    """The hash used for the leakage check: the detector-normalised text, UTF-8."""
    return hashlib.sha256(normalize_for_detection(text).text.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def held_out_hashes(corpus: Path, fixtures: Path = FIXTURES) -> dict[str, set[str]]:
    """Text hashes that must never be trained on: the distillation dev split and every
    document under ``eval/fixtures/**`` (any ``*.jsonl`` with a ``text`` field)."""
    out: dict[str, set[str]] = {"distill_dev": set(), "eval_fixtures": set()}
    for path in sorted((corpus / "labelled").glob("*-distill-dev.jsonl")):
        out["distill_dev"].update(text_hash(d["text"]) for d in read_jsonl(path))
    for path in sorted(fixtures.rglob("*.jsonl")):
        for d in read_jsonl(path):
            if isinstance(d.get("text"), str):
                out["eval_fixtures"].add(text_hash(d["text"]))
    return out


def answer(entities: Iterable[tuple[str, str]]) -> str:
    """The assistant message: the detector's JSON schema, nothing else."""
    items = [{"type": t, "text": s} for t, s in dict.fromkeys(entities)]
    return json.dumps({"entities": items}, ensure_ascii=False)


def chunk_entities(
    text: str, spans: Sequence[dict[str, Any]], offset: int, chunk: str, allowed: frozenset[str]
) -> list[tuple[str, str]]:
    """``(type, surface)`` for the spans wholly inside ``chunk`` (at ``offset`` in ``text``),
    in order of position, restricted to ``allowed`` types."""
    end = offset + len(chunk)
    found = []
    for s in sorted(spans, key=lambda s: (s["start"], s["end"])):
        if s["entity_type"] not in allowed or not (offset <= s["start"] and s["end"] <= end):
            continue
        surface = text[s["start"] : s["end"]].strip()
        if surface:
            found.append((s["entity_type"], surface))
    return found


def boundary_for(rng: random.Random) -> str:
    return f"{rng.getrandbits(48):012x}"


def build_examples(
    docs: Iterable[dict[str, Any]], *, seed: int, counts: Counter[str]
) -> Iterator[dict[str, Any]]:
    """Chat examples for ``docs`` (labelled corpus documents), counting into ``counts``."""
    rng = random.Random(seed)  # noqa: S311 - reproducible delimiters, not a secret
    for doc in docs:
        language = doc["language"]
        meta = doc.get("meta") or {}
        counts[f"documents.{language}"] += 1
        if meta.get("loss_ignore"):
            counts[f"excluded_disagreement.{language}"] += 1
            continue
        norm = normalize_for_detection(doc["text"])
        if norm.changed:  # labels are offsets into the original text
            counts[f"excluded_normalisation.{language}"] += 1
            continue
        profile = language_profile(language)
        allowed = frozenset(t.value for t in profile.entity_types)
        for s in doc["spans"]:
            if s["entity_type"] not in allowed:
                counts[f"dropped_type.{language}.{s['entity_type']}"] += 1
        chunks = chunk_text(norm.text, CHUNK_SIZE, CHUNK_OVERLAP)
        for offset, chunk in chunks:
            entities = chunk_entities(norm.text, doc["spans"], offset, chunk, allowed)
            messages = build_messages(chunk, language, boundary=boundary_for(rng))
            messages.append({"role": "assistant", "content": answer(entities)})
            counts[f"examples.{language}"] += 1
            counts[f"kind.{language}.{meta.get('kind', '?')}"] += 1
            if not entities:
                counts[f"empty_answers.{language}"] += 1
            for t, _ in dict.fromkeys(entities):
                counts[f"type.{language}.{t}"] += 1
            yield {"messages": messages}


def git_commit() -> str:
    try:
        return subprocess.run(  # noqa: S603 - fixed argument list
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _nest(counts: Counter[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in sorted(counts):
        node = out
        *parents, leaf = key.split(".")
        for p in parents:
            node = node.setdefault(p, {})
        node[leaf] = counts[key]
    return out


def build(corpus: Path, out: Path, *, seed: int = 1109, fixtures: Path = FIXTURES) -> dict:
    """Write ``out/train.jsonl`` and ``out/manifest.json``; returns the manifest."""
    sources = [corpus / "labelled" / f"{lang}-distill-train.jsonl" for lang in LANGUAGES]
    missing = [str(p) for p in sources if not p.is_file()]
    if missing:
        raise FileNotFoundError(f"labelled corpus files missing: {missing}")
    held = held_out_hashes(corpus, fixtures)
    counts: Counter[str] = Counter()
    out.mkdir(parents=True, exist_ok=True)
    target = out / "train.jsonl"
    seen: set[str] = set()

    def docs() -> Iterator[dict[str, Any]]:
        for path in sources:
            for doc in read_jsonl(path):
                h = text_hash(doc["text"])
                for name, hashes in held.items():
                    if h in hashes:
                        raise AssertionError(f"{doc['id']} is in the held-out set {name}")
                if h in seen:
                    counts[f"excluded_duplicate.{doc['language']}"] += 1
                    continue
                seen.add(h)
                yield doc

    with target.open("w", encoding="utf-8") as f:
        for example in build_examples(docs(), seed=seed, counts=counts):
            f.write(json.dumps(example, ensure_ascii=False) + "\n")
    manifest = {
        "build_version": BUILD_VERSION,
        "seed": seed,
        "source_commit": git_commit(),
        "chunking": {"size": CHUNK_SIZE, "overlap": CHUNK_OVERLAP},
        "targets": "labelled spans (gold + adopted teacher names); documents with teacher "
        "disagreements excluded; types restricted to those the language's prompt requests",
        "inputs": {
            str(p.relative_to(corpus)): {"sha256": file_sha256(p)}
            for p in [*sources, *sorted((corpus / "labelled").glob("*-distill-dev.jsonl"))]
        },
        "held_out_hashes": {k: len(v) for k, v in held.items()},
        "held_out_overlap": 0,
        "output": {
            "file": target.name,
            "sha256": file_sha256(target),
            "bytes": target.stat().st_size,
            "examples": sum(v for k, v in counts.items() if k.startswith("examples.")),
        },
        "counts": _nest(counts),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--corpus", type=Path, required=True, help="distillation corpus directory")
    p.add_argument("--out", type=Path, default=ROOT / "eval" / "generated" / "llm-sft")
    p.add_argument("--seed", type=int, default=1109)
    args = p.parse_args(argv)
    manifest = build(args.corpus, args.out, seed=args.seed)
    print(json.dumps(manifest["output"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
