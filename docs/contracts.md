# Contracts

> Status: accepted for the hackathon build. These are the interfaces the detectors, vault,
> API, evaluation harness and UI agree on. Sections marked **implemented** exist in code;
> sections marked **planned** are the contract the owning component must implement. Change a
> contract only together with every consumer, and update this file in the same pull request.

## Core types (implemented)

Module: `pii_guard.types`.

### `EntityType`

A `StrEnum` whose values equal their names, one member per row of
[entities.md](entities.md). The JSON form of a type is its name (`"PERSON"`).

| Group | Members |
|---|---|
| Text | `PERSON`, `ADDRESS`, `EMAIL`, `PHONE`, `DATE_OF_BIRTH`, `NATIONAL_ID_HU_TAX`, `NATIONAL_ID_HU_TAJ`, `ID_DOCUMENT`, `BANK_ACCOUNT`, `COMPANY_ID_HU`, `ORGANIZATION`, `PARCEL_NUMBER_HU`, `VEHICLE_PLATE` |
| Visual | `FACE`, `SIGNATURE`, `ID_PHOTO`, `STAMP` |

`TEXT_ENTITY_TYPES` and `VISUAL_ENTITY_TYPES` are `frozenset`s of the two groups;
`EntityType.X.is_visual` tells them apart. A test keeps the enum and `entities.md` in sync:
adding a type means adding it to both.

### `Span`

```python
@dataclass(frozen=True, slots=True)
class Span:
    start: int                # code-point offset into the analysed text, inclusive
    end: int                  # exclusive; text == source[start:end]
    entity_type: EntityType   # a plain "PERSON" string is accepted and normalized
    text: str                 # the raw value. Never log it.
    score: float              # detector confidence in [0, 1]
    detector: str             # registry name of the detector, e.g. "rules"

    length: int               # property, end - start
    def overlaps(self, other: Span) -> bool
    def to_public_dict(self) -> dict  # {start, end, entity_type, score, detector}, no text
```

- Construction validates: `0 <= start < end`, `len(text) == end - start`,
  `0 <= score <= 1`, non-empty `detector`, known `entity_type`. Violations raise
  `ValueError`.
- `repr()` / `str()` **omit `text`** (`text=<redacted>`), so spans can be logged or appear in
  assertion messages without leaking the value. Spans are hashable and compare by value.
- Offsets are Python `str` indices (code points), not bytes or UTF-16 units.

### `Detector`

```python
@runtime_checkable
class Detector(Protocol):
    name: str

    def detect(self, text: str, language: str = "hu") -> list[Span]: ...
```

- `language` is an ISO 639-1 code; `"hu"` first.
- Returned offsets refer to `text` exactly as passed in. Order is not significant; the
  resolver sorts and merges.
- A detector that can't finish raises `DetectionError`. It never returns a partial result
  silently ([ADR 0006](decisions/0006-fail-closed.md)).
- Constructors take keyword arguments only, so the registry can build them with
  `create_detector(name, **kwargs)`.

### Errors

```python
class PiiGuardError(Exception):      # code = "internal_error",   status_code = 500
class DetectionError(PiiGuardError): # code = "detection_failed", status_code = 503
class MaskingError(PiiGuardError):   # code = "masking_failed",   status_code = 500

PiiGuardError(message: str = "", *, code: str | None = None)
err.code     # stable machine-readable id, used in API error bodies
err.message  # the message, or the code when empty
```

Messages **must not contain raw values**: describe entity types, counts or placeholder ids
(`"could not mask 1 PERSON span"`). The API returns `code` and `message` to the client as is.
Subclass for new failure kinds and set `code` / `status_code` on the class.

## Detector registry (implemented)

Module: `pii_guard.registry`. Names map to `"package.module:ClassName"` strings that are
imported only when resolved, so model dependencies stay off the CLI and API import path.

```python
register_detector(name: str, target: str, *, replace: bool = False) -> None
detector_names() -> list[str]            # registered + entry-point names
resolve_detector(name: str) -> type[Detector]   # raises DetectionError if unknown / broken
create_detector(name: str, **kwargs) -> Detector
ENTRY_POINT_GROUP = "pii_guard.detectors"
```

