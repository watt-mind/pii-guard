"""Session placeholders for image regions, the masked transcript and the document summary.

:func:`label_image` takes what the visual pipeline found in one image (the OCR text with its
findings, the regions that will be covered) and the request's vault session, and returns:

- a **label** per covered region: the placeholder the session uses for the value there
  (``[[PERSON_a1b2c3]]``), or the region's kind plus the document holder's placeholder for
  faces, signatures and the MRZ (``PHOTO · [[PERSON_a1b2c3]]``);
- the **masked transcript**: the OCR text with every covered word replaced by its region's
  placeholder, then swept by the session for every value it already knows;
- the **document summary** (:mod:`pii_guard.visual.summary`).

Values are registered in the session exactly as text values are (:meth:`VaultSession.mask
<pii_guard.vault.VaultSession.mask>`), so a value on a card and the same value in a contract
of the same session share a placeholder, and the upstream answer unmasks with the session
as usual. OCR noise is bridged by :mod:`pii_guard.visual.fuzzy`: before a card value is
registered, it is matched against the session's values (and its pre-loaded known values); an
accepted match reuses that placeholder, an uncertain one gets a new placeholder and is
flagged (``match: "uncertain"``), never merged.

The holder of an ID document is the surname and given-name fields read together (``FIKTÍV`` +
``MÁRIA``), else a full-name field, else the MRZ name; its placeholder labels both name
fields, the portrait, the signature and the MRZ.

Fail closed (ADR 0006): a session error propagates, and a transcript or summary that still
contains a covered value raises :class:`~pii_guard.types.MaskingError`.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from pii_guard.policy import Policy
from pii_guard.types import EntityType, MaskingError, Span
from pii_guard.vault import PLACEHOLDER_RE, VaultSession, normalize_value
from pii_guard.visual.fuzzy import CONFUSION_GROUPS, Candidate, Match, match_value, name_tokens
from pii_guard.visual.mrz import MrzData, check_digit, parse_mrz
from pii_guard.visual.ocr import OcrText, OcrWord, TextFinding
from pii_guard.visual.regions import Box, Region, same_value
from pii_guard.visual.summary import (
    ID_DOCUMENTS,
    ExpiryPolicy,
    SummaryField,
    build_summary,
    document_type,
    field_name,
)

__all__ = [
    "KIND_LABELS",
    "ImageLabels",
    "RegionLabel",
    "VaultMatcher",
    "label_image",
]

logger = logging.getLogger(__name__)

#: What a covered visual region is called on its label.
KIND_LABELS: dict[EntityType, str] = {
    EntityType.FACE: "PHOTO",
    EntityType.ID_PHOTO: "PHOTO",
    EntityType.SIGNATURE: "SIGNATURE",
    EntityType.STAMP: "STAMP",
}
#: A word is replaced in the transcript when this share of its box is under a covered box.
WORD_COVER = 0.3
#: The detector name of values registered from an image.
IMAGE_DETECTOR = "image"
#: Values shorter than this (folded, letters and digits) are not checked for leaks (``M``).
MIN_LEAK_CHECK = 4
#: Longest run of OCR words :meth:`VaultMatcher.find` matches against one session value.
MAX_FIND_WORDS = 4
#: ``Region.source`` of a session value found on the image.
VAULT_SOURCE = "vault"
#: Shortest number (letters and digits, separators dropped) also looked for across tokens.
MIN_COMPACT_LEAK_CHECK = 6


@dataclass(frozen=True, slots=True)
class RegionLabel:
    """What is printed on a covered region, and the vault match behind it.

    ``placeholder``: the session placeholder of the value (``None`` for a face or signature
    with no known holder). ``match``: ``"exact"``, ``"fuzzy"`` (an existing placeholder was
    reused), ``"new"`` (no existing value came close) or ``"uncertain"`` (a close value
    exists, but not close enough: a new placeholder). ``confidence`` is the match's.
    """

    label: str | None
    placeholder: str | None
    match: str | None = None
    confidence: float | None = None


@dataclass(slots=True)
class ImageLabels:
    """The outcome of :func:`label_image`. Holds no raw value."""

    labels: list[RegionLabel]
    transcript: str
    summary: dict[str, Any]
    matches: dict[str, int] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"ImageLabels(labels={len(self.labels)}, matches={self.matches})"


class VaultMatcher:
    """Assigns session placeholders to OCR'd values, fuzzy-matching the session's values.

    One per request: it reads the session's values (and known values) once and remembers
    every value it registers, so the same name on a card front, back and MRZ, or on two
    images of one request, gets one placeholder.
    """

    def __init__(self, session: VaultSession, language: str = "hu") -> None:
        self.session = session
        self.language = language
        self._candidates: list[Candidate] = []
        self._known: dict[str, tuple[str, EntityType]] = {}
        #: Placeholders the session held before this request: the conversation's values.
        self.prior: frozenset[str] = frozenset(p for p, _t, _c in session.entities())
        for placeholder, entity_type, _count in session.entities():
            value = session.unmask(placeholder)
            if value != placeholder:
                self._candidates.append(Candidate(placeholder, entity_type, value))
        issued = {(c.entity_type, normalize_value(c.value)) for c in self._candidates}
        for index, known in enumerate(session.known_values.values()):
            if (known.entity_type, normalize_value(known.value)) in issued:
                continue  # already masked in this session: its placeholder is a candidate
            token = f"known:{index}"
            self._known[token] = (known.value, known.entity_type)
            self._candidates.append(Candidate(token, known.entity_type, known.value))

    def __repr__(self) -> str:
        return f"VaultMatcher(candidates={len(self._candidates)})"

    def match(self, value: str, entity_type: EntityType) -> Match:
        return match_value(value, entity_type, self._candidates)

    def match_one(self, value: str, candidate: Candidate) -> Match:
        """``value`` against one session value of its type (:meth:`find`)."""
        return match_value(value, candidate.entity_type, [candidate])

    def assign(self, value: str, entity_type: EntityType) -> RegionLabel:
        """The placeholder for ``value``: an accepted match's, else a newly registered one."""
        found = self.match(value, entity_type)
        if found.accepted and found.candidate is not None:
            placeholder = found.candidate.placeholder
            if placeholder in self._known:
                known_value, known_type = self._known.pop(placeholder)
                placeholder = self._register(known_value, known_type)
                self._retarget(found.candidate, placeholder)
            return RegionLabel(placeholder, placeholder, found.status, found.confidence)
        placeholder = self._register(value, entity_type)
        status = "uncertain" if found.status == "uncertain" else "new"
        confidence = found.confidence if found.status == "uncertain" else None
        return RegionLabel(placeholder, placeholder, status, confidence)

    def _retarget(self, old: Candidate, placeholder: str) -> None:
        self._candidates = [
            Candidate(placeholder, c.entity_type, c.value) if c is old else c
            for c in self._candidates
        ]

    def find(
        self, ocr: OcrText, masked_types: frozenset[EntityType] | None = None
    ) -> list[TextFinding]:
        """The session's values printed on the image where no detector found them.

        A badge prints the visitor's name with no caption and no detector finds it; the
        conversation already named that person, so the vault knows what to look for. Every
        run of up to :data:`MAX_FIND_WORDS` words on one OCR line, not already covered by a
        finding, is fuzzy-matched against the session's values (a name only by a run of as
        many words as it has: a lone surname in a footer is not the person). Accepted matches
        only, best first, never overlapping; an uncertain one is never a finding (guessing
        would cover the wrong person's placeholder). ``origin`` is ``"vault"``.

        Only findings of a masked type cover words here: a known person a weaker detector
        read as an ``ORGANIZATION`` (``keep``) is still found, so a known value wins over keep
        and the pixels agree with the transcript sweep (LAB-1351).
        """
        candidates = [
            c for c in self._candidates if masked_types is None or c.entity_type in masked_types
        ]
        if not candidates:
            return []
        covered = [
            f.region.box
            for f in ocr.findings
            if masked_types is None or f.region.entity_type in masked_types
        ]
        free = [
            w
            for w in ocr.words
            if not any(
                _overlap(w.box, box) >= WORD_COVER * w.box.width * w.box.height for box in covered
            )
        ]
        lines: dict[tuple[int, ...], list[OcrWord]] = {}
        for word in free:
            lines.setdefault(word.line, []).append(word)
        hits: list[tuple[float, int, tuple[int, ...], int, Candidate]] = []
        for key, words in lines.items():
            for start in range(len(words)):
                for size in range(1, min(MAX_FIND_WORDS, len(words) - start) + 1):
                    run = words[start : start + size]
                    text = " ".join(w.text for w in run)
                    if sum(c.isalnum() for c in text) < MIN_LEAK_CHECK:
                        continue
                    for candidate in candidates:
                        if (
                            candidate.entity_type is EntityType.PERSON
                            and len(name_tokens(candidate.value)) != size
                        ):
                            continue
                        found = self.match_one(text, candidate)
                        if found.accepted:
                            hits.append((found.confidence, -size, key, start, candidate))
        hits.sort(key=lambda h: (h[0], h[1]), reverse=True)
        taken: set[tuple[tuple[int, ...], int]] = set()
        out: list[TextFinding] = []
        for _confidence, negative_size, key, start, candidate in hits:
            span = [(key, i) for i in range(start, start - negative_size)]
            if any(item in taken for item in span):
                continue
            taken.update(span)
            run = lines[key][start : start - negative_size]
            box = Box(
                min(w.box.x1 for w in run),
                min(w.box.y1 for w in run),
                max(w.box.x2 for w in run),
                max(w.box.y2 for w in run),
            )
            region = Region(candidate.entity_type, box, None, VAULT_SOURCE)
            out.append(TextFinding(region, " ".join(w.text for w in run), "vault"))
        return out

    def sweep(self, text: str, masked_types: frozenset[EntityType] | None = None) -> str:
        """``text`` with every session value it spells out (whole tokens, case- and
        accent-insensitive; a number also with other separators) replaced by its placeholder.

        The transcript's backstop for values the image detectors missed but the conversation
        already named: a letter's signer named in the contract is masked in the transcript
        even when no detector found it on the image. Known values not yet issued get their
        placeholder here. ``masked_types``: only these types (``None``: all).
        """
        tokens = [_token_span(m) for m in _TOKEN_RE.finditer(text)]
        values = [(c.value, c.entity_type, c.placeholder) for c in self._candidates]
        values += [(v, t, token) for token, (v, t) in self._known.items()]
        values.sort(key=lambda item: -len(item[0]))
        cuts: list[tuple[int, int, str]] = []
        taken: set[int] = set()
        for value, entity_type, placeholder in values:
            if masked_types is not None and entity_type not in masked_types:
                continue
            needle = _alnum_tokens(value)
            if not needle or sum(len(t) for t in needle) < MIN_LEAK_CHECK:
                continue
            compact = "".join(needle)
            n = len(needle)
            for i in range(len(tokens)):
                run = None
                if [t for _s, _e, t in tokens[i : i + n]] == needle:
                    run = (i, i + n)
                elif n > 1 and any(c.isdigit() for c in compact) and tokens[i][2] == compact:
                    run = (i, i + 1)
                if run is None or any(j in taken for j in range(*run)):
                    continue
                if placeholder in self._known:
                    known_value, known_type = self._known.pop(placeholder)
                    placeholder = self._register(known_value, known_type)
                taken.update(range(*run))
                cuts.append((tokens[run[0]][0], tokens[run[1] - 1][1], placeholder))
        for start, end, placeholder in sorted(cuts, reverse=True):
            text = text[:start] + placeholder + text[end:]
        return text

    def _register(self, value: str, entity_type: EntityType) -> str:
        value = value.strip()
        if not value or entity_type.is_visual:
            raise MaskingError(f"cannot register an empty {entity_type.value} value")
        span = Span(0, len(value), entity_type, value, 1.0, IMAGE_DETECTOR)
        result = self.session.mask_with_report(value, [span], language=self.language)
        placeholder = next(p for start, _end, p in result.replacements if start == 0)
        if not any(c.placeholder == placeholder for c in self._candidates):
            self._candidates.append(Candidate(placeholder, entity_type, value))
        return placeholder


