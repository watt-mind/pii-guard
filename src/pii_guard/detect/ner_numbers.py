"""Cue and format checks for the numbers the NER model proposes (LAB-1293).

A v2 NER checkpoint (LAB-1150) proposes ``ID_DOCUMENT``, ``BANK_ACCOUNT`` and the Hungarian tax
and TAJ numbers, so a number whose checksum fails, or whose format no rule knows, is still
masked. The price was over-masking: the model also tags long numbers that are not personal
data, mostly when no word says what they are. On agent-traffic-dev 223 of the 253 over-masked
spans were these types: order and ticket numbers, SKUs, request and tool-call ids, tracking
numbers, an amount glued to the field before it, or a few digits cut out of a longer token.

:func:`check_numbers` runs on the NER spans of :data:`NUMBER_TYPES` before they leave the
detector, plus a split-only pass over :data:`_SPLIT_TYPES` (``PHONE``). Every other type
passes untouched. For each span:

1. **Fields.** A span that runs over a field separator (``,`` ``;`` ``|`` ``=`` a quote, a
   tab or a newline, as in ``SO4760429,77445.68``) is cut into its fields, and a tracking or
   reference token inside a field (``CP279078509AT 5576 0184 …``) is cut out of it; each piece
   is judged on its own. A ``PHONE`` span is only ever split at separators: one without a
   separator passes untouched.
2. **Machine ids: drop.** A lowercase hexadecimal id with letters and digits
   (``"id": "40aebd349d7fcb76"``, ``call_…``, ``req=…``), or any piece of one, whatever its key.
3. **Positive cue: keep.** An identity, account, card, tax or phone word in the column header
   of a CSV row, or in the line before the value with no other number between (a JSON or YAML
   key, a label), keeps
   the field whatever its shape. The typed cues of every language pack (``cues.tsv``) count,
   plus the field names in :data:`_POSITIVE`.
4. **Negative cue: drop.** The column header, or a label right before the value (at most one
   word between, no other number), names something that is not personal data: an order,
   ticket, SKU, invoice, tracking or request number (:data:`_NEGATIVE`). A reference word
   earlier in a sentence does not count. An ID prefix of the value itself does
   (``ORD-2024-…``, ``SKU-…``).
5. **No cue: the shape decides.** Dropped only when the shape rules personal data out:

   - a UPS (``1Z`` + 16) or UPU S10 (``LX123456785GB``) tracking number;
   - a timestamp-style reference (LAB-1344): a ``yyyymmddhhmmss`` stamp or epoch milliseconds
     from 2020-2035 that is no valid Romanian CNP, after an optional letter prefix
     (``TR20261029141749``); a year and serial (``2025/098820``); a 3-7-7 order number. An OCR
     ``O`` for a ``0`` counts as the digit. Tuned on the synthetic ``cee-dev`` split only;
   - an amount, or part of one: a decimal (``48170.94``), the digits before ``.94``, the cents.

   Everything else is kept (fail closed). Two more drop rules were tried on a fresh synthetic
   split and left out: an uncued all-digit number that fails every card, giro and IBAN check,
   and a value of three characters or fewer. Neither removed an over-masked span that the
   rules above had not already removed, and the first dropped phone numbers that
   normalisation had joined into one digit run (``4 4 2 0 …``).

Only NER spans are checked, on the text the model saw (in the pipeline, the normalised text).
The rules are unchanged, and a validated rule span still wins in the resolver.
"""

from __future__ import annotations

import datetime as dt
import re
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Sequence
from contextvars import ContextVar
from functools import lru_cache

from pii_guard.languages import on_change
from pii_guard.types import EntityType, Span

__all__ = ["NUMBER_TYPES", "check_numbers", "cue_before", "number_verdict"]

#: The NER types these checks apply to.
NUMBER_TYPES: frozenset[EntityType] = frozenset(
    {
        EntityType.ID_DOCUMENT,
        EntityType.BANK_ACCOUNT,
        EntityType.NATIONAL_ID_HU_TAX,
        EntityType.NATIONAL_ID_HU_TAJ,
    }
)