Resolution order:

1. Explicit registrations. Built in: `"rules"` → `pii_guard.detect.rules:RuleDetector`.
2. Entry points in the `pii_guard.detectors` group (third-party packages).
3. Convention: name `x` → module `pii_guard.detect.x`, attribute `DETECTOR_CLASS`.

A new built-in detector therefore only adds `src/pii_guard/detect/<name>.py` ending in
`DETECTOR_CLASS = MyDetector`; it doesn't edit the registry. The detector's `name` attribute
should equal its registry name, and it is what goes into `Span.detector`.

## Configuration (implemented)

Module: `pii_guard.config`. `Settings` is a pydantic-settings model; `get_settings()` returns
a cached instance (`get_settings.cache_clear()` after changing the environment in tests).
Values come from the environment, then `.env` in the working directory. Empty values count as
unset. Secrets are `SecretStr`.

| Env var | Field | Type | Default |
|---|---|---|---|
| `PII_GUARD_HOST` | `host` | `str` | `127.0.0.1` |
| `PII_GUARD_PORT` | `port` | `int` | `8787` |
| `PII_GUARD_LOG_LEVEL` | `log_level` | `str` | `info` |
| `PII_GUARD_DEFAULT_LANGUAGE` | `default_language` | `str` | `hu` |
| `PII_GUARD_UPSTREAM_BASE_URL` | `upstream_base_url` | `str \| None` | unset |
| `PII_GUARD_UPSTREAM_API_KEY` | `upstream_api_key` | `SecretStr \| None` | unset |
| `PII_GUARD_TENANT_KEY` | `tenant_key` | `SecretStr \| None` (hex) | unset |
| `PII_GUARD_LLM_DETECTOR_URL` | `llm_detector_url` | `str \| None` | unset |
| `PII_GUARD_LLM_DETECTOR_API_KEY` | `llm_detector_api_key` | `SecretStr \| None` | unset |
| `PII_GUARD_SAM_URL` | `sam_url` | `str \| None` | unset |
| `META_API_KEY` | `meta_api_key` | `SecretStr \| None` | unset |

