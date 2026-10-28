"""Structural guards for NER hits in agent text: file names, paths, code, tool names (LAB-1470).

Coding agents send system prompts, skill lists, file names, absolute paths and tool output in
every request. Measured live (``docs/integrations/harness-matrix-2026-10-28.md``), the NER
encoder reads some of that as personal data: ``contacts.json`` as an ``EMAIL`` (there is no
``@``), ``JSON``, ``Claude``, ``Codex`` and ``Muse Spark`` as a ``PERSON``, a workspace path
segment (``<project>-<uuid>``) as an ``ID_DOCUMENT`` or ``BANK_ACCOUNT``. The session sweep then
masks the value everywhere, the user's own prompt included, and the model reads a different
task (``write the fixture file [[EMAIL_…]]``).

:func:`guard_spans` runs on the NER detector's spans before they leave it, so a rejected hit
never becomes a session value. Every check is about the shape of the text around the hit, not
about the words of a language, and drops a hit only when that shape rules personal data out:

1. **An e-mail address has an ``@``.** An ``EMAIL`` hit is dropped unless its token holds an
   ``@`` (bracketed obfuscations such as ``[at]`` already read as ``@`` after normalisation,
   :mod:`pii_guard.detect.normalize`) or a spelled-out ``at`` … ``dot`` stands next to it.
2. **A code-fence info string is a language tag** (```` ```json ````): any hit inside it goes.
3. **File names and paths.** In a token that is a file name with a known extension
   (:data:`EXTENSIONS`: ``contacts.json``, ``s.json``) or a path (``/private/tmp/…``,
   ``src/schema/contact.json``):

   - a hit that covers the extension goes (``json`` in ``contacts.json``);
   - a number-like hit (``ID_DOCUMENT``, ``BANK_ACCOUNT``, ``PHONE``, tax and TAJ numbers,
     ``EMAIL``, ``DATE_OF_BIRTH``) goes: a path segment is not where the model's unvalidated
     numbers live, and the checksum and format rules still mask a valid one;
   - a name-like hit (``PERSON``, ``ADDRESS``, ``ORGANIZATION``) goes only when its path
     segment also holds a digit (``claude-501``, ``opencode-3f2b…``), which a home directory
     or a person's folder name does not. ``/Users/anna.kovacs/`` stays masked.

4. **Code identifiers.** A hit that is only part of a code identifier: a dotted, ``::`` or
   ``->`` chain called as a function (``JSON.stringify(``) or with a ``snake_case`` or
   ``camelCase`` part (``Customer.load_all``), or a single ``snake_case`` / ``camelCase``
   word. A hit that is the whole identifier (``anna_kovacs``) is kept. In an inline code span
   (`` `…` ``), a name-like hit that is not written as a name (lower case, all caps) goes too.
5. **Software names.** A ``PERSON`` hit that is exactly a listed software product, format,
   language or AI tool (:func:`software_names`, ``languages/software.tsv``): ``JSON``,
   ``Codex``, ``Muse Spark``. The list holds software only, never a person's name on its own;
   ``Claude`` alone is a given name, so it is not masked only in a software context: when the
   text after it completes a listed name (``Claude Code``, ``Claude API``), or when it is
   listed next to a software name (``Claude, Codex``, ``Claude or Codex``). A name that a
   language pack's lexicon knows (``Anna``) never takes these shortcuts, and neither does a
   hit with an honorific or another name next to it (:func:`pii_guard.detect.ner_orgs`'s
   rules for brands).

Fail closed: anything else passes untouched. The rules, the LLM detector and the values a
client pre-loaded (known values) are not checked here: they are validated or explicit.

The vault's session sweep (:meth:`pii_guard.vault.vault.VaultSession.mask`) asks
:func:`sweep_vetoed` before it masks another occurrence of a value that only the NER found, so
a value confirmed in prose (``Ask Claude``) does not spread into ``Claude Code`` or a path.

``PII_GUARD_NER_AGENT_TEXT=false`` turns the guards off (comparison runs).
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Sequence
from functools import cache
from importlib.resources import files

from pii_guard.types import EntityType, Span

__all__ = [
    "ENV_VAR",
    "EXTENSIONS",
    "enabled",
    "guard_spans",
    "software_names",
    "sweep_vetoed",
]

#: ``false`` / ``0`` / ``off`` turns the guards off (for comparison runs).
ENV_VAR = "PII_GUARD_NER_AGENT_TEXT"

#: File extensions that make a dotted token a file name. Lower case, without the dot. Only
#: extensions that are not also a common surname or given name.
EXTENSIONS: frozenset[str] = frozenset(
    {
        # data and config
        "json", "jsonl", "ndjson", "json5", "yaml", "yml", "toml", "xml", "csv", "tsv", "ini",
        "cfg", "conf", "env", "lock", "properties", "plist", "proto", "graphql", "sql", "db",
        "sqlite", "parquet",
        # text and docs
        "md", "markdown", "mdx", "rst", "txt", "log", "pdf", "docx", "doc", "xlsx", "xls",
        "pptx", "odt", "rtf", "tex", "html", "htm", "css", "scss", "svg",
        # code
        "py", "pyi", "ipynb", "js", "mjs", "cjs", "jsx", "ts", "tsx", "vue", "svelte", "rb",
        "go", "rs", "java", "kt", "kts", "swift", "c", "h", "cc", "cpp", "hpp", "cs", "php",
        "sh", "bash", "zsh", "fish", "ps1", "bat", "lua", "pl", "r", "scala", "sbt", "gradle",
        "tf", "hcl", "dockerfile", "makefile", "mk", "cmake", "wasm",
        # media and archives
        "png", "jpg", "jpeg", "gif", "webp", "ico", "mp3", "mp4", "wav", "zip", "tar", "gz",
        "tgz", "bz2", "xz", "7z", "whl", "jar", "bin", "exe", "dmg", "iso",
    }
)  # fmt: skip

#: Types a path segment or file name never carries as unvalidated NER hits.
_NUMBER_LIKE: frozenset[EntityType] = frozenset(
    {
        EntityType.ID_DOCUMENT,
        EntityType.BANK_ACCOUNT,
        EntityType.PHONE,
        EntityType.NATIONAL_ID_HU_TAX,
        EntityType.NATIONAL_ID_HU_TAJ,
        EntityType.EMAIL,
        EntityType.DATE_OF_BIRTH,
    }
)
_NAME_LIKE: frozenset[EntityType] = frozenset(
    {EntityType.PERSON, EntityType.ADDRESS, EntityType.ORGANIZATION}
)

# What ends a token: whitespace, quotes, brackets and field separators. A path or a file name
# never holds these unquoted; a sentence's full stop is stripped off the end separately.
_TOKEN_STOP = frozenset(" \t\r\n\u00a0\"'`()[]{}<>,;=|*")
_TRAILING = ".:!?"
_FILENAME_RE = re.compile(r"^(?P<stem>[^\s/\\]*?)\.(?P<ext>[A-Za-z0-9]{1,10})$")
_IDENT = r"[A-Za-z_$][\w$]*"
_CHAIN_RE = re.compile(rf"^{_IDENT}(?:(?:\.|::|->|#){_IDENT})+$")
_SINGLE_IDENT_RE = re.compile(rf"^{_IDENT}$")
_SNAKE_RE = re.compile(r"^_*[a-z0-9]+(?:_+[a-z0-9]+)+_*$")
_CAMEL_RE = re.compile(r"[a-z0-9][A-Z]")
_FENCE_RE = re.compile(r"^[ \t]*(?:`{3,}|~{3,})[ \t]*([^\s`]+)", re.MULTILINE)
_PACKAGE_SCOPE_RE = re.compile(r"^@[\w.-]+/[\w.-]")
_SPELLED_AT_RE = re.compile(r"(?<!\w)(?:at|ät|kukac)(?!\w)", re.IGNORECASE)
_SPELLED_DOT_RE = re.compile(r"(?<!\w)(?:dot|pont|punkt)(?!\w)", re.IGNORECASE)
# A list separator between two names: punctuation, or one coordinating conjunction of the
# built-in languages (they are a closed class: a pack adds its own with the next release).
_LIST_GAP_RE = re.compile(
    r"^[`'\"\u2019\u201d*]*\s*"
    r"(?:[,/|;&+]\s*(?:(?:or|and|und|oder|és|vagy|i|lub|oraz)\s+)?"
    r"|(?:or|and|und|oder|és|vagy|i|lub|oraz)\s+)"
    r"[`'\"\u201c\u201e*]*$",
    re.IGNORECASE,
)
# A technical acronym right after a word makes it a product name (``Claude API``).
_PRODUCT_ACRONYMS = frozenset({"API", "SDK", "CLI", "MCP", "IDE"})
_WORD_AFTER_RE = re.compile(r"^[ \t\u00a0]+([A-Za-z]{2,5})(?![\w])")
_WORD_RE = re.compile(r"[^\W\d_](?:[^\W\d_]|['\u2019.-](?=[^\W\d_]))*")


def enabled() -> bool:
    return os.environ.get(ENV_VAR, "").strip().lower() not in {"0", "false", "off", "no"}


@cache
def software_names() -> frozenset[str]:
    """Every name in ``languages/software.tsv``, case-folded, whitespace collapsed."""
    from pii_guard.detect.ner_orgs import parse_brands

    resource = files("pii_guard.languages").joinpath("software.tsv")
    return frozenset(n.casefold() for n in parse_brands(resource.read_text(encoding="utf-8")))


@cache
def _multiword_prefixes() -> dict[str, tuple[str, ...]]:
    """First word (folded) of each listed multi-word name -> the rest of each such name."""
    found: dict[str, list[str]] = {}
    for name in software_names():
        head, _, rest = name.partition(" ")
        if rest:
            found.setdefault(head, []).append(rest)
    return {head: tuple(sorted(rests, key=len, reverse=True)) for head, rests in found.items()}


def _token(text: str, start: int, end: int) -> tuple[int, int]:
    """The token around ``[start, end)``: no whitespace, quote, bracket or field separator;
    a trailing full stop or colon is not part of it."""
    ts = start
    while ts > 0 and text[ts - 1] not in _TOKEN_STOP:
        ts -= 1
    te = end
    while te < len(text) and text[te] not in _TOKEN_STOP:
        te += 1
    while te > max(ts, end) and text[te - 1] in _TRAILING:
        te -= 1
    return ts, te


def _is_path(token: str) -> bool:
    if "://" in token or ("/" not in token and "\\" not in token):
        return False
    if token.startswith(("/", "~/", "./", "../", "~\\", ".\\")) or re.match(r"^[A-Za-z]:\\", token):
        return any(ch.isalpha() for ch in token)
    segments = [s for s in re.split(r"[/\\]", token) if s]
    with_letters = [s for s in segments if any(ch.isalpha() for ch in s)]
    if len(with_letters) >= 2 and len(segments) >= 3:
        return True
    return len(with_letters) >= 2 and _extension(segments[-1]) is not None


def _extension(segment: str) -> int | None:
    """Where the known extension of ``segment`` starts (its dot), or ``None``."""
    match = _FILENAME_RE.match(segment)
    if match is None or match.group("ext").lower() not in EXTENSIONS:
        return None
    stem = match.group("stem")
    if stem and not any(ch.isalnum() for ch in stem):
        return None
    return match.start("ext") - 1


def _segment(text: str, ts: int, te: int, start: int, end: int) -> tuple[int, int]:
    """The path segment of the token ``[ts, te)`` that holds ``[start, end)``."""
    ss = start
    while ss > ts and text[ss - 1] not in "/\\":
        ss -= 1
    se = end
    while se < te and text[se] not in "/\\":
        se += 1
    return ss, se


def _name_shaped(value: str) -> bool:
    """Written as a name: every word starts upper case and goes on in lower case."""
    words = _WORD_RE.findall(value)
    if not words:
        return False
    return all(w[0].isupper() and any(ch.islower() for ch in w[1:]) for w in words)


def _in_inline_code(text: str, start: int, end: int) -> bool:
    """``[start, end)`` lies inside a one-line `` `…` `` span (not a fence)."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line = text[line_start : len(text) if line_end < 0 else line_end]
    if line.lstrip().startswith(("```", "~~~")):
        return False
    rel_start, rel_end = start - line_start, end - line_start
    opened: int | None = None
    for i, ch in enumerate(line):
        if ch != "`":
            continue
        if opened is None:
            opened = i
        else:
            if opened < rel_start and rel_end <= i:
                return True
            opened = None
    return False


