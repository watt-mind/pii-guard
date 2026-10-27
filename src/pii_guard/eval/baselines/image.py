"""Open-source image redaction baselines for ``pii-guard eval visual --baseline NAME``.

Each tool runs as a worker process in its own pinned ``uv`` environment, like the text
baselines (:mod:`pii_guard.eval.baselines.worker`), behind the line protocol in
``workers/_image_protocol.py``. The visual eval sends every image (the same downscaled PNG
pii-guard gets) and scores the boxes the tool would black out with the same scorer.

- ``presidio-image``: Presidio Image Redactor's ``ImageAnalyzerEngine`` (Tesseract + Presidio
  analyzer), defaults; spaCy models for en/de/hu (``workers/presidio_image_worker.py``).
- ``presidio-image-tuned``: the same, with Tesseract reading ``hun+eng`` on images enlarged
  to 2000 px, i.e. the OCR input pii-guard's own pipeline uses.
- ``eka``: Eka PII Redaction's ``ImagePIIRedactor`` (LayoutLMv3 text PII + YOLO visual
  entities), defaults, CPU (``workers/eka_worker.py``).
- ``eka-tuned``: the same with pii-guard's OCR input (``hun+eng``, 2000 px).

Text tools return one box per OCR word. :func:`merge_word_boxes` joins a detected entity's
words on the same text line into one box, the rule pii-guard applies to its own spans, so a
multi-word value is scored as one region for every system.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pii_guard.eval.baselines.base import BaselineUnavailable
from pii_guard.eval.baselines.mapping import map_label
from pii_guard.eval.baselines.worker import ENVS_DIR, WORKERS_DIR, uv_command, worker_env
from pii_guard.types import DetectionError, EntityType
from pii_guard.visual.regions import Box, Region

__all__ = [
    "IMAGE_BASELINES",
    "ImageWorkerBaseline",
    "WordBox",
    "create_image_baseline",
    "merge_word_boxes",
    "region_kinds",
]

#: Tuned settings: the OCR input pii-guard's own pipeline uses (Tesseract ``hun+eng``, images
#: enlarged to 2000 px on the longer side; :mod:`pii_guard.visual.ocr`).
TUNED_ARGS = ("--ocr-lang", "hun+eng", "--upscale-to", "2000")

#: Region kinds a tool can mask -> the eval's region types they can find.
_KIND_TYPES = {"text": ("text", "mrz"), "face": ("portrait",), "signature": ("signature",)}

_VISUAL_TYPES = {
    "face_photo": EntityType.FACE,
    "signature": EntityType.SIGNATURE,
    "seal_stamp": EntityType.STAMP,
}
#: Eka's coarse text groups -> the nearest pii-guard type (only used for ``matched_by``).
_EKA_GROUPS = {
    "person": EntityType.PERSON,
    "location": EntityType.ADDRESS,
    "date_time": EntityType.DATE_OF_BIRTH,
    "contact": EntityType.PHONE,
}


def region_kinds(supports: Sequence[str]) -> set[str]:
    """The eval region types (``text``, ``mrz``, ``portrait``, ``signature``) a tool masks."""
    return {t for kind in supports for t in _KIND_TYPES.get(kind, ())}


def entity_type_for(label: str, kind: str) -> EntityType:
    """A pii-guard type for a tool's label, for the report's ``matched_by`` only: every box a
    tool returns is masked and scored whatever its label."""
    if kind == "visual":
        return _VISUAL_TYPES.get(label, EntityType.STAMP)
    mapped = map_label(label)
    if mapped is not None:
        return mapped
    for prefix, entity_type in _EKA_GROUPS.items():
        if prefix in label:
            return entity_type
    return EntityType.ID_DOCUMENT


@dataclass(frozen=True, slots=True)
class WordBox:
    box: Box
    label: str
    kind: str
    group: str | None
    score: float | None


def _same_line(a: Box, b: Box) -> bool:
    ca, cb = (a.y1 + a.y2) / 2, (b.y1 + b.y2) / 2
    return abs(ca - cb) <= 0.5 * max(a.height, b.height)


def merge_word_boxes(words: Sequence[WordBox], max_gap: float = 1.5) -> list[WordBox]:
    """Merge the word boxes of each ``group`` per text line into one box.

    Words of a group whose vertical centres are within half a line height are on one line;
    on a line, a word joins the box to its left when the horizontal gap is at most
    ``max_gap`` line heights. Boxes without a group (visual entities) are kept as they are.
    """
    out: list[WordBox] = [w for w in words if w.group is None]
    groups: dict[str, list[WordBox]] = {}
    for w in words:
        if w.group is not None:
            groups.setdefault(w.group, []).append(w)
    for members in groups.values():
        lines: list[list[WordBox]] = []
        for w in sorted(members, key=lambda m: (m.box.y1 + m.box.y2) / 2):
            for line in lines:
                if _same_line(line[0].box, w.box):
                    line.append(w)
                    break
            else:
                lines.append([w])
        for line in lines:
            line.sort(key=lambda m: m.box.x1)
            height = max(m.box.height for m in line)
            current = line[0]
            for w in line[1:]:
                if w.box.x1 - current.box.x2 <= max_gap * height:
                    scores = [s for s in (current.score, w.score) if s is not None]
                    score = max(scores) if scores else None
                    current = WordBox(
                        current.box.union(w.box), current.label, current.kind, current.group, score
                    )
                else:
                    out.append(current)
                    current = w
            out.append(current)
    return out


class ImageWorkerBaseline:
    """An image baseline served by a worker process. Starting it blocks until it is ready."""

    def __init__(self, name: str, command: Sequence[str], *, env: dict[str, str] | None = None):
        self.name = name
        debug = os.environ.get("PII_GUARD_BASELINE_DEBUG") == "1"
        try:
            self._proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                list(command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None if debug else subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                env=worker_env() if env is None else env,
            )
        except OSError as exc:
            raise BaselineUnavailable(f"worker could not start ({type(exc).__name__})") from None
        ready = self._read()
        if not ready or not ready.get("ready"):
            code = self.close()
            raise BaselineUnavailable(
                f"worker exited (code {code}) before it was ready; "
                "rerun with PII_GUARD_BASELINE_DEBUG=1 to see its output"
            )
        self.info: dict[str, Any] = ready.get("info", {})
        self.supports: set[str] = region_kinds(self.info.get("supports", ["text"]))
        self._next_id = 0

    def _read(self) -> dict[str, Any] | None:
        stdout = self._proc.stdout
        line = stdout.readline() if stdout is not None else ""
        if not line:
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None

    def mask(self, image: bytes, language: str) -> tuple[list[Region], float]:
        """The regions the tool would black out in ``image`` (PNG bytes), and its time (ms)."""
        self._next_id += 1
        request = {
            "id": self._next_id,
            "image": base64.b64encode(image).decode("ascii"),
            "language": language,
        }
        try:
            if self._proc.stdin is None:
                raise OSError("no stdin")
            self._proc.stdin.write(json.dumps(request) + "\n")
            self._proc.stdin.flush()
        except OSError:
            raise DetectionError(f"{self.name} baseline worker is gone") from None
        reply = self._read()
        if reply is None or reply.get("id") != self._next_id:
            raise DetectionError(f"{self.name} baseline worker sent no valid reply")
        if "error" in reply:
            raise DetectionError(f"{self.name} baseline failed on an image ({reply['error']})")
        words = [
            WordBox(
                Box(*(int(v) for v in r["box"])),
                str(r["label"]),
                str(r.get("kind") or "text"),
                r.get("group"),
                r.get("score"),
            )
            for r in reply["regions"]
        ]
        regions = [
            Region(
                entity_type_for(w.label, w.kind),
                w.box,
                None if w.score is None else min(1.0, max(0.0, float(w.score))),
                self.name,
            )
            for w in merge_word_boxes(words)
        ]
        return regions, float(reply["ms"])

    def close(self) -> int | None:
        """Stop the worker; returns its exit code."""
        if self._proc.stdin is not None:
            with contextlib.suppress(OSError):
                self._proc.stdin.close()
        try:
            code = self._proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            code = self._proc.wait()
        if self._proc.stdout is not None:
            self._proc.stdout.close()
        return code


def _worker(name: str, env: str, script: str, *args: str) -> ImageWorkerBaseline:
    return ImageWorkerBaseline(
        name, [*uv_command(ENVS_DIR / f"{env}.txt", WORKERS_DIR / script), *args]
    )


IMAGE_BASELINES: dict[str, Callable[[], ImageWorkerBaseline]] = {
    "presidio-image": lambda: _worker(
        "presidio-image", "presidio-image", "presidio_image_worker.py"
    ),
    "presidio-image-tuned": lambda: _worker(
        "presidio-image-tuned", "presidio-image", "presidio_image_worker.py", *TUNED_ARGS
    ),
    "eka": lambda: _worker("eka", "eka", "eka_worker.py"),
    "eka-tuned": lambda: _worker("eka-tuned", "eka", "eka_worker.py", *TUNED_ARGS),
}


def create_image_baseline(name: str) -> ImageWorkerBaseline:
    """Start one image baseline by name; :class:`BaselineUnavailable` if it can't run here."""
    try:
        factory = IMAGE_BASELINES[name]
    except KeyError:
        raise BaselineUnavailable(
            f"unknown image baseline (known: {', '.join(sorted(IMAGE_BASELINES))})"
        ) from None
    return factory()
