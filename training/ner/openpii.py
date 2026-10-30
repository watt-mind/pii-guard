"""NER training rows from the Ai4Privacy OpenPII-1M **train** split, disjoint from the eval sample.

`ai4privacy/pii-masking-openpii-1m <https://huggingface.co/datasets/ai4privacy/pii-masking-openpii-1m>`_
(CC-BY-4.0, attribution "Ai4Privacy / Ai Suisse SA") is synthetic, machine-generated text.
pii-guard evaluates on a seeded sample of its **validation** split
(``eval/fixtures/public/ai4privacy-openpii-1m.json``); this script draws training rows from its
**train** split only, and refuses to write anything that shares a ``uid`` or a text with that
eval sample (:func:`assert_disjoint`). The rows themselves are never committed: only the
manifest (``training/ner/openpii-train-manifest.json``: source, revision, hash, seed, counts,
and a SHA-256 over the chosen uids), so the set is rebuilt from the pinned file::

    curl -L -o data/public/openpii-train/train.jsonl \\
        https://huggingface.co/datasets/ai4privacy/pii-masking-openpii-1m/resolve/<REVISION>/data/train.jsonl
    uv run python training/ner/openpii.py --source data/public/openpii-train/train.jsonl
    uv run python training/ner/openpii.py --source ... --check   # compare with the manifest

**Conversion** is the eval's (:func:`pii_guard.eval.public.ai4privacy.convert_row`): the same
label mapping, the same merge of a given name and a surname, address parts and the same
policy exclusions, so the student learns exactly what the eval scores. On top of that, the
characters of every ``DATE`` span go into ``meta.loss_ignore``: the dataset doesn't say which
dates are birth dates, so a date is neither taught as ``O`` nor as ``DATE_OF_BIRTH``. Titles,
ages, gender and a city on its own stay ``O`` (pii-guard keeps them on purpose).

**Filters** (counted in the manifest): rows that don't convert, rows over
:data:`MAX_CHARS` characters, and Hungarian rows that use English month names or an English
date order, the clearest sign of the slot-filled, unnatural Hungarian rows. **Sample**: per
language, rows ordered by ``sha256("<seed>:<uid>")``; the first ``dev`` go to a dev file (for
the training loop's model selection) and the next ``train`` to the train file.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from pii_guard.eval.fixtures import Document, load_fixtures, write_fixtures
from pii_guard.eval.public.ai4privacy import (
    ATTRIBUTION,
    DATASET,
    DEFAULT_MANIFEST,
    LICENSE,
    REVISION,
    ConversionError,
    convert_row,
)

FILE = "data/train.jsonl"
#: Git LFS object id (SHA-256) of ``FILE`` at ``REVISION``.
FILE_SHA256 = "f167e4290bc8dc9d92866e1e7be57821e3847f0dc4b02140a9a5540fb9151743"
FILE_SIZE = 3_690_456_830
DEFAULT_SEED = 1150
DEFAULT_TRAIN = {"hu": 5000, "en": 5000, "de": 5000}
DEFAULT_DEV = {"hu": 150, "en": 150, "de": 150}
DEFAULT_OUT = Path("eval/generated/openpii-train")
DEFAULT_TRAIN_MANIFEST = Path("training/ner/openpii-train-manifest.json")
EVAL_FIXTURES = tuple(
    Path(f"eval/fixtures/public/{lang}-ai4privacy.jsonl") for lang in ("hu", "en", "de")
)
MAX_CHARS = 1500
_EN_MONTHS = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\b"
)


class DisjointnessError(RuntimeError):
    """A training row shares a uid or a text with the eval sample. Never carries a value."""


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def eval_holdout(
    manifest: Path = DEFAULT_MANIFEST, fixtures: Sequence[Path] = EVAL_FIXTURES
) -> tuple[set[str], set[str]]:
    """The eval sample's uids (from its manifest) and text hashes (from its fixture files)."""
    data = json.loads(manifest.read_text(encoding="utf-8"))
    uids = {str(u) for block in data["languages"].values() for u in block["uids"]}
    texts = {text_sha(d.text) for d in load_fixtures([p for p in fixtures if p.exists()])}
    return uids, texts


