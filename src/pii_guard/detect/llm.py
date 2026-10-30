"""LLM detector: a second detection pass on an OpenAI-compatible Chat Completions endpoint.

The model is asked for personal data as JSON only (entity type + exact surface text). The
detector never trusts model offsets: it searches the returned surface strings in the input
itself, maps every occurrence to code-point offsets, and drops anything that does not appear
verbatim (hallucinated or "corrected" values). See ``docs/models.md``.

The default target is Meta's open-weight **Muse Spark Open** served on Baseten
(``meta-models/muse-spark-open-1026``), so detection can stay on infrastructure you control.
Any OpenAI-compatible endpoint works (vLLM, Baseten, the Meta Model API for fictional data).

Fail closed (ADR 0006): timeouts, HTTP errors and responses that are still not valid JSON after
one retry raise :class:`~pii_guard.types.DetectionError`. Error messages never contain the
input text or the model output, only status codes and counts.

No key, no request (LAB-1290): without ``PII_GUARD_LLM_DETECTOR_API_KEY`` the detector refuses
with :class:`~pii_guard.detect.stack.DetectionUnavailableError` (``503 detection_unavailable``)
before any HTTP client exists, so the text never leaves the machine unauthenticated. The one
exception is an endpoint on the loopback interface (a self-hosted model on this machine), where
the text does not leave the machine either.

Prompt injection (``docs/evaluation.md``, "Prompt injection"): the input is wrapped in
delimiters with a fresh random boundary per request and the system prompt says the text is data;
invisible characters and lookalike letters are normalised before the model sees the text
(:mod:`pii_guard.detect.normalize`, spans mapped back); an empty answer for a chunk in which
the rules find personal data is challenged once. None of this is relied on: the LLM can only
add spans, so rule detections survive whatever the model is talked into.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import secrets
import threading
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from pii_guard.config import Settings, get_settings
from pii_guard.detect.normalize import normalize_for_detection
from pii_guard.detect.stack import DetectionUnavailableError
from pii_guard.languages import LanguagePack, get_pack, primary_language
from pii_guard.types import TEXT_ENTITY_TYPES, DetectionError, EntityType, Span
from pii_guard.vault.inflection import inflection_for, variant_stems

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "DETECTOR_CLASS",
    "ENTITY_DESCRIPTIONS",
    "GENERIC_ENTITY_TYPES",
    "NO_KEY_MESSAGE",
    "LanguageProfile",
    "LlmDetector",
    "LlmEntity",
    "chunk_text",
    "clear_alignment_caches",
    "find_occurrences",
    "language_profile",
    "pack_profile",
    "parse_entities",
]

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "meta-models/muse-spark-open-1026"
DEFAULT_BASE_URL = "https://inference.baseten.co/v1"
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_TOKENS = 4096
#: Why a keyless detector refuses (the gateway's audit mode and ``/v1/*`` with ``llm``).
NO_KEY_MESSAGE = (
    "audit mode needs PII_GUARD_LLM_DETECTOR_API_KEY: the LLM detector has no key, so no text "
    "was sent"
)
_UNSET: Any = object()  # "argument not passed"; an explicit ``max_tokens=None`` means "omit it"
#: Counters in :attr:`LlmDetector.usage` (token counts as the endpoint reports them).
USAGE_KEYS = (
    "requests",
    "prompt_tokens",
    "cached_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "invalid_outputs",
    "refusals",
    "empty_challenged",
)

#: What the prompt tells the model about each text entity type.
ENTITY_DESCRIPTIONS: dict[EntityType, str] = {
    EntityType.PERSON: "a natural person's name (full name, surname, or given name used alone)",
    EntityType.ADDRESS: "a postal address or part of one (street, house number, postcode, town "
    "in an address), also when written in prose",
    EntityType.EMAIL: "an email address",
    EntityType.PHONE: "a phone or fax number",
    EntityType.DATE_OF_BIRTH: "a date that is someone's date of birth",
    EntityType.NATIONAL_ID_HU_TAX: (
        "Hungarian personal tax ID (adóazonosító jel): exactly 10 digits starting "
        "with 8; never the 11-digit personal number (személyi azonosító), "
        "which is an ID_DOCUMENT"
    ),
    EntityType.NATIONAL_ID_HU_TAJ: "Hungarian social security (TAJ) number, 9 digits",
    EntityType.ID_DOCUMENT: (
        "an ID card, passport or driving licence number, including the 11-digit "
        "Hungarian personal number (személyi azonosító)"
    ),
    EntityType.BANK_ACCOUNT: "a bank account number or IBAN",
    EntityType.COMPANY_ID_HU: "a company registration number (cégjegyzékszám) or company tax "
    "number (adószám)",
    EntityType.ORGANIZATION: "a company or institution name",
    EntityType.PARCEL_NUMBER_HU: "a land registry parcel number (helyrajzi szám, hrsz.)",
    EntityType.VEHICLE_PLATE: "a vehicle licence plate",
}

# Common names models use instead of ours. Anything else unknown is dropped (and counted).
_TYPE_ALIASES: dict[str, EntityType] = {
    "NAME": EntityType.PERSON,
    "PER": EntityType.PERSON,
    "PERSON_NAME": EntityType.PERSON,
    "LOCATION": EntityType.ADDRESS,
    "STREET_ADDRESS": EntityType.ADDRESS,
    "EMAIL_ADDRESS": EntityType.EMAIL,
    "PHONE_NUMBER": EntityType.PHONE,
    "DOB": EntityType.DATE_OF_BIRTH,
    "BIRTH_DATE": EntityType.DATE_OF_BIRTH,
    "IBAN": EntityType.BANK_ACCOUNT,
    "ORG": EntityType.ORGANIZATION,
    "COMPANY": EntityType.ORGANIZATION,
    "LICENSE_PLATE": EntityType.VEHICLE_PLATE,
}

_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_THINK_RE = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.DOTALL | re.IGNORECASE)


class _InvalidOutput(Exception):
    """The model answered, but not with the JSON we asked for. Retryable once."""


class _Retryable(Exception):
    """A transient transport or server failure."""


class LlmEntity:
    """One entity as the model reported it, before offset mapping."""

    __slots__ = ("entity_type", "occurrence", "text")

    def __init__(self, entity_type: EntityType, text: str, occurrence: int | None = None):
        self.entity_type = entity_type
        self.text = text
        self.occurrence = occurrence

    def __eq__(self, other: object) -> bool:
        return isinstance(other, LlmEntity) and (
            (self.entity_type, self.text, self.occurrence)
            == (other.entity_type, other.text, other.occurrence)
        )

    def __hash__(self) -> int:
        return hash((self.entity_type, self.text, self.occurrence))

    def __repr__(self) -> str:  # never the raw value
        return f"LlmEntity(entity_type={self.entity_type.value}, text=<redacted>)"


# --- Languages ----------------------------------------------------------------

#: Types requested for every language. Country-specific types (``*_HU``) are requested only
#: for their language; the rules still find Hungarian identifiers in any language.
GENERIC_ENTITY_TYPES: tuple[EntityType, ...] = tuple(
    t for t in ENTITY_DESCRIPTIONS if "_HU" not in t.value
)


@dataclass(frozen=True, slots=True)
class LanguageProfile:
    """How the detector prompts for and aligns one language.

    - ``notes``: language-specific instructions: the language pack's prompt resource, or a
      file name under ``prompts/languages/`` (``default.md`` for languages without a pack).
    - ``entity_types``: the types the prompt asks for.
    - ``allow_suffix``: a value may run on into a longer word (agglutinative languages such as
      Hungarian: "Teszt Elek" matches inside "Teszt Eleknek"). Otherwise the match must end at
      a word boundary.
    - ``word_boundary``: a match must start at a word boundary. Off for scripts written
      without spaces between words.
    """

    code: str
    name: str
    notes: str | Traversable = "default.md"
    entity_types: tuple[EntityType, ...] = GENERIC_ENTITY_TYPES
    allow_suffix: bool = True
    word_boundary: bool = True


def pack_profile(pack: LanguagePack) -> LanguageProfile:
    """A language pack's prompt notes, requested types and alignment (ADR 0010)."""
    extra = frozenset(pack.country_entity_types)
    return LanguageProfile(
        pack.code,
        pack.name,
        pack.prompt if pack.prompt is not None else "default.md",
        tuple(t for t in ENTITY_DESCRIPTIONS if t in GENERIC_ENTITY_TYPES or t in extra),
        allow_suffix=pack.allow_suffix,
        word_boundary=pack.word_boundary,
    )


