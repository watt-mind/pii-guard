"""Teacher audit for the NER v3 mix (LAB-1393): keep unlabelled PII out of the loss.

Generated corpora label only the values they planted. A name, an e-mail or an account number
the template or the generator added without a label would be taught as ``O``. A teacher
token classifier reads the English and German documents of the audited sources; any region
it tags as personal data that overlaps no gold span is added to ``meta.loss_ignore``, so it
is neither taught as an entity nor as ``O``. Gold spans are never changed: where the teacher
and the gold disagree, the token drops out of the loss, the gold stays. Hungarian and the
other languages keep their generated gold untouched.

Teacher (pinned): ``Horizon-Labs/pii-redactor-base`` (mmBERT-base fine-tune, Apache-2.0 with
LICENSE and NOTICE files in the repository), the teacher LAB-1391 recommends for English and
German document text.

Teacher labels that are not personal data in pii-guard's sense (dates, a place on its own,
ages) are not flagged. Everything else is, SECRET / URL / IP and the GDPR special categories
(medical ids) included: those stay with the rules or out of scope, so the student
is not taught them, either way. The audit is only applied to synthetic documents (ADR 0005);
it reads text and writes offsets, never values::

    uv run --no-sync python training/ner/v3_teachers.py eval/generated/v3/privy/*.jsonl \\
        --out eval/generated/v3-audited --json audit.json --device cuda
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pii_guard.eval.fixtures import Document, load_fixtures, write_fixtures


@dataclass(frozen=True)
class Teacher:
    repo: str
    revision: str
    license: str
    #: Teacher label types (BIO/BIOES prefix stripped) that are *not* flagged.
    benign: frozenset[str]
    #: Document languages the teacher is applied to (others pass through unchanged).
    languages: frozenset[str] = frozenset()


#: The teacher used for v3 (LAB-1391's recommendation): Apache-2.0 with a LICENSE and NOTICE
#: file in the repository, applied to English and German text only. Hungarian text and
#: identifiers keep their generated gold: every new encoder LAB-1391 measured is much worse
#: there than v2.0.
TEACHERS = (
    Teacher(
        "Horizon-Labs/pii-redactor-base",
        "42dfb0dccb0864c889c99300265567ace9fa6e6d",
        "Apache-2.0",
        frozenset({"O", "DATE", "LOCATION", "AGE"}),
        frozenset({"en", "de"}),
    ),
)


def label_type(label: str) -> str:
    """``B-PERSON_NAME`` -> ``PERSON_NAME``; ``O`` stays ``O``."""
    if len(label) > 2 and label[1] == "-" and label[0] in "BIESL":
        return label[2:]
    return label


def regions_from_tokens(
    offsets: Sequence[tuple[int, int]], types: Sequence[str], benign: frozenset[str]
) -> list[tuple[int, int, str]]:
    """Contiguous runs of tokens with the same flagged type, as ``(start, end, type)``."""
    out: list[tuple[int, int, str]] = []
    for (start, end), kind in zip(offsets, types, strict=True):
        if end <= start or kind in benign:
            continue
        if out and out[-1][2] == kind and start - out[-1][1] <= 1:
            out[-1] = (out[-1][0], end, kind)
        else:
            out.append((start, end, kind))
    return out


def outside_gold(
    doc: Document, regions: Iterable[tuple[int, int, str]]
) -> list[tuple[int, int, str]]:
    """The regions that overlap no gold span (whitespace-trimmed)."""
    kept = []
    for start, end, kind in regions:
        while start < end and doc.text[start].isspace():
            start += 1
        while end > start and doc.text[end - 1].isspace():
            end -= 1
        if start >= end:
            continue
        if any(s.start < end and start < s.end for s in doc.spans):
            continue
        kept.append((start, end, kind))
    return kept


def apply(doc: Document, flagged: Iterable[tuple[int, int, str]]) -> Document:
    """``doc`` with ``flagged`` regions added to ``meta.loss_ignore``."""
    meta = dict(doc.meta)
    regions = {(int(s), int(e)) for s, e in meta.get("loss_ignore") or ()}
    added = {(s, e) for s, e, _ in flagged} - regions
    meta["loss_ignore"] = [list(r) for r in sorted(regions | added)]
    meta["teacher_ignored"] = len(added)
    return Document(doc.id, doc.language, doc.text, doc.spans, meta)


class Runner:
    """One teacher on one device; windows of ``max_length`` tokens with ``stride`` overlap."""

    def __init__(self, teacher: Teacher, device: str, max_length: int = 512, stride: int = 64):
        import torch
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        self.teacher = teacher
        self.device = device
        self.max_length = max_length
        self.stride = stride
        self.tokenizer = AutoTokenizer.from_pretrained(teacher.repo, revision=teacher.revision)
        dtype = torch.bfloat16 if device == "cuda" else torch.float32
        self.model = (
            AutoModelForTokenClassification.from_pretrained(
                teacher.repo, revision=teacher.revision, dtype=dtype, use_safetensors=True
            )
            .to(device)
            .eval()
        )
        self.id2label = {int(k): v for k, v in self.model.config.id2label.items()}

    def regions(self, texts: Sequence[str], batch: int = 32) -> list[list[tuple[int, int, str]]]:
        import torch

        out: list[list[tuple[int, int, str]]] = [[] for _ in texts]
        if not texts:
            return out
        enc = self.tokenizer(
            list(texts),
            return_offsets_mapping=True,
            return_overflowing_tokens=True,
            truncation=True,
            max_length=self.max_length,
            stride=self.stride,
        )
        owners = enc["overflow_to_sample_mapping"]
        pad = self.tokenizer.pad_token_id or 0
        order = sorted(range(len(owners)), key=lambda i: len(enc["input_ids"][i]))
        for b in range(0, len(order), batch):
            idx = order[b : b + batch]
            width = max(len(enc["input_ids"][i]) for i in idx)
            rows = [enc["input_ids"][i] for i in idx]
            ids = torch.tensor([r + [pad] * (width - len(r)) for r in rows], device=self.device)
            mask = torch.tensor(
                [[1] * len(r) + [0] * (width - len(r)) for r in rows], device=self.device
            )
            with torch.inference_mode():
                pred = self.model(input_ids=ids, attention_mask=mask).logits.argmax(-1).tolist()
            for row, i in enumerate(idx):
                offsets = [tuple(o) for o in enc["offset_mapping"][i]]
                types = [label_type(self.id2label[p]) for p in pred[row][: len(offsets)]]
                out[owners[i]].extend(regions_from_tokens(offsets, types, self.teacher.benign))
        return out


def audit_files(paths: Sequence[Path], out_dir: Path, runners: Sequence[Runner]) -> dict[str, Any]:
    report: dict[str, Any] = {
        "teachers": [
            {
                "repo": r.teacher.repo,
                "revision": r.teacher.revision,
                "license": r.teacher.license,
                "languages": sorted(r.teacher.languages),
            }
            for r in runners
        ],
        "files": {},
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in paths:
        docs = load_fixtures([path])
        texts = [d.text for d in docs]
        flagged: list[list[tuple[int, int, str]]] = [[] for _ in docs]
        per_teacher: dict[str, Counter[str]] = {}
        for runner in runners:
            langs = runner.teacher.languages
            todo = [i for i, d in enumerate(docs) if not langs or d.language in langs]
            found = dict(zip(todo, runner.regions([texts[i] for i in todo]), strict=True))
            counter: Counter[str] = Counter()
            for i, doc in enumerate(docs):
                if i not in found:
                    continue
                extra = outside_gold(doc, found[i])
                counter.update(kind for _, _, kind in extra)
                flagged[i].extend(extra)
            per_teacher[runner.teacher.repo] = counter
        audited = [apply(d, f) for d, f in zip(docs, flagged, strict=True)]
        write_fixtures(out_dir / path.name, audited)
        report["files"][str(path)] = {
            "documents": len(docs),
            "documents_with_flags": sum(d.meta["teacher_ignored"] > 0 for d in audited),
            "regions_added": sum(d.meta["teacher_ignored"] for d in audited),
            "by_teacher_type": {k: dict(c.most_common()) for k, c in per_teacher.items()},
        }
        print(f"audit: {path.name}: {report['files'][str(path)]['regions_added']} regions",
              file=sys.stderr, flush=True)  # fmt: skip
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args(argv)
    runners = [Runner(t, args.device) for t in TEACHERS]
    report = audit_files(args.files, args.out, runners)
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
