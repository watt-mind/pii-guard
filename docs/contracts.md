# Contracts

> Status: accepted for the hackathon build. These are the interfaces the detectors, vault,
> API, evaluation harness and UI agree on. Sections marked **implemented** describe code that
> exists; a section for a component that is not built yet is marked **planned** and is the
> contract its owner must implement (none is at the moment). Change a contract only together
> with every consumer, and update this file in the same pull request.

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

## Rule detector (implemented)

Module: `pii_guard.detect.rules` (registry name `rules`). Deterministic and stateless: every
rule is a regular expression plus validation (checksum, known prefixes and area codes, label
or address context), so a look-alike such as a wrong check digit, digits inside a longer digit
run or a date is not reported. The identifier formats per language are listed in
[entities.md](entities.md#per-language); this section is the interface.

```python
class RuleDetector:                       # name = "rules"; implements Detector
    def detect(self, text: str, language: str = "hu") -> list[Span]   # DetectionError, never the text
    def rules_for(self, language: str) -> tuple[Rule, ...]            # every rule that runs

Rule = Callable[[str], Iterator[_Hit]]    # _Hit(start, end, entity_type, score)
@dataclass(frozen=True, slots=True)
class RulePack:
    language: str                         # ISO 639-1 code
    everywhere: tuple[Rule, ...] = ()     # run for every language
    rules: tuple[Rule, ...] = ()          # run only when the text's language matches

register_rule_pack(pack: RulePack) -> None   # replaces the rules of pack.language for new detectors
rule_packs() -> dict[str, RulePack]          # the language packs' rules, with overrides applied
```

- **Scopes.** The language-independent rules (`pii_guard.detect.rules.common`) run for every
  text. A language pack ([ADR 0008](decisions/0008-language-packs.md), `languages/<lang>/rules.py`)
  contributes `everywhere` rules (identifiers with a checksum or a distinctive validated format,
  run whatever the text's language: a Hungarian tax ID in an English e-mail is still personal
  data) and `rules` (formats that are only unambiguous in that language, such as postcodes,
  plates and national phone formats, run only when `language` matches, `en-GB` counting as
  `en`). A language without a pack gets the language-independent rules and every pack's
  `everywhere` rules.
- Hits that lie entirely inside a longer hit (digits inside an IBAN) are dropped; partial
  overlaps are left to the resolver. Spans carry code-point offsets and `detector == "rules"`.
- Rules that need a label (`személyi igazolvány száma:`, `hrsz.`) span only the value; the
  label stays outside the span.

Entity coverage and scores. Where a cell gives several scores, the higher one applies when
there is more evidence: a keyword such as `adóazonosító` or `TAJ` right before the value, a
label, a consistent postcode and settlement, or valid check digits:

| Scope | Entity types | Scores |
|---|---|---|
| all | `BANK_ACCOUNT` (IBAN, mod 97; payment card, issuer prefix + Luhn), `EMAIL`, `PHONE` (international `+<country>`) | IBAN 0.99, card 0.95 grouped / 0.9 compact, email 0.99, phone 0.85 |
| `hu`, everywhere | `NATIONAL_ID_HU_TAX`, `NATIONAL_ID_HU_TAJ`, `BANK_ACCOUNT` (giro), `PHONE` (`+36`, `06`), `COMPANY_ID_HU` (registration number, tax number), `ID_DOCUMENT` (personal ID, labelled ID card / passport / licence / permit numbers, MRZ), `PARCEL_NUMBER_HU` | tax ID 0.99 / 0.95, TAJ 0.95 / 0.8, giro 0.95, phone 0.9, company registration number 0.95 with the `Cg.` prefix, else 0.85, tax number 0.95, personal ID 0.99 / 0.85, ID document 0.95 / 0.85, MRZ 0.99 (check digits agree) / 0.8, parcel 0.9 or 0.95 near a settlement or `belterület` |
| `hu`, language | `ADDRESS` (postcode, address with settlement and street), `VEHICLE_PLATE`, bare `ID_DOCUMENT` card number, `PERSON` inside a company name with a legal form | postcode 0.75-0.9, address 0.75 / 0.85 / 0.97 (postcode and settlement agree), plate 0.85 / 0.8, bare ID card 0.7, company-name person 0.7-0.9 (`languages/hu/companies.py`) |
| `en`, everywhere | `ID_DOCUMENT` (US SSN, UK NINO) | SSN 0.95 / 0.85, NINO 0.95 / 0.9 |
| `en`, language | `PHONE` (UK, US/NANP), `ADDRESS` (UK postcode, US ZIP), `VEHICLE_PLATE` (UK), `ID_DOCUMENT` (labelled passport / licence, SSN after a label) | phone 0.8-0.85, postcode 0.75-0.85, ZIP 0.8 / 0.85, plate 0.8, labelled ID 0.85, SSN after a label 0.9 |
| `de`, everywhere | `ID_DOCUMENT` (Sozialversicherungsnummer, labelled Steuer-ID) | 0.9 / 0.97 |
| `de`, language | `ID_DOCUMENT` (Steuer-ID without a label), `PHONE`, `ADDRESS` (street + house number, postcode line) | Steuer-ID 0.85, phone 0.8, address 0.75 / 0.85, postcode line 0.7 |

Names, organisations, prose addresses and dates of birth are not rule territory; they come
from the NER and LLM detectors. Scores are heuristics for the resolver, not probabilities;
the code is the source of truth for the exact values.

### Checksum helpers

Module: `pii_guard.detect.checksums`. Each identifier has a public `*_check_digit` function
that computes the check digit(s) from the payload and an `is_valid_*` predicate on the
normalized value (digits only; IBANs upper-case without spaces). The check-digit functions are
public so synthetic data generators build valid fictional values; nothing here knows real people.

| Identifier | Compute | Validate |
|---|---|---|
| Hungarian personal tax ID (adóazonosító jel) | `hu_tax_id_check_digit(first9) -> int \| None` | `is_valid_hu_tax_id(value)` |
| Hungarian personal identification number (személyi azonosító) | `hu_personal_id_check_digit(first10) -> int \| None` | `is_valid_hu_personal_id(value)` |
| TAJ number | `taj_check_digit(first8) -> int` | `is_valid_taj(value)` |
| Giro account number | `giro_check_digit(payload) -> int` | `is_valid_giro(value)` |
| Hungarian company tax number | `hu_tax_number_check_digit(first7) -> int` | `is_valid_hu_tax_number(base, vat_code, area)` |
| IBAN | `iban_check_digits(country, bban) -> str` | `is_valid_iban(value)`; `IBAN_LENGTHS` maps country to length |
| Machine-readable zone (ICAO 9303) | `mrz_check_digit(field) -> int` | `is_valid_mrz_td3(line1, line2)` (passport, 2 x 44), `is_valid_mrz_td1(line1, line2, line3)` (ID card, 3 x 30) |

Payment cards (`is_valid_card_number`, `luhn_check_digit`) live in
`pii_guard.detect.rules.common`; the English SSN and NINO validators in
`languages/en/rules.py`.

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
| `PII_GUARD_VAULT_CASE_SENSITIVE_PLACEHOLDERS` | `vault_case_sensitive_placeholders` | `bool` | `false` |
| `PII_GUARD_LLM_DETECTOR_URL` | `llm_detector_url` | `str \| None` | unset |
| `PII_GUARD_LLM_DETECTOR_API_KEY` | `llm_detector_api_key` | `SecretStr \| None` | unset |
| `PII_GUARD_LLM_DETECTOR_MODEL` | `llm_detector_model` | `str \| None` | unset (detector default `meta-models/muse-spark-open-1026`) |
| `PII_GUARD_LLM_DETECTOR_REASONING_EFFORT` | `llm_detector_reasoning_effort` | `str \| None` | unset (not sent) |
| `PII_GUARD_LLM_DETECTOR_MAX_TOKENS` | `llm_detector_max_tokens` | `int \| None` (>= 256) | unset (detector default `4096`) |
| `PII_GUARD_LLM_DETECTOR_TIMEOUT` | `llm_detector_timeout` | `float \| None` (> 0, seconds) | unset (detector default `60`) |
| `PII_GUARD_SAM_URL` | `sam_url` | `str \| None` | unset |
| `META_API_KEY` | `meta_api_key` | `SecretStr \| None` | unset |

`PII_GUARD_DETECTORS` picks the REST API's detectors (`rules,llm` for the demo; the gateway
has its own per-mode set). `PII_GUARD_POLICY_OVERRIDES` is parsed and validated when the
settings load: an unknown type or policy stops startup. `LlmDetector` resolves its model,
reasoning effort, max tokens and timeout as the constructor argument, then the setting
(environment or `.env`), then its built-in default, so the registry and `pii-guard eval`
honour them too (Muse Spark Open on Baseten needs `REASONING_EFFORT=low`; contract-length
documents need a larger `MAX_TOKENS` and `TIMEOUT`). Folding the text size limit and the
gateway settings into `Settings` is LAB-1095.

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