def assert_disjoint(docs: Iterable[Document], eval_uids: set[str], eval_texts: set[str]) -> int:
    """Raise :class:`DisjointnessError` if any document is in the eval sample; return the count."""
    n = 0
    for doc in docs:
        n += 1
        uid = str(doc.meta.get("uid"))
        if uid in eval_uids:
            raise DisjointnessError(f"training row {doc.id} is an eval row (uid)")
        if text_sha(doc.text) in eval_texts:
            raise DisjointnessError(f"training row {doc.id} has an eval row's text")
    return n


def filter_reason(row: Mapping[str, Any]) -> str | None:
    """Why ``row`` is left out (``None``: kept)."""
    text = row.get("source_text") or ""
    if len(text) > MAX_CHARS:
        return "too_long"
    if row.get("language") == "hu" and _EN_MONTHS.search(text):
        return "hu_english_dates"
    return None


def training_document(row: Mapping[str, Any]) -> Document:
    """The eval conversion plus ``DATE`` spans excluded from the loss."""
    converted = convert_row(row).document
    ignore = sorted(
        {
            (int(m["start"]), int(m["end"]))
            for m in row.get("privacy_mask") or ()
            if m.get("label") == "DATE"
        }
    )
    meta = dict(converted.meta)
    meta["kind"] = "public-ai4privacy-train"
    meta["split"] = "train"
    meta["loss_ignore"] = [list(r) for r in ignore]
    return Document(converted.id, converted.language, converted.text, converted.spans, meta)


def _order_key(seed: int, uid: object) -> str:
    return hashlib.sha256(f"{seed}:{uid}".encode()).hexdigest()


def select(
    rows: Iterable[Mapping[str, Any]],
    want: Mapping[str, int],
    seed: int,
    eval_uids: set[str],
    eval_texts: set[str],
) -> tuple[dict[str, list[Document]], Counter[str]]:
    """The first ``want[lang]`` usable rows per language in seeded order (bounded memory)."""
    heaps: dict[str, list[tuple[str, int, Mapping[str, Any]]]] = {lang: [] for lang in want}
    counts: Counter[str] = Counter()
    for index, row in enumerate(rows):
        lang = row.get("language")
        if lang not in heaps:
            continue
        counts[f"rows_{lang}"] += 1
        if str(row.get("uid")) in eval_uids or text_sha(row.get("source_text") or "") in eval_texts:
            counts[f"eval_overlap_skipped_{lang}"] += 1
            continue
        reason = filter_reason(row)
        if reason:
            counts[f"filtered_{reason}_{lang}"] += 1
            continue
        # Max-heap of the smallest keys: negate by inverting the hex digits.
        key = _order_key(seed, row.get("uid")).translate(_INVERT)
        heap = heaps[lang]
        item = (key, index, row)
        if len(heap) < want[lang] + 200:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
    out: dict[str, list[Document]] = {}
    for lang, heap in heaps.items():
        chosen: list[Document] = []
        for _, _, row in sorted(heap, key=lambda it: it[0], reverse=True):
            if len(chosen) == want[lang]:
                break
            try:
                chosen.append(training_document(row))
            except ConversionError:
                counts[f"unconvertible_{lang}"] += 1
        out[lang] = chosen
    return out, counts


_INVERT = str.maketrans("0123456789abcdef", "fedcba9876543210")


def stream_file(path: Path, expected_sha256: str | None = FILE_SHA256) -> Iterator[dict[str, Any]]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for line in handle:
            digest.update(line)
            if line.strip():
                yield json.loads(line)
    if expected_sha256 and digest.hexdigest() != expected_sha256:
        raise RuntimeError(f"{path}: SHA-256 mismatch (expected the pinned {FILE})")