@dataclass(frozen=True, slots=True)
class _Holder:
    label: RegionLabel
    tokens: frozenset[str]


def _person_fields(findings: Sequence[TextFinding]) -> dict[str, list[TextFinding]]:
    out: dict[str, list[TextFinding]] = {}
    for finding in findings:
        if finding.origin == "caption" and finding.region.entity_type is EntityType.PERSON:
            name = field_name(finding.caption, EntityType.PERSON) or "name"
            out.setdefault(name, []).append(finding)
    return out


def _holder_text(fields: dict[str, list[TextFinding]], mrz: MrzData | None) -> str | None:
    """Surname + given names read together, else a full name, else the MRZ name."""
    given = fields.get("given_names")
    surname = fields.get("surname") or fields.get("name")
    if given and surname:
        return f"{surname[0].text} {given[0].text}"
    for name in ("name", "surname"):
        if fields.get(name):
            return fields[name][0].text
    if mrz is not None and mrz.name:
        return mrz.name
    return None


#: OCR confusions tried for an MRZ document number beyond :data:`CONFUSION_GROUPS`:
#: Tesseract reads ``J`` for ``I`` on OCR-B. Not a global confusion: one letter read for
#: another is another document (LAB-1211); the check digit gates the substitution here.
_MRZ_EXTRA_CONFUSIONS = ("IJ", "ij")