## REST API (implemented)

JSON over HTTP, UTF-8. Offsets are code-point indices into the request `text`. `language`
defaults to `Settings.default_language` (`"hu"`).

### Errors

Every non-2xx response, including validation errors and unknown routes, has this body:

```json
{"error": {"code": "invalid_request", "message": "invalid request body: body.text"}}
```

| Status | `code` | When |
|---|---|---|
| 404 | `not_found` | Unknown route, or an unknown or expired `session_id` on any route that takes one (`/v1/analyze`, `/v1/mask`, `/v1/mask/image`, `/v1/unmask`, the session and known-values routes, the gateway) |
| 422 | `invalid_request` | Body fails validation. The message lists field locations only, never values. |
| 422 | `invalid_known_value` | A pre-loaded known value is too short (< 3 non-space characters), too long, or has an unknown or visual type. The message names its index and type, never the value. |
| 422 | `too_many_known_values` | The session would hold more than `PII_GUARD_KNOWN_VALUES_MAX` known values; nothing is added. |
| 422 | `blocked_entity` | `/v1/mask` (or the gateway) found an entity type whose policy is `block`. The message lists types and counts only; nothing is masked, stored or forwarded. |
| 422 | `placeholder_in_input` | The text to mask contains a placeholder this session already issued; restoring it would put a value into text never masked. The message holds a count only. Other placeholder-shaped tokens in the input are left as they are and never issued as a placeholder. |
| 500 | `vault_not_configured` | `PII_GUARD_TENANT_KEY` is unset, not hex or shorter than 16 bytes: `/v1/mask`, `/v1/unmask`, the known-values routes and the gateway fail closed. The message never echoes the key. |
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

