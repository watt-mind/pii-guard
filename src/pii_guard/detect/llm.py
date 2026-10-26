"""LLM detector: a second detection pass on an OpenAI-compatible Chat Completions endpoint.

The model is asked for personal data as strict JSON (entity type + exact surface text). The
detector never trusts model offsets: it searches the returned surface strings in the input
itself, maps every occurrence to code-point offsets, and drops anything that does not appear
verbatim (hallucinated or "corrected" values). See ``docs/models.md``.

The default target is Meta's open-weight **Muse Spark Open** served on Baseten
(``meta-models/muse-spark-open-1026``), so detection can stay on infrastructure you control.
Any OpenAI-compatible endpoint works (vLLM, Baseten, the Meta Model API for fictional data).

Fail closed (ADR 0006): timeouts, HTTP errors and responses that are still not valid JSON after
one retry raise :class:`~pii_guard.types.DetectionError`. Error messages never contain the
input text or the model output, only status codes and counts.
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Any

import httpx
from pydantic import SecretStr

from pii_guard.config import Settings, get_settings
from pii_guard.types import TEXT_ENTITY_TYPES, DetectionError, EntityType, Span
from pii_guard.vault.inflection import inflection_for, variant_stems

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "DETECTOR_CLASS",
    "ENTITY_DESCRIPTIONS",
    "GENERIC_ENTITY_TYPES",
    "LANGUAGES",
    "LanguageProfile",
    "LlmDetector",
    "LlmEntity",
    "chunk_text",
    "find_occurrences",
    "language_profile",
    "parse_entities",
]

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "meta-models/muse-spark-open-1026"
DEFAULT_BASE_URL = "https://inference.baseten.co/v1"
MODEL_ENV_VAR = "PII_GUARD_LLM_DETECTOR_MODEL"

#: What the prompt tells the model about each text entity type.
ENTITY_DESCRIPTIONS: dict[EntityType, str] = {
    EntityType.PERSON: "a natural person's name (full name, surname, or given name used alone)",
    EntityType.ADDRESS: "a postal address or part of one (street, house number, postcode, town "
    "in an address), also when written in prose",
    EntityType.EMAIL: "an email address",
    EntityType.PHONE: "a phone or fax number",
    EntityType.DATE_OF_BIRTH: "a date that is someone's date of birth",
    EntityType.NATIONAL_ID_HU_TAX: "Hungarian personal tax ID (adóazonosító jel), 10 digits",
    EntityType.NATIONAL_ID_HU_TAJ: "Hungarian social security (TAJ) number, 9 digits",
    EntityType.ID_DOCUMENT: "an ID card, passport or driving licence number",
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

    - ``notes``: file under ``prompts/languages/`` with language-specific instructions.
    - ``entity_types``: the types the prompt asks for.
    - ``allow_suffix``: a value may run on into a longer word (agglutinative languages such as
      Hungarian: "Teszt Elek" matches inside "Teszt Eleknek"). Otherwise the match must end at
      a word boundary.
    - ``word_boundary``: a match must start at a word boundary. Off for scripts written
      without spaces between words.
    """

    code: str
    name: str
    notes: str = "default.md"
    entity_types: tuple[EntityType, ...] = GENERIC_ENTITY_TYPES
    allow_suffix: bool = True
    word_boundary: bool = True


LANGUAGES: dict[str, LanguageProfile] = {
    "hu": LanguageProfile(
        "hu", "Hungarian", "hu.md", tuple(ENTITY_DESCRIPTIONS), allow_suffix=True
    ),
    "en": LanguageProfile("en", "English", "en.md", allow_suffix=False),
}
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
    code = (language or "").strip().lower().replace("_", "-").split("-")[0] or "und"
    if code in LANGUAGES:
        return LANGUAGES[code]
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


def build_messages(text: str, language: str) -> list[dict[str, str]]:
    """The chat messages for one chunk, for ``language`` (see :func:`language_profile`).

    Placeholders are substituted with ``str.replace`` so braces in the input or in the JSON
    example are never interpreted.
    """
    profile = language_profile(language)
    types = "\n".join(f"- {t.value}: {ENTITY_DESCRIPTIONS[t]}" for t in profile.entity_types)
    system = (
        _template("system.md")
        .replace("{entity_types}", types)
        .replace("{language_name}", profile.name)
        .replace("{language_notes}", _template("languages", profile.notes).strip())
    )
    user = _template("user.md").replace("{language}", profile.code).replace("{text}", text)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# --- Parsing ----------------------------------------------------------------