`settings.tenant_key_bytes() -> bytes | None` decodes the hex tenant key (raises
`ValueError`, without echoing the key, if it isn't hex). A new key goes into `Settings`,
`.env.example` and this table together; a test checks every `.env.example` key has a field.

## Application and CLI (implemented)

- `pii_guard.api.app:create_app(settings: Settings | None = None) -> FastAPI`. Settings are
  on `request.app.state.settings`.
- `GET /healthz` → `200 {"status": "ok", "version": "<package version>"}`.
- **Routers.** Every module in `pii_guard/api/routes/` that defines a module-level
  `router: fastapi.APIRouter` is mounted by `pii_guard.api.routes.include_routers(app)`, in
  module-name order; modules starting with `_` are skipped. Routers declare full paths
  (`@router.post("/v1/mask")`). Adding an endpoint = adding a module; no shared file changes.
  Import errors propagate, so a broken router stops startup.
- `pii_guard.api.errors.error_response(status_code, code, message) -> JSONResponse` builds the
  error body for routers that need one directly; raising a `PiiGuardError` is usually simpler.
- CLI `pii-guard` (`pii_guard.cli:main(argv: Sequence[str] | None = None) -> int`):
  - `serve [--host H] [--port P] [--reload]` runs `create_app` under uvicorn, defaults from
    `Settings` (port 8787);
  - `eval [...]` passes everything after `eval` untouched to
    `pii_guard.eval.cli:main(argv: Sequence[str] | None) -> int` and exits with its return
    code (see "Evaluation fixtures and harness" below).

## REST API (planned)

JSON over HTTP, UTF-8. Offsets are code-point indices into the request `text`. `language`
defaults to `Settings.default_language` (`"hu"`).

### Errors

Every non-2xx response, including validation errors and unknown routes, has this body:

```json
{"error": {"code": "invalid_request", "message": "invalid request body: body.text"}}
```

| Status | `code` | When |
|---|---|---|
| 404 | `not_found` | Unknown route, or unknown `session_id` on unmask |
| 422 | `invalid_request` | Body fails validation. The message lists field locations only, never values. |
| 500 | `masking_failed` | `MaskingError` |
| 503 | `detection_failed` | `DetectionError` (including timeouts) |
| 500 | `internal_error` | Anything unexpected. No exception text is returned. |

Fail closed: on any error the response carries no masked or partially masked text.

### `POST /v1/analyze`

Detect without masking.

```json
// request
{"text": "Teszt Elek, teszt.elek@example.com", "language": "hu"}
// response 200
{"spans": [
  {"start": 0,  "end": 10, "entity_type": "PERSON", "score": 0.97, "detector": "ner"},
  {"start": 12, "end": 34, "entity_type": "EMAIL",  "score": 1.0,  "detector": "rules"}
]}
```

Spans are sorted by `start`, after the resolver has merged overlaps. The raw `text` of a span
is **not** returned (the caller already has it; it can slice). This is
`Span.to_public_dict()`.

### `POST /v1/mask`

```json
// request
{"text": "Teszt Elek írt Teszt Eleknek.", "language": "hu", "session_id": null}
// response 200
{
  "masked_text": "[[PERSON_7f3a]] írt [[PERSON_7f3a]]nek.",
  "session_id": "s_2c9e…",
  "entities": [{"placeholder": "[[PERSON_7f3a]]", "entity_type": "PERSON", "count": 2}]
}
```

- `session_id` omitted or `null` → a new session is created and returned. Passing an existing
  id reuses its mapping, so the same value keeps the same placeholder across calls.
- `entities` lists each distinct placeholder once, with how many occurrences were replaced.
  It never contains original values.
- Entity types whose policy is `keep` are left in place and not listed; a `block` policy hit
  fails the request.

### `POST /v1/unmask`

```json
// request
{"text": "Kedves [[PERSON_7f3a]]!", "session_id": "s_2c9e…"}
// response 200
{"text": "Kedves Teszt Elek!", "unresolved": []}
```

`unresolved` lists placeholder-shaped tokens (`[[TYPE_id]]`) that aren't in the session
mapping (invented or mangled by the model). They are left in `text` as is. Unknown or
expired `session_id` → 404 `not_found`.

## Vault (planned)

Package: `pii_guard.vault`. Implements [ADR 0007](decisions/0007-keyed-pseudonyms.md).

```python
class Vault:
    def __init__(self, tenant_key: bytes) -> None: ...

    # None -> a new session with a fresh random id; an existing id -> that session.
    def session(self, session_id: str | None = None) -> VaultSession: ...


class VaultSession:
    session_id: str

    # Replace each span with its placeholder and record the mapping.
    def mask(self, text: str, spans: list[Span]) -> str: ...

    # Replace known placeholders with their original values.
    def unmask(self, text: str) -> str: ...

    # (placeholder, entity_type, count) for every placeholder this session issued.
    def entities(self) -> list[tuple[str, EntityType, int]]: ...


class StreamUnmasker:
    def __init__(self, session: VaultSession) -> None: ...

    # Text that is safe to emit now; holds back a trailing partial "[[...".
    def feed(self, chunk: str) -> str: ...

    # Whatever is still buffered, at the end of the stream.
    def flush(self) -> str: ...
```

- **Placeholder format:** `[[<TYPE>_<id>]]`, where `<TYPE>` is the `EntityType` value and
  `<id>` is lowercase hex, at least 4 characters, from a truncated HMAC-SHA256 of the
  normalized value under the tenant key (optionally mixed with the session key). Regex:
  `\[\[([A-Z][A-Z0-9_]*)_([0-9a-f]{4,})\]\]`. Example: `[[PERSON_7f3a]]`. Collisions inside a
  session extend the id.
- Same normalized value → same placeholder within a session; different tenants never share
  placeholders.
- `mask` raises `MaskingError` on overlapping or out-of-range spans rather than guessing.
- `StreamUnmasker.feed("[[PERS") + feed("ON_7f3a]] ok") + flush()` equals
  `session.unmask("[[PERSON_7f3a]] ok")`: concatenated output is identical to unmasking the
  whole text at once.
- The mapping never leaves the process, is never logged, and has a TTL.

## Evaluation fixtures and harness (implemented)

Package: `pii_guard.eval`. Committed synthetic fixtures live under `eval/fixtures/` as JSON
Lines, one document per line, UTF-8, **one file per language and set**:
`eval/fixtures/<language>-<set>.jsonl` (`hu-smoke.jsonl`, `en-smoke.jsonl`). The record's
`language` field is authoritative; the file name is a convention.

```json
{"id": "hu-contract-0001", "language": "hu", "text": "Alulírott Teszt Elek …", "spans": [{"start": 10, "end": 20, "entity_type": "PERSON", "text": "Teszt Elek"}], "meta": {"kind": "contract"}}
```

| Field | Type | Notes |
|---|---|---|
| `id` | string | Unique across everything loaded together, stable across regenerations with the same seed |
| `language` | string | BCP-47-style tag, e.g. `hu`, `en`, `en-GB`. Passed as is to detectors and the vault; selects the surface-form hook for the leak rate (`en-GB` falls back to `en`) |
| `text` | string | The synthetic document |
| `spans` | list | Gold labels: `start`, `end` (code-point offsets, end exclusive), `entity_type` (a text `EntityType` value), optional `text` (must equal `text[start:end]`) |
| `meta` | object | Optional, free-form: `kind`, `tags` (e.g. `hard-negative`), generator seed, template |

Gold spans don't overlap, aren't blank and don't start or end with whitespace. A Hungarian
suffix that leaves the value intact stays outside the span (`Teszt Elek|nek`); a
stem-changing form is labelled as the whole word (`Minta Annának`). Every value is fictional
([ADR 0005](decisions/0005-synthetic-data-only.md)). `load_fixtures` rejects anything else with
file, line and field, never the value.

Python API (`from pii_guard.eval import …`), for the CLI, corpus generators and red-team
scorers:

```python
load_fixtures(paths) -> list[Document]          # files or directories; validates
write_fixtures(path, docs); dump_document(doc)  # JSONL out
from_markup(id, "… {{PERSON|Teszt Elek}}nek …", language="hu") -> Document; label(type, value)
find_surface_forms(text, value, entity_type, language) -> list[(start, end)]
register_language_forms(LanguageForms(...))     # per-language surface-form hook
DetectorAnalyzer(["rules", "llm"])              # registry names; unloadable ones -> .skipped
run_documents(docs, analyzer) -> list[DocumentResult]   # detect, vault-mask, unmask
summarize(results) -> dict; match_counts(gold, pred, "exact"|"overlap"); prf(counts)
leak_report(doc, masked_text) -> list[ValueLeak]; over_masked(doc, masked_spans)
build_scorecard(results, detectors=[...], fixture_paths=[...]) -> dict; render_markdown(card)
```

`run_documents` accepts any object with `analyze(text, language) -> list[Span]`, so a
detection pipeline plugs in without changes here. Only `mask`-policy types are masked
(`DEFAULT_POLICY`: everything except `ORGANIZATION` and `COMPANY_ID_HU`), each document in a
fresh vault session under the public `EVAL_TENANT_KEY`.

CLI: `pii-guard eval [--fixtures PATH ...] [--detectors rules[,ner,llm]] [--language hu[,en]]
[--json OUT] [--markdown OUT]` (`pii_guard.eval.cli:main(argv)`). `--fixtures` repeats and
accepts directories (default `eval/fixtures`). Unloadable detectors are skipped with a
warning. Markdown goes to stdout. Exit codes: 0 ok, 1 a detector or the vault failed during the
run (fail closed, no scorecard), 2 bad arguments, fixtures or no loadable detector.

The JSON scorecard (`schema_version` 1) has `meta` (commit, dirty flag, version, detectors,
skipped detectors, language filter, fixture paths with SHA-256), `overall` and `languages`
(one block per language). A block holds `detection.{exact,overlap}.{per_type,micro,macro}`,
`leak`, `over_masking` (both with `per_type`), `roundtrip` and `latency_ms`. It never
contains document text or labelled values.
