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
| `PII_GUARD_DETECTORS` | `detectors` | `tuple[str, ...]` (comma-separated registry names) | `rules` |
| `PII_GUARD_POLICY_OVERRIDES` | `policy_overrides` | `dict[EntityType, Policy]` (`TYPE=mask\|keep\|block,...`) | none |
| `PII_GUARD_UPSTREAM_BASE_URL` | `upstream_base_url` | `str \| None` | unset |
| `PII_GUARD_UPSTREAM_API_KEY` | `upstream_api_key` | `SecretStr \| None` | unset |
| `PII_GUARD_TENANT_KEY` | `tenant_key` | `SecretStr \| None` (hex) | unset |
| `PII_GUARD_KNOWN_VALUES_MAX` | `known_values_max` | `int` (known values per session) | `1000` |
| `PII_GUARD_KNOWN_VALUES_MAX_LENGTH` | `known_values_max_length` | `int` (characters per value) | `256` |
| `PII_GUARD_LLM_DETECTOR_URL` | `llm_detector_url` | `str \| None` | unset |
| `PII_GUARD_LLM_DETECTOR_API_KEY` | `llm_detector_api_key` | `SecretStr \| None` | unset |
| `PII_GUARD_SAM_URL` | `sam_url` | `str \| None` | unset |
| `META_API_KEY` | `meta_api_key` | `SecretStr \| None` | unset |

`PII_GUARD_DETECTORS` picks the REST API's detectors (`rules,llm` for the demo; the gateway
has its own per-mode set). `PII_GUARD_POLICY_OVERRIDES` is parsed and validated when the
settings load: an unknown type or policy stops startup. The LLM detector also reads
`PII_GUARD_LLM_DETECTOR_MODEL` and `PII_GUARD_LLM_DETECTOR_REASONING_EFFORT` from the
environment (`LlmDetector` falls back to both itself, so the registry and `pii-guard eval`
honour them too; Muse Spark Open on Baseten needs `REASONING_EFFORT=low`); folding those, the text size limit and the gateway settings into `Settings` is
LAB-1095.