Optional `session_id` (1-128 characters, as on `/v1/mask`) previews the session's pre-loaded
known values: the spans the `known` detector adds are merged in exactly as `/v1/mask` does and
come back with `"detector": "known"`, covering the stem (an inflectional suffix stays outside).

```json
// request
{"text": "Üdv, Gyakorló Tihamérnak!", "session_id": "s_..."}
// response 200
{"spans": [{"start": 5, "end": 21, "entity_type": "PERSON", "score": 1.0, "detector": "known", "policy": "mask"}]}
```

- A known value reports `policy: "mask"` even when its type's policy is `keep` (`/v1/mask`
  masks it); a `block` type reports `block` (analyze still does not refuse).
- Unknown or expired `session_id`: `404 not_found`, no text in the body. A session is never
  created and nothing is stored (the session's counters and entities are unchanged); its
  sliding TTL is extended as for any use.
- Without `session_id` the vault is not touched, so no tenant key is needed.
- The access log gets `known=<count>` and `session=<bool>`, never values or the session id.

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

Options (JSON fields, or query parameters with a raw upload):

- `render`: `labels` (default, `PII_GUARD_IMAGE_RENDER`) prints each covered region's vault
  placeholder in its box and returns a masked transcript and a document summary; `opaque`
  fills boxes solid black and returns neither. Without a tenant key the default falls back
  to `opaque`; an explicit `labels` is then `500 vault_not_configured`.
- `session_id`: the vault session to mask in (`labels` only), shared with `/v1/mask` and the
  gateway, so the same person gets the same placeholder in text and in images. Omitted: a new
  session is created and returned. Unknown or expired: `404 not_found`.
- `expiry`: `reduce` (default; the summary says `expired: true|false` only) or `keep` (the
  summary also carries the ISO expiry date).

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

With `render: "labels"` (the default) the response also carries:

```json
{
  "render": "labels",
  "session_id": "s_3f2a…",
  "regions": [
    {"entity_type": "PERSON", "box": [310, 92, 402, 112], "source": "ocr", "detector": "captions", "score": 0.8, "policy": "mask",
     "placeholder": "[[PERSON_a1b2c3]]", "label": "[[PERSON_a1b2c3]]", "match": "fuzzy", "match_confidence": 0.93,
     "cover_box": [308, 90, 452, 114]},
    {"entity_type": "FACE", "box": [72, 116, 188, 262], "source": "sam", "detector": "sam", "score": null, "policy": "mask",
     "placeholder": "[[PERSON_a1b2c3]]", "label": "PHOTO · [[PERSON_a1b2c3]]", "match": "fuzzy", "match_confidence": 0.93,
     "cover_box": [70, 114, 190, 264]}
  ],
  "transcript": "AZONOSÍTÓ KÁRTYA / IDENTITY CARD\nCsaládi név / Surname\n[[PERSON_a1b2c3]]\n…",
  "summary": {
    "document_type": "id_card", "holder": "[[PERSON_a1b2c3]]", "holder_match": "fuzzy",
    "holder_confidence": 0.93, "document_number": "[[ID_DOCUMENT_d4e5f6]]",
    "issuing_country": "UTO", "expiry": null, "expired": false, "mrz_present": true,
    "mrz_valid": true, "fields_found": {"date_of_birth": "[[DATE_OF_BIRTH_0a1b2c]]", "…": "…"},
    "fields_uncertain": []
  },
  "matches": {"exact": 1, "fuzzy": 2, "new": 3, "uncertain": 0}
}
```

- `placeholder` is the session placeholder of the covered value; `label` is what is printed in
  the box (`PHOTO · [[PERSON_x]]` on a portrait of the card's holder, `SIGNATURE`, `STAMP`).
  `match` says how the value was tied to the session: `exact` or `fuzzy` (it reuses a value
  the conversation already named, `match_confidence` in `[0, 1]`), `new` (first seen here,
  registered in the session) or `uncertain` (close to a session value but not accepted: a
  **new** placeholder, never a guess; the summary lists it in `fields_uncertain`).
- Fuzzy matching (`pii_guard.visual.fuzzy`) is case-, accent- and token-order-insensitive
  (`FIKTIV<<MARIA` is `Fiktív Mária`) and treats OCR confusions between a letter and a digit
  (`0`/`o`, `1`/`l`/`i`, `5`/`s`) as cheap, but one real letter of difference keeps two names
  apart (`Mustermonn`), including a letter OCR may read for another: `ELIA` is not `Ella`,
  `Delia` is not `Della`. The only letter pairs treated as OCR noise are the ones of the same
  shape as printed, compared with their case: a capital `I` and a small `l` (`llse` is
  `Ilse`), a small `e`/`c` and `u`/`v`. A card name with tokens the session's name doesn't
  have (`KOVÁCS ANNA ZSÓFIA` against `Kovács Anna`), or a single token of a longer name
  (`ANNA`), is at most `uncertain`; a card that leaves out a middle name (`PÉLDA GÁBOR`
  against `Példa Gábor István`) still matches. Identifiers match across separators and
  letter↔digit confusions only (`XJXK89KU4` is not `XJXK89KV4`, `HU-ABE-123` is not
  `HU-ABC-123`).
- Session values printed where no detector found them (a visitor badge's name) are also
  covered and labelled (`detector: "vault"`), for accepted matches only.
- `cover_box` is the area actually painted: the box grown by 2 px and, when the label would
  not fit legibly, extended to the right into free space (never over visible words or another
  box). `box` stays the detected area in both render modes, so coverage is identical.
- `transcript` is the OCR text with every covered value replaced by its placeholder (or
  `[PHOTO]`, `[SIGNATURE]`); values the session knows are also replaced wherever they appear.
  Before the response is returned, the transcript and summary are checked against every
  covered value; one found there fails closed with `500 masking_failed`. Text the detectors
  did not find stays in the transcript exactly as it stays visible in the image.

- `box` is `[x1, y1, x2, y2]`, inclusive pixel corners in the image after EXIF orientation.
  `source` is `sam` (SAM 3.1 segmentation) or `ocr` (OCR word boxes of a span a text detector
  found); `detector` is `sam`, the text detector's registry name, or `captions` for a value
  printed next to a known field caption (`Név`, `Date of birth`; score 0.8). SAM gives no
  scores.
- `FACE` boxes are grown before masking (40% up, 10% on each side, 5% down, clamped to the
  image) because SAM's face box leaves hair and ears visible; the reported box is the grown
  one, i.e. the area covered.
- `analysis.ocr.models` maps each model-backed text detector to its model id, so clients can
  label regions by what actually ran.
- Regions never carry the covered text or pixels. Overlapping regions of the same type and
  source are merged into their union (SAM's `signature` and `squiggly line` prompts).
- Policies apply per region: `mask` regions are covered (plus 2 px; solid black with `opaque`,
  a neutral labelled box with `labels`), `keep` regions
  (`STAMP` by default) are reported and left visible, any `block` region is
  `422 blocked_entity` with no image.
- Segmenters (`pii_guard.visual.segment.Segmenter`): anything with
  `segment(image: bytes, entity_types=None) -> list[Region]` that raises `DetectionError` on
  any failure, including a requested type it cannot find. `SamClient` (SAM 3.1, Meta API) is
  the one the API and gateway use. `LocalSegmenter` (YuNet on the CPU, `uv sync --extra
  local-vision`, model via `python -m pii_guard.visual.segment fetch` into
  `PII_GUARD_MODEL_DIR`, default `~/.cache/pii-guard/models`) finds `FACE` and `ID_PHOTO` only
  (`source: "yunet"`, with scores) and raises for `SIGNATURE`; a missing OpenCV, a missing model
  or one whose SHA-256 differs from the pinned value raises too. It is not wired into the API
  (LAB-1229: no local signature detector is close enough to SAM; see
  [models.md](models.md#local-segmentation)).
- SAM segments every visual type it has a prompt for (one Meta API request per prompt:
  `face`, `signature`, `squiggly line`, `photo of a person`, `stamp`). It needs `META_API_KEY` (or
  `PII_GUARD_SAM_API_KEY`); without one every call is `503 detection_failed`.
- Text in the image: when Tesseract is installed (`uv sync --extra ocr` and the `tesseract`
  binary with `hun`/`eng` data; the Docker image ships both), OCR text goes through the API's
  detectors (`PII_GUARD_DETECTORS`, so names need `llm`). Without it the image is refused with
  `503 ocr_unavailable` before SAM runs (fail closed), here and in the gateway. Only with
  `PII_GUARD_IMAGE_REQUIRE_OCR=false` does SAM run alone, and `analysis.ocr` is
  `{"ran": false, "engine": null, "detectors": [], "models": {}, "reason": "tesseract_unavailable"}`:
  text in the image was **not** checked (the gateway says `X-PII-Guard-Image-OCR: off`).
- Fail closed: any SAM, OCR or detector error is `503 detection_failed`, a masking error
  `500 masking_failed`; an undecodable image or bad base64 is `422 invalid_image`. Error bodies
  never contain the image.

The gateway (`POST /v1/chat/completions`) runs the same pipeline on `image_url` content parts
whose URL is an inline `data:image/png|jpeg;base64,…` URL, with the request mode's detectors
for OCR text, and forwards a masked PNG data URL in its place (`detail` is kept; any other
field is rejected, see [Gateway request fields](#gateway-request-fields-implemented)). Remote `http(s)` and other URLs are `400 unsupported_content`: the guard
never fetches URLs. Limits: `PII_GUARD_GATEWAY_MAX_IMAGES` (4) images of
`PII_GUARD_GATEWAY_MAX_IMAGE_BYTES` (10 MiB) each, `PII_GUARD_GATEWAY_IMAGE_TIMEOUT` (120 s)
for all of a request's images. With `PII_GUARD_IMAGE_RENDER=labels` (the default) images are
masked in the request's vault session after its text, so a name in the message and on a card
share one placeholder, and a text part follows each image part: `[pii-guard: image N was
masked; …]`, its document summary (JSON) and its masked transcript. The model's answer is
unmasked as usual. Responses to requests with images carry `X-PII-Guard-Images`,
`X-PII-Guard-Image-Regions-Masked` and `X-PII-Guard-Image-OCR: on|off`.

## Gateway request fields (implemented)

`POST /v1/chat/completions` walks the whole body against an allow-list
(`pii_guard.gateway.request`) and fails closed (ADR 0006): every key below is masked, checked
or passed through as stated, and **any other key is rejected** with
`400 unsupported_content`, at the top level, in a message, a content part, a tool call or a
nested object listed here. A malformed value (a string where a number belongs, a non-object
message, ...) is `400 invalid_request`. Nothing is forwarded or vault-stored for a rejected
request, and error messages name the location (a field name, or `#position` when the key
itself could be a value), never the value.

Treatments:

- **mask**: free text. Detected values are replaced by placeholders and restored in the
  answer.
- **mask JSON**: every string in the value, object keys included, is masked as its own text.
- **check**: an identifier or enum-like setting that can't carry a placeholder. Detected
  personal data rejects the request (`400 unsupported_content`); otherwise it is forwarded
  unchanged. The API's own words (`auto`, `function`, `json_schema`, ...) are not checked.
- **pass**: numbers, booleans and null only (strings are `400 invalid_request`), or an opaque
  provider-issued blob forwarded untouched.

| Where | Key | Treatment |
| --- | --- | --- |
| body | `model` | pass (non-empty string, required) |
| body | `messages` | per message, below (non-empty array, required) |
| body | `temperature`, `top_p`, `n`, `max_tokens`, `max_completion_tokens`, `presence_penalty`, `frequency_penalty`, `seed`, `logprobs`, `top_logprobs`, `stream`, `parallel_tool_calls`, `store`, and the extension knobs `top_k`, `min_p`, `repetition_penalty` | pass |
| body | `reasoning_effort`, `service_tier`, `verbosity`, `modalities`, `stream_options`, `audio`, `tool_choice`, `function_call` | check (every string and key) |
| body | `user`, `safety_identifier`, `prompt_cache_key` | mask |
| body | `stop` (string or array of strings) | mask |
| body | `prediction` | `type` check; `content` mask (string or text parts) |
| body | `web_search_options` | `search_context_size` check; `user_location` mask JSON |
| body | `logit_bias` | keys must be token ids, values numbers |
| body | `metadata` | keys check; values mask JSON |
| body | `tools`, `functions` | definitions: `name` and other keys check; `parameters`/`schema` walked as JSON Schema (free text masked, `properties` keys and `required` entries checked, `type`/`$ref`/`format`/... passed); every other string or array mask JSON (e.g. an MCP tool's `server_description`); entries must be objects |
| body | `response_format` | `type` check; `json_schema` as a definition |
| message | `role` | one of `system`, `developer`, `user`, `assistant`, `tool`, `function` |
| message | `content` | string mask; array of content parts, below |
| message | `refusal`, `reasoning_content`, `reasoning` | mask (a non-string value: mask JSON) |
| message | `reasoning_details`, `thinking_blocks` | per block: `text`, `summary`, `thinking` mask JSON; `type`, `format`, `id`, `index` check; `data`, `signature`, `encrypted_content` pass (opaque, provider-signed) |
| message | `audio` | `transcript` mask; `id` check; `expires_at` pass |
| message | `annotations` | mask JSON |
| message | `name` | detected personal data removes the field; for `role: function` it is checked instead (it must match the call) |
| message | `tool_call_id`, `cache_control`, `prefix` | check |
| message | `tool_calls[]` | `id`, `type` check; `index` pass; `function.name` check; `function.arguments` as below; `custom.name` check, `custom.input` mask JSON |
| message | `function_call` | `name` check; `arguments` as below |
| tool call | `arguments` | a JSON string: parsed, mask JSON, re-serialised (not JSON: mask); an object or array (LiteLLM/Ollama style): mask JSON in place; anything else `400 invalid_request` |
| content part | `{"type": "text"}` | `text` mask; `cache_control` check |
| content part | `{"type": "refusal"}` | `refusal` mask |
| content part | `{"type": "image_url"}` | inline PNG/JPEG data URL masked as an image (above); `image_url.detail` and `cache_control` check |
| content part | any other type (`input_audio`, `file`, ...) | `400 unsupported_content` |

## Vault (implemented)

Package: `pii_guard.vault`. Implements [ADR 0007](decisions/0007-keyed-pseudonyms.md). The
mapping lives in memory only and is keyed by the tenant key.

```python
class Vault:
    def __init__(
        self,
        tenant_key: bytes,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        id_length: int = DEFAULT_ID_LENGTH,
        clock=time.monotonic,
        case_sensitive_placeholders: bool = False,
    ) -> None: ...

    # PII_GUARD_TENANT_KEY (and PII_GUARD_VAULT_CASE_SENSITIVE_PLACEHOLDERS) from Settings.
    @classmethod
    def from_settings(cls, settings: Settings, **kwargs) -> Vault: ...

    # None -> a new session with a fresh random id ("s_" + 32 hex); an existing id -> that session.
    def session(self, session_id: str | None = None) -> VaultSession: ...

    def drop(self, session_id: str) -> None: ...  # close and forget now; no error if gone
    def purge_expired(self) -> int: ...  # drop every expired session, return how many
    def __len__(self) -> int: ...  # live sessions


class VaultSession:
    session_id: str
    expired: bool  # property
    known_values: KnownValues  # property, see the known-values routes

    # Replace each span (and every other occurrence of a confirmed value) with its placeholder.
    def mask(
        self, text: str, spans: Sequence[Span], *, language: str = "hu", remask: bool = False
    ) -> str: ...

    # Same, plus (start, end, placeholder) of every replacement in input offsets.
    def mask_with_report(self, text, spans, *, language="hu", remask=False) -> MaskResult: ...

    # Replace known placeholders with their original values.
    def unmask(self, text: str) -> str: ...

    # Same, plus the placeholder-shaped tokens that are not in the mapping.
    def unmask_with_report(self, text: str) -> UnmaskResult: ...

    # (placeholder, entity_type, count) for every placeholder this session issued.
    def entities(self) -> list[tuple[str, EntityType, int]]: ...

    def close(self) -> None: ...  # forget the mapping now


@dataclass(frozen=True, slots=True)
class MaskResult:
    text: str
    replacements: tuple[tuple[int, int, str], ...]


@dataclass(frozen=True, slots=True)
class UnmaskResult:
    text: str
    unresolved: tuple[str, ...]  # once each, in order of appearance


class StreamUnmasker:
    def __init__(self, session: VaultSession) -> None: ...

    # Text that is safe to emit now; holds back a trailing partial "[[...".
    def feed(self, chunk: str) -> str: ...

    # Whatever is still buffered, at the end of the stream. feed() after flush() is an error.
    def flush(self) -> str: ...

    unresolved: tuple[str, ...]  # property, unknown placeholders seen so far
```

`MaskResult` and `UnmaskResult` hold original values in `text`, so their `repr()` hides it.
`DEFAULT_TTL_SECONDS` is 3600; `MIN_TENANT_KEY_BYTES` is 16 (`Vault` raises `ValueError`
for a shorter key, without echoing it). `Vault.session` and the per-session methods (`mask`,
`unmask`, `entities`, `known_values`) are thread-safe; each call holds the session's lock, so
two calls never see each other half-done. `StreamUnmasker` is **not**: it buffers one
response, so use one per stream from one thread at a time (it may share its session with
other streams). Two calls are not one transaction either: read what a `mask` call replaced
from `mask_with_report().replacements`, not from `entities()` before and after it
(`/v1/mask` reports its `entities` that way, so a concurrent request on the same session
doesn't inflate them).

### Errors

| Exception | `code` | HTTP | When |
|---|---|---|---|
| `SessionNotFoundError` (`PiiGuardError`) | `not_found` | 404 | The session id is unknown, expired or closed. Raised by `Vault.session` and by every `VaultSession` method (and so by `StreamUnmasker`) once the session is gone; the gateway fails the request instead of forwarding unrestored text. |
| `MaskingError` | `masking_failed` | 500 | A span is invalid, out of range, overlapping, blank, a visual type or does not match the text; no id could be made unique. Nothing is recorded. |
| `MaskingError` | `vault_not_configured` | 500 | `Vault.from_settings` without `PII_GUARD_TENANT_KEY`. |
| `PlaceholderInInputError` (`MaskingError`) | `placeholder_in_input` | 422 | The text to mask holds a placeholder this session already issued. |

Messages and `repr()`s carry types, counts and placeholder ids, never an original value.

### Lifetime

- A session lives for `ttl_seconds` and the TTL is **sliding**: every use (mask, unmask,
  entities, `known_values`, `Vault.session(id)`) extends it. An expired session is closed and
  forgotten on the next access, and `Vault.purge_expired()` (also run by `session()` and
  `len(vault)`) drops all expired ones.
- `Vault.drop(id)` and `VaultSession.close()` forget the mapping and the known values at once;
  later calls raise `SessionNotFoundError`. The mapping never leaves the process, is never
  logged and has no persistence.

### Placeholders

- **Format:** `[[<TYPE>_<id>]]`, where `<TYPE>` is the `EntityType` value and `<id>` is
  lowercase hex. The id is the first `id_length` characters of an HMAC-SHA256 under the tenant
  key over a domain tag, the entity type, the **session id** and the normalized value (NFKC,
  case-folded, whitespace collapsed; `normalize_value`). Regex (`PLACEHOLDER_RE`):
  `\[\[([A-Z][A-Z0-9_]*)_([0-9a-f]{4,})\]\]`. Example: `[[PERSON_7f3a9c]]`.
- **Length:** `DEFAULT_ID_LENGTH` is 6 hex characters, `MIN_ID_LENGTH` 4, `MAX_ID_LENGTH` 64 (a
  full digest). A placeholder that collides with another value's, or with a placeholder-shaped
  token from the input, extends its id by two characters at a time up to the maximum.
- Same normalized value of the same type → same placeholder within a session. Different
  tenants, and different sessions, never share placeholders: without the key an id can't be
  reversed, enumerated or linked.
- **Inflection.** The key is the value's **lemma**: every inflected form of one value shares one
  placeholder, with the suffix outside it. Hungarian: `Próba Zsuzsannának` →
  `[[PERSON_x]]nak`, `Próba Zsuzsannát` → `[[PERSON_x]]t`, `Kováccsal` → `[[PERSON_y]]al`,
  `Teszt Elekkel` → `[[PERSON_z]]kel`, `ABC-123-nak` → `[[VEHICLE_PLATE_w]]-nak`. A detector
  span that includes a suffix is narrowed to the stem; an ambiguous split (`Zoltán` could be
  `Zolta` + `n`) is applied only when the lemma is confirmed (it occurs on its own, another span
  or an earlier request has it, or two different forms agree). Otherwise the whole word is masked
  and the candidate lemmas' forms get the same placeholder (recall first).
- `unmask` re-inflects: a known placeholder followed by a suffix restores the stem as written in
  the input for that suffix, or, for a suffix the model added itself, the language's inflected
  stem (`[[PERSON_x]]nak` → `Próba Zsuzsannának`, `[[PERSON_y]]val` → `Kováccsal`).
- **Occurrences** are searched in a folded view of the text: the detection normaliser's
  (invisible characters dropped, accents composed, Unicode spaces and dashes folded) plus a
  full case fold, with an offset map back. So `TESZT ELEK`, a decomposed `Kova\u0301cs`
  (macOS copy-paste), `WEISS` for `Weiß` and `Teszt\u200bElek` are masked along with the
  span, and known values are found the same way. Hungarian `-val`/`-vel` after a doubled
  consonant is matched without a third letter (`Kiss` → `Kissel`, `Varga Bernadett` →
  `Varga Bernadettel`, `Szabó Mariann` → `Szabó Mariannal`).
- **Aliases:** a form found only through an unconfirmed lemma of a span (`Minta Kende` after a
  `Minta Kendét` span) gets that lemma's own placeholder, so it is restored as written, not as
  the span's surface.
- **Layout:** an occurrence written with a line break or tab inside it (`Teszt\nElek`), or
  with decomposed accents, after the value was confirmed in another layout gets a placeholder
  of its own (its form is mixed into the HMAC, like a casing class), so `unmask` gives it back
  as written. Runs of plain spaces count as one space and share the placeholder.
- **Casing:** occurrences match case-insensitively, so `TESZT ELEK` and `teszt elek` are
  masked along with a `Teszt Elek` span. By default they share its placeholder and `unmask`
  restores the value as first written (`TESZT ELEK és Teszt Elek.` → `Teszt Elek és Teszt
  Elek.`): a known limitation that keeps one id per value for the upstream model, and lets an
  ALL-CAPS name from an ID card share the placeholder of the same name written in prose.
  `PII_GUARD_VAULT_CASE_SENSITIVE_PLACEHOLDERS=true` (`Vault(case_sensitive_placeholders=True)`)
  gives an occurrence in another casing class (ALL CAPS, lower case, mixed) its own
  placeholder, with the class mixed into the HMAC, so the round trip is exact; the model then
  sees one id per casing. Within a class the first-written form is restored (`Teszt ELEK`
  after `Teszt Elek` comes back as `Teszt Elek`). In both modes a suffixed occurrence is
  restored with the stem as written before that exact suffix, so `Teszt Eleknek …, TESZT
  ELEKNEK` round-trips exactly (the suffix's casing tells the two apart).
- **Placeholder-shaped text in the input.** A token equal to a placeholder this session already
  issued makes `mask` raise `PlaceholderInInputError` (`placeholder_in_input`, 422), since
  `unmask` would restore a value into text that was never masked. Any other `[[TYPE_id]]` token
  is reserved: left as it is and never issued later. `remask=True` is for text this session's
  own `mask` produced (a second pass that catches values confirmed later).
- `mask` raises `MaskingError` on overlapping or out-of-range spans rather than guessing, and
  records nothing when it raises.

### Inflection hook

Module: `pii_guard.vault.inflection`; the interface and `Split` live in
`pii_guard.languages.inflection` (the module re-exports them), and each language pack
([ADR 0008](decisions/0008-language-packs.md)) supplies its matcher: Hungarian
(`HungarianSuffixMatcher`, `languages/hu/inflection.py`), English (`EnglishPossessiveMatcher`:
`Smith's` → `[[PERSON_7f3a]]'s`), German (`GermanGenitiveMatcher`). The vault masks the value
itself and keeps the suffix, so re-identification is exact.

```python
@runtime_checkable
class InflectionMatcher(Protocol):
    # A regex fragment (no capturing groups) for an allowed suffix; "" means none. Required.
    def suffix_pattern(self, value: str, entity_type: EntityType) -> str: ...
    # Optional, for languages whose stems change before a suffix:
    def variant_stems(self, value: str, entity_type: EntityType) -> list[tuple[str, str]]: ...
    def splits(self, surface: str, entity_type: EntityType) -> list[Split]: ...
    def restore(self, lemma: str, suffix: str, entity_type: EntityType) -> str: ...

@dataclass(frozen=True, slots=True)
class Split:                  # one reading of a surface form as stem + suffix of a lemma
    lemma: str                # dictionary form as written: "Próba Zsuzsanna"
    stem: str                 # "Próba Zsuzsanná"; stem + suffix is the surface form
    suffix: str               # "nak"
    strong: bool = False      # unambiguous enough to apply alone; a weak one needs a confirmed lemma

class ExactMatcher:           # no inflection: the value must stand alone between word boundaries

register_inflection(language: str, matcher: InflectionMatcher) -> None   # beats the pack's matcher
inflection_for(language: str) -> InflectionMatcher   # registered, then the pack's, then ExactMatcher; "en-GB" -> "en"
variant_stems(matcher, value, entity_type) -> list[tuple[str, str]]   # fall back to []
splits(matcher, surface, entity_type) -> list[Split]                  # fall back to []
restore(matcher, lemma, suffix, entity_type) -> str                   # fall back to lemma + suffix
following_suffix(text: str, pos: int) -> str   # the word-character run (after one hyphen) at pos
MAX_SUFFIX_LENGTH = 12   # a longer run is never a suffix; it bounds what the stream holds back
```

- `variant_stems` returns the changed stems of a lemma with the regex of the suffixes that must
  follow them (occurrence expansion in the vault and `LlmDetector.align`).
- `splits` reads a detected surface form as `lemma + suffix` (`Próba Zsuzsannának` → `Próba
  Zsuzsanna` + `nak`), so the placeholder covers the stem. `restore` re-inflects on unmask.
- A matcher that only has `suffix_pattern` keeps exact-stem behaviour; call the module
  functions, which provide the fallbacks. A hook registered with `register_inflection` applies
  to new masking calls of that primary language.

### Streaming

`StreamUnmasker.feed("[[PERS") + feed("ON_7f3a]] ok") + flush()` equals
`session.unmask("[[PERSON_7f3a]] ok")`: concatenated output is identical to unmasking the
whole text at once. It holds back a trailing partial `[[...`, and a complete placeholder
followed only by word characters (a suffix that may still grow, at most `MAX_SUFFIX_LENGTH`
characters) until the next non-word character. Errors from the session propagate, so the caller
can fail the response.

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
register_language_forms(LanguageForms(...))     # override a language pack's surface forms
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