def mrz_number_fixes(mrz: MrzData) -> list[str]:
    """The document number with one OCR-confusion substitution that makes its check digit
    pass (LAB-1197): Tesseract reads ``O`` for ``0``, ``I`` for ``1`` (and ``J`` for ``I``
    on OCR-B) and the like; the digit says which read is right. ``[]`` when the check
    digit itself is unreadable or nothing passes."""
    check = mrz.number_check
    if len(check) != 1 or not check.isdigit() or not mrz.document_number:
        return []
    out: list[str] = []
    for index, char in enumerate(mrz.document_number):
        for group in (*CONFUSION_GROUPS, *_MRZ_EXTRA_CONFUSIONS):
            if char.casefold() not in group:
                continue
            for alt in group:
                if not alt.isalnum() or alt == char.casefold():
                    continue
                fixed = alt.upper() if alt.isalpha() else alt
                variant = mrz.document_number[:index] + fixed + mrz.document_number[index + 1 :]
                if check_digit(variant) == check and variant not in out:
                    out.append(variant)
    return out


def _overlap(a: Box, b: Box) -> int:
    ix = min(a.x2, b.x2) - max(a.x1, b.x1) + 1
    iy = min(a.y2, b.y2) - max(a.y1, b.y1) + 1
    return ix * iy if ix > 0 and iy > 0 else 0