# Fallback alignment for languages without a profile yet. Languages that rarely inflect the
# end of a name require matches to end at a word boundary; all others (Finnish, Turkish,
# Slavic languages, ...) tolerate a suffix, which favours recall. Scripts written without
# spaces between words get no word-boundary checks at all.
_NO_NAME_SUFFIXES = frozenset({"en", "fr", "it", "es", "pt", "nl", "ro", "sv", "da", "no"})
_NO_WORD_SPACES = frozenset({"zh", "ja", "th", "lo", "km", "my"})


def language_profile(language: str) -> LanguageProfile:
    """The profile for an ISO 639-1 code (``"en"``, ``"en-GB"``, ``"HU"``).

    Unknown languages get a generic profile rather than an error: generic entity types,
    language-neutral notes, and alignment that tolerates suffixes (recall first).
    """
    code = primary_language(language)
    pack = get_pack(code)
    if pack is not None:
        return pack_profile(pack)
    return LanguageProfile(
        code,
        code,
        allow_suffix=code not in _NO_NAME_SUFFIXES,
        word_boundary=code not in _NO_WORD_SPACES,
    )


# --- Prompt -----------------------------------------------------------------


@cache
def _template(*parts: str) -> str:
    return files("pii_guard.detect").joinpath("prompts", *parts).read_text(encoding="utf-8")