#: Further NER types split at field separators (LAB-1380): a single-field span keeps its
#: verdict-free pass; only a span running over a separator has its fields judged on their own
#: (a phone number never holds a field separator: ``07700900316,703`` is two fields).
_SPLIT_TYPES: frozenset[EntityType] = frozenset({EntityType.PHONE})

# Field names and labels, folded (lower case, no accents). A trailing "*" takes any suffix.
# Positive: the value is (or may be) an identity, account, card or tax number.
_POSITIVE = (
    "iban", "bic", "swift", "card*", "kartya*", "karte*", "konto*", "account*", "acct",
    "bankszamla*", "szamlaszam*", "bank*", "passport*", "utlevel*", "reisepass*", "pass",
    "passnummer*", "ausweis*", "personalausweis*", "igazolvany*", "szig", "szemelyi*",
    "szemelyazonosito*", "national*", "nemzeti*", "tax*", "ado", "adoazonosito*", "adoszam*",
    "steuer*", "ssn", "nino", "taj*", "social*", "insurance*", "biztosit*", "tarsadalombiztosit*",
    "versicherung*", "sozialversicherung*", "licen*", "jogositvany*", "fuhrerschein*",
    "document*", "dokument*", "okmany*", "identity*", "identitat*", "identification*",
    "identifikation*", "personal*", "pesel", "cnp", "oib", "emso", "jmbg", "egn", "rodne*",
    "dni", "nie", "nif", "bsn", "pin", "vat", "ust*", "kontonummer*", "giro*",
)  # fmt: skip
# Negative: the value is a business or machine reference. Amount words ("amount", "Betrag")
# and generic reference words ("reference", "case", "product", "serial") are left out on
# purpose: amounts are told by their shape, and in real text an account or ID number often
# follows those words ("payment reference: <IBAN>").
_NEGATIVE = (
    "order*", "ord", "invoice*", "inv", "receipt*", "booking*", "tracking*", "shipment*",
    "shipping*", "parcel*", "consignment*", "awb", "ticket*", "sku*", "item", "items",
    "article*", "req", "request*", "trace", "span", "txn", "transaction*", "session*", "uuid",
    "guid", "hash*", "sha", "digest*", "commit*",
    "rendeles*", "megrendeles*", "sorszam*", "cikkszam*", "csomag*", "kuldemeny*", "jegy",
    "jegyszam*", "ugyszam*", "iktatoszam*", "nyugta*",
    "bestell*", "auftrag*", "artikel*", "sendung*", "rechnung*", "ticketnummer*",
    "zamowien*", "zlecen*", "faktur*", "paragon*", "przesyłk*", "przesylk*", "przesyłek",
    "paczk*", "rezerwacj*", "zgłoszen*", "zgloszen*", "transakcj*", "sledzeni*", "sygn",
    "sygnatur*", "artykuł*", "artykul*",
)  # fmt: skip

#: Words of a pack cue too generic to count on their own ("account number", "TAJ szám").
_GENERIC = frozenset({"number", "nummer", "szam", "szama", "numer", "mit", "der", "the", "ending"})

#: How far before a value the nearest cue is looked for, on the same line.
_WINDOW = 60

_FIELD_SEPARATORS = ",;|=\"'\t\n"
#: A piece of a number span on a later line shorter than this is dropped (LAB-1604).
_MIN_PIECE = 4
_WORD_RE = re.compile(r"[^\W\d_]+")
_WORD_OR_NUMBER_RE = re.compile(r"[^\W\d_]+|\d+")
#: Words of a label that don't count as words between it and its value ("order number").
_FILLER = frozenset({"number", "no", "nr", "num", "nummer", "numer", "szam", "szama", "id"})
#: A negative word counts as a value's label only this close (in words) before it.
_LABEL_WORDS = 2
_HEX_RE = re.compile(r"(?:[a-z]+_)?(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{8,}")
_UPS_RE = re.compile(r"1Z[0-9A-Z]{16}")
# The serial of an S10 id may hold an OCR "O" for a "0" (``UA222O53650HU``).
_S10_RE = re.compile(r"[A-Z]{2}[0-9O]{9}[A-Z]{2}")
#: A ``yyyymmddhhmmss`` stamp, or 13-digit epoch milliseconds, after an optional short letter
#: prefix (``TR…``, ``PAY…``): checked by :func:`_stamp` and :func:`_epoch_ms`.
_STAMP_RE = re.compile(r"(?:[A-Z]{1,4}-?)?([0-9O]{13,14})")
_YEAR_SERIAL_RE = re.compile(r"(?:[A-Z]{1,4} )?(?:19|20)\d{2}/\d{3,6}")
_ORDER_377_RE = re.compile(r"\d{3}-\d{7}-\d{7}")
_DECIMAL_RE = re.compile(r"\d{1,3}(?:[ ,.]\d{3})*[.,]\d{2}|\d+[.,]\d{2}")
_DECIMAL_AFTER_RE = re.compile(r"[.,]\d{1,2}(?![\w.,])")
_TOKEN_CHAR = re.compile(r"[0-9A-Za-z_]")
_COMMA_RE = re.compile(",")


