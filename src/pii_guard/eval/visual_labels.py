"""Placeholder matching between images and text on the fictional visual set (LAB-1156).

```
uv run python -m pii_guard.eval.visual_labels [--matcher fuzzy|exact] [--noise 0.0]
        [--json OUT] [--record-ocr] [--write-namesakes] [--coverage]
```

For every fictional document in ``eval/fixtures/visual/`` (LAB-1121) and every personal value
printed on it (``generation.json``: the holder's name, document number, date of birth, e-mail,
phone, address, a letter's signer), a vault session first masks a short text that names the
value the way a contract would (``Fiktív Mária``, mixed case and natural order; ISO dates),
together with that value's **near-namesakes** (``eval/fixtures/visual/near-namesakes.json``:
``Fiktív Márta``, a document number one digit off). The image is then masked with placeholder
labels in that session, and the value is scored:

- **match** (true positive): the image carries the text's placeholder for it;
- **false merge**: the image carries a near-namesake's placeholder. Each document is run a
  second time with **only** the near-namesakes in the session; any reuse there is a false
  merge too. The target is zero;
- **uncertain**: the vault matcher flagged a close-but-not-accepted value (a new placeholder);
- **swept**: no image region carries it, but the session sweep masked it in the transcript
  (a value the conversation named and no image detector found: still visible in the pixels);
- **leaked**: a value spelled out in the transcript or summary (the target is zero).

``--noise P`` simulates OCR noise on the recorded words before matching: each character is
replaced by an OCR confusion (``o``->``0``, ``i``->``1``, ``s``->``5``, ...) with probability P,
and half of the words lose their accents (seeded, so runs repeat). ``--matcher exact`` is the
baseline: an image value reuses a text placeholder only when the two are equal up to case and
whitespace (:func:`pii_guard.vault.normalize_value`), i.e. what registering OCR values in the
vault without fuzzy matching would do.

OCR words come from ``eval/fixtures/visual/ocr/tesseract.json`` (recorded from the committed
fictional images with ``--record-ocr``, Tesseract ``hun+eng``, images enlarged to 2000 px), so
the eval runs without Tesseract and without network. SAM is not called: placeholder matching
concerns text values only. ``--coverage`` also scores the covered boxes of both render modes
against the labelled text and MRZ regions (visual recall must not depend on the mode).

Also defines the **"which parties have an ID?"** demo documents (:func:`demo_documents`):
a fictional contract naming three parties, the ID card of one, and the ID card of another
with its expiry date reprinted in the past. ``examples/which_parties_have_an_id.py`` and the
end-to-end test use them.

Results contain counts, ratios and document ids only, never values.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from pii_guard.detect.rules import RuleDetector
from pii_guard.eval.record import with_role
from pii_guard.eval.stats import percentile
from pii_guard.eval.visual_labels_core import (
    _CONFUSIONS as _CONFUSIONS,
)
from pii_guard.eval.visual_labels_core import (
    EVAL_KEY as EVAL_KEY,
)
from pii_guard.eval.visual_labels_core import (
    FIXTURES as FIXTURES,
)
from pii_guard.eval.visual_labels_core import (
    GOLD_TYPES as GOLD_TYPES,
)
from pii_guard.eval.visual_labels_core import (
    NAMESAKES as NAMESAKES,
)
from pii_guard.eval.visual_labels_core import (
    OCR_CACHE as OCR_CACHE,
)
from pii_guard.eval.visual_labels_core import (
    CachedOcr as CachedOcr,
)
from pii_guard.eval.visual_labels_core import (
    CachedOcrFromDict as CachedOcrFromDict,
)
from pii_guard.eval.visual_labels_core import (
    ExactMatcher as ExactMatcher,
)
from pii_guard.eval.visual_labels_core import (
    _confusable_doc as _confusable_doc,
)
from pii_guard.eval.visual_labels_core import (
    _confusable_token as _confusable_token,
)
from pii_guard.eval.visual_labels_core import (
    _manifest as _manifest,
)
from pii_guard.eval.visual_labels_core import (
    _namesake_token as _namesake_token,
)
from pii_guard.eval.visual_labels_core import (
    _NoSam as _NoSam,
)
from pii_guard.eval.visual_labels_core import (
    _seed as _seed,
)
from pii_guard.eval.visual_labels_core import (
    _strip as _strip,
)
from pii_guard.eval.visual_labels_core import (
    _word_from_json as _word_from_json,
)
from pii_guard.eval.visual_labels_core import (
    _word_to_json as _word_to_json,
)
from pii_guard.eval.visual_labels_core import (
    load_gold as load_gold,
)
from pii_guard.eval.visual_labels_core import (
    load_namesakes as load_namesakes,
)
from pii_guard.eval.visual_labels_core import (
    near_namesakes as near_namesakes,
)
from pii_guard.eval.visual_labels_core import (
    noisy_words as noisy_words,
)
from pii_guard.eval.visual_labels_core import (
    pixel_key as pixel_key,
)
from pii_guard.eval.visual_labels_core import (
    record_ocr as record_ocr,
)
from pii_guard.eval.visual_labels_core import (
    write_namesakes as write_namesakes,
)
from pii_guard.policy import Policy, PolicySet
from pii_guard.types import EntityType
from pii_guard.vault import PLACEHOLDER_RE, Vault
from pii_guard.visual.captions import caption_values
from pii_guard.visual.image import encode_image, load_image
from pii_guard.visual.labels import VaultMatcher
from pii_guard.visual.masking import ImageMasker
from pii_guard.visual.ocr import OcrWord
from pii_guard.visual.summary import field_name

__all__ = [
    "DEMO_PARTIES",
    "CachedOcr",
    "DemoDocuments",
    "ExactMatcher",
    "demo_documents",
    "evaluate",
    "load_gold",
    "main",
    "near_namesakes",
    "noisy_words",
]


def _image_placeholders(outcome: Any) -> set[str]:
    """The placeholders the image itself carries: its covered regions' labels and summary.
    (A transcript-only placeholder, from the session sweep, is counted as ``swept``: the
    value is masked in the transcript but still visible in the pixels.)"""
    found: set[str] = set()
    for region in outcome.regions:
        if region.label is not None and region.label.placeholder:
            found.add(region.label.placeholder)
    for match in PLACEHOLDER_RE.finditer(json.dumps(outcome.summary or {})):
        found.add(match.group(0))
    return found


def _transcript_placeholders(outcome: Any) -> set[str]:
    return {m.group(0) for m in PLACEHOLDER_RE.finditer(outcome.transcript or "")}


@dataclass
class _Tally:
    gold: int = 0
    matched: int = 0
    false_merges: int = 0
    uncertain: int = 0
    leaked: int = 0
    swept: int = 0
    transcripts: int = 0
    transcripts_resolved: int = 0
    match_ms: list[float] = field(default_factory=list)
    by_type: dict[str, list[int]] = field(default_factory=dict)  # type -> [gold, tp, fp]
    by_language: dict[str, _Tally] = field(default_factory=dict)
    people: dict[tuple[str, str], list[bool]] = field(default_factory=dict)


def _leaks(text: str, value: str) -> bool:
    from pii_guard.visual.labels import _leaks as leaks

    return leaks(text, [value])


def _record_transcript_and_leaks(
    session: Any,
    outcome: Any,
    values: dict[str, str],
    tallies: Sequence[_Tally],
) -> None:
    for t in tallies:
        t.transcripts += 1
        restored = session.unmask_with_report(outcome.transcript or "")
        t.transcripts_resolved += not restored.unresolved
        text = (outcome.transcript or "") + json.dumps(outcome.summary or {})
        t.leaked += sum(_leaks(text, v) for v in values.values())


def _build_phase_seeds(
    doc: str,
    values: dict[str, str],
    namesakes: dict[tuple[str, str], list[str]],
    phase: str,
) -> tuple[list[tuple[str, EntityType]], list[tuple[str, str]]]:
    seeds: list[tuple[str, EntityType]] = []
    owners: list[tuple[str, str]] = []
    for key, value in sorted(values.items()):
        entity_type = GOLD_TYPES[key]
        if phase == "with-true":
            seeds.append((value, entity_type))
            owners.append((key, "true"))
        for name in namesakes.get((doc, key), []):
            seeds.append((name, entity_type))
            owners.append((key, "namesake"))
    return seeds, owners


def _score_phase(
    *,
    doc: str,
    language: str,
    data: bytes,
    values: dict[str, str],
    namesakes: dict[tuple[str, str], list[str]],
    phase: str,
    matcher: str,
    masker: ImageMasker,
    vault: Vault,
    total: _Tally,
    tally: _Tally,
) -> None:
    session = vault.session()
    seeds, owners = _build_phase_seeds(doc, values, namesakes, phase)
    placeholders = _seed(session, seeds)
    vault_matcher = (ExactMatcher if matcher == "exact" else VaultMatcher)(session, language)
    started = time.perf_counter()
    outcome = masker.mask(data, language, render="labels", matcher=vault_matcher)
    elapsed = (time.perf_counter() - started) * 1000
    found = _image_placeholders(outcome)
    in_transcript = _transcript_placeholders(outcome)
    uncertain = outcome.matches.get("uncertain", 0)
    for t in (total, tally):
        t.uncertain += uncertain if phase == "with-true" else 0
        t.match_ms.append(elapsed)
    for (key, owner), placeholder in zip(owners, placeholders, strict=True):
        hit = placeholder in found
        type_name = GOLD_TYPES[key].value
        for t in (total, tally):
            row = t.by_type.setdefault(type_name, [0, 0, 0])
            if owner == "true":
                t.gold += 1
                row[0] += 1
                if hit:
                    t.matched += 1
                    row[1] += 1
                elif placeholder in in_transcript:
                    t.swept += 1
            elif hit:
                t.false_merges += 1
                row[2] += 1
        if owner == "true" and GOLD_TYPES[key] is EntityType.PERSON:
            total.people.setdefault((values[key], key), []).append(hit)
    if phase == "with-true":
        _record_transcript_and_leaks(session, outcome, values, (total, tally))
    vault.drop(session.session_id)


def evaluate(
    *,
    matcher: str = "fuzzy",
    noise: float = 0.0,
    root: Path = FIXTURES,
    ocr: CachedOcr | None = None,
) -> dict[str, Any]:
    """Run the placeholder-matching eval; return the report dict (counts and ratios only)."""
    ocr = ocr or CachedOcr.load(root / "ocr" / "tesseract.json")
    gold = load_gold(root)
    namesakes = load_namesakes(root / "near-namesakes.json")
    masker = ImageMasker(sam=_NoSam(), policies=PolicySet(), ocr=ocr, text_detector=RuleDetector())
    vault = Vault(EVAL_KEY)
    total = _Tally()
    started_all = time.perf_counter()
    for entry in _manifest(root):
        doc, language = entry["id"], entry["language"]
        values = gold.get(doc, {})
        if not values:
            continue
        data = (root / "images" / entry["file"]).read_bytes()
        image = load_image(data)
        masker.ocr = CachedOcr({pixel_key(image): noisy_words(ocr.words(image), noise, doc)})
        tally = total.by_language.setdefault(language, _Tally())
        for phase in ("with-true", "namesakes-only"):
            _score_phase(
                doc=doc,
                language=language,
                data=data,
                values=values,
                namesakes=namesakes,
                phase=phase,
                matcher=matcher,
                masker=masker,
                vault=vault,
                total=total,
                tally=tally,
            )
    report = _report(total, matcher=matcher, noise=noise)
    report["wall_s"] = round(time.perf_counter() - started_all, 2)
    return report


def _ratio(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def _block(t: _Tally) -> dict[str, Any]:
    predicted = t.matched + t.false_merges
    return {
        "values": t.gold,
        "matched": t.matched,
        "false_merges": t.false_merges,
        "match_accuracy": _ratio(t.matched, t.gold),
        "precision": _ratio(t.matched, predicted),
        "uncertain": t.uncertain,
        "leaked": t.leaked,
        "swept": t.swept,
        "transcripts": t.transcripts,
        "transcripts_resolved": t.transcripts_resolved,
        "by_type": {
            k: {"values": g, "matched": tp, "false_merges": fp}
            for k, (g, tp, fp) in sorted(t.by_type.items())
        },
        "match_ms_p50": percentile(t.match_ms, 0.5, 1),
        "match_ms_p95": percentile(t.match_ms, 0.95, 1),
    }


def _report(total: _Tally, *, matcher: str, noise: float) -> dict[str, Any]:
    people = total.people
    consistent = sum(all(hits) for hits in people.values())
    multi = {k: v for k, v in people.items() if len(v) > 1}
    return {
        "matcher": matcher,
        "noise": noise,
        "overall": _block(total),
        "languages": {lang: _block(t) for lang, t in sorted(total.by_language.items())},
        "consistency": {
            "people": len(people),
            "consistent": consistent,
            "multi_occurrence": len(multi),
            "multi_consistent": sum(all(v) for v in multi.values()),
        },
    }


# --- coverage: labels vs opaque ------------------------------------------------------------------


def coverage(root: Path = FIXTURES, ocr: CachedOcr | None = None) -> dict[str, Any]:
    """Text + MRZ region recall of both render modes on the fictional set (OCR only)."""
    from pii_guard.eval.visual import load_specimens, score_regions

    ocr = ocr or CachedOcr.load(root / "ocr" / "tesseract.json")
    specimens = load_specimens(root / "manifest.json", root / "labels.json", root / "images")
    masker = ImageMasker(sam=_NoSam(), policies=PolicySet(), ocr=ocr, text_detector=RuleDetector())
    vault = Vault(EVAL_KEY)
    out: dict[str, Any] = {}
    for mode in ("opaque", "labels"):
        hits_iou = hits_cov = regions = 0
        pixels_changed: list[float] = []
        for spec in specimens:
            data = spec.path.read_bytes()
            session = vault.session()
            outcome = masker.mask(
                data,
                spec.language or "hu",
                render=mode,
                matcher=VaultMatcher(session) if mode == "labels" else None,
            )
            expected = [r for r in spec.regions if r.type in ("text", "mrz")]
            covered = [r.region for r in outcome.regions if r.policy is Policy.MASK]
            scores, _ = score_regions(expected, covered, (outcome.width, outcome.height))
            regions += len(scores)
            hits_iou += sum(s.hit_iou for s in scores)
            hits_cov += sum(s.hit_coverage for s in scores)
            pixels_changed.append(_changed_share(data, outcome.image, expected))
            vault.drop(session.session_id)
        out[mode] = {
            "regions": regions,
            "recall_iou50": _ratio(hits_iou, regions),
            "recall_cov90": _ratio(hits_cov, regions),
            "gold_pixels_overwritten": round(statistics.mean(pixels_changed), 4),
        }
    return out


def _changed_share(original: bytes, masked: bytes, expected: Sequence[Any]) -> float:
    """Share of labelled-region pixels whose colour changed (a cover drawn over them)."""
    a, b = load_image(original), load_image(masked)
    width, height = a.size
    changed = total = 0
    for region in expected:
        box = region.to_pixels(width, height)
        crop_a = a.crop((box.x1, box.y1, box.x2 + 1, box.y2 + 1)).tobytes()
        crop_b = b.crop((box.x1, box.y1, box.x2 + 1, box.y2 + 1)).tobytes()
        n = len(crop_a) // 3
        total += n
        changed += sum(crop_a[i * 3 : i * 3 + 3] != crop_b[i * 3 : i * 3 + 3] for i in range(n))
    return changed / total if total else 1.0


# --- the demo ------------------------------------------------------------------------------------

#: The contract's parties: name, role, and which document the demo uploads for them.
DEMO_PARTIES: tuple[tuple[str, str, str | None], ...] = (
    ("Fiktív Mária", "eladó", "hu-id_card-front"),
    ("Erika Mustermann", "vevő", "de-id_card-front"),
    ("Fiktív Márta", "kezes", None),
)
#: The reprinted (past) expiry date of the demo's expired card.
DEMO_EXPIRED = dt.date(2025, 3, 31)
DEMO_CONTRACT = (
    "ADÁSVÉTELI SZERZŐDÉS (fiktív minta)\n"
    "Eladó: Fiktív Mária. Vevő: Erika Mustermann. Kezes: Fiktív Márta.\n"
    "Az eladó, Fiktív Mária, eladja a vevőnek, Erika Mustermannak a Kitalált utca 7. alatti "
    "lakást. Fiktív Márta kezesként felel a vételár megfizetéséért.\n"
    "A felek személyazonosságát érvényes személyazonosító okmánnyal igazolják."
)
DEMO_QUESTION = (
    "Which parties of the contract have a valid ID document among the attached images? "
    "For each party give: ID present / missing / expired."
)


@dataclass(frozen=True)
class DemoDocuments:
    """The demo inputs: the contract text, the images (PNG), and the expected answer."""

    contract: str
    question: str
    images: list[tuple[str, bytes]]
    expected: dict[str, str]  # party name -> "present" | "expired" | "missing"
    ocr: CachedOcr

    @property
    def parties(self) -> list[str]:
        return list(self.expected)

    def __repr__(self) -> str:
        return f"DemoDocuments(images={len(self.images)})"


def _demo_card_words(ocr: CachedOcr, root: Path = FIXTURES) -> tuple[Image.Image, list[list[Any]]]:
    image, words = _expired_card(ocr, root)
    return image, [_word_to_json(w) for w in words]


def _expired_card(ocr: CachedOcr, root: Path = FIXTURES) -> tuple[Image.Image, list[OcrWord]]:
    """The ``de-id_card-front`` fixture with its expiry date reprinted as :data:`DEMO_EXPIRED`,
    and its recorded OCR words with the expiry word replaced accordingly."""
    base = load_image((root / "images" / "de-id_card-front.png").read_bytes())
    words = ocr.words(base)
    expiry = next(
        v
        for v in caption_values(words, include_non_personal=True)
        if v.entity_type is None and field_name(v.caption) == "expiry"
    )
    box = expiry.box
    image = base.copy()
    draw = ImageDraw.Draw(image)
    left = image.getpixel((max(0, box.x1 - 6), box.y1 + box.height // 2))
    draw.rectangle((box.x1 - 2, box.y1 - 2, box.x2 + 40, box.y2 + 2), fill=left)
    text = DEMO_EXPIRED.strftime("%d.%m.%Y")
    font = ImageFont.load_default(size=box.height + 4)
    draw.text((box.x1, box.y1 - 3), text, fill=(20, 20, 24), font=font)
    expiry_ids = {id(w) for w in expiry.words}
    new_words: list[OcrWord] = []
    for word in words:
        if id(word) in expiry_ids:
            if word is expiry.words[0]:
                new_words.append(OcrWord(text, word.box, word.line))
            continue
        new_words.append(word)
    return image, new_words


def demo_documents(root: Path = FIXTURES, ocr: CachedOcr | None = None) -> DemoDocuments:
    """The "which parties have an ID?" demo (see :data:`DEMO_PARTIES`)."""
    ocr = ocr or CachedOcr.load(root / "ocr" / "tesseract.json")
    valid = (root / "images" / "hu-id_card-front.png").read_bytes()
    expired_image, expired_words = _expired_card(ocr, root)
    ocr.add(expired_image, expired_words)
    expired = encode_image(expired_image)
    return DemoDocuments(
        DEMO_CONTRACT,
        DEMO_QUESTION,
        [("hu-id_card-front", valid), ("de-id_card-front-expired", expired)],
        {"Fiktív Mária": "present", "Erika Mustermann": "expired", "Fiktív Márta": "missing"},
        ocr,
    )


def demo_messages(demo: DemoDocuments) -> list[dict[str, Any]]:
    """The chat request of the demo: the contract, the images, the question (one user turn)."""
    import base64

    content: list[dict[str, Any]] = [{"type": "text", "text": demo.contract}]
    for _name, png in demo.images:
        url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": url}})
    content.append({"type": "text", "text": demo.question})
    return [{"role": "user", "content": content}]


def demo_mock_answer(body: dict[str, Any]) -> str:
    """A deterministic stand-in for the upstream model: reads only what the guard forwarded
    (the masked contract and the image summaries) and answers per party, with placeholders.
    Proves the forwarded request carries enough to answer; the live run uses a real model."""
    # The user turn, not a system note the guard may have put in front of it (LAB-1471).
    parts = next(m["content"] for m in body["messages"] if m.get("role") == "user")
    contract = parts[0]["text"]
    parties = list(dict.fromkeys(m.group(0) for m in PLACEHOLDER_RE.finditer(contract)))
    parties = [p for p in parties if p.startswith("[[PERSON_")]
    holders: dict[str, bool] = {}
    for part in parts:
        text = part.get("text", "") if part.get("type") == "text" else ""
        for line in text.splitlines():
            if line.startswith("Document summary: "):
                summary = json.loads(line.removeprefix("Document summary: "))
                if summary.get("holder"):
                    holders[summary["holder"]] = bool(summary.get("expired"))
    lines = []
    for party in parties:
        if party not in holders:
            lines.append(f"- {party}: ID missing")
        elif holders[party]:
            lines.append(f"- {party}: ID card expired")
        else:
            lines.append(f"- {party}: ID card present, valid")
    return "\n".join(lines)


_STATUS_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("expired", ("expired", "lejárt", "no longer valid", "not valid")),
    (
        "missing",
        ("missing", "no id", "not provided", "hiányzik", "none", "not among", "no document"),
    ),
    ("present", ("present", "valid", "érvényes", "has an id", "provided")),
)


def _names(line: str, party: str) -> bool:
    return all(token in line for token in party.split())


def _line_status(line: str) -> str | None:
    """The status a line states: ``expired`` over ``missing`` over ``present`` (``ID present
    / expired`` is expired)."""
    lowered = line.lower()
    for name, words in _STATUS_WORDS:
        if any(word in lowered for word in words):
            return name
    return None


def score_demo_answer(answer: str, expected: dict[str, str]) -> dict[str, Any]:
    """Per party: the status the (unmasked) answer gives in the part about it, and whether
    it is the expected one. The part runs from the first line naming the party to a blank
    line or a line naming another party; its status is that of the first line in it that
    states one (a later ``expired: false`` detail is not the verdict). Counts only; the
    names stay in the caller. Lines naming the party alone are read before lines naming
    several parties."""
    found: dict[str, str | None] = {}
    lines = answer.splitlines()
    for party in expected:
        status = None
        others = [p for p in expected if p != party]
        naming = [i for i, line in enumerate(lines) if _names(line, party)]
        alone = [i for i in naming if not any(_names(lines[i], o) for o in others)]
        for index in alone + [i for i in naming if i not in alone]:
            block = [lines[index]]
            for following in lines[index + 1 :]:
                if not following.strip() or any(_names(following, o) for o in others):
                    break
                block.append(following)
            status = next((s for s in map(_line_status, block) if s is not None), None)
            if status is not None:
                break
        found[party] = status
    correct = sum(found[p] == s for p, s in expected.items())
    return {
        "parties": len(expected),
        "answered": sum(v is not None for v in found.values()),
        "correct": correct,
        "accuracy": _ratio(correct, len(expected)),
        "statuses": [found[p] for p in expected],
        "expected": list(expected.values()),
    }


# --- run records ---------------------------------------------------------------------------------
#
# The placeholder metrics map onto a ``text`` run record (eval/results/schema/run.schema.json):
# a gold "span" is a value printed on an image, a true positive is the image carrying the
# text's placeholder for it, a predicted span that is not a true positive is a false merge
# (over-masking: the wrong person's placeholder), ``consistency`` is per person, ``roundtrip``
# is every transcript placeholder resolving in the session, and ``latency_ms.mask`` is the
# whole image masking (OCR from the cache, matching, rendering) per image.


def _match_block(gold: int, tp: int, fp: int) -> dict[str, Any]:
    pred = tp + fp
    precision, recall = _ratio(tp, pred), _ratio(tp, gold)
    f1 = (
        round(2 * precision * recall / (precision + recall), 4)
        if precision and recall
        else (0.0 if gold else None)
    )
    return {
        "gold": gold,
        "pred": pred,
        "tp_pred": tp,
        "tp_gold": tp,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _text_block(block: dict[str, Any], people: dict[str, Any] | None = None) -> dict[str, Any]:
    gold, tp, fp = block["values"], block["matched"], block["false_merges"]
    match = _match_block(gold, tp, fp)
    consistency = None
    if people is not None:
        consistency = {
            "entities": people["people"],
            "consistent": people["consistent"],
            "rate": _ratio(people["consistent"], people["people"]),
            "multi_occurrence": people["multi_occurrence"],
            "multi_consistent": people["multi_consistent"],
            "multi_rate": _ratio(people["multi_consistent"], people["multi_occurrence"]),
        }
    return {
        "documents": block["transcripts"],
        "gold_spans": gold,
        "predicted_spans": tp + fp,
        "exact": match,
        "overlap": match,
        "macro_f1_overlap": match["f1"],
        "leak": {
            "values": gold,
            "leaked": block["leaked"],
            "partial": 0,
            "rate": _ratio(block["leaked"], gold),
            "partial_rate": 0.0 if gold else None,
        },
        "over_masking": {"masked": tp + fp, "over_masked": fp, "rate": _ratio(fp, tp + fp)},
        "roundtrip": {
            "documents": block["transcripts"],
            "exact": block["transcripts_resolved"],
            "rate": _ratio(block["transcripts_resolved"], block["transcripts"]),
        },
        "consistency": consistency,
        "latency_ms": {
            "detect": None,
            "mask": {"p50": block["match_ms_p50"], "p95": block["match_ms_p95"]},
        },
        "per_type": {
            name: {
                "gold": g,
                "pred": t + f,
                "exact_tp_gold": t,
                "exact_tp_pred": t,
                "overlap_tp_gold": t,
                "overlap_tp_pred": t,
                "leak": None,
                "over_masking": {"masked": t + f, "over_masked": f},
            }
            for name, row in block["by_type"].items()
            for g, t, f in [(row["values"], row["matched"], row["false_merges"])]
        },
    }


def _run_record(
    *,
    run_id: str,
    kind: str,
    fixture_set: str,
    title: str,
    notes: list[str],
    detectors: list[dict[str, Any]],
    key: str,
    label: str,
    languages: list[str],
    metrics: dict[str, Any],
    cost: dict[str, Any] | None = None,
    documents: int | None = None,
) -> dict[str, Any]:
    from pii_guard.eval import record as rec
    from pii_guard.eval.report import git_commit

    commit, dirty = git_commit()

    return {
        "schema_version": rec.RECORD_SCHEMA_VERSION,
        "run_id": run_id,
        "kind": kind,
        "date": run_id[:10],
        "recorded_at": rec.now_iso(),
        "source": "recorded",
        "imported_from": None,
        "title": title,
        "notes": notes,
        "code": {
            "commit": commit,
            "dirty": dirty,
            "pii_guard_version": "0.1.0",
            "note": None,
        },
        "system": with_role(
            {
                "key": key,
                "label": label,
                "family": "pii-guard",
                "tool": "pii-guard",
                "version": None,
                "detectors": detectors,
            }
        ),
        "fixture_set": fixture_set,
        "fixtures": [
            {
                "path": "eval/fixtures/visual/manifest.json",
                "sha256": None,
                "set": fixture_set,
                "language": None,
                "origin": "generated",
                "generator": "muse-image",
                "documents": documents,
            }
        ],
        "languages": languages,
        "hardware": {**rec.host_info(), "description": "local CPU; OCR words from the cache"},
        "cost": cost or {**rec.empty_cost(), "usd": 0.0, "estimated": True, "model_calls": 0},
        "metrics": metrics,
    }


def _matcher_detectors(matcher: str, noise: float) -> list[dict[str, Any]]:
    return [
        {
            "name": "ocr",
            "model": "tesseract",
            "model_ref": "eval/fixtures/visual/ocr/tesseract.json",
            "revision": None,
            "settings": {"cached": True, "noise": noise},
            "serving": None,
        },
        {
            "name": "rules",
            "model": None,
            "model_ref": None,
            "revision": None,
            "settings": {"captions": True},
            "serving": None,
        },
        {
            "name": "vault-match",
            "model": None,
            "model_ref": None,
            "revision": None,
            "settings": {"matcher": matcher},
            "serving": None,
        },
    ]


def placeholder_record(report: dict[str, Any], run_id: str, notes: list[str]) -> dict[str, Any]:
    """The placeholder-matching report (:func:`evaluate`) as a ``text`` run record."""
    matcher, noise = report["matcher"], report["noise"]
    fixture_set = "visual-placeholders" + ("-noisy" if noise else "")
    return _run_record(
        run_id=run_id,
        kind="text",
        fixture_set=fixture_set,
        title=f"image placeholders, {matcher} vault matching, OCR noise {noise}",
        notes=notes,
        detectors=_matcher_detectors(matcher, noise),
        key=f"visual-labels:{matcher}",
        label=f"pii-guard image placeholders ({matcher} matching)",
        languages=sorted(report["languages"]),
        metrics={
            "overall": _text_block(report["overall"], report["consistency"]),
            "languages": {k: _text_block(v) for k, v in sorted(report["languages"].items())},
        },
        documents=report["overall"]["transcripts"],
    )


BASETEN_PRICES = (1.25, 0.15, 4.25)  # USD per 1M prompt, cached-prompt, completion tokens


def demo_record(result: dict[str, Any], run_id: str, notes: list[str]) -> dict[str, Any]:
    """One run of ``examples/which_parties_have_an_id.py`` as a ``text`` run record: a gold
    span is a party, a true positive the answer giving its ID status correctly, a predicted
    span not a true positive a wrong status; ``leak`` counts party names forwarded raw."""
    score, render = result["score"], result["render"]
    parties, correct, answered = score["parties"], score["correct"], score["answered"]
    match = _match_block(parties, correct, answered - correct)
    live = result["upstream"] != "mock"
    usage = result.get("usage") or {}
    cost = None
    if live:
        from pii_guard.eval.record import empty_cost

        prompt = int(usage.get("prompt_tokens") or 0)
        cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        reasoning = int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
        p_in, p_cached, p_out = BASETEN_PRICES
        usd = ((prompt - cached) * p_in + cached * p_cached + completion * p_out) / 1e6
        cost = {
            **empty_cost(),
            "usd": round(usd, 4),
            "estimated": True,
            "model_calls": 1,
            "tokens": {
                "prompt": prompt,
                "cached": cached,
                "completion": completion,
                "reasoning": reasoning,
            },
            "note": "From the token counts the endpoint reported, at list prices.",
        }
    seconds = float(result.get("seconds") or 0.0) * 1000
    block = {
        "documents": 1,
        "gold_spans": parties,
        "predicted_spans": answered,
        "exact": match,
        "overlap": match,
        "macro_f1_overlap": match["f1"],
        "leak": {
            "values": parties,
            "leaked": int(result.get("leaked", 0)),
            "partial": 0,
            "rate": _ratio(int(result.get("leaked", 0)), parties),
            "partial_rate": 0.0,
        },
        "over_masking": {"masked": answered, "over_masked": answered - correct, "rate": None},
        "roundtrip": None,
        "consistency": None,
        "latency_ms": {
            "detect": None,
            "mask": {"p50": round(seconds, 1), "p95": round(seconds, 1)},
        },
        "per_type": {},
    }
    upstream = "Muse Spark Open (Baseten)" if live else "mock upstream"
    detectors = [
        *_matcher_detectors("fuzzy", 0.0)[:2],
        {
            "name": "upstream",
            "model": "muse-spark-open" if live else None,
            "model_ref": result["upstream"],
            "revision": None,
            "settings": {"render": render},
            "serving": "Baseten Model APIs" if live else None,
        },
    ]
    return _run_record(
        run_id=run_id,
        kind="text",
        fixture_set="demo-which-parties",
        title=f'"which parties have an ID?" demo, {render} images, {upstream}',
        notes=notes,
        detectors=detectors,
        key=f"demo-which-parties:{render}:{'live' if live else 'mock'}",
        label=f"pii-guard gateway, {render} images, {upstream}",
        languages=["hu"],
        metrics={"overall": block, "languages": {"hu": block}},
        cost=cost,
        documents=1,
    )


# --- CLI ------------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m pii_guard.eval.visual_labels")
    parser.add_argument("--matcher", choices=("fuzzy", "exact"), default="fuzzy")
    parser.add_argument("--noise", type=float, default=0.0, help="OCR noise per character")
    parser.add_argument("--coverage", action="store_true", help="also score both render modes")
    parser.add_argument("--json", type=Path, help="write the report here")
    parser.add_argument("--record-ocr", action="store_true", help="re-record the OCR cache")
    parser.add_argument("--write-namesakes", action="store_true")
    parser.add_argument(
        "--record-run", metavar="RUN_ID", help="also write eval/results/runs/RUN_ID.json"
    )
    parser.add_argument("--note", action="append", default=[], help="a note for the record")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.write_namesakes:
        return write_namesakes()
    if args.record_ocr:
        return record_ocr()
    report = evaluate(matcher=args.matcher, noise=args.noise)
    if args.coverage:
        report["coverage"] = coverage()
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
    if args.record_run:
        from pii_guard.eval.record import write_records

        write_records([placeholder_record(report, args.record_run, args.note)], overwrite=True)
    print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