def _best_finding(region: Region, labelled: Sequence[tuple[TextFinding, RegionLabel]]) -> int:
    """The finding behind ``region``: its own if it is one, else the same-type finding that
    overlaps it most, ties going to the tightest box. A value inside a wide read of the row
    keeps its own finding's label, not the wide read's (LAB-1672)."""
    best, best_key = -1, (0, 0)
    for index, (finding, _label) in enumerate(labelled):
        if finding.region.entity_type is not region.entity_type:
            continue
        if finding.region is region:
            return index
        area = _overlap(finding.region.box, region.box)
        key = (area, -finding.region.box.width * finding.region.box.height)
        if area > 0 and key > best_key:
            best, best_key = index, key
    return best


def _same_text(a: str, b: str) -> bool:
    """Whether the shorter read's tokens (folded, letters and digits) are a contiguous run of
    the longer read's: ``ZX123456`` and ``ZX123456 UTO`` are one value, ``ZX123456`` and
    ``ZX123457 UTO`` are not."""
    ta, tb = _alnum_tokens(a), _alnum_tokens(b)
    short, long = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if not short:
        return False
    n = len(short)
    return any(long[k : k + n] == short for k in range(len(long) - n + 1))


def _unify(
    covered: Sequence[tuple[Region, Policy]],
    labels: list[RegionLabel],
    reads: dict[int, tuple[str, str]],
    prior: frozenset[str],
    preferred: frozenset[str] = frozenset(),
) -> tuple[list[RegionLabel], dict[str, str]]:
    """One label for masked text regions of one type that read the same value (LAB-1672).

    Two detectors often read one printed value: the caption read is tight
    (``[319,264,429,294]``), an NER read runs along the row (``[321,266,695,292]``), and each
    got its own placeholder. Printed as two labels in overlapping covers, neither is
    readable, and the transcript names the value twice.

    ``reads`` maps a region's index to its finding's ``(origin, text)``. Regions join a group
    only when every pair in it is :func:`~pii_guard.visual.regions.same_value` and
    :func:`_same_text` (one read is a contiguous run of the other). Never unified:

    - a region whose overlapping same-type neighbours are not the same value as each other
      (a wide NER box over two distinct numbers keeps its own label, so neither number's
      placeholder is handed to the other);
    - a group that overlaps another same-type masked region outside it;
    - a read whose own vault match was ``uncertain`` (the matcher's gate stands), and a
      region with no finding or no placeholder.

    The group's label: the holder's placeholder (``preferred``), else one the session held
    before this request (the conversation's value), else a reused match
    (``exact``/``fuzzy``), else the caption read's, else the tightest box's. Only labels
    change: every region is still covered with its own box. Returns the labels and each
    losing placeholder's winner, so the summary and other labels can follow.
    """
    candidates = [
        i
        for i, (region, policy) in enumerate(covered)
        if policy is Policy.MASK and not region.entity_type.is_visual
    ]

    def near(i: int, j: int) -> bool:
        a, b = covered[i][0], covered[j][0]
        return a.entity_type is b.entity_type and same_value(a.box, b.box)

    neighbours = {i: [j for j in candidates if j != i and near(i, j)] for i in candidates}
    ambiguous = {
        i
        for i, around in neighbours.items()
        if any(not near(a, b) for a, b in combinations(around, 2))
    }
    joinable = [
        i
        for i in candidates
        if i not in ambiguous
        and i in reads
        and labels[i].placeholder is not None
        and labels[i].match != "uncertain"
    ]

    def same(i: int, j: int) -> bool:
        return near(i, j) and _same_text(reads[i][1], reads[j][1])

    root = {i: i for i in joinable}

    def find(i: int) -> int:
        while root[i] != i:
            root[i] = root[root[i]]
            i = root[i]
        return i

    for i, j in combinations(joinable, 2):
        if same(i, j):
            root[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in joinable:
        groups.setdefault(find(i), []).append(i)

    def rank(i: int) -> tuple[bool, bool, bool, bool, int]:
        label, box = labels[i], covered[i][0].box
        return (
            label.placeholder in preferred,
            label.placeholder in prior,
            label.match in ("exact", "fuzzy"),
            reads[i][0] == "caption",
            -box.width * box.height,
        )

    out = list(labels)
    winners: dict[str, str] = {}
    for group in groups.values():
        members = set(group)
        if len({labels[i].placeholder for i in group}) < 2:
            continue
        if not all(same(i, j) for i, j in combinations(group, 2)):
            continue
        if any(j not in members for i in group for j in neighbours[i]):
            continue
        best = labels[max(group, key=rank)]
        for i in group:
            loser = labels[i].placeholder
            if loser is not None and loser != best.placeholder and best.placeholder:
                winners[loser] = best.placeholder
            out[i] = best
    if winners:
        out = [_remap(label, winners) for label in out]
    return out, winners


def _remap(label: RegionLabel, winners: dict[str, str]) -> RegionLabel:
    """``label`` naming the winner of a unified placeholder (``MRZ · …`` included)."""
    old = label.placeholder
    if old is None or old not in winners:
        return label
    new = winners[old]
    text = label.label.replace(old, new) if label.label else label.label
    return RegionLabel(text, new, label.match, label.confidence)


def _kind_label(entity_type: EntityType, holder: _Holder | None) -> RegionLabel:
    kind = KIND_LABELS.get(entity_type, entity_type.value)
    if holder is None or holder.label.placeholder is None:
        return RegionLabel(kind, None)
    placeholder = holder.label.placeholder
    return RegionLabel(f"{kind} · {placeholder}", placeholder, holder.label.match)


#: The transcript token for a non-personal expiry value under ``expiry="reduce"``.
EXPIRY_MARKER = "[EXPIRY]"


def _expiry_redactions(ocr: OcrText | None, expiry: ExpiryPolicy) -> list[tuple[Box, str]]:
    """The expiry value boxes to redact in the transcript when ``expiry="reduce"``
    (LAB-1196): ``reduce`` then means the same in the transcript as in the summary.
    Empty under ``expiry="keep"``: the date stays verbatim."""
    if ocr is None or expiry != "reduce":
        return []
    return [
        (value.box, EXPIRY_MARKER) for value in ocr.fields if field_name(value.caption) == "expiry"
    ]


def _transcript(
    words: Sequence[OcrWord],
    covered: Sequence[tuple[Box, RegionLabel]],
    redacted: Sequence[tuple[Box, str]] = (),
) -> str:
    """The OCR text, lines kept, with every covered word replaced by its region's token
    (the placeholder, or ``[PHOTO · [[PERSON_x]]]`` for a labelled visual region / MRZ).
    Consecutive words of one region collapse into one token. ``redacted`` additionally
    replaces the words under its boxes with a fixed marker (the ``[EXPIRY]`` transcript
    redaction); a covered word keeps its placeholder."""
    parts: list[str] = []
    previous_line: tuple[int, ...] | None = None
    previous_token: str | None = None
    for word in words:
        area = word.box.width * word.box.height
        best: RegionLabel | None = None
        best_area, best_size = 0, 0
        for box, label in covered:
            inter = _overlap(word.box, box)
            size = box.width * box.height
            # Ties go to the tightest cover: a word inside a wide read of the row and inside
            # its own value's box is that value (LAB-1672).
            if inter > best_area or (inter and inter == best_area and size < best_size):
                best, best_area, best_size = label, inter, size
        replaced = best is not None and best_area >= WORD_COVER * area
        token = word.text
        if replaced and best is not None:
            if best.placeholder is not None and best.label == best.placeholder:
                token = best.placeholder
            else:
                token = f"[{best.label or 'MASKED'}]"
        elif redacted:
            for box, marker in redacted:
                if _overlap(word.box, box) >= WORD_COVER * area:
                    token, replaced = marker, True
                    break
        if word.line != previous_line:
            if parts:
                parts.append("\n")
        elif replaced and token == previous_token:
            continue
        else:
            parts.append(" ")
        parts.append(token)
        previous_line, previous_token = word.line, (token if replaced else None)
    return "".join(parts)


_TOKEN_RE = re.compile(r"\[\[[A-Z0-9_]+\]\]|[^\s<]+")


def _token_span(match: re.Match[str]) -> tuple[int, int, str]:
    """A token's offsets without its leading and trailing punctuation, and its folded form."""
    token, start, end = match.group(0), match.start(), match.end()
    while start < end and not _text_char(token[start - match.start()]):
        start += 1
    while end > start and not _text_char(token[end - 1 - match.start()]):
        end -= 1
    return start, end, _alnum_token(token)


def _text_char(char: str) -> bool:
    return char.isalnum() or char in "[]_"


def _alnum_token(token: str) -> str:
    if PLACEHOLDER_RE.fullmatch(token):
        return ""  # never part of a value
    return "".join(c for c in "".join(name_tokens(token)) if c.isalnum())


def _alnum_tokens(text: str) -> list[str]:
    tokens = ("".join(c for c in t if c.isalnum()) for t in name_tokens(text))
    return [t for t in tokens if t]


def _leaks(text: str, values: Sequence[str]) -> bool:
    """Whether any value (as a run of whole tokens, accent- and case-insensitive) is in
    ``text``. Checked: values with a digit or of two or more tokens, of at least
    :data:`MIN_LEAK_CHECK` characters. A one-word name alone is not (``Fiktív`` is a surname
    on a card and a word in its footer); the sweep still masks it wherever the vault finds it.
    """
    haystack = _alnum_tokens(text)
    for value in values:
        needle = _alnum_tokens(value)
        if not needle or sum(len(t) for t in needle) < MIN_LEAK_CHECK:
            continue
        if len(needle) < 2 and not any(c.isdigit() for c in needle[0]):
            continue
        n = len(needle)
        if any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1)):
            return True
        compact = "".join(needle)
        # A number written with other separators (123-456-788): fail closed.
        if (
            any(c.isdigit() for c in compact)
            and len(compact) >= MIN_COMPACT_LEAK_CHECK
            and compact in "".join(haystack)
        ):
            return True
    return False