def _lexicon(entries: Iterable[str]) -> tuple[frozenset[str], tuple[str, ...]]:
    exact = frozenset(e for e in entries if not e.endswith("*"))
    stems = tuple(sorted((e[:-1] for e in entries if e.endswith("*")), key=len, reverse=True))
    return exact, stems


@lru_cache(maxsize=1)
def _lexicons() -> tuple[tuple[frozenset[str], tuple[str, ...]], tuple[frozenset[str], ...]]:
    """(positive exact words, positive stems), (negative exact words, negative stems).

    The typed cues of every language pack join the positive words (phone cues too: a number
    after "phone" is personal data whatever type the model gave it), so a pack that adds a cue
    protects the values after it here too. The negative words are every pack's
    ``ner``-scoped ``references.tsv`` entries (LAB-1345), or the built-in :data:`_NEGATIVE`
    when no pack provides any (a language without a pack keeps its behavior).
    """
    from pii_guard.detect.rules import _pack_cues

    pos_words = list(_POSITIVE)
    for _, cues in _pack_cues():
        for cue in cues:
            if cue.entity_type is None:
                continue  # a "-" cue names something that is not personal data
            for word in _WORD_RE.findall(cue.key):
                if len(word) > 2 and word not in _GENERIC:  # "ID card" adds "card"
                    pos_words.append(word + ("*" if cue.suffix else ""))
    negatives = _pack_negatives()
    if negatives is None:
        negatives = list(_NEGATIVE)
    return _lexicon(pos_words), _lexicon(negatives)  # type: ignore[return-value]


# A new pack's reference words rebuild the lexicons, like its cue words.
on_change(_lexicons.cache_clear)


def _pack_negatives() -> list[str] | None:
    """Folded negative words from every pack's ``references.tsv``, or ``None``.

    ``None`` (no pack provides references) keeps the built-in :data:`_NEGATIVE`. Entries
    hold single words: a multi-word entry (``sygn. akt``) contributes its first token, and
    a trailing dot is not part of the folded word (``sygn.`` -> ``sygn``).
    """
    from pii_guard.languages.references import pack_references

    words: list[str] = []
    for _, entries in pack_references():
        for entry in entries:
            if entry.scope not in ("both", "ner"):
                continue  # ``rules``-only and ``weak`` entries never drop an NER number
            words.append(_fold(entry.text.split()[0].rstrip(".")) + ("*" if entry.suffix else ""))
    return words or None


def _classify_word(word: str) -> bool | None:
    """True for a positive cue word, False for a negative one, None for neither."""
    (pos_exact, pos_stems), (neg_exact, neg_stems) = _lexicons()
    if word in pos_exact or any(word.startswith(s) for s in pos_stems):
        return True
    if word in neg_exact or any(word.startswith(s) for s in neg_stems):
        return False
    return None


def _fold(text: str) -> str:
    # Not at import time, and the rules first: languages.cues and the rules import each other.
    import pii_guard.detect.rules  # noqa: F401
    from pii_guard.languages.cues import fold

    return fold(text)


def _classify_label(label: str) -> bool | None:
    """The cue of a label (a CSV header, a key): its last cue word wins, positive over none."""
    verdict: bool | None = None
    for m in _WORD_RE.finditer(_fold(label)):
        word_verdict = _classify_word(m.group())
        if word_verdict is not None:
            verdict = word_verdict
    return verdict