def _fence_info(text: str, start: int, end: int) -> bool:
    """``[start, end)`` lies in the info string of a code fence line (```` ```json ````)."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", line_start)
    line = text[line_start : len(text) if line_end < 0 else line_end]
    match = _FENCE_RE.match(line)
    if match is None:
        return False
    return line_start + match.start(1) <= start and end <= line_start + match.end(1)


def _code_identifier(text: str, start: int, end: int) -> bool:
    """``[start, end)`` is a strict part of a code identifier token."""
    ts, te = _token(text, start, end)
    # A call: the identifier chain may run up to an opening parenthesis.
    token = text[ts:te]
    if (ts, te) == (start, end) or not token:
        return False
    called = te < len(text) and text[te] == "("
    if _CHAIN_RE.match(token):
        parts = re.split(r"\.|::|->|#", token)
        return called or any(_SNAKE_RE.match(p) or _CAMEL_RE.search(p) for p in parts)
    if _SINGLE_IDENT_RE.match(token):
        return bool(_SNAKE_RE.match(token) or _CAMEL_RE.search(token))
    return False


def _email_ok(text: str, start: int, end: int) -> bool:
    ts, te = _token(text, start, end)
    token = text[ts:te]
    if _PACKAGE_SCOPE_RE.match(token):
        return False  # an npm scope (``@scope/package``), not an address
    if "@" in token or "\uff20" in token:
        return True
    window = text[max(0, start - 40) : min(len(text), end + 60)]
    return bool(_SPELLED_AT_RE.search(window) and _SPELLED_DOT_RE.search(window))


def _is_software(value: str) -> bool:
    return " ".join(value.split()).casefold() in software_names()


def _completes_software(text: str, start: int, end: int) -> bool:
    """The text after the hit completes a listed multi-word name (``Claude`` + `` Code``)."""
    head = " ".join(text[start:end].split()).casefold()
    rests = _multiword_prefixes().get(head)
    if not rests:
        return False
    after = text[end : end + 40]
    for rest in rests:
        match = re.match(
            r"[ \t\u00a0]+" + r"[ \t\u00a0]+".join(map(re.escape, rest.split())),
            after,
            re.IGNORECASE,
        )
        if match and not (
            match.end() < len(after) and (after[match.end()].isalnum() or after[match.end()] == "_")
        ):
            return True
    return False


def _acronym_after(text: str, end: int) -> bool:
    match = _WORD_AFTER_RE.match(text[end : end + 12])
    return match is not None and match.group(1) in _PRODUCT_ACRONYMS


@cache
def _software_alternation() -> str:
    """One regex alternation of every listed name, longest first, flexible whitespace."""
    names = sorted(software_names(), key=len, reverse=True)
    return "|".join(r"[ \t\u00a0]+".join(map(re.escape, n.split())) for n in names)


@cache
def _neighbour_res() -> tuple[re.Pattern[str], re.Pattern[str]]:
    names = _software_alternation()
    gap = _LIST_GAP_RE.pattern.strip("^$")
    after = re.compile(rf"^{gap}(?:{names})(?![\w])", re.IGNORECASE)
    before = re.compile(rf"(?<![\w.])(?:{names}){gap}$", re.IGNORECASE)
    return after, before


def _listed_with_software(text: str, start: int, end: int) -> bool:
    """A neighbour in a list (``Claude, Codex``, ``Claude or Codex``) is a software name."""
    after, before = _neighbour_res()
    if after.match(text[end : end + 60]):
        return True
    return before.search(text[max(0, start - 60) : start]) is not None


def _software_context(
    text: str, start: int, end: int, language: str, persons: Sequence[Span]
) -> bool:
    from pii_guard.detect.ner_orgs import _part_of_name, _person_names

    value = text[start:end]
    folded = " ".join(value.split()).casefold()
    if folded in _person_names():
        return False
    probe = Span(start, end, EntityType.PERSON, value, 1.0, "ner")
    if _part_of_name(text, probe, [p for p in persons if (p.start, p.end) != (start, end)]):
        # ``Codex`` right after a name (``Anna Codex``) is part of that name.
        return False
    if _is_software(value):
        return True
    if " " in value.strip():
        return False
    return (
        _completes_software(text, start, end)
        or _acronym_after(text, end)
        or _listed_with_software(text, start, end)
    )


def _vetoed(
    text: str,
    start: int,
    end: int,
    entity_type: EntityType,
    language: str,
    persons: Sequence[Span] = (),
) -> bool:
    if entity_type is EntityType.EMAIL and not _email_ok(text, start, end):
        return True
    if _fence_info(text, start, end):
        return True
    ts, te = _token(text, start, end)
    token = text[ts:te]
    last = max(token.rfind("/"), token.rfind("\\"))
    dot = _extension(token[last + 1 :])
    path = _is_path(token)
    if dot is not None or path:
        if dot is not None and end > ts + last + 1 + dot:
            return True  # the hit covers the extension (or its dot)
        if entity_type in _NUMBER_LIKE:
            return True
        if entity_type in _NAME_LIKE and path:
            ss, se = _segment(text, ts, te, start, end)
            if any(ch.isdigit() for ch in text[ss:se]):
                return True
    if entity_type in _NAME_LIKE or entity_type is EntityType.EMAIL:
        if _code_identifier(text, start, end):
            return True
        if (
            entity_type in _NAME_LIKE
            and not _name_shaped(text[start:end])
            and _in_inline_code(text, start, end)
        ):
            return True
    return entity_type is EntityType.PERSON and _software_context(
        text, start, end, language, persons
    )


def guard_spans(text: str, spans: Iterable[Span], language: str = "hu") -> list[Span]:
    """``spans`` without the NER hits the structure of ``text`` rules out (module docstring).

    Order is kept. With :data:`ENV_VAR` off, ``spans`` is returned unchanged.
    """
    found = list(spans)
    if not found or not enabled():
        return found
    persons = [s for s in found if s.entity_type is EntityType.PERSON]
    return [s for s in found if not _vetoed(text, s.start, s.end, s.entity_type, language, persons)]


def sweep_vetoed(text: str, start: int, end: int, entity_type: EntityType, language: str) -> bool:
    """Whether the session sweep should leave this occurrence of an NER-only value alone.

    The same checks as :func:`guard_spans`, for one occurrence (no other spans are known).
    """
    if not enabled():
        return False
    return _vetoed(text, start, end, entity_type, language)


def _clear() -> None:
    software_names.cache_clear()
    _multiword_prefixes.cache_clear()
    _software_alternation.cache_clear()
    _neighbour_res.cache_clear()
