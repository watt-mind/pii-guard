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

6. **Machine tokens (LAB-1482).** Request metadata and commands that coding agents send
   (``docs/integrations/harness-matrix-2026-10-29.md``):

   - a hit inside a bare UUID (``8-4-4-4-12`` hex, anywhere: Codex's ``prompt_cache_key`` and
     ``client_metadata`` ids) goes, whatever its type: hex digits and dashes hold no name, and a
     phone number or an account in one is not the model's to find;
   - a hit that is exactly a JSON literal (``true``, ``false``, ``null``) in value position
     (after ``:``, ``=``, ``,`` or ``[``) goes;
   - a number-like hit that is a whole epoch timestamp (10 digits for seconds, 13 for
     milliseconds) and the value of a time field (``*_ms``, ``*_at``, ``*_ts``, ``*unix*``,
     ``*time*``, ``*timestamp*``, ``*epoch*``) goes;
   - a name-like hit that is a whole lower-case executable name at command position (after
     ``&&``, ``||``, ``|``, ``;``, ``$(``, a ``$`` prompt, ``sudo``/``env``/``exec``/``xargs``,
     or first in a ``"command"`` value: ``python3``, ``node``) goes; a name in an argument
     (``--to "Kovács Réka"``) is not at command position and stays;
   - a ``PERSON`` or ``ORGANIZATION`` hit with no letter in it (``89`` in ``len 89``) goes;
   - in a path, a name-like hit in the package segment right after ``node_modules/`` (or in its
     ``@scope`` segment and the package after it) goes: those are npm package names.

7. **Bare numbers as addresses (LAB-1477, narrowed by LAB-1599).** An ``ADDRESS`` hit with
   digits and no letter goes only when something positive says it is not an address. A missing
   street or city never decides: a bare house number, building number or postcode
   (``building number 800``, ``the zip code for the area is 92004``, ``a 1126 területen``) is
   kept, because a leak costs more than an over-mask. It goes when:

   - the word right before it labels a non-address number (:data:`_NON_ADDRESS_LABELS`: a
     port word, ``ticket``, ``issue``, ``PR``, ``version``, ``build``, ``pid``, ``sku``,
     ``priority``, ``timeout``, ``minutes``; ``--port 8787``, ``"ticket": 4471``,
     ``sku: GT-81215``), or ``hrsz``/``helyrajzi`` names it a parcel (the parcel rule masks it);
   - it is assigned (``VAULT_MAX_KEYS=8192``, ``PORT=8787``); a ``#`` alone is not a sign
     (``Bypass Road #542``), ``PR #295`` is;
   - a weaker sign stands near it and nothing address-like does: a port word (``port``,
     ``Ports``, ``localhost``, ``listens``) on its line within 100 characters, ``up to`` right
     before it (``up to 4096 keyed digests``), or the shape of an amount (``7869.62``).
     Address-like means a word written as a name touching it (``1051 Budapest``,
     ``Musterstraße 12``, ``H-6720 Szeged``), an address word (:data:`_ADDRESS_WORDS`) among
     the two words before it or the word after it, or another ``ADDRESS`` hit touching it.

   A four-digit number has the shape of a Hungarian postcode, so the shape alone never decides.

8. **Eponyms (LAB-1477).** A one-word ``PERSON`` hit that is followed by the noun of a method
   (:data:`_METHOD_WORDS`: ``Luhn test``, ``Luhn check``, ``Dijkstra's algorithm``,
   ``Luhn-algoritmus``, ``Luhn-Prüfsumme``, ``Bloom filter``) goes: it names an algorithm, not a
   person. A name a language pack's lexicon knows (``Kovács``) and a hit that is part of a
   longer name (``Hans Luhn test``) are kept, like the software-name shortcuts.

9. **Family words in firm names (LAB-1220).** A ``PERSON`` hit that is just the family word of
   a Hungarian firm name (``Fia``, ``Fiai``, ``Lánya``, ``Társa`` in ``Balogh és Fia Kkt.``,
   ``Simon & Társa Bt.``) goes: it says "and son" or "and partner", not who. It needs the
   connector before it and the legal form after it (``languages/hu/companies.py``); the
   member's surname (``Balogh``) is a separate hit and stays.

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
_UUID_RE = re.compile(
    r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
    r"(?![0-9A-Fa-f])"
)
_JSON_LITERALS = frozenset({"true", "false", "null"})
# Before a JSON value: ``:``, ``=``, ``,`` or ``[`` (and spaces); after it: an end of value.
_LITERAL_BEFORE = frozenset(":=,[")
_LITERAL_AFTER = frozenset(",}]\\\"' \t\r\n")
# The key of the value the text ends in: ``"turn_started_at_unix_ms":`` or ``created_at=``
# (quotes may be JSON-escaped).
_KEY_BEFORE_RE = re.compile(r"([A-Za-z0-9_.-]{1,64})[\\\"']*[ \t]*[:=][ \t]*[\\\"']*$")
_TIME_KEY_RE = re.compile(
    r"(?:^|[_.-])(?:ms|millis|at|ts|time|timestamp|epoch)$|unix|timestamp|epoch", re.IGNORECASE
)
# Epoch seconds (2001-09 .. 2286) and milliseconds over the same range.
_EPOCH_RE = re.compile(r"^(?:[1-9][0-9]{9}|[1-9][0-9]{12})$")
_EXECUTABLE_RE = re.compile(r"^[a-z][a-z0-9._+-]{0,39}$")
# What puts the next word at command position in a shell command.
_COMMAND_BEFORE_RE = re.compile(
    r"(?:&&|\|\||[|;]|\$\(|(?:^|\n)[ \t]*\$)[ \t]*$"
    r"|(?<![\w-])(?:sudo|env|exec|xargs|nohup)[ \t]+$"
    r"|[\\\"']?(?:command|cmd)[\\\"']?[ \t]*:[ \t]*[\\]?[\"'][ \t]*$"
)
_NODE_MODULES_RE = re.compile(r"(?:^|[/\\])node_modules[/\\](?:@[^/\\]+[/\\])?$")
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

# --- LAB-1477: bare numbers as ADDRESS, eponyms as PERSON ---------------------------------
# Words that make a number next to them part of an address, folded (lower case, no accents).
# A trailing "*" takes any suffix. Street types, address and postcode labels of the built-in
# languages; a pack adds its own with the next release.
_ADDRESS_WORDS: tuple[str, ...] = (
    # labels
    "address*", "addr", "adresse*", "anschrift*", "wohnort*", "adres*", "cim", "cime*",
    "cimem", "cimre", "cimen", "lakcim*", "szekhely*", "telephely*", "postacim*",
    "zip*", "postcode*", "postal*", "plz", "postleitzahl*", "irsz", "iranyitoszam*",
    "pocztowy*", "kod",
    # street types and parts of an address
    "street*", "st", "road*", "rd", "avenue*", "ave", "lane*", "ln", "grove", "crescent",
    "terrace", "flat", "apt", "apartment*", "suite", "utca*", "u", "ut", "utja", "ter",
    "tere", "koz", "sor", "korut*", "krt", "fasor*", "sugarut*", "em", "emelet*", "ajto*",
    "fszt", "hazszam*", "strasse*", "str", "weg", "allee", "platz", "gasse", "hausnummer*",
    "wohnung*", "ul", "ulica*", "al", "aleja*", "os", "osiedle*",
)  # fmt: skip
_ADDRESS_SUFFIXES = ("strasse", "weg", "allee", "platz", "gasse")
# A port word right before a number: it is a port, not a postcode.
_PORT_WORD_RE = re.compile(
    r"^(?:ports?|port(?:on|ot|ra|ja|szam\w*|nummer\w*|e|en|s)|listen|listens|listening)$"
)
# LAB-1599: the word right before a number that labels it as something other than an address,
# folded. Only a positive sign like this drops a bare-number ADDRESS hit; a missing street or
# city does not. "number", "no", "szam" and "line" are not here: they label house numbers too.
_NON_ADDRESS_LABELS: tuple[str, ...] = (
    "ticket*", "issue*", "pr", "pull", "version*", "ver", "build", "pid", "sku", "priority",
    "timeout", "minute*", "second*", "ms", "hrsz", "helyrajzi*",
)  # fmt: skip
_PORT_HOST_RE = re.compile(r"^(?:localhost|listen\w*)$")
_UP_TO_RE = re.compile(r"(?:\bup to|\bbis zu|\blegfeljebb)[ \t\u00a0]$", re.IGNORECASE)
_CODE_LETTERS_RE = re.compile(r"^[A-Z]{1,4}$")
_AMOUNT_RE = re.compile(r"^\d{1,9}\.\d{2}$")
# What may stand between a number and a word that makes it an address: spaces, a comma, a
# full stop, a hyphen (``H-1051``), a slash or a line break; at most three characters.
_ADDRESS_GAP_RE = re.compile(r"^[ \t\u00a0,.\-\u2013/\r\n]{1,3}$")
_LETTER_WORD_RE = re.compile(r"[^\W\d_]+")
# A full stop and a space after the number end its sentence: the next word is not its city.
_SENTENCE_END_RE = re.compile(r"\.\s")
# Between a label and its number: spaces, a quote, a full stop, a colon, an equals sign, a dash
# or a "#" (``PR #295``). A "#" alone says nothing: ``Bypass Road #542`` is a house number.
_LABEL_GAP_RE = re.compile(r"^[ \t\u00a0\"'.:=#\-]{1,4}$")
# The noun of a method after an eponym, folded. English forms are listed whole (``tested``
# is a verb); Hungarian and German forms take suffixes (``algoritmussal``, ``Prüfsummen``).
_METHOD_WORDS: tuple[str, ...] = (
    "test", "tests", "check", "checks", "checksum", "checksums", "algorithm", "algorithms",
    "formula", "formulas", "method", "methods", "filter", "filters", "transform",
    "transforms", "distance", "coding", "encoding", "digit", "validation", "scheme",
    "algoritmus*", "ellenorz*", "teszt*", "proba*", "keplet*", "modszer*", "szuro*",
    "eljaras*", "transzformaci*", "tavolsag*", "algorithmus*", "algorithmen", "prufung*",
    "prufsumme*", "prufziffer*", "verfahren*", "formel*", "methode*", "transformation*",
    "abstand*",
)  # fmt: skip
_EPONYM_AFTER_RE = re.compile(r"^(?:['\u2019]s)?[ \t\u00a0-]+([^\W\d_]+)")


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


def _in_uuid(text: str, start: int, end: int) -> bool:
    """``[start, end)`` lies inside a bare UUID."""
    lo = max(0, start - 36)
    for match in _UUID_RE.finditer(text, lo, min(len(text), end + 36)):
        if match.start() <= start and end <= match.end():
            return True
    return False


def _json_literal(text: str, start: int, end: int) -> bool:
    """The hit is exactly ``true``/``false``/``null`` in a JSON (or ``key=value``) value slot."""
    if text[start:end] not in _JSON_LITERALS:
        return False
    before = text[:start].rstrip(" \t\\\"'")
    if not before or before[-1] not in _LITERAL_BEFORE:
        return False
    return end == len(text) or text[end] in _LITERAL_AFTER


def _epoch_in_time_field(text: str, start: int, end: int) -> bool:
    """The hit is a whole epoch timestamp and the value of a time-named field."""
    value = text[start:end]
    if not _EPOCH_RE.match(value):
        return False
    if (start > 0 and text[start - 1].isdigit()) or (end < len(text) and text[end].isdigit()):
        return False
    key = _KEY_BEFORE_RE.search(text[max(0, start - 80) : start])
    return key is not None and _TIME_KEY_RE.search(key.group(1)) is not None


def _executable_at_command_position(text: str, start: int, end: int) -> bool:
    """A whole lower-case word in command position of a shell command (``&& python3 -c``)."""
    if not _EXECUTABLE_RE.match(text[start:end]):
        return False
    if end < len(text) and not (text[end].isspace() or text[end] in "\"'\\);&|"):
        return False
    return _COMMAND_BEFORE_RE.search(text[max(0, start - 40) : start]) is not None


def _npm_package_segment(text: str, ts: int, ss: int) -> bool:
    """The path segment starting at ``ss`` is a package (or its scope) under node_modules."""
    return _NODE_MODULES_RE.search(text[ts:ss]) is not None


def _fold(word: str) -> str:
    from pii_guard.languages.cues import fold

    return fold(word).replace("ß", "ss").rstrip(".")


def _listed(word: str, listed: tuple[str, ...]) -> bool:
    folded = _fold(word)
    return any(folded.startswith(w[:-1]) if w.endswith("*") else folded == w for w in listed)


def _address_word(word: str) -> bool:
    return _listed(word, _ADDRESS_WORDS) or _fold(word).endswith(_ADDRESS_SUFFIXES)


def _port_word(word: str) -> bool:
    folded = _fold(word).lstrip("-")
    return bool(_PORT_WORD_RE.match(folded) or _PORT_HOST_RE.match(folded))


def _address_context(text: str, start: int, end: int, addresses: Sequence[Span]) -> bool:
    """Something address-like touches the number: a name, an address word, an address hit."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end < 0 else line_end
    before = list(_LETTER_WORD_RE.finditer(text, max(line_start, start - 30), start))
    after = list(_LETTER_WORD_RE.finditer(text, end, min(line_end, end + 30)))
    for other in addresses:
        if (other.start, other.end) == (start, end):
            continue
        if other.start < end and start < other.end:
            return True  # overlapping: one address
        gap = text[other.end : start] if other.end <= start else text[end : other.start]
        if not gap or _ADDRESS_GAP_RE.match(gap):
            return True  # touching: the model split one address in two
    if any(_address_word(m.group()) for m in [*before[-2:], *after[:1]]):
        return True
    # A word written as a name touching the number (a line break may stand between).
    near = list(_LETTER_WORD_RE.finditer(text, max(0, start - 40), start))
    if (
        near
        and _ADDRESS_GAP_RE.match(text[near[-1].end() : start])
        and _name_shaped(near[-1].group())
    ):
        return True
    nxt = _LETTER_WORD_RE.search(text, end, min(len(text), end + 40))
    return (
        nxt is not None
        and _ADDRESS_GAP_RE.match(text[end : nxt.start()]) is not None
        and not _SENTENCE_END_RE.search(text[end : nxt.start()])
        and _name_shaped(nxt.group())
    )


def _labelled_non_address(text: str, start: int, end: int) -> bool:
    """The number is labelled, assigned or numbered as something other than an address."""
    if (
        start >= 2
        and text[start - 1] == "="
        and (text[start - 2].isalnum() or text[start - 2] == "_")
    ):
        return True  # VAULT_MAX_KEYS=8192, PORT=8787
    line_start = text.rfind("\n", 0, start) + 1
    before = list(_LETTER_WORD_RE.finditer(text, max(line_start, start - 30), start))
    anchor = start
    if (
        before
        and _CODE_LETTERS_RE.match(before[-1].group())
        and text[before[-1].end() : start] == "-"
    ):
        anchor = before.pop().start()  # the letters of a code (GT-81215): read the label before
    if before:
        last = before[-1]
        if _LABEL_GAP_RE.match(text[last.end() : anchor]) and (
            _PORT_WORD_RE.match(_fold(last.group()).lstrip("-"))
            or _listed(last.group(), _NON_ADDRESS_LABELS)
        ):
            return True
    nxt = _LETTER_WORD_RE.search(text, end, min(len(text), end + 8))
    return (
        nxt is not None
        and _ADDRESS_GAP_RE.match(text[end : nxt.start()]) is not None
        and _listed(nxt.group(), ("hrsz", "helyrajzi*"))
    )


def _bare_number_address(text: str, start: int, end: int, addresses: Sequence[Span] = ()) -> bool:
    """A letterless ``ADDRESS`` hit with a positive non-address sign (module rule 7)."""
    value = text[start:end]
    if not any(ch.isdigit() for ch in value) or any(ch.isalpha() for ch in value):
        return False
    if _labelled_non_address(text, start, end):
        return True
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end < 0 else line_end
    window = [
        *_LETTER_WORD_RE.finditer(text, max(line_start, start - 100), start),
        *_LETTER_WORD_RE.finditer(text, end, min(line_end, end + 100)),
    ]
    weak = (
        any(_port_word(m.group()) for m in window)
        or _UP_TO_RE.search(text, max(0, start - 12), start) is not None
        or _AMOUNT_RE.match(value.strip()) is not None
    )
    return weak and not _address_context(text, start, end, addresses)


def _eponym(text: str, start: int, end: int, persons: Sequence[Span]) -> bool:
    """A one-word ``PERSON`` hit followed by a method's noun (module rule 8)."""
    from pii_guard.detect.ner_orgs import _part_of_name, _person_names

    value = text[start:end]
    if not _SINGLE_IDENT_RE.match(value) or not _name_shaped(value):
        return False
    match = _EPONYM_AFTER_RE.match(text[end : end + 40])
    if match is None or not _listed(match.group(1), _METHOD_WORDS):
        return False
    if value.casefold() in _person_names():
        return False
    probe = Span(start, end, EntityType.PERSON, value, 1.0, "ner")
    return not _part_of_name(text, probe, [p for p in persons if (p.start, p.end) != (start, end)])


def _family_firm_word(text: str, start: int, end: int) -> bool:
    """``Fia`` in ``Balogh és Fia Kkt.``: a firm's family word (module rule 9)."""
    from pii_guard.languages.hu.companies import family_word_in_firm

    return family_word_in_firm(text, start, end)


def _vetoed(
    text: str,
    start: int,
    end: int,
    entity_type: EntityType,
    language: str,
    persons: Sequence[Span] = (),
    addresses: Sequence[Span] = (),
) -> bool:
    if entity_type is EntityType.EMAIL and not _email_ok(text, start, end):
        return True
    if entity_type is EntityType.ADDRESS and _bare_number_address(text, start, end, addresses):
        return True
    if _fence_info(text, start, end):
        return True
    if _in_uuid(text, start, end) or _json_literal(text, start, end):
        return True
    if entity_type in _NUMBER_LIKE and _epoch_in_time_field(text, start, end):
        return True
    if entity_type in _NAME_LIKE and _executable_at_command_position(text, start, end):
        return True
    if entity_type in (EntityType.PERSON, EntityType.ORGANIZATION) and not any(
        ch.isalpha() for ch in text[start:end]
    ):
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
            if any(ch.isdigit() for ch in text[ss:se]) or _npm_package_segment(text, ts, ss):
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
    return entity_type is EntityType.PERSON and (
        _software_context(text, start, end, language, persons)
        or _eponym(text, start, end, persons)
        or _family_firm_word(text, start, end)
    )


def guard_spans(text: str, spans: Iterable[Span], language: str = "hu") -> list[Span]:
    """``spans`` without the NER hits the structure of ``text`` rules out (module docstring).

    Order is kept. With :data:`ENV_VAR` off, ``spans`` is returned unchanged.
    """
    found = list(spans)
    if not found or not enabled():
        return found
    persons = [s for s in found if s.entity_type is EntityType.PERSON]
    addresses = [s for s in found if s.entity_type is EntityType.ADDRESS]
    return [
        s
        for s in found
        if not _vetoed(text, s.start, s.end, s.entity_type, language, persons, addresses)
    ]


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