def cue_before(text: str, start: int, *, label_words: int = _LABEL_WORDS) -> bool | None:
    """The cue for a value at ``start``: True positive, False negative, None none.

    A CSV row's column header decides first. Then the words before the value on its line,
    nearest first, within :data:`_WINDOW` characters: a positive word keeps the value when no
    other number stands between them (``card 4699 …, TR2026…``: the card cue is the card's, not
    the reference's; LAB-1344); a negative word drops it only as its label, fewer than
    :data:`_LABEL_WORDS` words before it with no other number between (``"order": "…"``,
    ``Rendelés módosítása …``), so a reference word earlier in a sentence ("for my order, my
    number is …") does not drop it.
    """
    header = _csv_header(text, start)
    if header is not None:
        verdict = _classify_label(header)
        if verdict is not None:
            return verdict
    line_start = text.rfind("\n", 0, start) + 1
    window = _fold(text[max(line_start, start - _WINDOW) : start])
    words = 0
    label = True
    for m in reversed(list(_WORD_OR_NUMBER_RE.finditer(window))):
        if m.group()[0].isdigit():
            label = False  # another value stands between: no longer this one's label
            continue
        verdict = _classify_word(m.group())
        if verdict is True and label:
            return True
        if verdict is False and label and words < label_words:
            return False
        if m.group() not in _FILLER:
            words += 1
    return None


def _unquoted_commas(line: str) -> list[int]:
    """Offsets of the commas outside double quotes (a ``""`` escape toggles twice)."""
    if '"' not in line:
        return [m.start() for m in _COMMA_RE.finditer(line)]
    out, quoted = [], False
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif ch == "," and not quoted:
            out.append(i)
    return out


def _split_fields(line: str) -> list[str]:
    """``line`` cut at its unquoted commas, each field trimmed and unquoted (``""`` -> ``"``).

    The same quoting rules as :func:`_unquoted_commas`, so a header and its rows count their
    columns alike (``"note,order",passport`` is two fields).
    """
    fields, prev = [], 0
    for c in [*_unquoted_commas(line), len(line)]:
        field = line[prev:c].strip()
        if len(field) >= 2 and field[0] == field[-1] == '"':
            field = field[1:-1].replace('""', '"')
        fields.append(field.strip().strip('"'))
        prev = c + 1
    return fields