def _extract_json(content: str) -> Any:
    """The first JSON value in ``content``, ignoring reasoning blocks and code fences."""
    content = _THINK_RE.sub("", content)
    # An unterminated reasoning block ("...</think>" with the opening tag stripped upstream).
    for closing in ("</think>", "</thinking>", "</reasoning>"):
        if closing in content:
            content = content.rsplit(closing, 1)[1]
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[{\[]", content):
        try:
            value, _ = decoder.raw_decode(content, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict | list):
            return value
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
    no text are dropped. Raises ``_InvalidOutput`` when there is no usable JSON structure.
    """
    data = _extract_json(content)
    items = data.get("entities") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise _InvalidOutput("model output has no entities list")
    entities: list[LlmEntity] = []
    dropped = 0
    for item in items:
        if not isinstance(item, dict):
            dropped += 1
            continue
        entity_type = _to_entity_type(item.get("type", item.get("entity_type")))
        value = item.get("text", item.get("value"))
        if entity_type is None or not isinstance(value, str) or not value.strip():
            dropped += 1
            continue
        occurrence = item.get("occurrence")
        valid = isinstance(occurrence, int) and not isinstance(occurrence, bool)
        if not valid or occurrence < 1:
            occurrence = None
        entities.append(LlmEntity(entity_type, value.strip(), occurrence))
    if dropped:
        logger.debug("llm detector dropped %d malformed or unknown-type entities", dropped)
    return entities


# --- Offset mapping ---------------------------------------------------------


@cache
def _pattern(value: str, word_boundary: bool, allow_suffix: bool) -> re.Pattern[str]:
    """Literal match, but any whitespace run in ``value`` matches any whitespace run."""
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
    answer. Returns ``[]`` when the value is not in the text: the caller drops it as
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
    return sorted(found)


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


class LlmDetector:
    """Detect personal data with an LLM on an OpenAI-compatible Chat Completions endpoint.

    Every argument is keyword-only and optional; unset ones come from :class:`Settings`
    (``PII_GUARD_LLM_DETECTOR_URL``, ``PII_GUARD_LLM_DETECTOR_API_KEY``) and
    ``PII_GUARD_LLM_DETECTOR_MODEL``, then the Baseten Muse Spark Open defaults.

    - ``base_url``: the API root (``.../v1``) or the full ``.../chat/completions`` URL.
    - ``reasoning_effort``: sent only when set. Muse Spark always reasons and rejects
      ``"none"``; use ``"minimal"`` or ``"low"`` for detection.
    - ``json_mode``: send ``response_format: {"type": "json_object"}``.
    - ``chunk_size`` / ``chunk_overlap``: in code points; long inputs are split and each chunk
      is a separate request. Values are then searched in the whole text.
    - ``max_retries``: extra attempts after a timeout, a transport error, a retryable HTTP
      status (429, 5xx) or output that is not valid JSON.
    - ``transport``: an ``httpx.BaseTransport`` (tests use ``httpx.MockTransport``).
    """

    name = "llm"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | SecretStr | None = None,
        model: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 1,
        temperature: float = 0.0,
        reasoning_effort: str | None = None,
        json_mode: bool = True,
        max_tokens: int | None = 4096,
        chunk_size: int = 6000,
        chunk_overlap: int = 300,
        score: float = 0.85,
        transport: httpx.BaseTransport | None = None,
        settings: Settings | None = None,
    ) -> None:
        settings = settings if settings is not None else get_settings()
        url = (base_url or settings.llm_detector_url or DEFAULT_BASE_URL).rstrip("/")
        self.url = url if url.endswith("/chat/completions") else url + "/chat/completions"
        key = api_key if api_key is not None else settings.llm_detector_api_key
        self._api_key = key.get_secret_value() if isinstance(key, SecretStr) else key
        self.model = (
            model
            or getattr(settings, "llm_detector_model", None)
            or os.environ.get(MODEL_ENV_VAR)
            or DEFAULT_MODEL
        )
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if not 0.0 <= score <= 1.0:
            raise ValueError("score must be in [0, 1]")
        chunk_text("", chunk_size, chunk_overlap)  # validates the chunk parameters
        self.timeout = timeout
        self.max_retries = max_retries
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort
        self.json_mode = json_mode
        self.max_tokens = max_tokens
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.score = score
        self._transport = transport

    def __repr__(self) -> str:  # never the key
        return f"LlmDetector(url={self.url!r}, model={self.model!r})"

    # -- public --

    def detect(self, text: str, language: str = "hu") -> list[Span]:
        if not text.strip():
            return []
        entities: list[LlmEntity] = []
        with self._client() as client:
            for _, chunk in chunk_text(text, self.chunk_size, self.chunk_overlap):
                entities.extend(self._detect_chunk(client, chunk, language))
        return self.align(text, entities, language)

    def align(self, text: str, entities: Iterable[LlmEntity], language: str = "hu") -> list[Span]:
        """Map entities to spans over ``text``; values not found verbatim are dropped.

        Where the language changes a value's stem before a suffix (Hungarian ``Zsuzsanna`` ->
        ``Zsuzsannának``, ``Kovács`` -> ``Kováccsal``), the changed stem is found too, when an
        allowed suffix follows it; the span covers the stem (``Próba Zsuzsanná|nak``) and the
        vault keys it on the lemma.
        """
        profile = language_profile(language)
        matcher = inflection_for(language)
        spans: set[Span] = set()
        hallucinated = 0
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
                hallucinated += 1
                continue
            # Every occurrence is masked, whatever the model's "occurrence" hint says: a value
            # that is personal data once is personal data everywhere (recall over precision).
            for start, end in hits:
                spans.add(
                    Span(start, end, entity.entity_type, text[start:end], self.score, self.name)
                )
        if hallucinated:
            logger.info("llm detector dropped %d values not found in the input", hallucinated)
        return sorted(spans, key=lambda s: (s.start, s.end, s.entity_type.value))

    # -- HTTP --

    def _client(self) -> httpx.Client:
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
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _detect_chunk(self, client: httpx.Client, chunk: str, language: str) -> list[LlmEntity]:
        payload = self._payload(chunk, language)
        last_error = "no attempt made"
        for attempt in range(self.max_retries + 1):
            try:
                content = self._complete(client, payload)
                return parse_entities(content)
            except (_Retryable, _InvalidOutput) as exc:
                last_error = str(exc)
            logger.warning(
                "llm detector attempt %d/%d failed: %s",
                attempt + 1,
                self.max_retries + 1,
                last_error,
            )
        raise DetectionError(f"llm detector failed: {last_error}")

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
        if choice.get("finish_reason") == "length":
            raise _InvalidOutput("completion truncated (finish_reason=length)")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):  # content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        if not isinstance(content, str) or not content.strip():
            raise _InvalidOutput("empty completion content")
        return content


DETECTOR_CLASS = LlmDetector