`settings.tenant_key_bytes() -> bytes | None` decodes the hex tenant key (raises
`ValueError`, without echoing the key, if it isn't hex). A new key goes into `Settings`,
`.env.example` and this table together; a test checks every `.env.example` key has a field.

## Application and CLI (implemented)

- `pii_guard.api.app:create_app(settings: Settings | None = None) -> FastAPI`. Settings are
  on `request.app.state.settings`, the detector names on `app.state.detector_names` and the
  `PolicySet` on `app.state.policies`. An unknown name in `PII_GUARD_DETECTORS` raises
  `DetectionError` here, at startup. The analyzer (`app.state.analyzer`, default
  `pii_guard.api.deps.RegistryAnalyzer`) runs the detectors through `DetectionPipeline`.
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

## Entity policies (implemented)

Module: `pii_guard.policy`. Every entity type has a `Policy`: `mask` (replace with a
placeholder), `keep` (leave in place) or `block` (refuse the request). Defaults are in
[entities.md](entities.md): `ORGANIZATION`, `COMPANY_ID_HU` and `STAMP` are `keep`, the rest
`mask`.

```python
class Policy(StrEnum): MASK = "mask"; KEEP = "keep"; BLOCK = "block"
DEFAULT_POLICIES: Mapping[EntityType, Policy]
parse_overrides("ORGANIZATION=mask,EMAIL=block") -> dict[EntityType, Policy]  # ValueError
PolicySet(overrides=None)            # defaults + overrides; PolicySet.from_settings(settings)
policies.of(EntityType.EMAIL) -> Policy; policies.keep_types -> frozenset[EntityType]
policies.apply(spans) -> PolicyDecision(masked, kept)   # raises BlockedEntityError
class BlockedEntityError(PiiGuardError): code = "blocked_entity"; status_code = 422
```

Policies are applied **after** the resolver: `keep` types lose overlaps against masked types
(`DetectionPipeline(keep_types=policies.keep_types)`), so a name inside a sole trader's
company name is still masked, and are then left in place. `BlockedEntityError` carries types
and counts (`counts`), never values. The REST API, the gateway and the eval share the
resolver (`DetectionPipeline`) and the defaults. The gateway's `PII_GUARD_GATEWAY_KEEP_TYPES`
is a deprecated alias: when set, it is the exact keep set; `PII_GUARD_POLICY_OVERRIDES` wins.

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
| 422 | `invalid_known_value` | A pre-loaded known value is too short (< 3 non-space characters), too long, or has an unknown or visual type. The message names its index and type, never the value. |
| 422 | `too_many_known_values` | The session would hold more than `PII_GUARD_KNOWN_VALUES_MAX` known values; nothing is added. |
| 422 | `blocked_entity` | `/v1/mask` (or the gateway) found an entity type whose policy is `block`. The message lists types and counts only; nothing is masked, stored or forwarded. |
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
  {"start": 0,  "end": 10, "entity_type": "PERSON", "score": 0.97, "detector": "ner",   "policy": "mask"},
  {"start": 12, "end": 34, "entity_type": "EMAIL",  "score": 1.0,  "detector": "rules", "policy": "mask"}
]}
```

Spans are sorted by `start`, after the resolver (`DetectionPipeline`) has merged overlaps. The
raw `text` of a span is **not** returned (the caller already has it; it can slice). This is
`Span.to_public_dict()` plus `policy`, the type's effective policy. Every span is returned,
including `keep` and `block` ones: analyze never refuses on policy.

### `POST /v1/mask`

```json
// request
{"text": "Teszt Elek írt Teszt Eleknek.", "language": "hu", "session_id": null}
// response 200
{
  "masked_text": "[[PERSON_7f3a]] írt [[PERSON_7f3a]]nek.",
  "session_id": "s_2c9e…",
  "entities": [{"placeholder": "[[PERSON_7f3a]]", "entity_type": "PERSON", "count": 2}],
  "kept": []
}
```

- `session_id` omitted or `null` → a new session is created and returned. Passing an existing
  id reuses its mapping, so the same value keeps the same placeholder across calls.
- `entities` lists each distinct placeholder once, with how many occurrences were replaced.
  It never contains original values.
- Only `mask`-policy spans are replaced. Spans of `keep` types are left in place and reported
  in `kept` as `{"entity_type": "ORGANIZATION", "count": 1}`, sorted by type: no values, no
  offsets.
- Any `block`-policy span fails the request with `422 blocked_entity`: no masked text, no
  vault entry (a session the request created is dropped; an existing one is unchanged).
- If the session has known values (below), the `known` detector runs on top of the configured
  detectors: its spans win every conflict in the resolver and are masked even when their
  type's policy is `keep` (the application asked for it); a `block` type still refuses.

### `POST /v1/sessions` and `POST /v1/sessions/{session_id}/known-values`

Pre-load values the application already knows are sensitive in this conversation (a customer
record, a case file, a contact list). Every occurrence is then masked by the deterministic
`known` detector (`src/pii_guard/detect/known.py`, score `1.0`), in `/v1/mask` and in the
gateway (`X-PII-Guard-Session`), even when no statistical detector finds it. It is an extra
detector, never a requirement.

```json
// POST /v1/sessions (the body is optional)
{"known_values": [{"value": "Gyakorló Tihamér", "entity_type": "PERSON"},
                  {"value": "KX-77-3021", "entity_type": "ID_DOCUMENT"}]}
// response 201
{"session_id": "s_2c9e…", "added": 2, "total": 2}