class _CsvIndex:
    """The lines of one text and, per line, the first line of its CSV block, built once.

    A row's block is the run of lines just above it with the same number of unquoted commas,
    and its first line is the header candidate. Walking back over the block again for every
    number was quadratic in rows (LAB-1352); this is one pass over the text, on first use.
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.starts: list[int] = []
        self.commas: list[list[int]] = []
        self.top: list[int] = []
        self._fields: dict[int, list[str] | None] = {}

    def _build(self) -> None:
        text = self.text
        self.starts = [0, *(m.end() for m in re.finditer("\n", text))]
        ends = [*(s - 1 for s in self.starts[1:]), len(text)]
        for i, (start, end) in enumerate(zip(self.starts, ends, strict=True)):
            self.commas.append(_unquoted_commas(text[start:end]))
            same = i > 0 and len(self.commas[i - 1]) == len(self.commas[i])
            self.top.append(self.top[i - 1] if same else i)

    def header(self, pos: int) -> str | None:
        if not self.starts:
            self._build()
        line = bisect_right(self.starts, pos) - 1
        commas = self.commas[line]
        top = self.top[line]
        if len(commas) < 2 or top == line:
            return None
        if top not in self._fields:
            end = self.starts[top + 1] - 1
            header = self.text[self.starts[top] : end]
            digit = any(ch.isdigit() for ch in header)
            self._fields[top] = None if digit else _split_fields(header)
        fields = self._fields[top]
        if fields is None:
            return None  # the block's first line holds a digit: a data row, no header
        column = bisect_left(commas, pos - self.starts[line])
        return fields[column] if column < len(fields) else None


#: The index of the text :func:`check_numbers` is checking, shared by all its spans.
_INDEX: ContextVar[_CsvIndex | None] = ContextVar("ner_numbers_csv_index", default=None)


def _csv_header(text: str, pos: int) -> str | None:
    """The column header of ``pos`` if it sits in a CSV row under a header line, else None.

    A row has two commas or more; the header is the first line of the block of lines with the
    same number of fields, and holds no digit. Commas inside double quotes, in the header as in
    the row, don't separate fields.
    """
    line_end = text.find("\n", pos)
    if text.count(",", text.rfind("\n", 0, pos) + 1, line_end if line_end >= 0 else len(text)) < 2:
        return None  # not a row (most values): no index needed
    index = _INDEX.get()
    if index is None or index.text is not text:
        index = _CsvIndex(text)
    return index.header(pos)


def _token(text: str, start: int, end: int) -> tuple[int, int]:
    """The run of ASCII letters, digits and ``_`` around ``[start, end)``."""
    while start > 0 and _TOKEN_CHAR.match(text[start - 1]):
        start -= 1
    while end < len(text) and _TOKEN_CHAR.match(text[end]):
        end += 1
    return start, end


_JOINED_RE = re.compile(r"[0-9A-Za-z]+[-/]$")


def _run_start(text: str, start: int) -> int:
    """Start of the hyphen- or slash-joined run ending in the token at ``start`` (``AD-12345``)."""
    while True:
        m = _JOINED_RE.search(text, max(0, start - 16), start)
        if m is None or (m.start() > 0 and _TOKEN_CHAR.match(text[m.start() - 1])):
            return start
        start = m.start()


def _amount(text: str, start: int, end: int) -> bool:
    """True if ``text[start:end]`` is an amount or part of one (``48170.94``, ``…70.94``)."""
    if _DECIMAL_RE.fullmatch(text[start:end]):
        return True
    if not text[start:end].isdigit():
        return False
    if _DECIMAL_AFTER_RE.match(text, end):  # "48170" of "48170.94"
        return True
    # "94" of "48170.94": the cents after a decimal mark
    return end - start <= 2 and start >= 2 and text[start - 1] in ".," and text[start - 2].isdigit()


def _is_cnp(digits: str) -> bool:
    """True for a Romanian personal number (CNP): sex digit, birth month and day, check digit."""
    if digits[0] == "0" or not ("01" <= digits[3:5] <= "12" and "01" <= digits[5:7] <= "31"):
        return False
    total = sum(int(d) * int(w) for d, w in zip(digits, "279146358279", strict=False))
    check = total % 11
    return digits[-1] == str(1 if check == 10 else check)


def _stamp(digits: str) -> bool:
    """True for a ``yyyymmddhhmmss`` stamp in 2000-2039."""
    try:
        t = dt.datetime.strptime(digits, "%Y%m%d%H%M%S")  # noqa: DTZ007
    except ValueError:
        return False
    return 2000 <= t.year < 2040


def _epoch_ms(digits: str) -> bool:
    """True for epoch milliseconds in 2020-2035 that are no valid CNP (``17…`` is a 1970s birth).

    The window is recent on purpose: a reference is minted now, and an older value (``14…``,
    2016) is as likely a 13-digit identity number.
    """
    return 1_577_836_800_000 <= int(digits) < 2_082_758_400_000 and not _is_cnp(digits)


def _reference(value: str) -> bool:
    """True if ``value`` is a tracking number or a timestamp-style or CEE order reference.

    UPS ``1Z…``, UPU S10 (``LX123456785GB``), a ``yyyymmddhhmmss`` stamp or epoch milliseconds
    with an optional letter prefix (``TR20261029141749``), a year and serial (``2025/098820``,
    ``FV 2026/06039``), a 3-7-7 order number. An OCR ``O`` for a ``0`` counts as the digit.
    """
    if _UPS_RE.fullmatch(value) or _S10_RE.fullmatch(value):
        return _S10_RE.fullmatch(value) is None or sum(c.isdigit() for c in value) >= 7
    if _YEAR_SERIAL_RE.fullmatch(value) or _ORDER_377_RE.fullmatch(value):
        return True
    m = _STAMP_RE.fullmatch(value)
    if m is None:
        return False
    digits = m.group(1)
    if digits.count("O") > 1:
        return False
    digits = digits.replace("O", "0")
    return _stamp(digits) if len(digits) == 14 else _epoch_ms(digits)


def number_verdict(text: str, start: int, end: int) -> bool:
    """True to keep the NER number ``text[start:end]``, False to drop it."""
    tok_start, tok_end = _token(text, start, end)
    token = text[tok_start:tok_end]
    if _HEX_RE.fullmatch(token):
        return False  # a machine id, whatever its key says ("tool_calls" … "call_9f…")
    run_start = _run_start(text, tok_start)
    if run_start < tok_start:  # "ORD-2024-…", "SKU-…": the prefix names the value
        prefix = _WORD_RE.match(_fold(text[run_start:tok_start]))
        if prefix is not None and _classify_word(prefix.group()) is False:
            return False
    # A word between the label and the value ("Bestellnummer bleibt SO…") only for a value with
    # letters in it; a bare number needs its label right before it.
    tail = text[run_start:end]
    letters = any(ch.isascii() and ch.isalpha() for ch in tail)
    cue = cue_before(text, run_start, label_words=_LABEL_WORDS if letters else 1)
    if cue is not None:
        return cue
    if any(_reference(v) for v in {token, tail, text[start:end]}):
        return False
    return not (_amount(text, start, end) or _amount(text, tok_start, tok_end))


def _fields(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """``[start, end)`` cut at field separators, each piece trimmed to letters and digits."""
    out: list[tuple[int, int]] = []
    i = start
    while i < end:
        j = i
        while j < end and text[j] not in _FIELD_SEPARATORS:
            j += 1
        a, b = i, j
        while a < b and not text[a].isalnum():
            a += 1
        while b > a and not text[b - 1].isalnum():
            b -= 1
        if a < b:
            out.append((a, b))
        i = j + 1
    return out


def _cut_references(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """A field cut around the whitespace-separated tokens that are a reference on their own.

    The model joins neighbours into one span (``CP279078509AT 5576 0184 …``, a UPU id and a
    card); the reference is judged alone and the rest stays one piece.
    """
    tokens = [(m.start(), m.end()) for m in re.finditer(r"\S+", text[start:end])]
    if len(tokens) < 2 or _reference(text[start:end]):
        return [(start, end)]
    out: list[tuple[int, int]] = []
    run: tuple[int, int] | None = None
    for a, b in tokens:
        a, b = start + a, start + b
        if _reference(text[a:b]):
            if run is not None:
                out.append(run)
                run = None
            out.append((a, b))
        else:
            run = (run[0], b) if run is not None else (a, b)
    if run is not None:
        out.append(run)
    return out


def check_numbers(text: str, spans: Sequence[Span]) -> list[Span]:
    """``spans`` with the NER numbers that fail :func:`number_verdict` removed or cut down."""
    token = _INDEX.set(_CsvIndex(text))
    try:
        return _check_numbers(text, spans)
    finally:
        _INDEX.reset(token)


def _line_remainder(text: str, span_start: int, field: tuple[int, int]) -> bool:
    """Whether ``field`` is a short piece the span picked up past a newline (LAB-1604).

    The model runs a number over the line break into the next row (``…7654 32\n2``, the next
    CSV row's id). A piece that short on a later line is no number of these types.
    """
    a, b = field
    return b - a < _MIN_PIECE and text.find("\n", span_start, a) >= 0


def _check_numbers(text: str, spans: Sequence[Span]) -> list[Span]:
    out: list[Span] = []
    for span in spans:
        if span.entity_type not in NUMBER_TYPES | _SPLIT_TYPES:
            out.append(span)
            continue
        fields = _fields(text, span.start, span.end)
        split = len(fields) > 1
        if split:
            fields = [f for f in fields if not _line_remainder(text, span.start, f)]
        if span.entity_type not in NUMBER_TYPES:
            if not split:
                out.append(span)  # one field: no separator ran through it, leave it alone
                continue
        else:
            fields = [c for f in fields for c in _cut_references(text, *f)]
        kept = [f for f in fields if number_verdict(text, f[0], f[1])]
        if kept == [(span.start, span.end)]:
            out.append(span)
            continue
        for a, b in kept:
            out.append(Span(a, b, span.entity_type, text[a:b], span.score, span.detector))
    return out