def label_image(
    ocr: OcrText | None,
    covered: Sequence[tuple[Region, Policy]],
    matcher: VaultMatcher,
    *,
    expiry: ExpiryPolicy = "reduce",
    today: dt.date | None = None,
    masked_types: frozenset[EntityType] | None = None,
) -> ImageLabels:
    """Label every ``covered`` region (``(region, policy)``, in output order) and build the
    transcript and summary. Regions whose policy is not ``mask`` get an empty label.

    ``masked_types``: the text types whose policy is ``mask``; findings of other types
    (``keep``) are not registered in the session. ``None``: every type is masked.
    """
    findings = ocr.findings if ocr is not None else []
    if masked_types is not None:
        findings = [f for f in findings if f.region.entity_type in masked_types]
    words = ocr.words if ocr is not None else []
    text = " ".join(w.text for w in words)
    mrz_data: MrzData | None = None
    if ocr is not None:
        for zone in ocr.zones:
            mrz_data = parse_mrz(zone.lines)
            if mrz_data is not None:
                break
    is_id = document_type(text, mrz_data) in ID_DOCUMENTS or mrz_data is not None

    labelled: list[tuple[TextFinding, RegionLabel]] = []
    summary_fields: list[SummaryField] = []
    matches: dict[str, int] = {}
    holder: _Holder | None = None
    person_fields = _person_fields(findings)
    holder_value = _holder_text(person_fields, mrz_data) if is_id else None
    holder_findings: set[int] = set()
    if holder_value:
        label = matcher.assign(holder_value, EntityType.PERSON)
        holder = _Holder(label, frozenset(name_tokens(holder_value)))
        matches[label.match or "new"] = matches.get(label.match or "new", 0) + 1
        for name in ("surname", "given_names", "name"):
            for finding in person_fields.get(name, ()):
                if set(name_tokens(finding.text)) <= holder.tokens:
                    holder_findings.add(id(finding))
                    summary_fields.append(
                        SummaryField(name, label.placeholder or "", label.match or "new")
                    )
    mrz_document: str | None = None
    if mrz_data is not None and mrz_data.document_number:
        # A valid zone's number is registered; a misread one is only matched, never stored.
        if mrz_data.valid:
            mrz_document = matcher.assign(
                mrz_data.document_number, EntityType.ID_DOCUMENT
            ).placeholder
        else:
            # A misread zone's number is only matched, never stored. First as read, then
            # the check-digit-gated OCR-confusion fixes (LAB-1197). A fix reconstructs the
            # printed number with the digit's certainty, so it must match exactly: a fuzzy
            # reuse could merge a near-namesake the digit ruled out.
            found = matcher.match(mrz_data.document_number, EntityType.ID_DOCUMENT)
            if (
                found.accepted
                and found.candidate is not None
                and not found.candidate.placeholder.startswith("known:")
            ):
                mrz_document = found.candidate.placeholder
            else:
                for fix in mrz_number_fixes(mrz_data):
                    fixed = matcher.match(fix, EntityType.ID_DOCUMENT)
                    if (
                        fixed.status == "exact"
                        and fixed.candidate is not None
                        and not fixed.candidate.placeholder.startswith("known:")
                    ):
                        mrz_document = fixed.candidate.placeholder
                        break
    for finding in findings:
        if id(finding) in holder_findings and holder is not None:
            labelled.append((finding, holder.label))
            continue
        if finding.origin == "mrz":
            target = mrz_document or (holder.label.placeholder if holder else None)
            text_label = f"MRZ · {target}" if target else "MRZ"
            labelled.append((finding, RegionLabel(text_label, target, None)))
            continue
        label = matcher.assign(finding.text, finding.region.entity_type)
        matches[label.match or "new"] = matches.get(label.match or "new", 0) + 1
        labelled.append((finding, label))
        name = field_name(finding.caption, finding.region.entity_type) if finding.caption else None
        if finding.origin == "caption" and name is not None and label.placeholder:
            summary_fields.append(SummaryField(name, label.placeholder, label.match or "new"))
    if mrz_document is not None and not any(f.name == "document_number" for f in summary_fields):
        summary_fields.append(SummaryField("document_number", mrz_document, "new"))

    region_labels: list[RegionLabel] = []
    reads: dict[int, tuple[str, str]] = {}
    for position, (region, policy) in enumerate(covered):
        if policy is not Policy.MASK:
            region_labels.append(RegionLabel(None, None))
            continue
        if region.entity_type.is_visual:
            label = _kind_label(region.entity_type, holder)
        else:
            index = _best_finding(region, labelled)
            label = (
                labelled[index][1] if index >= 0 else RegionLabel(region.entity_type.value, None)
            )
            if index >= 0:
                finding = labelled[index][0]
                reads[position] = (finding.origin, finding.text)
        region_labels.append(label)
    region_labels, winners = _unify(
        covered,
        region_labels,
        reads,
        getattr(matcher, "prior", frozenset()),
        frozenset({holder.label.placeholder})
        if holder and holder.label.placeholder
        else frozenset(),
    )
    summary_fields = [
        SummaryField(f.name, winners.get(f.placeholder, f.placeholder), f.status)
        for f in summary_fields
    ]
    covered_boxes = [
        (region.box, label)
        for (region, policy), label in zip(covered, region_labels, strict=True)
        if policy is Policy.MASK
    ]

    transcript = _transcript(words, covered_boxes, _expiry_redactions(ocr, expiry))
    transcript = matcher.sweep(transcript, masked_types)
    transcript = matcher.session.mask(transcript, [], language=matcher.language, remask=True)
    summary = build_summary(
        text=text,
        fields=summary_fields,
        caption_fields=ocr.fields if ocr is not None else [],
        mrz=mrz_data,
        holder=(
            SummaryField("holder", holder.label.placeholder or "", holder.label.match or "new")
            if holder is not None
            else None
        ),
        holder_confidence=holder.label.confidence if holder is not None else None,
        expiry=expiry,
        today=today,
    )
    values = [f.text for f, _ in labelled if f.origin != "mrz"]
    if holder_value:
        values.append(holder_value)
    if mrz_data is not None:
        values.extend(v for v in (mrz_data.document_number, mrz_data.name) if v)
    if _leaks(transcript, values) or _leaks(repr(summary), values):
        raise MaskingError("image transcript or summary would contain a covered value")
    logger.debug("image labels: %d region(s), matches=%s", len(region_labels), matches)
    return ImageLabels(region_labels, transcript, summary, matches)