def build_manifest(
    split: Mapping[str, Mapping[str, Sequence[Document]]],
    counts: Mapping[str, int],
    seed: int,
    train: Mapping[str, int],
    dev: Mapping[str, int],
) -> dict[str, Any]:
    languages: dict[str, Any] = {}
    for lang in train:
        block: dict[str, Any] = {
            "rows_in_split": counts.get(f"rows_{lang}", 0),
            "eval_overlap_skipped": counts.get(f"eval_overlap_skipped_{lang}", 0),
            "filtered": {
                k.removeprefix("filtered_").removesuffix(f"_{lang}"): v
                for k, v in sorted(counts.items())
                if k.startswith("filtered_") and k.endswith(f"_{lang}")
            },
            "unconvertible": counts.get(f"unconvertible_{lang}", 0),
        }
        for name in ("train", "dev"):
            docs = split[name][lang]
            gold: Counter[str] = Counter(s.entity_type.value for d in docs for s in d.spans)
            uids = sorted(str(d.meta["uid"]) for d in docs)
            block[name] = {
                "documents": len(docs),
                "gold_spans": dict(sorted(gold.items())),
                "loss_ignore_regions": sum(len(d.meta["loss_ignore"]) for d in docs),
                "uids_sha256": hashlib.sha256("\n".join(uids).encode()).hexdigest(),
            }
        languages[lang] = block
    return {
        "dataset": DATASET,
        "url": f"https://huggingface.co/datasets/{DATASET}",
        "revision": REVISION,
        "file": FILE,
        "file_sha256": FILE_SHA256,
        "license": LICENSE,
        "attribution": ATTRIBUTION,
        "synthetic": True,
        "rows_committed": False,
        "seed": seed,
        "requested": {"train": dict(train), "dev": dict(dev)},
        "sample_rule": (
            "per language, usable rows ordered by sha256('<seed>:<uid>'): the first n_dev are "
            "dev, the next n_train are train"
        ),
        "filters": {
            "max_chars": MAX_CHARS,
            "hu_english_dates": "Hungarian rows with an English month name",
        },
        "loss_ignore": "every DATE span (birth dates are not marked in the dataset)",
        "eval_holdout": {
            "manifest": str(DEFAULT_MANIFEST),
            "rule": "no uid of the eval manifest and no text of the eval fixtures",
            "disjoint": True,
        },
        "languages": languages,
    }


def _parse(value: str) -> dict[str, int]:
    out = {}
    for item in value.split(","):
        lang, _, n = item.partition("=")
        out[lang.strip()] = int(n)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", type=Path, required=True, help=f"local copy of {FILE}")
    parser.add_argument("--train", type=_parse, default=dict(DEFAULT_TRAIN))
    parser.add_argument("--dev", type=_parse, default=dict(DEFAULT_DEV))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_TRAIN_MANIFEST)
    parser.add_argument("--check", action="store_true", help="fail unless it matches the manifest")
    args = parser.parse_args(argv)
    if set(args.dev) != set(args.train):
        parser.error("--train and --dev must name the same languages")

    eval_uids, eval_texts = eval_holdout()
    want = {lang: args.train[lang] + args.dev[lang] for lang in args.train}
    chosen, counts = select(stream_file(args.source), want, args.seed, eval_uids, eval_texts)
    split: dict[str, dict[str, list[Document]]] = {"train": {}, "dev": {}}
    for lang, docs in chosen.items():
        assert_disjoint(docs, eval_uids, eval_texts)
        split["dev"][lang] = docs[: args.dev[lang]]
        split["train"][lang] = docs[args.dev[lang] :]
    manifest = build_manifest(split, counts, args.seed, args.train, args.dev)
    if args.check:
        committed = json.loads(args.manifest.read_text(encoding="utf-8"))
        if committed["languages"] != manifest["languages"]:
            print(f"openpii: the rebuilt set differs from {args.manifest}", file=sys.stderr)
            return 1
        print("openpii: matches the manifest", file=sys.stderr)
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    for name, by_lang in split.items():
        for lang, docs in by_lang.items():
            path = args.out / f"{lang}-openpii-{name}.jsonl"
            write_fixtures(path, docs)
            print(f"openpii: {len(docs)} {lang} {name} rows -> {path}", file=sys.stderr)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"openpii: manifest -> {args.manifest}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