// POST /v1/sessions/s_2c9e…/known-values
{"known_values": [{"value": "Minta Rozália", "entity_type": "PERSON"}]}
// response 200
{"session_id": "s_2c9e…", "added": 1, "total": 3}
```

- Matching follows the vault's occurrence rules: case- and whitespace-insensitive, whole words,
  and per language the inflected forms (Hungarian suffixes and stem changes such as
  `Gyakorló Tihamérnak`, `Próba Zsuzsannát`, `Kováccsal`; the English possessive). Spans cover
  the stem, so the suffix stays outside the placeholder.
- Placeholders are the usual keyed ones: a value that is pre-loaded *and* found by another
  detector (or masked earlier in the session) gets one placeholder.
- Values are stored only on the vault session (same sliding TTL) and are forgotten when it
  expires or is dropped. They are never logged or echoed: responses carry counts only
  (`added` excludes duplicates), and the access log shows the route template, not the id.
- Limits: `PII_GUARD_KNOWN_VALUES_MAX` values per session (default 1000) and
  `PII_GUARD_KNOWN_VALUES_MAX_LENGTH` characters per value (default 256). Values with fewer
  than 3 non-space characters are refused (`422 invalid_known_value`): they would over-mask.
  A refused request adds nothing; a refused `POST /v1/sessions` creates no session.
- Unknown or expired `session_id` → 404 `not_found`.

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

### `POST /v1/mask/image`

Cover faces, signatures, ID photos and text personal data in a PNG or JPEG image
(`pii_guard.api.routes.image`, shared pipeline in `pii_guard.api.routes.image_masking`).

Request, either form:

- **raw upload**: the image bytes as the body with `Content-Type: image/png` or `image/jpeg`;
  optional `?language=hu`. `curl --data-binary @card.png -H 'Content-Type: image/png' …`
- **JSON**: `{"image": "<base64>" | "data:image/png;base64,…", "language": "hu"}`.

The format is sniffed from the bytes; anything but PNG/JPEG is `415 unsupported_media_type`.
Images up to 10 MiB decoded (`app.state.max_image_bytes`); larger is `413`. Multipart form
uploads are not accepted (they would need an extra dependency).

```json
// response 200
{
  "image": "iVBORw0KGgo…",            // the masked image, base64 PNG, re-encoded from pixels
  "media_type": "image/png",
  "width": 720, "height": 450,
  "regions": [
    {"entity_type": "FACE", "box": [72, 116, 188, 262], "source": "sam", "detector": "sam", "score": null, "policy": "mask"},
    {"entity_type": "NATIONAL_ID_HU_TAJ", "box": [310, 184, 437, 206], "source": "ocr", "detector": "rules", "score": 1.0, "policy": "mask"},
    {"entity_type": "STAMP", "box": [392, 572, 548, 728], "source": "sam", "detector": "sam", "score": null, "policy": "keep"}
  ],
  "masked": [{"entity_type": "FACE", "count": 1}, {"entity_type": "NATIONAL_ID_HU_TAJ", "count": 1}],
  "kept": [{"entity_type": "STAMP", "count": 1}],
  "analysis": {
    "sam": {"model": "sam-3.1", "entity_types": ["FACE", "SIGNATURE", "ID_PHOTO", "STAMP"]},
    "ocr": {"ran": true, "engine": "tesseract", "detectors": ["rules", "llm"], "models": {"llm": "muse-spark-1.3"}, "reason": null}
  }
}
```

- `box` is `[x1, y1, x2, y2]`, inclusive pixel corners in the image after EXIF orientation.
  `source` is `sam` (SAM 3.1 segmentation) or `ocr` (OCR word boxes of a span a text detector
  found); `detector` is `sam` or the text detector's registry name. SAM gives no scores.
- `FACE` boxes are grown before masking (40% up, 10% on each side, 5% down, clamped to the
  image) because SAM's face box leaves hair and ears visible; the reported box is the grown
  one, i.e. the area covered.
- `analysis.ocr.models` maps each model-backed text detector to its model id, so clients can
  label regions by what actually ran.
- Regions never carry the covered text or pixels. Overlapping regions of the same type and
  source are merged into their union (SAM's `signature` and `squiggly line` prompts).
- Policies apply per region: `mask` regions are filled solid black (plus 2 px), `keep` regions
  (`STAMP` by default) are reported and left visible, any `block` region is
  `422 blocked_entity` with no image.
- SAM segments every visual type it has a prompt for (one Meta API request per prompt:
  `face`, `signature`, `squiggly line`, `id photo`, `stamp`). It needs `META_API_KEY` (or
  `PII_GUARD_SAM_API_KEY`); without one every call is `503 detection_failed`.
- Text in the image: when Tesseract is installed (`uv sync --extra ocr` and the `tesseract`
  binary with `hun`/`eng` data), OCR text goes through the API's detectors
  (`PII_GUARD_DETECTORS`, so names need `llm`). Otherwise only SAM runs and `analysis.ocr` is
  `{"ran": false, "engine": null, "detectors": [], "models": {}, "reason": "tesseract_unavailable"}`: text in
  the image was **not** checked.
- Fail closed: any SAM, OCR or detector error is `503 detection_failed`, a masking error
  `500 masking_failed`; an undecodable image or bad base64 is `422 invalid_image`. Error bodies
  never contain the image.

The gateway (`POST /v1/chat/completions`) runs the same pipeline on `image_url` content parts
whose URL is an inline `data:image/png|jpeg;base64,…` URL, with the request mode's detectors
for OCR text, and forwards a masked PNG data URL in its place (other part fields such as
`detail` are kept). Remote `http(s)` and other URLs are `400 unsupported_content`: the guard
never fetches URLs. Limits: `PII_GUARD_GATEWAY_MAX_IMAGES` (4) images of
`PII_GUARD_GATEWAY_MAX_IMAGE_BYTES` (10 MiB) each, `PII_GUARD_GATEWAY_IMAGE_TIMEOUT` (120 s)
for all of a request's images. Responses to requests with images carry `X-PII-Guard-Images`,
`X-PII-Guard-Image-Regions-Masked` and `X-PII-Guard-Image-OCR: on|off`.

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
    def mask(self, text: str, spans: list[Span], *, language: str = "hu") -> str: ...

    # Same, plus (start, end, placeholder) of every replacement in input offsets.
    def mask_with_report(self, text, spans, *, language="hu") -> MaskResult: ...

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
  placeholders. The key is the value's **lemma**: every inflected form of one value shares one
  placeholder, with the suffix outside it. Hungarian: `Próba Zsuzsannának` →
  `[[PERSON_x]]nak`, `Próba Zsuzsannát` → `[[PERSON_x]]t`, `Kováccsal` → `[[PERSON_y]]al`,
  `Teszt Elekkel` → `[[PERSON_z]]kel`, `ABC-123-nak` → `[[VEHICLE_PLATE_w]]-nak`. A detector
  span that includes a suffix is narrowed to the stem; an ambiguous split (`Zoltán` could be
  `Zolta` + `n`) is applied only when the lemma is confirmed (it occurs on its own, another span
  or an earlier request has it, or two different forms agree). Otherwise the whole word is masked
  and the candidate lemmas' forms get the same placeholder (recall first). See
  `vault/inflection.py` (`splits`, `variant_stems`, `restore`).
- `unmask` re-inflects: a known placeholder followed by a suffix restores the stem as written in
  the input for that suffix, or, for a suffix the model added itself, the language's inflected
  stem (`[[PERSON_x]]nak` → `Próba Zsuzsannának`, `[[PERSON_y]]val` → `Kováccsal`).
- `mask` raises `MaskingError` on overlapping or out-of-range spans rather than guessing.
- `StreamUnmasker.feed("[[PERS") + feed("ON_7f3a]] ok") + flush()` equals
  `session.unmask("[[PERSON_7f3a]] ok")`: concatenated output is identical to unmasking the
  whole text at once. A complete placeholder followed only by word characters (a suffix that
  may still grow, at most 12 characters) is held back until the next non-word character.
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

`run_documents` accepts any object with `analyze(text, language) -> list[Span]`.
`DetectorAnalyzer` resolves with `DetectionPipeline`, the same resolver as the API and the
gateway. Types whose policy is `keep` are not masked (`DEFAULT_POLICY`, derived from
`pii_guard.policy.DEFAULT_POLICIES`: everything except `ORGANIZATION` and `COMPANY_ID_HU`);
`block` types are masked like `mask` ones so their values never count as leaked. Each document
runs in a fresh vault session under the public `EVAL_TENANT_KEY`.

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