def _notes(notes: str | Traversable) -> str:
    if isinstance(notes, str):
        return _template("languages", notes)
    return notes.read_text(encoding="utf-8")


def build_messages(
    text: str,
    language: str,
    *,
    profile: LanguageProfile | None = None,
    boundary: str | None = None,
) -> list[dict[str, str]]:
    """The chat messages for one chunk, for ``language`` (see :func:`language_profile`).

    ``profile`` overrides the looked-up profile (the conformance suite renders an
    unregistered pack's prompt this way). The text is wrapped in ``<<<TEXT-<boundary>`` /
    ``TEXT-<boundary>>>>`` with a random ``boundary`` per call (unless given), so a message
    can't fake the end of the input. Placeholders are substituted with ``str.replace`` so
    braces in the input or in the JSON example are never interpreted; the text is
    substituted last.
    """
    boundary = boundary or secrets.token_hex(6)
    profile = profile if profile is not None else language_profile(language)
    types = "\n".join(f"- {t.value}: {ENTITY_DESCRIPTIONS[t]}" for t in profile.entity_types)
    system = (
        _template("system.md")
        .replace("{entity_types}", types)
        .replace("{language_name}", profile.name)
        .replace("{language_notes}", _notes(profile.notes).strip())
    )
    user = (
        _template("user.md")
        .replace("{language}", profile.code)
        .replace("{boundary}", boundary)
        .replace("{text}", text)
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# --- Parsing ----------------------------------------------------------------


_JSON_START = re.compile(r"[{\[]")


def _json_values(content: str) -> Iterator[dict[str, Any] | list[Any]]:
    """Every top-level JSON object or array in ``content``, in order (values nested in one
    are not yielded separately)."""
    decoder = json.JSONDecoder()
    position = 0
    while (match := _JSON_START.search(content, position)) is not None:
        try:
            value, end = decoder.raw_decode(content, match.start())
        except json.JSONDecodeError:
            position = match.start() + 1
            continue
        yield value
        position = end


def _extract_json(content: str) -> Any:
    """The answer in ``content``, ignoring reasoning blocks and code fences.

    Prose around the answer may contain other JSON (``Types I checked: ["PERSON"]``), so the
    first value is not necessarily the answer (LAB-1215). In order of preference: the first
    object with an ``entities`` list, the first non-empty list of objects, the first value.
    """
    content = _THINK_RE.sub("", content)
    # An unterminated reasoning block ("...</think>" with the opening tag stripped upstream).
    for closing in ("</think>", "</thinking>", "</reasoning>"):
        if closing in content:
            content = content.rsplit(closing, 1)[1]
    first: Any = None
    object_list: list[Any] | None = None
    for value in _json_values(content):
        if isinstance(value, dict) and isinstance(value.get("entities"), list):
            return value
        if (
            object_list is None
            and isinstance(value, list)
            and value
            and all(isinstance(item, dict) for item in value)
        ):
            object_list = value
        if first is None:
            first = value
    if object_list is not None:
        return object_list
    if first is not None:
        return first
    raise _InvalidOutput("no JSON value in model output")


def _to_entity_type(raw: object) -> EntityType | None:
    if not isinstance(raw, str):
        return None
    key = raw.strip().upper().replace("-", "_").replace(" ", "_")
    try:
        entity_type = EntityType(key)
    except ValueError:
        entity_type = _TYPE_ALIASES.get(key)
    if entity_type is None or entity_type not in TEXT_ENTITY_TYPES:
        return None
    return entity_type


def parse_entities(content: str) -> list[LlmEntity]:
    """Parse the model's message content into entities.

    Accepts ``{"entities": [...]}`` or a bare list. Each item needs a ``type`` (alias
    ``entity_type``) and a non-empty ``text`` (alias ``value``). Items with an unknown type or
    no text are dropped. Raises ``_InvalidOutput`` when there is no usable JSON structure, and
    when nothing is kept from a non-empty list that has malformed items in it (not an object,
    no type string, no text): that is not an answer in our format, so it is retried rather
    than read as "no personal data". A list of only unknown, well-formed types is an answer.
    """
    data = _extract_json(content)
    items = data.get("entities") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise _InvalidOutput("model output has no entities list")
    entities: list[LlmEntity] = []
    dropped = malformed = 0
    for item in items:
        if not isinstance(item, dict):
            dropped += 1
            malformed += 1
            continue
        raw_type = item.get("type", item.get("entity_type"))
        entity_type = _to_entity_type(raw_type)
        value = item.get("text", item.get("value"))
        if not isinstance(raw_type, str) or not isinstance(value, str) or not value.strip():
            dropped += 1
            malformed += 1
            continue
        if entity_type is None:
            dropped += 1
            continue
        occurrence = item.get("occurrence")
        valid = isinstance(occurrence, int) and not isinstance(occurrence, bool)
        if not valid or occurrence < 1:
            occurrence = None
        entities.append(LlmEntity(entity_type, value.strip(), occurrence))
    if dropped:
        logger.debug("llm detector dropped %d malformed or unknown-type entities", dropped)
    if not entities and malformed:
        raise _InvalidOutput(f"no usable entity in model output ({malformed} malformed)")
    return entities


# --- Offset mapping ---------------------------------------------------------


# Between two characters of a value: a line break, optionally after a hyphen (``Mé-\nszáros``).
_LINE_BREAK = r"(?:-?[ \t]*\r?\n[ \t]*)?"
_MAX_BROKEN_VALUE = 120

# Alignment patterns embed the value the model reported, so they are personal data. They are
# built per call and not cached here (LAB-1353): nothing in this module keeps a value after
# ``align()`` returns. Python's ``re`` keeps its own bounded cache of recently compiled
# patterns (``re._MAXCACHE``, 512 on 3.12), shared with the vault; ``clear_alignment_caches``
# drops it.


def clear_alignment_caches() -> None:
    """Drop every compiled pattern this process still holds, alignment patterns included.

    The LLM detector keeps no cache of its own; this purges Python's bounded ``re`` cache,
    the one place recently aligned values can still sit (with the vault's patterns). The cost
    is a recompile of any pattern a later call needs.
    """
    re.purge()


def _pattern(
    value: str, word_boundary: bool, allow_suffix: bool, line_breaks: bool = False
) -> re.Pattern[str]:
    """Literal match, but any whitespace run in ``value`` matches any whitespace run.

    With ``line_breaks``, a line break (optionally hyphenated) may also sit between any two
    characters of a word: the value was wrapped in the text but reported unwrapped.
    """
    if line_breaks:
        parts = [_LINE_BREAK.join(re.escape(c) for c in p) for p in value.split()]
    else:
        parts = [re.escape(p) for p in value.split()]
    body = r"\s+".join(parts)
    prefix = r"(?<!\w)" if word_boundary and value[0].isalnum() else ""
    if value[-1].isdigit():
        suffix = r"(?!\d)"  # never part of a longer number
    elif value[-1].isalnum() and word_boundary and not allow_suffix:
        suffix = r"(?!\w)"
    else:
        suffix = ""
    return re.compile(prefix + body + suffix)


def find_occurrences(
    text: str, value: str, *, word_boundary: bool = True, allow_suffix: bool = True
) -> list[tuple[int, int]]:
    """Every ``(start, end)`` where ``value`` occurs in ``text``, in code points.

    Matches start at a word boundary (unless ``word_boundary`` is off, for scripts without
    spaces) and, unless ``allow_suffix``, end at one. Tries the value as given and in NFC and
    NFD forms, so a decomposed input ("e" + combining acute) still matches a precomposed model
    answer. When there is no match at all, a value of up to 120 characters is also searched
    with line breaks allowed inside its words (``leopold.fabricant@`` + newline +
    ``example.net``). Returns ``[]`` when the value is not in the text: the caller drops it as
    hallucinated.
    """
    value = value.strip()
    if not value:
        return []
    found: set[tuple[int, int]] = set()
    for form in dict.fromkeys(
        (value, unicodedata.normalize("NFC", value), unicodedata.normalize("NFD", value))
    ):
        pattern = _pattern(form, word_boundary, allow_suffix)
        found.update(m.span() for m in pattern.finditer(text))
    if not found and len(value) <= _MAX_BROKEN_VALUE and "\n" in text:
        for form in dict.fromkeys((value, unicodedata.normalize("NFC", value))):
            pattern = _pattern(form, word_boundary, allow_suffix, line_breaks=True)
            found.update(m.span() for m in pattern.finditer(text))
    return sorted(found)


# Fallback alignment (LAB-1215): a model "corrects" the surface form it reports (letter case,
# typographic apostrophes and dashes, phone and date separators). Only used for a value with
# no verbatim match, so it never changes what an exact answer aligns to.
_APOSTROPHES = "'\u2019\u2018\u02bc\u0060\u00b4"
_DASHES = "-\u2010\u2011\u2012\u2013\u2014\u2212"
_APOSTROPHE_CLASS = "[" + re.escape(_APOSTROPHES) + "]"
_DASH_CLASS = "[" + re.escape(_DASHES) + "]"
# What may sit between two characters of a number: spaces, dashes, dots, slashes, brackets.
_NUMBER_SEPARATORS = "[\\s" + re.escape(_DASHES + "./()") + "]*"
_MIN_SEPARATED_DIGITS = 4


def _loose_char(c: str) -> str:
    if c in _APOSTROPHES:
        return _APOSTROPHE_CLASS
    if c in _DASHES:
        return _DASH_CLASS
    return re.escape(c)


def _loose_pattern(
    value: str, word_boundary: bool, allow_suffix: bool, separators: bool
) -> re.Pattern[str] | None:
    """Case-insensitive, apostrophe- and dash-insensitive match of ``value``. With
    ``separators``, only the letters, digits and ``+`` of ``value`` must match, with any run of
    number separators between them (``+36 30 123 4567`` matches ``+36-30-123-4567``)."""
    if separators:
        chars = [c for c in value if c.isalnum() or c == "+"]
        if not chars:
            return None
        body = _NUMBER_SEPARATORS.join(re.escape(c) for c in chars)
        first, last = chars[0], chars[-1]
    else:
        body = r"\s+".join("".join(_loose_char(c) for c in p) for p in value.split())
        first, last = value[0], value[-1]
    prefix = r"(?<!\w)" if word_boundary and first.isalnum() else ""
    if last.isdigit():
        suffix = r"(?!\d)"
    elif last.isalnum() and word_boundary and not allow_suffix:
        suffix = r"(?!\w)"
    else:
        suffix = ""
    return re.compile(prefix + body + suffix, re.IGNORECASE)


def _loose_occurrences(
    text: str, value: str, *, word_boundary: bool = True, allow_suffix: bool = True
) -> list[tuple[int, int]]:
    """Where ``value`` occurs in ``text`` up to letter case, apostrophe and dash style, then
    (for a value with at least four digits) up to number separators. ``[]`` if nowhere."""
    value = value.strip()
    if not value:
        return []
    forms = dict.fromkeys(
        (value, unicodedata.normalize("NFC", value), unicodedata.normalize("NFD", value))
    )
    stages = [False]
    if sum(c.isdigit() for c in value) >= _MIN_SEPARATED_DIGITS:
        stages.append(True)
    for separators in stages:
        found: set[tuple[int, int]] = set()
        for form in forms:
            pattern = _loose_pattern(form, word_boundary, allow_suffix, separators)
            if pattern is not None:
                found.update(m.span() for m in pattern.finditer(text))
        found = {(start, end) for start, end in found if start < end}
        if found:
            return sorted(found)
    return []


# --- Chunking ---------------------------------------------------------------


def chunk_text(text: str, size: int, overlap: int) -> list[tuple[int, str]]:
    """Split ``text`` into ``(offset, chunk)`` pieces of at most ``size`` code points.

    Consecutive chunks share about ``overlap`` code points, so an entity cut by one boundary is
    whole in the next chunk. Boundaries are moved back to whitespace where possible.
    """
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("chunk size must be positive and overlap in [0, size)")
    if len(text) <= size:
        return [(0, text)]
    chunks: list[tuple[int, str]] = []
    start = 0
    while True:
        end = min(start + size, len(text))
        if end < len(text):
            cut = text.rfind(" ", start + overlap + 1, end)
            cut = max(cut, text.rfind("\n", start + overlap + 1, end))
            if cut > start:
                end = cut
        chunks.append((start, text[start:end]))
        if end >= len(text):
            return chunks
        next_start = end - overlap
        # Prefer to start the next chunk at a word start, never going backwards.
        ws = text.find(" ", next_start, end)
        start = ws + 1 if ws != -1 and ws + 1 > start else max(next_start, start + 1)


# --- Detector ---------------------------------------------------------------


def _is_loopback(url: str) -> bool:
    """Whether ``url``'s host is this machine (``localhost``, ``127.0.0.0/8``, ``::1``)."""
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return False
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class LlmDetector:
    """Detect personal data with an LLM on an OpenAI-compatible Chat Completions endpoint.

    Every argument is keyword-only and optional; unset ones come from :class:`Settings`
    (``PII_GUARD_LLM_DETECTOR_URL``, ``PII_GUARD_LLM_DETECTOR_API_KEY``) and
    ``PII_GUARD_LLM_DETECTOR_MODEL``, then the Baseten Muse Spark Open defaults.

    - ``base_url``: the API root (``.../v1``) or the full ``.../chat/completions`` URL.
    - ``timeout`` / ``max_tokens``: per request; unset ones come from
      ``PII_GUARD_LLM_DETECTOR_TIMEOUT`` / ``PII_GUARD_LLM_DETECTOR_MAX_TOKENS``, then 60 s and
      4096. ``max_tokens=None`` sends no ``max_tokens`` at all.
    - ``reasoning_effort``: sent only when set (default
      ``PII_GUARD_LLM_DETECTOR_REASONING_EFFORT``). Muse Spark always reasons and rejects
      ``"none"``; use ``"minimal"`` or ``"low"`` for detection. Muse Spark Open on Baseten
      needs ``"low"``: at its default effort the reasoning uses up ``max_tokens`` and the
      content comes back empty.
    - ``reasoning_strength``: sent as ``chat_template_kwargs: {"reasoning_strength": ...}``
      when set (default ``PII_GUARD_LLM_DETECTOR_REASONING_STRENGTH``). Muse Glimmer served by
      vLLM ignores ``reasoning_effort`` and reasons at ``high`` unless this says otherwise;
      ``"low"`` is the detection setting.
    - ``json_mode``: send ``response_format: {"type": "json_object"}``.
    - ``chunk_size`` / ``chunk_overlap``: in code points; long inputs are split and each chunk
      is a separate request. Values are then searched in the whole text.
    - ``challenge_empty``: when the model reports nothing for a chunk in which the rules find
      personal data, ask once more (one extra request; counted in ``usage["empty_challenged"]``).
    - ``max_retries``: extra attempts after a timeout, a transport error, a retryable HTTP
      status (429, 5xx) or output that is not valid JSON.
    - ``transport``: an ``httpx.BaseTransport`` (tests use ``httpx.MockTransport``).

    :attr:`usage` counts requests, reported tokens, invalid outputs and refusals for this
    instance (counts only, never text), for cost and refusal reporting.
    """

    name = "llm"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | SecretStr | None = None,
        model: str | None = None,
        timeout: float | None = None,
        max_retries: int = 1,
        temperature: float = 0.0,
        reasoning_effort: str | None = None,
        reasoning_strength: str | None = None,
        json_mode: bool = True,
        max_tokens: int | None = _UNSET,
        chunk_size: int = 6000,
        chunk_overlap: int = 300,
        score: float = 0.85,
        challenge_empty: bool = True,
        transport: httpx.BaseTransport | None = None,
        settings: Settings | None = None,
    ) -> None:
        settings = settings if settings is not None else get_settings()
        from pii_guard.detection_profile import refuse_remote

        refuse_remote(settings, "LLM detection, including loopback HTTP detectors")
        self._profile_settings = settings
        url = (base_url or settings.llm_detector_url or DEFAULT_BASE_URL).rstrip("/")
        self.url = url if url.endswith("/chat/completions") else url + "/chat/completions"
        key = api_key if api_key is not None else settings.llm_detector_api_key
        self._api_key = key.get_secret_value() if isinstance(key, SecretStr) else key
        self.model = model or settings.llm_detector_model or DEFAULT_MODEL
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if not 0.0 <= score <= 1.0:
            raise ValueError("score must be in [0, 1]")
        chunk_text("", chunk_size, chunk_overlap)  # validates the chunk parameters
        self.timeout = (
            timeout if timeout is not None else (settings.llm_detector_timeout or DEFAULT_TIMEOUT)
        )
        self.max_retries = max_retries
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort or settings.llm_detector_reasoning_effort or None
        self.reasoning_strength = reasoning_strength or settings.llm_detector_reasoning_strength
        self.json_mode = json_mode
        if max_tokens is _UNSET:
            max_tokens = settings.llm_detector_max_tokens or DEFAULT_MAX_TOKENS
        self.max_tokens = max_tokens
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.score = score
        self.challenge_empty = challenge_empty
        self._transport = transport
        self.usage: dict[str, int] = dict.fromkeys(USAGE_KEYS, 0)
        self._usage_lock = threading.Lock()

    def __repr__(self) -> str:  # never the key
        return f"LlmDetector(url={self.url!r}, model={self.model!r})"

    @property
    def unavailable_reason(self) -> str | None:
        """Why this detector refuses to send text, or ``None`` when it may.

        It may with a key, or keyless to an endpoint on the loopback interface (the text stays
        on this machine). Anything else would send the text unauthenticated: refused.
        """
        if (self._api_key or "").strip() or _is_loopback(self.url):
            return None
        return NO_KEY_MESSAGE

    def require_available(self) -> None:
        """Raise :class:`DetectionUnavailableError` if :attr:`unavailable_reason` is set."""
        reason = self.unavailable_reason
        if reason is not None:
            raise DetectionUnavailableError(reason)

    # -- public --

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        """Spans over ``text``. The model sees :func:`normalize_for_detection`'s cleaned text;
        its spans are mapped back, covering any invisible characters inside a value."""
        from pii_guard.detection_profile import refuse_remote

        refuse_remote(self._profile_settings, "LLM detection")
        self.require_available()  # before anything else: no key, no request (LAB-1290)
        if not text.strip():
            return []
        norm = normalize_for_detection(text)
        entities: list[LlmEntity] = []
        with self._client() as client:
            for _, chunk in chunk_text(norm.text, self.chunk_size, self.chunk_overlap):
                entities.extend(self._detect_chunk(client, chunk, language))
        spans = self.align(norm.text, entities, language)
        if not norm.changed:
            return spans
        mapped: set[Span] = set()
        for s in spans:
            start, end = norm.to_original(s.start, s.end)
            mapped.add(Span(start, end, s.entity_type, text[start:end], s.score, s.detector))
        return sorted(mapped, key=lambda s: (s.start, s.end, s.entity_type.value))

    def align(self, text: str, entities: Iterable[LlmEntity], language: str = "hu") -> list[Span]:
        """Map entities to spans over ``text``; values not found in it are dropped.

        A value is searched verbatim first. Only when that finds nothing (nor an inflected
        stem, below) is it searched up to letter case, apostrophe and dash style, then number
        separators (``KOVÁCS JÁNOS`` for ``Kovács János``, ``+36-30-123-4567`` for
        ``+36 30 123 4567``; LAB-1215).

        Where the language changes a value's stem before a suffix (Hungarian ``Zsuzsanna`` ->
        ``Zsuzsannának``, ``Kovács`` -> ``Kováccsal``), the changed stem is found too, when an
        allowed suffix follows it; the span covers the stem (``Próba Zsuzsanná|nak``) and the
        vault keys it on the lemma.
        """
        profile = language_profile(language)
        matcher = inflection_for(language)
        spans: set[Span] = set()
        hallucinated = loose = 0
        for entity in dict.fromkeys(entities):
            hits = find_occurrences(
                text,
                entity.text,
                word_boundary=profile.word_boundary,
                allow_suffix=profile.allow_suffix,
            )
            if profile.allow_suffix:
                for stem, suffix in variant_stems(matcher, entity.text.strip(), entity.entity_type):
                    follows = re.compile(f"(?:{suffix})(?!\\w)", re.IGNORECASE)
                    hits += [
                        (start, end)
                        for start, end in find_occurrences(
                            text, stem, word_boundary=profile.word_boundary, allow_suffix=True
                        )
                        if follows.match(text, end)
                    ]
            if not hits:
                hits = _loose_occurrences(
                    text,
                    entity.text,
                    word_boundary=profile.word_boundary,
                    allow_suffix=profile.allow_suffix,
                )
                if hits:
                    loose += 1
            if not hits:
                hallucinated += 1
                continue
            # Every occurrence is masked, whatever the model's "occurrence" hint says: a value
            # that is personal data once is personal data everywhere (recall over precision).
            for start, end in hits:
                spans.add(
                    Span(start, end, entity.entity_type, text[start:end], self.score, self.name)
                )
        if loose:
            logger.debug("llm detector aligned %d values only up to case or format", loose)
        if hallucinated:
            logger.info("llm detector dropped %d values not found in the input", hallucinated)
        return sorted(spans, key=lambda s: (s.start, s.end, s.entity_type.value))

    # -- HTTP --

    def _client(self) -> httpx.Client:
        # Every request goes through a client made here: refuse again, so no future caller of
        # _client can send text without a key.
        self.require_available()
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return httpx.Client(
            timeout=httpx.Timeout(self.timeout),
            headers=headers,
            transport=self._transport,
        )

    def _payload(self, chunk: str, language: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": build_messages(chunk, language),
            "temperature": self.temperature,
            "stream": False,
        }
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        if self.reasoning_effort is not None:
            payload["reasoning_effort"] = self.reasoning_effort
        if self.reasoning_strength:
            payload["chat_template_kwargs"] = {"reasoning_strength": self.reasoning_strength}
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _detect_chunk(self, client: httpx.Client, chunk: str, language: str) -> list[LlmEntity]:
        payload = self._payload(chunk, language)
        last_error = "no attempt made"
        for attempt in range(self.max_retries + 1):
            try:
                content = self._complete(client, payload)
                entities = parse_entities(content)
                if not entities and self.challenge_empty:
                    entities = self._challenge_empty(client, payload, content, chunk, language)
                return entities
            except _InvalidOutput as exc:
                self._count(invalid_outputs=1)
                last_error = str(exc)
            except _Retryable as exc:
                last_error = str(exc)
            logger.warning(
                "llm detector attempt %d/%d failed: %s",
                attempt + 1,
                self.max_retries + 1,
                last_error,
            )
        raise DetectionError(f"llm detector failed: {last_error}")

    def _challenge_empty(
        self,
        client: httpx.Client,
        payload: dict[str, Any],
        answer: str,
        chunk: str,
        language: str,
    ) -> list[LlmEntity]:
        """The model reported nothing. If the rules find personal data in ``chunk``, the text
        probably talked the model out of it: ask once more, naming the types (never values).
        The second answer is taken as it is (empty again is not an error: the rules' spans
        are kept by the pipeline either way)."""
        from pii_guard.detect.rules import RuleDetector

        found = sorted({s.entity_type.value for s in RuleDetector().detect(chunk, language)})
        if not found:
            return []
        self._count(empty_challenged=1)
        logger.info("llm detector: empty answer but rules found %s; asking again", found)
        retry = dict(payload)
        retry["messages"] = [
            *payload["messages"],
            {"role": "assistant", "content": answer},
            {
                "role": "user",
                "content": _template("challenge.md").replace("{types}", ", ".join(found)),
            },
        ]
        try:
            return parse_entities(self._complete(client, retry))
        except (_InvalidOutput, _Retryable):
            # The first, valid answer stands; the rules cover what they found.
            return []

    def _complete(self, client: httpx.Client, payload: dict[str, Any]) -> str:
        try:
            response = client.post(self.url, json=payload)
        except httpx.TimeoutException:
            raise _Retryable("request timed out") from None
        except httpx.HTTPError as exc:
            raise _Retryable(f"transport error ({type(exc).__name__})") from None
        if response.status_code in _RETRYABLE_STATUS:
            raise _Retryable(f"HTTP {response.status_code}")
        if response.status_code >= 400:
            # Not retryable (auth, bad request). The body may echo the input: never include it.
            raise DetectionError(f"llm detector failed: HTTP {response.status_code}")
        try:
            data = response.json()
            choice = data["choices"][0]
            message = choice["message"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise _InvalidOutput("malformed completion response") from None
        self._record_usage(data.get("usage"))
        if isinstance(message, dict) and message.get("refusal"):
            self._count(refusals=1)
            raise _InvalidOutput("model refused")
        if choice.get("finish_reason") == "length":
            raise _InvalidOutput("completion truncated (finish_reason=length)")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):  # content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        if not isinstance(content, str) or not content.strip():
            raise _InvalidOutput("empty completion content")
        return content

    def _count(self, **deltas: int) -> None:
        with self._usage_lock:
            for key, delta in deltas.items():
                self.usage[key] += delta

    def _record_usage(self, usage: object) -> None:
        """Add one response's ``usage`` block (OpenAI shape) to :attr:`usage`."""
        deltas = {"requests": 1}
        if isinstance(usage, dict):
            for key in ("prompt_tokens", "completion_tokens"):
                if isinstance(usage.get(key), int):
                    deltas[key] = usage[key]
            for details, key, out in (
                ("prompt_tokens_details", "cached_tokens", "cached_tokens"),
                ("completion_tokens_details", "reasoning_tokens", "reasoning_tokens"),
            ):
                value = (usage.get(details) or {}).get(key)
                if isinstance(value, int):
                    deltas[out] = value
        self._count(**deltas)


DETECTOR_CLASS = LlmDetector
