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
| Text | `PERSON`, `ADDRESS`, `EMAIL`, `PHONE`, `DATE_OF_BIRTH`, `NATIONAL_ID_HU_TAX`, `NATIONAL_ID_HU_TAJ`, `ID_DOCUMENT`, `BANK_ACCOUNT`, `PAYMENT_CARD`, `COMPANY_ID_HU`, `ORGANIZATION`, `PARCEL_NUMBER_HU`, `VEHICLE_PLATE`, `SECRET` |
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
    forced_by: str | None = None  # resolver debug metadata, see "Policies"; not compared
    subtype: str | None = None    # which shape of the type, e.g. SECRET "github_token"; not compared

    length: int               # property, end - start
    def overlaps(self, other: Span) -> bool
    def to_public_dict(self) -> dict  # {start, end, entity_type, score, detector[, subtype]}, no text
```

- Construction validates: `0 <= start < end`, `len(text) == end - start`,
  `0 <= score <= 1`, non-empty `detector`, known `entity_type`. Violations raise
  `ValueError`.
- `forced_by` is set only by the resolver (below) and is left out of equality, hashing and
  `to_public_dict()`.
- `subtype` is set by the rule that found the span and kept by the resolver. It is left out
  of equality and hashing; `to_public_dict()` (and so `POST /v1/analyze`) includes it only
  when set. Today only `SECRET` spans carry one: `aws_access_key_id`, `github_token`,
  `slack_token`, `stripe_key`, `api_key` (`sk-` style), `google_api_key`, `jwt`, `private_key`,
  `url_password`, `url_user`, `bearer_token`, `assignment`
  (`pii_guard.detect.rules.secrets.SUBTYPES`). A subtype names a rule, never a value.
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
class DetectionUnavailableError(DetectionError):  # pii_guard.detect.stack
                                     # code = "detection_unavailable", status_code = 503
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

- **Scopes.** The language-independent rules (`pii_guard.detect.rules.common` and
  `pii_guard.detect.rules.secrets`) run for every text. A language pack ([ADR 0008](decisions/0008-language-packs.md), `languages/<lang>/rules.py`)
  contributes `everywhere` rules (identifiers with a checksum or a distinctive validated format,
  run whatever the text's language: a Hungarian tax ID in an English email is still personal
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
| all | `BANK_ACCOUNT` (IBAN, mod 97), `PAYMENT_CARD` (issuer prefix + Luhn), `EMAIL`, `PHONE` (international `+<country>`) | IBAN 0.99, card 0.95 grouped / 0.9 compact, email 0.99, phone 0.85 |
| all | `SECRET` (provider key shapes, PEM private keys, `scheme://user:password@host`, values assigned to a secret-ish key, `Authorization: Bearer/Basic`; [entities.md](entities.md#language-independent)) | provider shape 0.9-0.97, private key 0.99, URL password 0.9 / user 0.85, bearer 0.9, assignment 0.85 |
| `hu`, everywhere | `NATIONAL_ID_HU_TAX`, `NATIONAL_ID_HU_TAJ`, `BANK_ACCOUNT` (giro), `PHONE` (`+36`, `06`), `COMPANY_ID_HU` (registration number, tax number), `ID_DOCUMENT` (personal ID, labeled ID card / passport / license / permit numbers, MRZ), `PARCEL_NUMBER_HU` | tax ID 0.99 / 0.95, TAJ 0.95 / 0.8, giro 0.95, phone 0.9, company registration number 0.95 with the `Cg.` prefix, else 0.85, tax number 0.95, personal ID 0.99 / 0.85, ID document 0.95 / 0.85, MRZ 0.99 (check digits agree) / 0.8, parcel 0.9 or 0.95 near a settlement or `belterület` |
| `hu`, language | `ADDRESS` (postcode, address with settlement and street), `VEHICLE_PLATE`, bare `ID_DOCUMENT` card number, `PERSON` inside a company name with a legal form | postcode 0.75-0.9, address 0.75 / 0.85 / 0.97 (postcode and settlement agree), plate 0.85 / 0.8, bare ID card 0.7, company-name person 0.7-0.9 (`languages/hu/companies.py`) |
| `en`, everywhere | `ID_DOCUMENT` (US SSN, UK NINO) | SSN 0.95 / 0.85, NINO 0.95 / 0.9 |
| `en`, language | `PHONE` (UK, US/NANP), `ADDRESS` (UK postcode, US ZIP), `VEHICLE_PLATE` (UK), `ID_DOCUMENT` (labeled passport / license, SSN after a label) | phone 0.8-0.85, postcode 0.75-0.85, ZIP 0.8 / 0.85, plate 0.8, labeled ID 0.85, SSN after a label 0.9 |
| `de`, everywhere | `ID_DOCUMENT` (Sozialversicherungsnummer, labeled Steuer-ID) | 0.9 / 0.97 |
| `de`, language | `ID_DOCUMENT` (Steuer-ID without a label), `PHONE`, `ADDRESS` (street + house number, postcode line) | Steuer-ID 0.85, phone 0.8, address 0.75 / 0.85, postcode line 0.7 |

Names, organizations, prose addresses and dates of birth are not rule territory; they come
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
| `PII_GUARD_DETECTION_PROFILE` | `detection_profile` | `standard \| local-only` | `standard` |
| `PII_GUARD_DETECTORS` | `detectors` | `tuple[str, ...] \| None` (comma-separated registry names) | unset (the gateway fast-mode stack: `rules`, plus `ner` when available) |
| `PII_GUARD_MAX_TEXT_CHARS` | `max_text_chars` | `int` (>= 1, code points) | `200000` |
| `PII_GUARD_POLICY_OVERRIDES` | `policy_overrides` | `dict[EntityType, Policy]` (`TYPE=mask\|keep\|block,...`) | none |
| `PII_GUARD_GATEWAY_KEEP_TYPES` | `gateway_keep_types` | `frozenset[EntityType] \| None` (deprecated) | unset |
| `PII_GUARD_NER_MODEL` | `ner_model` | `str \| None` (hub id or directory) | unset (detector default; a set model makes a missing `ner` extra stop startup) |
| `PII_GUARD_NER_REVISION` | `ner_revision` | `str \| None` | unset (pinned for the default model) |
| `PII_GUARD_NER_DEVICE` | `ner_device` | `str \| None` (`auto\|cpu\|mps\|cuda`) | unset (`auto`) |
| `PII_GUARD_NER_WARMUP_TIMEOUT` | `ner_warmup_timeout` | `float` (> 0, seconds): how long a detecting request waits for the background NER load | `120` |
| `PII_GUARD_BODY_READ_TIMEOUT` | `body_read_timeout` | `float` (> 0, seconds): whole request-body read deadline on the REST API; past it, 408 `request_timeout` and nothing is processed (raise it for large image bodies on slow links) | `30` |
| `PII_GUARD_UPSTREAM_BASE_URL` | `upstream_base_url` | `str \| None` | unset |
| `PII_GUARD_UPSTREAM_API_KEY` | `upstream_api_key` | `SecretStr \| None` | unset |
| `PII_GUARD_TENANT_KEY` | `tenant_key` | `SecretStr \| None` (hex) | unset |
| `PII_GUARD_PROJECT_STATE_PATH` | `project_state_path` | `str` (SQLite project metadata path) | `~/.local/share/pii-guard/projects/state.sqlite3` |
| `PII_GUARD_KNOWN_VALUES_MAX` | `known_values_max` | `int` (known values per session) | `1000` |
| `PII_GUARD_KNOWN_VALUES_MAX_LENGTH` | `known_values_max_length` | `int` (characters per value) | `256` |
| `PII_GUARD_VAULT_CASE_SENSITIVE_PLACEHOLDERS` | `vault_case_sensitive_placeholders` | `bool` | `false` |
| `PII_GUARD_VAULT_MAX_ENTRIES` | `vault_max_entries` | `int` (≥ 1): most placeholders in one get-or-create session before it starts a new generation | `10000` |
| `PII_GUARD_UNMASK_MAX_RESTORED_CHARS` | `unmask_max_restored_chars` | `int` (≥ 1): most characters of original values one `/v1/unmask` call or one gateway response restores | `1000000` |
| `PII_GUARD_VAULT_INSPECT` | `vault_inspect` | `"off"` \| `"masked"` \| `"full"`: the vault inspector (`/v1/vault/sessions*`); `full` only on a loopback bind | `masked` |
| `PII_GUARD_LLM_DETECTOR_URL` | `llm_detector_url` | `str \| None` | unset |
| `PII_GUARD_LLM_DETECTOR_API_KEY` | `llm_detector_api_key` | `SecretStr \| None` | unset |
| `PII_GUARD_LLM_DETECTOR_MODEL` | `llm_detector_model` | `str \| None` | unset (detector default `meta-models/muse-spark-open-1026`) |
| `PII_GUARD_LLM_DETECTOR_REASONING_EFFORT` | `llm_detector_reasoning_effort` | `str \| None` | unset (not sent) |
| `PII_GUARD_LLM_DETECTOR_MAX_TOKENS` | `llm_detector_max_tokens` | `int \| None` (>= 256) | unset (detector default `4096`) |
| `PII_GUARD_LLM_DETECTOR_TIMEOUT` | `llm_detector_timeout` | `float \| None` (> 0, seconds) | unset (detector default `60`) |
| `PII_GUARD_SAM_URL` | `sam_url` | `str \| None` | unset |
| `PII_GUARD_SAM_API_KEY` | `sam_api_key` | `SecretStr \| None` | unset (falls back to `META_API_KEY`) |
| `PII_GUARD_SAM_MODEL` | `sam_model` | `str \| None` | unset (SamClient default `sam-3.1`) |
| `PII_GUARD_SEGMENTER` | `segmenter` | `hybrid \| sam-api \| local \| off` | `hybrid` |
| `META_API_KEY` | `meta_api_key` | `SecretStr \| None` | unset |

One factory, `pii_guard.detect.stack`, picks the detectors for both the REST API and the
gateway (LAB-1270). Without `PII_GUARD_DETECTORS` the REST API runs the gateway fast-mode stack:
`rules`, plus `ner` when the `ner` extra is installed. An explicit `PII_GUARD_DETECTORS`
(`rules,llm`, say) wins for the REST API only; the gateway keeps its per-mode set: `fast`, the
default, or `audit`, which adds the LLM detector, chosen by `PII_GUARD_GATEWAY_MODE` or the
`X-PII-Guard-Mode` header (old mode names: [operations.md](operations.md#modes)). NER fails
closed (ADR 0006): with `PII_GUARD_NER_MODEL` set but the extra missing, startup raises
`DetectionError` ("ner configured but the 'ner' extra is not installed") in both; with neither,
NER is skipped and one WARNING is logged. `NerDetector` gets its model, revision and device
from `Settings`. Every detector's output goes through `CheckedDetector`: anything other than a
list of spans whose offsets match the text is `503 detection_failed`, in the gateway as in the
REST API. `PII_GUARD_POLICY_OVERRIDES` is parsed and validated when the
settings load: an unknown type or policy stops startup. `LlmDetector` resolves its model,
reasoning effort, max tokens and timeout as the constructor argument, then the setting
(environment or `.env`), then its built-in default, so the registry and `pii-guard eval`
honor them too (Muse Spark Open on Baseten needs `REASONING_EFFORT=low`; contract-length
documents need a larger `MAX_TOKENS` and `TIMEOUT`). Folding the text size limit and the
gateway settings into `Settings` is LAB-1095.

### Local-only detection profile

`PII_GUARD_DETECTION_PROFILE=local-only` constrains components that receive original input.
`standard` preserves the behavior above. Local-only permits built-in `rules` and in-process
Transformers `ner` only; default rules + NER requires the `ner` extra and an explicit existing
`PII_GUARD_NER_MODEL` directory. Loading uses `local_files_only=True`, with no implicit model
fetch or downgrade. Explicit `PII_GUARD_DETECTORS=rules` deliberately selects reduced coverage
for both REST and gateway fast mode in this profile. Hub model IDs, GLiNER, plugin detectors
and LLM detection are refused. This includes loopback HTTP LLM detectors: the supported
local-only text path is in-process.

Gateway `audit` (including its `strict` alias) is refused before any processing or downstream
request. Images require `PII_GUARD_SEGMENTER=local|off` and built-in Tesseract OCR; missing
models/dependencies and unsupported visual `mask`/`block` policies still fail closed. Cached
remote segmenters and custom OCR engines are refused. Unused endpoint settings and the default
`hybrid` segmenter do not prevent text-only startup; selecting them for an image does refuse.
Profile refusals use `503 detection_profile_denied`; existing component-specific missing-model
and unsupported-capability errors remain valid.

The downstream model configuration is independent: masked external inference is allowed.
This is enforcement for the supported component configuration, not a network sandbox for
arbitrary Python extensions. See [local-only setup](operations.md#local-only-detection) and
[data-flow boundaries](privacy-model.md#local-only-detection-boundary).

`settings.tenant_key_bytes() -> bytes | None` decodes the hex tenant key (raises
`ValueError`, without echoing the key, if it isn't hex). A new key goes into `Settings`,
`.env.example` and this table together; a test checks every `.env.example` key has a field.

## Application and CLI (implemented)

- `pii_guard.api.app:create_app(settings: Settings | None = None) -> FastAPI`. Settings are
  on `request.app.state.settings`, the detector names on `app.state.detector_names` and the
  `PolicySet` on `app.state.policies`. An unknown name in `PII_GUARD_DETECTORS`, or a
  configured but missing NER, raises `DetectionError` here, at startup. The analyzer (`app.state.analyzer`, default
  `pii_guard.api.deps.RegistryAnalyzer`) runs the detectors through `DetectionPipeline`.
- `GET /healthz` → `200 {"status": "ok", "version": "<package version>", "ner": "<state>"}`.
  `ner` is `off` (no NER in the stack), `loading`, `ready` or `failed`. `status` stays `ok`
  while it loads: it is a liveness check.
- **NER warm-up (LAB-1274, LAB-1303).** With `PII_GUARD_NER_MODEL` set, the lifespan loads the
  model before the app serves, and a model that can't load stops startup. Without it, when the
  stack has `ner` (the resolved published model or the public fallback, `docs/models.md`), the
  lifespan starts loading it, download included, in a background thread
  (`pii_guard.detect.stack.NerWarmup`, `app.state.ner_warmup`): the server answers at once.
  `POST` requests to the detecting routes (`/v1/analyze`, `/v1/mask`, `/v1/mask/image`,
  `/v1/chat/completions`, `/v1/responses`, also under `/s/<session>/`) that arrive meanwhile
  wait for it, without blocking the event loop, up to `PII_GUARD_NER_WARMUP_TIMEOUT` seconds.
  Still loading then: `503 detector_loading` with `Retry-After`. The load failed:
  `503 detection_unavailable` ("ner model unavailable: …", the exception type only) until
  restart. Every other route answers while it loads.
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
company name is still masked, and are then left in place. **A detector that says mask wins
over a kept type** (fail closed, [ADR 0006](decisions/0006-fail-closed.md)): when an
authoritative rule span has a `keep` type (`COMPANY_ID_HU` on an adószám) and a span of a
masked type from any detector (NER, LLM, another rule) overlaps it, the resolver keeps the
rule's boundaries and takes the masked type, so a sole trader's tax number that the LLM calls
`NATIONAL_ID_HU_TAX` is masked. The masked type comes from an authoritative span first, then
the adjudicator, then the largest overlap, score and detector order, and `Span.forced_by`
names the detector it came from. Only a `keep` policy for that masked type as well leaves the
value in place. `BlockedEntityError` carries types
and counts (`counts`), never values. The REST API, the gateway and the eval share the
resolver (`DetectionPipeline`), the defaults and one policy builder, `PolicySet.from_settings`.
`PII_GUARD_GATEWAY_KEEP_TYPES` is a deprecated alias, applied to the REST API and the gateway
alike: when set, it is the exact keep set (with a deprecation warning);
`PII_GUARD_POLICY_OVERRIDES` wins.

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
| 400 | `unsupported_content` | Gateway: the body holds a key or content part outside the [request allow-list](#gateway-request-fields-implemented) (an unknown field, a remote image URL, an audio part). Nothing is forwarded or stored. A malformed gateway body (not JSON, a wrong value type) is `400 invalid_request`. |
| 400 | `unsupported_api` | `POST /v1/messages` (and `/v1/messages/count_tokens`): the upstream has no Anthropic Messages API (it answered 404 or 405 on `.../messages`). The message points to an Anthropic-compatible upstream, the OpenAI-compatible routes (`/v1/chat/completions`) and the console's Connect page; the response has `x-should-retry: false`. Only the masked request reached that upstream; the call is one `refused` traffic event. |
| 401 | `unauthorized` | `PII_GUARD_API_TOKEN` is set and the request has no valid token (every route but `/healthz`). |
| 403 | `traffic_log_not_local` | `PII_GUARD_TRAFFIC_LOG=full` and the connection is not loopback on both ends. |
| 403 | `project_access_denied` | Hosted project management lacks an authenticated Google owner, or the request tries to use an endpoint key outside its permitted route/scope. |
| 403 | `vault_inspect_not_local` | `PII_GUARD_VAULT_INSPECT=full` and a `/v1/vault/*` connection is not loopback on both ends. |
| 403 | `vault_reveal_disabled` | `GET /v1/vault/sessions/{ref}?reveal=true` while `PII_GUARD_VAULT_INSPECT` is not `full`. |
| 404 | `not_found` | Unknown route, or an unknown or expired `session_id` on any route that takes one (`/v1/analyze`, `/v1/mask`, `/v1/mask/image`, `/v1/unmask`, the session and known-values routes, the gateway) |
| 404 | `project_not_found` | The project-owned resource is unknown or does not belong to the selected project/owner. |
| 404 | `traffic_log_disabled` | `GET /v1/traffic` and `/v1/traffic/stream` while `PII_GUARD_TRAFFIC_LOG=off` (the default). |
| 404 | `vault_inspect_disabled` | The `/v1/vault/*` routes while `PII_GUARD_VAULT_INSPECT=off`. |
| 408 | `project_request_timeout` | An endpoint gateway request body did not finish within its bounded read deadline. |
| 413 | `payload_too_large` | The body, text or image is larger than the configured limit (see docs/operations.md). |
| 413 | `unmask_output_too_large` | Restoring would output more than `PII_GUARD_UNMASK_MAX_RESTORED_CHARS` characters of original values: one `/v1/unmask` text, or one gateway response (non-streaming: this error; streaming: the stream ends with an error event of this code). Nothing past the limit is returned. |
| 415 | `unsupported_media_type` | `/v1/mask/image`: the image is not a PNG or JPEG (sniffed from its bytes). |
| 422 | `invalid_request` | Body fails validation. The message lists field locations only, never values. |
| 422 | `invalid_image` | `/v1/mask/image`: the image can't be decoded, or its base64 or JSON body is malformed. |
| 422 | `invalid_known_value` | A pre-loaded known value is too short (< 3 non-space characters), too long, or has an unknown or visual type. The message names its index and type, never the value. |
| 422 | `too_many_known_values` | The session would hold more than `PII_GUARD_KNOWN_VALUES_MAX` known values; nothing is added. |
| 422 | `blocked_entity` | `/v1/mask` (or the gateway) found an entity type whose policy is `block`. The message lists types and counts only; nothing is masked, stored or forwarded. |
| 422 | `invalid_project_config` | A project, policy, endpoint or endpoint-key configuration is invalid. |
| 422 | `upstream_destination_not_allowed` | Hosted endpoint destination does not satisfy the public HTTPS/port policy. |
| 422 | `outbound_check_failed` | Gateway: after masking, the request still held a value its vault session knows (the [outbound re-check](architecture-gateway.md#outbound-re-check), LAB-1500); nothing was sent. The message lists entity types and counts only; the response has `X-PII-Guard-Outbound-Check: blocked`. |
| 422 | `placeholder_in_input` | The text to mask contains a placeholder this session already issued; restoring it would put a value into text never masked. The message holds a count only. Other placeholder-shaped tokens in the input are left as they are and never issued as a placeholder. |
| 409 | `session_entry_limit_reached` | An explicit vault session (`X-PII-Guard-Session`, or a path or `prompt_cache_key` id) already holds `PII_GUARD_VAULT_MAX_ENTRIES` placeholders. Explicit sessions are never rotated, so nothing is masked or sent; start a new session (LAB-1565). |
| 502 | `upstream_credential_rejected` | Listing a provider's models (`POST /v1/projects/{project_id}/endpoints/models`, a pass-through `/e/{endpoint_id}/v1/models`): the provider answered 401 or 403, so the API key is wrong or lacks access. The message is fixed; the provider's own status text and body are never passed on. |
| 501 | `responses_unsupported` | `POST /v1/responses`: the upstream answered 404 or 405, so it has no native Responses API. Nothing is translated or retried. |
| 502 | `upstream_unavailable` | Gateway: the upstream could not be reached or answered with something unusable. The provider's own error text is never passed on. |
| 502 | `upstream_did_not_stream` | `POST /v1/chat/completions` with `stream: true`: the upstream answered without `text/event-stream`. The body is not read or forwarded; retry without `stream` (see [Gateway chat streaming](#gateway-chat-streaming-implemented)). |
| 503 | `upstream_not_configured` | Gateway: the server has no upstream (`PII_GUARD_UPSTREAM_BASE_URL`). |
| 503 | `vault_capacity_exhausted` | A new vault session is needed while every session slot is held by an active request, or this client identity already holds `PII_GUARD_VAULT_MAX_LEASES_PER_IDENTITY` in-flight requests (LAB-1584; then even an existing session is refused); nothing is masked or sent. Retry once a request finishes. |
| 503 | `vault_not_configured` | `PII_GUARD_TENANT_KEY` is unset, not hex or shorter than 16 bytes: `/v1/mask`, `/v1/unmask`, the known-values routes and the gateway fail closed. The message never echoes the key. |
| 500 | `masking_failed` | `MaskingError` |
| 503 | `detection_failed` | `DetectionError` (including timeouts) |
| 503 | `detection_profile_denied` | The selected or cached raw-processing component is not permitted by `PII_GUARD_DETECTION_PROFILE`; nothing is forwarded. |
| 503 | `project_storage_unavailable` | The local SQLite project configuration store cannot safely be opened or used. |
| 503 | `detection_unavailable` | `DetectionUnavailableError` (a `DetectionError`): a configured detector can't run safely, so nothing ran and nothing was sent. Today: the LLM detector without `PII_GUARD_LLM_DETECTOR_API_KEY` (gateway audit mode, or `PII_GUARD_DETECTORS` with `llm` on `/v1/*`); the message is "audit mode needs PII_GUARD_LLM_DETECTOR_API_KEY …". Refused before any detection, image segmentation or request, so the text never leaves the machine. A keyless endpoint on loopback (`localhost`, `127.0.0.1`, `::1`) is allowed: the text stays on the machine. |
| 503 | `detector_loading` | `DetectorLoadingError` (a `DetectionError`): the NER model is still loading in the background after `PII_GUARD_NER_WARMUP_TIMEOUT` (default 120 s, see "NER warm-up" above). Nothing ran and nothing was sent; the response has `Retry-After`. |
| 503 | `ocr_unavailable` | `/v1/mask/image` (and gateway images): no OCR engine, so the text in the image can't be checked (`PII_GUARD_IMAGE_REQUIRE_OCR`, the default). |
| 500 | `internal_error` | Anything unexpected. No exception text is returned. |

Fail closed: on any error the response carries no masked or partially masked text.

The OpenAPI schema (`/openapi.json`, `/docs`) declares the codes each route can return, with
the `ErrorResponse` body (`pii_guard.api.errors.ERROR_CODES`). The public subset, with the gateway's
codes added, is committed as [openapi.json](openapi.json) and rendered at
[guard.watt-mind.com/#api](https://guard.watt-mind.com/#api); the runtime pages stay off on
the hosted service. See [api.md](api.md).

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
including `keep` and `block` ones: analyze never refuses on policy. A span whose rule sets a
`subtype` carries it (`{"entity_type": "SECRET", "subtype": "github_token", ...}`); spans
without one leave the key out rather than sending `null` (LAB-1349).

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
expired `session_id` → 404 `not_found`. Restoring more than
`PII_GUARD_UNMASK_MAX_RESTORED_CHARS` characters of original values (default 1 000 000) →
413 `unmask_output_too_large`, with no text (LAB-1350).

Owner rule (LAB-1580): a session that a gateway request bound to a credential (its
`Authorization` value) unmasks only for that same value. Any other `Authorization` value, or
none, gets 404 `not_found`, as if the session did not exist. Sessions no gateway request has
presented, and anonymous-owned ones, unmask for every caller. Unmask only checks the owner: it
never binds a session. In hosted mode `Authorization` is stripped before routing, so isolation
there is the per-owner vault.

### `POST /v1/mask/image`

Cover faces, signatures, ID photos and text personal data in a PNG or JPEG image
(`pii_guard.api.routes.image`, shared pipeline in `pii_guard.visual.masking`).

Request, either form:

- **raw upload**: the image bytes as the body with `Content-Type: image/png` or `image/jpeg`;
  optional `?language=hu`. `curl --data-binary @card.png -H 'Content-Type: image/png' …`
- **JSON**: `{"image": "<base64>" | "data:image/png;base64,…", "language": "hu"}`.

Options (JSON fields, or query parameters with a raw upload):

- `render`: `labels` (default, `PII_GUARD_IMAGE_RENDER`) prints each covered region's vault
  placeholder in its box and returns a masked transcript and a document summary; `opaque`
  fills boxes solid black and returns neither. Without a tenant key the default falls back
  to `opaque`; an explicit `labels` is then `503 vault_not_configured`.
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
    {"entity_type": "FACE", "box": [72, 116, 188, 262], "source": "local", "detector": "yunet", "score": 0.93, "policy": "mask"},
    {"entity_type": "SIGNATURE", "box": [402, 380, 560, 430], "source": "sam", "detector": "sam", "score": null, "policy": "mask"},
    {"entity_type": "NATIONAL_ID_HU_TAJ", "box": [310, 184, 437, 206], "source": "ocr", "detector": "rules", "score": 1.0, "policy": "mask"}
  ],
  "masked": [{"entity_type": "FACE", "count": 1}, {"entity_type": "SIGNATURE", "count": 1}, {"entity_type": "NATIONAL_ID_HU_TAJ", "count": 1}],
  "kept": [],
  "analysis": {
    "sam": {"model": "yunet-2023mar+sam-3.1", "entity_types": ["FACE", "SIGNATURE", "ID_PHOTO"]},
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
    {"entity_type": "FACE", "box": [72, 116, 188, 262], "source": "local", "detector": "yunet", "score": 0.93, "policy": "mask",
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
  covered and labeled (`detector: "vault"`), for accepted matches only.
- `cover_box` is the area actually painted: the box grown by 2 px and, when the label would
  not fit legibly, extended to the right into free space (never over visible words or another
  box). `box` stays the detected area in both render modes, so coverage is identical.
- `transcript` is the OCR text with every covered value replaced by its placeholder (or
  `[PHOTO]`, `[SIGNATURE]`); values the session knows are also replaced wherever they appear.
  Before the response is returned, the transcript and summary are checked against every
  covered value; one found there fails closed with `500 masking_failed`. Text the detectors
  did not find stays in the transcript exactly as it stays visible in the image.

- `box` is `[x1, y1, x2, y2]`, inclusive pixel corners in the image after EXIF orientation.
  `source` is `sam` (SAM 3.1 segmentation), `local` (the on-device face detector, YuNet) or
  `ocr` (OCR word boxes of a span a text detector found); `detector` is `sam`, `yunet`, the text
  detector's registry name, or `captions` for a value printed next to a known field caption
  (`Név`, `Date of birth`; score 0.8). SAM gives no scores; YuNet does.
- `FACE` boxes are grown before masking (40% up, 10% on each side, 5% down, clamped to the
  image) because SAM's face box leaves hair and ears visible; the reported box is the grown
  one, i.e. the area covered.
- `analysis.ocr.models` maps each model-backed text detector to its model id, so clients can
  label regions by what actually ran.
- Regions never carry the covered text or pixels. Overlapping regions of the same type and
  source are merged into their union (SAM's `signature` and `squiggly line` prompts).
- Policies apply per region: `mask` regions are covered (plus 2 px; solid black with `opaque`,
  a neutral labeled box with `labels`), `keep` regions
  (`STAMP` by default) are reported and left visible (`STAMP` is only segmented with
  `sam-api`, or when its policy is not `keep`), any `block` region is
  `422 blocked_entity` with no image.
- Segmenters (`pii_guard.visual.segment.Segmenter`): anything with
  `segment(image: bytes, entity_types=None) -> list[Region]` that raises `DetectionError` on
  any failure, including a requested type it cannot find. The API and the gateway build theirs
  from `PII_GUARD_SEGMENTER` (`pii_guard.visual.segmenters.build_segmenter`, LAB-1245):
  - `hybrid` (default): `LocalSegmenter` (YuNet on the CPU) finds `FACE` and `ID_PHOTO`, SAM 3.1
    on the Meta API finds `SIGNATURE` (and `STAMP` only when its policy is not `keep`): **2 Meta
    API requests per image** (`signature`, `squiggly line`), run alongside YuNet. The image
    still leaves the machine for those two requests. `analysis.sam.model` is
    `yunet-2023mar+sam-3.1`; `analysis.sam.entity_types` lists the visual types asked for
    (`["FACE", "SIGNATURE", "ID_PHOTO"]` with the default policies).
  - `sam-api` (the default before LAB-1245): SAM segments every visual type it has a prompt for,
    one request per prompt: `face`, `signature`, `squiggly line`, `photo of a person`, `stamp`
    (**5 requests per image**; `keep` stamps are found and reported).
  - `local`: YuNet only, nothing leaves the machine. It cannot find signatures, so while
    `SIGNATURE` is `mask` or `block` every image is `503 detection_failed`; with
    `PII_GUARD_POLICY_OVERRIDES=SIGNATURE=keep` images are accepted with signatures visible.
  - `off`: every image is `503 detection_failed` (nothing is segmented, nothing is returned).
  - Fallbacks, decided when the segmenter is first built: `hybrid` without OpenCV or the YuNet
    model logs a warning and sends faces and ID photos to SAM too (4 requests; still masked);
    without them **and** without a SAM API key it is `503 detection_failed`. `local` never
    falls back to the API.
  - `LocalSegmenter` needs `uv sync --extra local-vision` and the model (`python -m
    pii_guard.visual.segment fetch` into `PII_GUARD_MODEL_DIR`, default
    `~/.cache/pii-guard/models`; the Docker image ships both). A missing OpenCV, a missing
    model or one whose SHA-256 differs from the pinned value raises.
  - Every mode other than `sam-api` asks only for visual types whose policy is not
    `keep` (a kept region stays visible anyway).
- Region `source`: `sam` (SAM 3.1), `local` (on-device, `detector: "yunet"`, with a score) or
  `ocr`. SAM needs `META_API_KEY` (or `PII_GUARD_SAM_API_KEY`); without one every SAM request
  is `503 detection_failed`.
- Text in the image: when Tesseract is installed (`uv sync --extra ocr` and the `tesseract`
  binary with `hun`/`eng` data; the Docker image ships both), OCR text goes through the API's
  detectors (`PII_GUARD_DETECTORS`, else rules + ner when available; names need `llm` too). Without it the image is refused with
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

`POST /v1/responses` does the same for `input_image` parts (`{"type": "input_image",
"image_url": "data:image/png;base64,…", "detail": …}`, as Muse Code `--image` sends them), in
message content and in tool-call output arrays; the text that follows each image is an
`input_text` part. `file_id` images and remote URLs are `400 unsupported_content` (LAB-1285).

### `GET /v1/status`

What this server runs, read-only, for the web UI's Overview, Connect and Policy pages
(`pii_guard.api.routes.status`). It takes no body and no parameters, never touches a vault
session and never calls a detector or the upstream. One route in both modes
([ADR 0013](decisions/0013-one-console-owner-scoped-api.md)): hosted owners get the
[hosted projection](#hosted-projection) below.

**Auth.** Like every route but `/healthz`: when `PII_GUARD_API_TOKEN` is set the request needs
`Authorization: Bearer <token>` or `X-PII-Guard-Token: <token>`, otherwise
`401 unauthorized`. With no token set the route is open. `auth.token_required` tells the UI which.

**No secrets.** Configuration only: never a key, a token, a value or a session. A secret
appears only as "set or not" (`auth.token_required`, `gateway.modes.audit.available`,
`images.sam`), never its value. The upstream is reported by origin (`scheme://host[:port]`),
without its path, query, user or password.

```json
// response 200 (shortened)
{
  "version": "0.1.0",
  "gateway": {
    "default_mode": "fast",
    "url": "http://localhost:8787/v1",
    "modes": {
      "fast": {"detectors": ["rules", "ner"], "available": true, "reason": null},
      "audit": {"detectors": ["rules", "ner", "llm"], "available": false,
                "reason": "audit mode needs PII_GUARD_LLM_DETECTOR_API_KEY …", "model": null}
    }
  },
  "rest": {"detectors": ["rules", "ner"]},
  "ner": {"available": true, "model": null, "state": "ready", "error": null},
  "upstream": {"configured": true, "mock": false, "origin": "https://models.example.com:8443"},
  "images": {"segmenter": "hybrid", "sam": false, "ocr_required": true, "gaps": [],
             "available": true},
  "policies": {"PERSON": "mask", "ORGANIZATION": "keep"},
  "auth": {"token_required": false},
  "default_language": "hu",
  "traffic_log": "off",
  "vault_inspect": "masked",
  "metrics": false,
  "capabilities": {"text": true, "chat": true, "images": true, "logs": false, "vault": true,
                   "server_policy": true, "projects": true, "connect": true,
                   "evaluation": true, "accounts": false}
}
```

| Field | Type | Meaning |
|---|---|---|
| `version` | string | The server's version (same as `/healthz`). |
| `gateway.default_mode` | `"fast"` \| `"audit"` | The mode a gateway request without a mode override runs in. |
| `gateway.url` | string | This request's own base URL plus `/v1`: the address a client on the same network path (the browser that asked) reaches the gateway at. Not the upstream. |
| `gateway.modes.fast.detectors` | string[] | Detector names the fast mode runs, in order. Empty when the stack can't be built. |
| `gateway.modes.fast.available` | bool | The fast detectors can run. |
| `gateway.modes.fast.reason` | string \| null | Why not (the detection error text, no values); `null` when available. |
| `gateway.modes.audit.detectors` | string[] | The fast detectors plus `llm`. |
| `gateway.modes.audit.available` | bool | Audit can run: the fast detectors can, and the LLM detector is configured (a key, or a keyless loopback endpoint; see `detection_unavailable`). |
| `gateway.modes.audit.reason` | string \| null | Why not: the fast reason first, else the LLM detector's. Names the setting, never a value. |
| `gateway.modes.audit.model` | string \| null | The LLM detector's model name; `null` if it can't be configured. |
| `rest.detectors` | string[] | Detectors `/v1/analyze` and `/v1/mask` run (`PII_GUARD_DETECTORS`, or the fast default). |
| `ner.available` | bool | `ner` is in the fast detectors. |
| `ner.model` | string \| null | `PII_GUARD_NER_MODEL`, `null` when unset (the detector default). |
| `ner.state` | string | Live: `off`, `loading` (detecting requests wait), `ready` or `failed` (as `/healthz`). |
| `ner.error` | string \| null | Why the load failed (exception type only, no path or value); `null` otherwise. |
| `upstream.configured` | bool | An upstream is set (or the mock one is used). |
| `upstream.mock` | bool | The gateway answers from the built-in mock upstream. |
| `upstream.origin` | string \| null | Origin only (`scheme://host[:port]`); `null` when unset, unparseable or mock. |
| `images.segmenter` | `"hybrid"` \| `"sam-api"` \| `"local"` \| `"off"` | `PII_GUARD_SEGMENTER`. |
| `images.sam` | bool | A SAM backend is configured (Meta API key or `PII_GUARD_SAM_URL`); the key itself is never returned. |
| `images.ocr_required` | bool | `PII_GUARD_IMAGE_REQUIRE_OCR`. |
| `images.gaps` | string[] | What image masking still needs: `ocr` (the extra), `tesseract`, `segmenter`. `["unknown"]` if it can't be checked. |
| `images.available` | bool | `gaps` is empty: `/v1/mask/image` can run. |
| `policies` | object | Every `EntityType` name → its effective policy (`mask`, `keep` or `block`): defaults plus `PII_GUARD_POLICY_OVERRIDES`. |
| `auth.token_required` | bool | `PII_GUARD_API_TOKEN` is set. |
| `default_language` | string | `PII_GUARD_DEFAULT_LANGUAGE` (`"hu"`). |
| `traffic_log` | `"off"` \| `"masked"` \| `"full"` | `PII_GUARD_TRAFFIC_LOG` level. |
| `vault_inspect` | `"off"` \| `"masked"` \| `"full"` | `PII_GUARD_VAULT_INSPECT`: whether the vault inspector answers, and whether it can reveal values. |
| `metrics` | bool | Request metrics are collected (`/metrics`). |
| `capabilities` | object | Which console sections this server offers, below. The UI's only source for them: it never branches on the mode or the build. |

Everything but `gateway.url`, `traffic_log`, `metrics` and `capabilities` is fixed for the life
of the app and computed on the first call; a settings change needs a restart.

**`capabilities`.** Booleans computed from settings and mode. `logs` and `vault` come from the
caller's own view (the server's settings locally, the owner's runtime when hosted).

| Key | Local | Hosted | Section |
|---|---|---|---|
| `text` | `true` | `true` | Text masking (`/v1/analyze`, `/v1/mask`, `/v1/unmask`). |
| `chat` | `true` | `true` | The gateway chat (`/v1/chat/completions`, `/v1/responses`). |
| `images` | `true` | `PII_GUARD_HOSTED_IMAGES` and no masked visual type the on-device segmenter can't find | Image masking (`/v1/mask/image`); `images.available` says whether it can run locally. Hosted: signed-in owners, local processing only ([ADR 0014](decisions/0014-hosted-local-images.md)). |
| `logs` | `traffic_log != "off"` | `true` | The traffic log (`/v1/traffic`). |
| `vault` | `vault_inspect != "off"` | `true` | The vault inspector (`/v1/vault/sessions`). |
| `server_policy` | `true` | `false` | The server-wide entity policy page (`policies`). Without it, Policy shows the owner's default project policy read-only (from the project API) and points to Projects. |
| `projects` | `true` | `true` | Projects, policies and endpoints (`/v1/projects`). |
| `connect` | `true` | `true` | Connect (`/v1/connect/snippets`). |
| `evaluation` | `true` | `true` | The benchmark and evaluation pages. |
| `accounts` | `false` | `true` | Account, API keys and connections (`/v1/account`). |

#### Hosted projection

Hosted, `/v1/status` needs a signed-in Google principal: guests get `401 unauthorized`, and
guard API keys and endpoint keys are refused with `401` (keys are for the gateway and REST).
The response is an allow-list of the fields above: a field not listed here is not returned.

```json
// response 200, hosted
{
  "version": "0.1.0",
  "gateway": {
    "default_mode": "fast",
    "url": "https://guard.example/v1",
    "modes": {"fast": {"detectors": ["rules", "ner"], "available": true, "reason": null}}
  },
  "ner": {"available": true, "state": "ready", "error": null},
  "policies": {"PERSON": "mask", "ORGANIZATION": "keep"},
  "default_language": "hu",
  "traffic_log": "masked",
  "vault_inspect": "masked",
  "capabilities": {"text": true, "chat": true, "images": true, "logs": true, "vault": true,
                   "server_policy": false, "projects": true, "connect": true,
                   "evaluation": true, "accounts": true}
}
```

| Field | Local | Hosted |
|---|---|---|
| `version` | yes | yes |
| `gateway.default_mode` | `PII_GUARD_GATEWAY_MODE` | always `fast` |
| `gateway.url` | the request's base URL + `/v1` | `HOSTED_PUBLIC_ORIGIN` + `/v1`, never the request's `Host` |
| `gateway.modes` | `fast` and `audit` | `fast` only (audit is not offered hosted) |
| `rest` | yes | dropped |
| `ner` | `available`, `model`, `state`, `error` | `available`, `state`, `error` (no model: it may name a local path) |
| `upstream` | yes | dropped |
| `images` | yes | dropped |
| `policies` | effective server policies | the default policies (projects pin their own) |
| `auth` | yes | dropped |
| `default_language` | yes | yes |
| `traffic_log` | server-wide level | the owner's own log (`masked`) |
| `vault_inspect` | `PII_GUARD_VAULT_INSPECT` | the owner's own inspector (`masked`) |
| `metrics` | yes | dropped |
| `capabilities` | yes | yes (hosted values) |

### `GET /v1/connect/snippets`

The Connect quickstart's copy-paste blocks (`pii_guard.api.routes.connect`,
`pii_guard.integrations.snippets`); `pii-guard connect <tool> --print` prints the same code.
Never a key: blocks name keys as `$VARIABLE`, and an upstream appears by origin and preset name
only.

- `?session=<id>`, `?model=<id>` (local): blocks at `<base>/s/<session>/v1` with the
  operator's upstream and models, `auth.token_env` `PII_GUARD_API_TOKEN`.
- `?endpoint=<id>`: the same blocks for one of the caller's project endpoints
  ([ADR 0013](decisions/0013-one-console-owner-scoped-api.md)). `gateway_url` is
  `<origin>/e/<endpoint>/v1`: `HOSTED_PUBLIC_ORIGIN` hosted, the request's base URL locally.
  The model is the endpoint's (pass-through: `model` and `endpoint.model` are `null`, `models`
  is empty and the blocks carry the `<model-id>` placeholder for the client's own), `auth` is `{"token_required": true, "token_env":
  "PII_GUARD_ENDPOINT_KEY"}`, `session`/`session_url`/`session_ref` are `null`, `presets` is
  empty, and `upstream` has the preset name but `origin: null`. `endpoint` is
  `{"id", "name", "model", "enabled"}`. Muse Code is `supported: false` (it reads its catalog
  from the gateway root, which endpoint URLs don't serve); pi's block adds
  `--no-session-path --api-key '$PII_GUARD_ENDPOINT_KEY'`. `session` or `model` with
  `endpoint` is `422 invalid_request`.

**Owner check.** The endpoint must belong to the caller: the signed-in Google principal hosted,
`local-owner` locally (with no `PII_GUARD_API_TOKEN`, only from loopback on both ends, else
`403 project_access_denied`, as project management). An unknown id and another owner's id both
get the same `404 project_not_found`.

**Hosted.** Signed-in Google principals only, as `/v1/status`: guests `401`, API keys and
endpoint keys `401`. `endpoint` is required (`422 invalid_request` without it).

### `GET /v1/traffic`

`{"level": "masked" | "full", "size": int, "boot": str, "events": [...]}`, events oldest first
(`docs/operations.md`, "Traffic log", for an event's fields). `?limit=` keeps the newest N,
`?after=<seq>` only events with a larger `seq`. `seq` restarts at 1 with the server process;
`boot` (`b_` + 16 hex, random per process) changes with it, so a client holding an `after`
cursor resets it to 0 when `boot` differs from the one it saw last. `GET /v1/traffic/stream`
sends the same events as server-sent events (`id:` = `seq`).

An event's `outcome` is additive: new values can appear, so a consumer treats an unknown one
as a failure. `upstream_failed` (LAB-1629) marks a call whose masked request was forwarded and
then failed upstream (`502 upstream_unavailable`, `upstream_did_not_stream`); such calls were
`refused` before, and their `error.code` is unchanged.

### Vault inspector: `/v1/vault/sessions`

For troubleshooting (LAB-1328): which vault sessions exist, where each came from and what it
maps. `PII_GUARD_VAULT_INSPECT` sets the mode:

| Mode | What the routes return |
|---|---|
| `off` | 404 `vault_inspect_disabled` on every route. |
| `masked` (default) | Sessions, placeholders, counts and a redacted **hint** of each value. Never an original, a form or a session id. `reveal=true` is 403 `vault_reveal_disabled`. |
| `full` | As `masked`; `reveal=true` also returns the originals, their other forms and the session id. Startup refuses it unless `PII_GUARD_HOST` is loopback and `PII_GUARD_ALLOWED_HOSTS` holds loopback names only (`VaultInspectConfigError`), and every `/v1/vault/*` request must be loopback on both ends (403 `vault_inspect_not_local`), like `PII_GUARD_TRAFFIC_LOG=full`. |

`PII_GUARD_API_TOKEN` and the `Host` check apply as on every route. Reading never touches a
session: no TTL is extended.

A session is addressed by its **`ref`**, the traffic log's `session_ref` (`s_` + 16 hex, an
HMAC of the session id under a per-process key that changes on restart). The session id is a
bearer handle to the vault (`/v1/unmask` with it restores every value), so it is never listed;
only a revealed read returns it. A traffic event's `session_ref` is the same ref, so a Logs
row links to its session.

- `GET /v1/vault/sessions[?source=header|path|prompt_cache_key|default|api]`: every live
  session, most recently used first.

  ```json
  {"mode": "masked", "ttl_seconds": 3600, "sessions": [
    {"ref": "s_3f9a1c0b7d2e4a61", "source": "path", "client": "anonymous",
     "created": "2026-10-28T09:12:03+00:00", "last_used": "2026-10-28T09:14:40+00:00",
     "ttl_left_seconds": 3443.2, "generation": 9, "entries": 6, "occurrences": 11,
     "known_values": 0,
     "entity_counts": {"EMAIL": 2, "PERSON": 4}}]}
  ```

  `source` is the step that chose a gateway session (see "Gateway sessions"), or `api` for one
  created by `/v1/mask` or `/v1/sessions`; a later request that names the session in
  `X-PII-Guard-Session` keeps its source. `client` is the first 12 hex characters of the
  SHA-256 of the creating request's `Authorization` value, or `anonymous`; `null` (and
  `created` `null`) for an `api` session, whose creation is not recorded.
- `GET /v1/vault/sessions/{ref}[?reveal=true]`: the session's summary plus `mode`,
  `revealed`, `session_id` (revealed only) and `items`: one per placeholder (casing and layout
  variants after their value, with `variant_of`), then the known values nothing matched yet
  (`placeholder: null`). Each item has `placeholder`, `entity_type`, `origin` (`detected`, or
  `known` for a pre-loaded value), `count` (occurrences masked), `forms` (how many other written
  forms matched: inflected stems, split surfaces), `hint`, `detector` (the detector of the
  first span that created the entry), `first_seen` and `last_seen` (vault-clock seconds of
  the first and latest masked occurrence), and on a revealed read `original`
  and `known_forms`. Every revealed read is logged at `WARNING` with the ref and the counts,
  never a value or the session id.

  The hint keeps each word's first character and length (`T•••• E•••`; words under three
  characters are all bullets), a number's last two digits when it has at least six
  (`+•• •• ••• ••67`), and the separators; a `SECRET` is up to 12 bullets.
- `DELETE /v1/vault/sessions/{ref}`: 204; the session is dropped as if it expired. A client
  naming it in `X-PII-Guard-Session` then gets 404; a derived gateway session (path,
  `prompt_cache_key`, default) starts again, empty, on its next request.

Unknown or expired ref: 404 `not_found`; a malformed one: 422 `invalid_request`.

## Gateway sessions (implemented)

Every gateway call (`/v1/chat/completions`, `/v1/responses`, `/v1/messages`) uses one vault session, chosen in
this order (`pii_guard.gateway.sessions`, LAB-1286; details in
[architecture-gateway.md](architecture-gateway.md#sessions)):

| Step | `X-PII-Guard-Session-Source` | Session | Missing |
|---|---|---|---|
| 1 | `header` | `X-PII-Guard-Session` | `404 not_found` (malformed: `400 invalid_request`) |
| 2 | `path` | the id in a `/s/<session>/v1/...` or `/s/<session>/muse-code/...` URL, same grammar as the header | created (malformed: `400 invalid_request`) |
| 3 | `prompt_cache_key` | `HMAC(tenant key, "pck:" + identity + ":" + prompt_cache_key)` | created |
| 4 | `default` | `HMAC(tenant key, "default:" + identity)` | created |

`identity` is the SHA-256 of the request's `Authorization` value, or `anonymous` (a single
local principal by construction: see `gateway/sessions.py`). Every
response carries `X-PII-Guard-Session` (the id used, including a derived `d_…` one) and
`X-PII-Guard-Session-Source`; the traffic record has `session_source` next to `session_ref`.
Steps 2-4 go through `Vault.session_or_create` and its `PII_GUARD_VAULT_MAX_ENTRIES` cap.
An explicit session (steps 1-2) is bound to the credentialed identity that first presents
it to the gateway (LAB-1565): another credentialed identity presenting the same id gets
`404 not_found` (the credential-less local principal is never refused by a binding), and
session ids are 3-128 characters. A dropped, expired or rotated session id re-created as a
new incarnation starts clean: no detection-cache entries and no issued-id exemptions carry
over.

Lifetime of a session a refused call created (LAB-1316): a call holds its session from
resolving it until masking finished or failed. When the call that created the session is
refused, the session is dropped only once no other call holds it and no call on it finished
masking; the last holder to leave does the drop. So a refused call never turns a concurrent
call on the same session (Muse Code sends its main turn and reminder observers together) into
`404 not_found`, and with nobody succeeding the refused call's values are still forgotten
(fail closed). Once any call on the session finished masking, the session stays, including
the entries the refused call added. A refused call never drops a session it did not create
(as before), and a lone refused call still drops the one it created.

Every gateway response that reached the upstream carries `X-PII-Guard-Outbound-Check: passed`;
a request refused by the re-check gets `422 outbound_check_failed` with
`X-PII-Guard-Outbound-Check: blocked` (policy and short-value rules:
[architecture-gateway.md](architecture-gateway.md#outbound-re-check)). Besides re-reading the
walker's texts, the re-check scans the serialized masked body as one text, so a field no
walker slot covers can't carry a session value out either (LAB-1563).

## Gateway chat streaming (implemented)

For Chat Completions, `stream: true` requires an upstream `text/event-stream` response.
A successful non-SSE response is closed without reading or forwarding its body and returns
sanitized HTTP `502` with error code `upstream_did_not_stream`; the client can retry without
`stream`. The gateway does not synthesize SSE from a JSON answer. Non-streaming JSON success
and upstream HTTP error status/sanitization remain unchanged. The traffic record marks the
call as failed with this code and retains the upstream status, without the rejected body.

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
  A JSON number with six or more decimal digits is detected too (`{"tax_id": <NUMBER>}` uses
  schematic placeholder notation; an
  integral float in its integer form): a number with detected personal data is replaced by
  the placeholder **string** (`"[[NATIONAL_ID_HU_TAX]]"`), because a JSON number can't
  carry a placeholder; any other number is forwarded as the same number (LAB-1348). The
  session records that the placeholder replaced a JSON number and its literal. When the
  answer's tool-call arguments (chat `function.arguments` and legacy `function_call`,
  Responses `function_call.arguments`; whole and streamed) hold that placeholder as a whole
  string value (`"tax_id": "[[NATIONAL_ID_HU_TAX]]"`), it is restored as the original
  number literal (`<NUMBER>`, or `<NUMBER>.0` for a float), quotes dropped (LAB-1361).
  It stays a string inside a longer string, as an object key, in message text, and whenever
  the same placeholder also replaced a whole string or a different number literal
  (fail closed). The restored value is charged to the restore budget as usual. In a stream
  the `"` before a possible placeholder is held back with it. If distinct object keys mask to the same key (including
  case or Unicode variants), the request fails closed with `400 invalid_request`, at any
  nesting depth. No values are merged or silently dropped, and nothing is forwarded
  (LAB-1568).
- **check**: an identifier or enum-like setting that can't carry a placeholder. Detected
  personal data rejects the request (`400 unsupported_content`); otherwise it is forwarded
  unchanged. The API's own words (`auto`, `function`, `json_schema`, ...) are not checked.
  Numbers with at least six digits in a checked value, and JSON-Schema keyword numbers
  (`maximum`, `minLength`, ...), are checked the same way.
  The traffic log keeps a checked `model` only after the check passed (the outbound re-check
  ran clean): a refused, blocked or failed call records `"[withheld]"` in the event's `model`,
  and in the `full` original (LAB-1358).

**Chat line-number gutters.** Message content, text/refusal content parts and the string
fields `refusal`, `reasoning_content` and `reasoning` share the Responses gutter handling:
a leading line number and pipe (e.g. `12|`, including indentation) become same-length spaces
for detection, preserving offsets. Gutters are restored in masked text when line counts
match and the replacement spaces survive; when masking spans lines and changes the line
count, gutters are dropped rather than writing any original text back. A prefix counts as a gutter
only inside a run of at least two adjacent lines whose numbers go up by exactly one (`11|`,
`12|`), as `read_file` and `cat -n` print them; a lone `1234567|...` line (a pipe-delimited
table row with an id), decreasing numbers or numbered lines that aren't adjacent stay visible
to detection and to the outbound re-check (LAB-1583). Residual: a table whose row ids are
themselves consecutive integers is still read as numbered lines.

**Declared tool names.** A tool or namespace name the request declares (`tools[].name`,
`tools[].function.name`, `functions[].name`, ...) is the client's vocabulary: a `PERSON`,
`ORGANIZATION` or `ADDRESS` detection whose whole value is a declared name is dropped **in
identifiers only** ("Muse" read as a person, LAB-1299/LAB-1317/LAB-1324). The same value in
message prose or any other masked text is masked as usual (LAB-1563: a declared name is
client-controlled and must not suppress prose detections). No other type
is exempt: a value found by format or checksum (a tax ID, an IBAN, ...) is masked wherever it
appears, and a tool named after one is `400 unsupported_content` (LAB-1348). Values the operator
pre-loaded (`known`) are never exempt.
- **pass**: numbers, booleans and null only (strings are `400 invalid_request`), or an opaque
  provider-issued blob forwarded untouched.

| Where | Key | Treatment |
| --- | --- | --- |
| body | `model` | check (non-empty string, required; LAB-1563) |
| body | `messages` | per message, below (non-empty array, required) |
| body | `temperature`, `top_p`, `n`, `max_tokens`, `max_completion_tokens`, `presence_penalty`, `frequency_penalty`, `seed`, `logprobs`, `top_logprobs`, `stream`, `parallel_tool_calls`, `store`, and the extension knobs `top_k`, `min_p`, `repetition_penalty` | pass |
| body | `reasoning_effort`, `service_tier`, `verbosity`, `modalities`, `stream_options`, `audio`, `tool_choice`, `function_call` | check (every string and key) |
| body | `user`, `safety_identifier`, `prompt_cache_key` | mask |
| body | `stop` (string or array of strings) | mask |
| body | `prediction` | `type` check; `content` mask (string or text parts) |
| body | `web_search_options` | `search_context_size` check; `user_location` mask JSON |
| body | `logit_bias` | keys must be token ids, values numbers |
| body | `metadata` | keys check; values mask JSON |
| body | `tools`, `functions` | definitions: `name` and other keys check; `parameters`/`schema` walked as JSON Schema (free text masked, `properties` keys and `required` entries checked, `type`/`$ref`/`format`/... **values** checked, LAB-1563); a custom tool's `format.grammar.definition` mask, its other `format` leaves check; every other string, array or direct numeric leaf mask JSON (e.g. an MCP tool's `server_description`); entries must be objects |
| body | `response_format` | `type` check; `json_schema` as a definition |
| message | `role` | one of `system`, `developer`, `user`, `assistant`, `tool`, `function` |
| message | `content` | string mask (line-number gutters hidden during detection, restored when forwarding); array of content parts, below; applies to every role, including tool/function output |
| message | `refusal`, `reasoning_content`, `reasoning` | mask (strings use the same gutter treatment; a non-string value: mask JSON) |
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

## Responses API (implemented)

`POST /v1/responses` is the gateway for clients that speak the OpenAI **Responses API**, such
as Muse Code (docs/integrations/muse-code.md). It gives the same guarantees as
`/v1/chat/completions` and uses the same headers (`X-PII-Guard-Mode`, `-Language`, `-Session`,
`-Echo`), session resolution, detectors, cache and vault (`pii_guard.gateway.responses`). The masked body goes to
the upstream's own `{PII_GUARD_UPSTREAM_BASE_URL}/responses` (a `/chat/completions` suffix is
dropped first). Nothing is translated to Chat Completions: an upstream that answers that path
with 404 or 405 gets **`501 responses_unsupported`**. Other upstream errors keep their status
and only the upstream's `type`/`code` tokens, never its message.

**Request fields.** These are walked against an allow-list (`pii_guard.gateway.responses_request`),
with the treatments of the table above. Any other key, item type or part type is
`400 unsupported_content`, and nothing is forwarded.

| Where | Key | Treatment |
| --- | --- | --- |
| body | `model` | check (non-empty string, required; LAB-1563) |
| body | `input` | a string (mask), or a non-empty array of items, below (required) |
| body | `instructions` | mask |
| body | `temperature`, `top_p`, `top_logprobs`, `max_output_tokens`, `max_tool_calls`, `parallel_tool_calls`, `store`, `stream`, `background` | pass |
| body | `reasoning`, `include`, `tool_choice`, `truncation`, `service_tier`, `stream_options` | check |
| body | `user`, `safety_identifier`, `prompt_cache_key` | mask |
| body | `metadata`, `client_metadata` (Codex's per-turn ids) | keys check; values mask JSON |
| body | `text` | `verbosity` check; `format` (`type`, `name`, `schema`, `description`, `strict`) as a definition |
| body | `tools` | `function` and `custom` tools as definitions (as for chat, including a custom tool's `format.grammar.definition` mask); `namespace` tools: `name` check, `description` mask, `tools` (function/custom only) walked; hosted tools (`web_search`, `file_search`, `mcp`, ...) `400` |
| body | `previous_response_id`, `conversation`, `prompt` | `400`: server-side state would hold another vault session's placeholders; send the whole `input` with `store: false` |
| every item | `type`, `id`, `call_id`, `status`, `phase` | check |
| `message` item (or `{role, content}` without `type`) | `role` | one of `system`, `developer`, `user`, `assistant` |
| `message` item | `content` | string mask; or parts: `input_text`/`output_text` (`text` mask, `annotations`/`logprobs` mask JSON), `refusal` (`refusal` mask); `input_image` with an inline PNG/JPEG data URL `image_url` (masked image, `detail` check; `file_id` or remote URL `400`); `input_file`/`input_audio` `400` |
| `function_call` item | `name` check; `arguments` | as a chat tool call's `arguments` (JSON parsed, mask JSON, re-serialised) |
| `function_call_output` item | `output` | string mask, or text and `input_image` parts as above |
| `custom_tool_call` item | `name` check; `input` | mask |
| `custom_tool_call_output` item | `output` | as `function_call_output` |
| `reasoning` item | `summary[]` (`summary_text`), `content[]` (`reasoning_text`) | `text` mask |
| `reasoning` item | `encrypted_content` | pass (opaque, provider-encrypted) |
| other items (`item_reference`, `web_search_call`, ...) | | `400` |

A **line-number gutter** at the start of a line of message text or tool output (`12|`, as Muse
Code's `read_file` prints files) is shown to the detectors as spaces of the same length and
kept in the forwarded text, so the first word of the line is detected on its own. The same
handling, and the same rule for what counts as a gutter (only runs of consecutive line
numbers, see "Chat line-number gutters"), applies to `instructions` and to reasoning
`summary_text`/`reasoning_text` parts (LAB-1583).

**Restore.** In a whole `response` object, every string the upstream returns is restored
(output text, refusals, reasoning summaries, and the request fields it echoes back).
`arguments` get JSON-escaped values, as chat tool-call arguments do. `encrypted_content` is
left as is. `X-PII-Guard-Unresolved` counts unknown placeholders.

**Regex-escaped placeholders in tool input** (both APIs, whole and streamed; LAB-1481). A model with
only a shell tool may write a placeholder escaped for a `sed`/`perl`/`python` pattern:
`\[\[EMAIL_x\]\]` (or `\[\[EMAIL_x]]`). In custom tool `input` that form, and in `arguments` the
same form JSON-encoded (`\\[\\[EMAIL_x\\]\\]`), is restored to the value as a regex literal, so the
command still matches the file: `.*[]^$/\` get a backslash and `+?(){}|@` are bracketed (`[+]`),
which is literal in BRE, ERE, Perl, PCRE, Python and JS alike (`\+` and `\(` are operators in GNU
`sed`, and Perl interpolates `@name`). Nothing else changes: message text keeps an escaped
placeholder as written; other escape depths (`\\[\\[` in freeform input, an escape after a
backslash) are left; an unknown or other session's placeholder stays as written and is counted as
unresolved; the restored value is charged to the response's restore budget.

**Shell quoting in command arguments** (both APIs, whole and streamed; LAB-1483, LAB-1564). A restored
value is byte-exact, except in one context the gateway reads for sure: the string value of a top-level
`command` or `cmd` key in JSON `arguments` (or the script after `-c`/`-lc` in a `command` array),
read by a small shell lexer. There a value restored inside a single-quoted string gets `'` written
as `'\''`; inside the single-quoted script word of a `sed` command, in an `s` replacement, `\`, `&`,
the delimiter and a newline also get a backslash (an escaped placeholder in an `s` pattern also gets a
delimiter backslashed that the regex literal leaves as is); inside a double-quoted string, `$`,
backtick, `"` and `\` get a backslash (a newline is already literal there); unquoted, every shell
metacharacter and whitespace gets a backslash (a newline goes in as a single-quoted segment). So a
restored value can never act as shell syntax — no command or parameter substitution, word splitting
or extra commands. Then it is JSON-escaped as usual. So `echo '[[PERSON_x]]'` with `O'Brien Teszt`
and `sed 's/x/[[ADDRESS_x]]/'` with `Fő utca 1/A` run as meant. Custom tool `input` gets the same
escaping **inside quotes only**: freeform input may be a patch or program text, so an unquoted
placeholder there stays byte-exact, while one inside single or double quotes (or a single-quoted
`sed` script) is escaped for that quoting. **Limitation:** everywhere else the value stays byte-exact:
a heredoc, `$'...'`, a comment, command substitution inside double quotes, a nested or argv-array
command, another `sed` command or a bracket expression are not modelled by the lexer. Other keys,
message text and file content are never touched.

**Encoded placeholder brackets in tool input** (both APIs, whole and streamed; LAB-1564). In
`arguments` and custom tool `input` a placeholder whose brackets are `\uXXXX`-escaped
(`\u005b\u005bEMAIL_x\u005d\u005d`) or `%XX`-encoded (`%5B%5BEMAIL_x%5D%5D`), with each bracket in
either form or literal, is also restored to the plain value (through the same shell/JSON escaping
as a plain placeholder); an unknown one stays as written and counts as unresolved. Message text
keeps encoded forms as written.

**Streaming** (`stream: true`). The `response.*` events keep their `event:` lines. Each delta
stream has its own streaming unmasker, keyed by `output_index` plus `content_index` or
`summary_index`: `response.output_text.delta`, `response.refusal.delta`,
`response.function_call_arguments.delta` (JSON-escaped), `response.reasoning_summary_text.delta`,
`response.reasoning_text.delta` and `response.custom_tool_call_input.delta`; an unmodelled event
type ending in `.delta` with a string `delta` gets the same treatment, keyed by its own type and
indexes (LAB-1564). A placeholder split across deltas is held back until it is complete. When the
stream's `.done` event arrives (or the stream ends), what is held back goes out as one more delta
event just before it, so the joined deltas equal the restored `.done` text. Every other event
(`response.created`, `response.output_item.added`/`.done`, `response.content_part.*`,
`response.completed`, ...) is restored whole. The shared restore budget is charged once per logical
text: a whole copy of text already charged as deltas (the `.done`, item-done and
`response.completed` repetitions) does not charge again, while any new text charges normally
(LAB-1564). A chat chunk with `error: null` streams normally; only a truthy `error` is fatal.
`sequence_number` is renumbered so it stays strictly increasing. An upstream
`error` event becomes `{"type": "error", "code": "upstream_error", ...}`, and
`response.failed` keeps its status with a generic `error`. `data: [DONE]` is passed on.

**Echo.** `X-PII-Guard-Echo: masked` works on non-streamed calls: the answer gets
`pii_guard: {masked_input: [{role, content}], masked_output: [{index, content}]}` (placeholders
only). With `stream: true` the header is `400 invalid_request`.

**`GET /muse-code/models`** is Muse Code's catalog, served at the gateway root. With
`PII_GUARD_UPSTREAM_MODELS` set, it is those ids. Otherwise it is the upstream's
`{scheme://host}/muse-code/models` with only `id`, `object`, `created`, `owned_by` and
`metadata["muse-code"]` kept per model. On a 404 it is `GET /v1/models` with default client
settings (`tool_call`, text in and out, a 128k context). Upstream errors keep their status
(5xx becomes 502), never their message.

## Messages API (implemented)

`POST /v1/messages` is the gateway for clients that speak the Anthropic **Messages API**, such
as Claude Code (docs/integrations/claude-code.md, LAB-1605). It gives the same guarantees as
`/v1/chat/completions` and uses the same headers (`X-PII-Guard-Mode`, `-Language`, `-Session`,
`-Echo`), session resolution (an `x-api-key` alone does not derive an identity: such clients are
`anonymous`; per-key isolation is a follow-up, LAB-1643), known values, outbound re-check, detectors, cache and vault
(`pii_guard.gateway.messages`). The masked body goes to the upstream's own
`{PII_GUARD_UPSTREAM_BASE_URL}/messages` (a `/chat/completions`, `/responses` or `/messages`
suffix is dropped first; `https://api.anthropic.com/v1` is the Anthropic API). Nothing is
translated to Chat Completions: an upstream that answers that path with 404 or 405 gets
**`400 unsupported_api`** (with `x-should-retry: false`). Other upstream errors keep their
status in the Anthropic error shape (`{"type": "error", "error": {"type", "code":
"upstream_error", "message"}}`) with only the upstream's error `type` token
(`overloaded_error`, `rate_limit_error`, ...), never its message.
`POST /v1/messages/count_tokens` masks the same body the same way, forwards it to
`.../messages/count_tokens` and answers only `{"input_tokens": n}`.

**Upstream headers.** A configured `PII_GUARD_UPSTREAM_API_KEY` is sent as `x-api-key` (no
`Authorization`). Without one, the client's own `x-api-key` and `Authorization` are passed
through. `anthropic-version` (default `2023-06-01`) and the `anthropic-beta` tokens are passed
on when they are plain tokens (`[A-Za-z0-9._-]`); other client headers are not.

**Request fields.** Walked against an allow-list (`pii_guard.gateway.messages_request`), with
the treatments of the chat table. Any other key, block type or tool type is
`400 unsupported_content`, and nothing is forwarded.

| Where | Key | Treatment |
| --- | --- | --- |
| body | `model` | check (non-empty string, required) |
| body | `messages` | non-empty array of `{role: user\|assistant, content}` (required) |
| body | `system` | string mask, or `text` blocks |
| body | `max_tokens`, `stream`, `temperature`, `top_k`, `top_p` | pass |
| body | `thinking`, `tool_choice`, `context_management`, `service_tier`, `output_config` | check |
| body | `stop_sequences` | mask |
| body | `metadata` | `user_id` mask (Claude Code sends a JSON string of its ids) |
| body | `tools` | client tools (no `type`, or `custom`): `name` check, `description` mask, `input_schema` as a JSON Schema (as chat `parameters`), `defer_loading`/`strict` pass, `cache_control` check; server tools (`web_search_*`, `code_execution_*`, ...) `400` |
| body | `mcp_servers`, `container` | `400`: tools and state kept upstream act on data the gateway never sees |
| every block | `type`, `cache_control` | check |
| `text` block | `text` | mask (line-number gutters as for chat); non-empty `citations` `400` |
| `image` block | `source` | inline `base64` PNG/JPEG: the masked image (and, with placeholder labels, its transcript as a `text` block after it); `url`/`file` sources `400` |
| `tool_use` block | `id`, `name` check; `input` | mask JSON (every string, keys included, and long numbers), as chat tool-call arguments |
| `tool_result` block | `tool_use_id` check; `is_error` pass; `content` | string mask, or `text` and `image` blocks as above |
| `thinking` block | `thinking` mask; `signature` | pass (opaque, provider-signed; the masked text is what the model wrote, so it still matches) |
| `redacted_thinking` block | `data` | pass (opaque) |
| other blocks (`document`, `search_result`, `server_tool_use`, ...) | | `400` |

**Placeholder note.** When the masked body holds a placeholder, the note goes in front of
`system` (a first paragraph of a string, or a first `text` block; the client's `cache_control`
marks stay on its own blocks).

**Restore.** In a whole `message`, every string the upstream returns is restored (`text` and
`thinking` blocks, `stop_sequence`, ...). A `tool_use` block's `input` is serialised and
restored like chat tool-call `arguments` (JSON-escaped values, shell quoting in a `command`,
masked numbers back as numbers), then parsed again; one that no longer parses fails the call
(`502`, nothing half-restored). `signature` and `data` are left as is.
`X-PII-Guard-Unresolved` counts unknown placeholders.

**Streaming** (`stream: true`). Events keep their `event:` lines. Each `content_block_delta`
stream has its own streaming unmasker, keyed by block `index`: `text_delta.text`,
`thinking_delta.thinking` and `input_json_delta.partial_json` (JSON-escaped). A placeholder
split across deltas is held back until it is complete; at the block's `content_block_stop`
(or the end of the stream) what is held back goes out as one more delta just before it.
`signature_delta` passes through; every other event (`message_start`, `content_block_start`,
`message_delta`, `message_stop`, `ping`) is restored whole. An upstream `error` event becomes
`{"type": "error", "error": {"type": "api_error", "message": "upstream stream error"}}`; a
stream that fails inside the gateway ends with the same shape.

**Echo.** `X-PII-Guard-Echo: masked` works on non-streamed `/v1/messages` calls: the answer
gets `pii_guard: {masked_input: [{role, content}], masked_output}` (placeholders only). With
`stream: true` or on `count_tokens` the header is `400 invalid_request`.

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
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_restored_chars: int = DEFAULT_MAX_RESTORED_CHARS,  # 1_000_000, LAB-1350
    ) -> None: ...

    # PII_GUARD_TENANT_KEY (and the PII_GUARD_VAULT_* / PII_GUARD_UNMASK_MAX_RESTORED_CHARS
    # settings) from Settings.
    @classmethod
    def from_settings(cls, settings: Settings, **kwargs) -> Vault: ...

    # None -> a new session with a fresh random id ("s_" + 32 hex); an existing id -> that session.
    def session(self, session_id: str | None = None) -> VaultSession: ...

    # Get-or-create (LAB-1286): never SessionNotFoundError. -> (session, created). Once the
    # session holds max_entries placeholders (PII_GUARD_VAULT_MAX_ENTRIES), the id moves on to a
    # new, empty generation with a derived id; the returned session_id is then not session_id.
    def session_or_create(self, session_id: str) -> tuple[VaultSession, bool]: ...

    # "d_" + 32 hex of HMAC-SHA256(tenant key, material): stable per deployment, keyed.
    def derive_session_id(self, material: str) -> str: ...

    # Resolve (session, created, metadata) and acquire an LRU pin in one vault transaction.
    def acquire_session(
        self, resolve: Callable[[], tuple[VaultSession, bool, T]]
    ) -> tuple[VaultSession, bool, T]: ...
    def release_session(self, session: VaultSession) -> None: ...  # one per acquire

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

    # Replace known placeholders with their original values. Restored values are charged to
    # budget (default: a fresh restore_budget() for this call); past its limit, raises
    # UnmaskOutputTooLargeError (unmask_output_too_large, 413) before the output grows further.
    def unmask(self, text: str, *, budget: RestoreBudget | None = None) -> str: ...

    # Same, plus the placeholder-shaped tokens that are not in the mapping.
    def unmask_with_report(
        self, text: str, *, budget: RestoreBudget | None = None
    ) -> UnmaskResult: ...

    # A RestoreBudget at max_restored_chars, for one whole output: the gateway shares one
    # across every choice, field, tool call and stream chunk of a response.
    def restore_budget(self) -> RestoreBudget: ...

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
| `VaultNotConfiguredError` (`PiiGuardError`) | `vault_not_configured` | 503 | `Vault.from_settings` without `PII_GUARD_TENANT_KEY`. |
| `VaultCapacityError` (`MaskingError`) | `vault_capacity_exhausted` | 503 | Creating a session at capacity while all sessions are leased, or any gateway request (new or existing session) from an identity already at `max_leases_per_identity` leases. |
| `PlaceholderInInputError` (`MaskingError`) | `placeholder_in_input` | 422 | The text to mask holds a placeholder this session already issued. |
| `SessionEntryLimitError` (`MaskingError`) | `session_entry_limit_reached` | 409 | An explicit session already holds its `max_entries` placeholders; it is never rotated. |

Messages and `repr()`s carry types, counts and placeholder ids, never an original value.

`VaultSession.unmasked(texts, language)` (LAB-1500) lists every occurrence of a value the
session holds (its entries, their surfaces and aliases, and its known values) that is still
written out in `texts`, with the sweep's own patterns and guards; occurrences inside a
placeholder never count and overlapping ones count once. Each `Unmasked` has the text index,
offsets, entity type, the value's letter-and-digit count, `digits_only`, `model_only` and
`known`, never the value. Read-only: nothing is recorded. The gateway's outbound re-check is
built on it.

### Lifetime

- A session lives for `ttl_seconds` and the TTL is **sliding**: every use (mask, unmask,
  entities, `known_values`, `Vault.session(id)`) extends it. An expired session is closed and
  forgotten on the next access, and `Vault.purge_expired()` (also run by `session()` and
  `len(vault)`) drops all expired ones.
- `Vault.drop(id)` and `VaultSession.close()` forget the mapping and the known values at once;
  later calls raise `SessionNotFoundError`. The mapping never leaves the process, is never
  logged and has no persistence.

- Capacity eviction chooses only sessions without leases. `acquire_session(resolve)` holds
  the vault lock across lookup/creation and pin acquisition, closing the lookup-to-eviction
  race. Each successful acquire needs one `release_session(session)`, even if the session
  expired or was explicitly dropped in the meantime. Leases are counted per session object.
  The gateway holds its lease through detection, masking, upstream work, restoration and
  stream cleanup, releasing it on failures and cancellation as well as success.
- If every capacity slot is leased, creating another session fails closed with HTTP 503
  `vault_capacity_exhausted`; it neither exceeds the cap nor evicts an active session.
- An identity already holding `max_leases_per_identity` leases
  (`PII_GUARD_VAULT_MAX_LEASES_PER_IDENTITY`) is refused with the same 503 before lookup or
  creation, for an existing session as well as a new one, so one client can't pin every slot;
  other identities still acquire (LAB-1584).
  Leases do not suspend sliding TTL or explicit deletion/purge semantics.
- `VaultSession.commit(fork)` consumes the fork once and validates its entire journal against
  a private snapshot under the parent lock before publishing the state. A replay mismatch
  raises `MaskingError` and leaves all parent mapping, memo, count and generation state
  unchanged. The caller must discard the fork output on any commit failure.

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
  and the candidate lemmas' forms get the same placeholder (recall first). Before the vault sees
  them, the detection pipeline ends a whole-word PERSON span at its stem when the language pack
  reads it confidently (`pii_guard.detect.suffix_trim`, LAB-1174; Hungarian:
  `HungarianSuffixMatcher.confident_split`), for every detector: `Kerekes Ottótól` →
  `[[PERSON_x]]tól`. Confident means the lemma's last word is a lexicon name and the surface's
  is not (`Ottó` + `tól`, `Béla` + `t`), or the ending can't end a name (`Tihamérnak`,
  `Szabolccsal`); `Márton`, `Kornél` and `Simon` stay whole. `/v1/analyze` returns the trimmed
  span.
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
- **Case-sensitive types** (`CASE_SENSITIVE_TYPES`, LAB-1350): `SECRET` only (tokens, API
  keys, passwords, private keys, URL passwords). Letter case is part of a credential, so a
  `SECRET` is keyed by its exact value (up to whitespace, invisible characters and Unicode
  form): `AbC…1` and `aBc…1` are two secrets with two placeholders, both modes, and an
  occurrence in another case is not masked with the confirmed secret's placeholder (the
  detector decides about it on its own). Every other type is case-insensitive as below:
  names and other natural-language values (with their inflection), and IBANs, plates, ID
  numbers and email addresses, which are case-insensitive by their own rules.
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
- A matcher that only has `suffix_pattern` keeps exact-stem behavior; call the module
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
stem-changing form is labeled as the whole word (`Minta Annának`). Every value is fictional
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

The JSON scorecard (`schema_version` 1) has `meta` (commit, dirty flag and `dirty_paths`,
version, detectors, skipped detectors, language filter, fixture paths with SHA-256), `overall` and `languages`
(one block per language). A block holds `detection.{exact,overlap}.{per_type,micro,macro}`,
`leak`, `over_masking` (both with `per_type`), `roundtrip` and `latency_ms`. It never
contains document text or labeled values.

## Hosted boundary (implemented, opt-in)

`PII_GUARD_HOSTED=true` opts into a separate security boundary. Local behavior is unchanged.
Startup requires a 32-byte tenant key, an HTTPS `HOSTED_PUBLIC_ORIGIN`,
`HOSTED_TRUST_EASY_AUTH=true` and `HOSTED_SINGLE_PROCESS=true`. These last two settings are
operator assertions: Azure Easy Auth must strip/replace identity headers on the only ingress
path, and the deployment must run exactly one worker and one replica without overlapping
revisions. Setting a flag does not secure a directly accessible application origin.
Google's stable subject claim, never email, establishes ownership. Account linking is not
implemented. Invalid identity headers or invalid guard keys fail closed; they do not become
guests. Guard authorization and platform identity headers are removed before downstream calls.

Only `/v1/account` and the curated `/v1/demo` are anonymous API routes. Landing/static assets
and health probes remain public. Other data routes require Google identity or an owned guard
API key. Hosted mode serves `/v1/status` and `/v1/connect/snippets` only to signed-in Google
principals, as owner projections (ADR 0013, [`GET /v1/status`](#hosted-projection)), and
refuses docs/OpenAPI, metrics, image masking and audit detection. Cookie-authenticated mutations require `Origin` to equal
`HOSTED_PUBLIC_ORIGIN`; cross-site requests are rejected. Responses use `Cache-Control: no-store`.
The host-prefixed guest cookie is signed, Secure, HttpOnly, SameSite=Strict and lasts one hour.
A new/expired cookie creates a different guest, with global quotas bounding cookie rotation.

`PII_GUARD_HOSTED_CLIENT_IP_SOURCE=off` (default) leaves anonymous network admission
disabled. The opt-in `aca_xff_rightmost` source is valid only behind verified direct Azure
Container Apps ingress: it uses the ACA-appended rightmost `X-Forwarded-For` address.
One header, at most 2048 ASCII bytes and 32 valid IP hops, is required for anonymous
`POST /v1/demo`; duplicate, missing or malformed signals return 503
`abuse_signal_unavailable` before the body is read. There is no first-hop, `Forwarded`,
`X-Real-IP` or socket-peer fallback. Forwarding address headers are removed from the
downstream application scope. This does not configure platform or server access logging.

Secondary admission immediately HMACs each normalized IPv4 address or IPv6 /64 with a
random process-only key; mapped IPv4 uses the same bucket as IPv4. Its bounded in-memory
tables hold digests and counters/timestamps only. Each table holds at most 4096 entries,
with one-hour idle and 24-hour absolute expiry; a full table evicts its least recently used
bucket once it has been idle for five minutes (a fully refilled burst), and otherwise
refuses new entries without evicting live allowances. Anonymous sponsored demo requests
share a 30-request network burst, refilling 30/minute, and 120 requests per fixed hour
starting at bucket creation. Each request also charges its aggregate (IPv4 /24, IPv6 /48):
a 120-request burst refilling 60/minute and 480 requests per fixed hour, tracking at most
64 networks, so one allocation cannot fill the network table or multiply its allowance.
Guest cookie rotation does not reset that network allowance. Authenticated principals
have separate 10-request work bursts refilling 30/minute, independent of network usage and
without requiring an address signal, plus a separate read bucket (120 burst, 10/s) for
`GET`/`HEAD`. `/v1/account` (every method) is never charged; sign-in remains reachable.
Secondary charges happen after identity/path/origin validation, before body reads, and
survive downstream failure. Clock/accounting failure refuses admission.

Burst or capacity exhaustion returns 429 `abuse_throttled` with `Retry-After` seconds:
the wait for the slowest refusing level, or until a full table's first slot can free.
Anonymous hourly exhaustion returns 429 `sign_in_required`, `Retry-After` until the hour
ends and a message directing Google sign-in or the free walkthrough. Sign-in never
replenishes global requests, tokens, daily spend or the finite sponsored allocation.
There is no external CAPTCHA or claim of bot-proof protection. Keep the address source
off until deployed ingress spoof/header and logging checks pass (see
[operations.md](operations.md#hosted-secondary-abuse-admission)).

Each owner has a separately HMAC-derived vault key, bounded vault, detection cache, session
coordination, masked traffic log and inspector directory. Identical caller-chosen session IDs
never cross an owner boundary. Detectors are shared, with globally bounded compute workers
(including work whose HTTP caller has timed out). Active requests pin their runtime through
stream completion/cancellation; inactive runtimes expire after one hour. A 30-second cleanup
loop forgets expired state. Session capacity refuses new sessions rather than evicting active
ones. Runtimes are taken only by routes that use one: no `/v1/account` method, no `OPTIONS`
request and no key or connection management route takes one, and a guest takes one only for
`POST /v1/demo`. Guests draw on a separate pool (`HOSTED_MAX_GUEST_RUNTIMES`, default 8),
so anonymous traffic never occupies a signed-in owner's runtime, and a guest's runtime is
dropped as soon as its demo finishes. Defaults: 256 signed-in runtimes, 20 sessions per
owner, 256 cached detections, 50 masked traffic events; the owner's traffic log scrubs the
provider key a request may send (sponsored or the selected connection's). Full vault reveal is never available. All state is ephemeral; restart loses mappings,
connections and guard API keys. Durable multi-replica state is deferred to LAB-1376.

### Account and credentials

`GET /v1/account` returns:

```json
{"mode":"hosted","authenticated":false,"principal":null,"login_url":"/.auth/login/google","logout_url":"/.auth/logout","tier":"anonymous","providers":["meta","openai","fireworks","openrouter","custom"],"included_model":"muse-spark-1.3","limits":{"requests_per_day":5,"tokens_per_day":100000,"concurrent_requests":2,"max_output_tokens":8192,"sponsored_enabled":false},"usage":{"requests_today":0,"tokens_today":0,"resets_at":"2026-10-29T00:00:00+00:00"},"state":{"persistence":"ephemeral","restart_loses_sessions":true},"connections":[]}
```

`included_model` is the model free runs answer with (the first of `PII_GUARD_HOSTED_MODELS`), so
the public page names it from the API. Authenticated `principal` is `{id,provider:"google"}` with an
opaque ID; tier is `standard`.
The account remains readable when quota is exhausted. Key and connection management
(`/v1/account/api-keys*`, `/v1/account/connections*`) requires a signed-in Google session:
a guard API key gets `401 unauthorized`, so a leaked key cannot mint successors that
outlive its revocation. `POST /v1/account/api-keys {name}`
returns 201 `{id,name,key,prefix,created_at}`; only that response contains the raw key.
`GET /v1/account/api-keys` returns metadata arrays; `DELETE /v1/account/api-keys/{id}` returns
204 and revokes future use. Keys last 24 hours, at most five per owner and 1000 globally;
only SHA-256 verifiers are stored. Send a guard key as `Authorization: Bearer <key>` or
`X-PII-Guard-Token`; it is never an upstream credential.

`POST /v1/account/connections {provider,api_key,base_url?}` returns 201
`{id,provider,origin,expires_at}`; delete the same owner-scoped resource with
`DELETE /v1/account/connections/{id}` (204). At most five profiles per owner and 256 globally,
with a fixed one-hour expiry. Secrets stay in server memory and never appear in metadata.
Select one immutable connection explicitly using `X-PII-Guard-Connection` on chat, Responses
or model catalogs. No selection means sponsored Meta. An unknown, deleted, expired or
another owner's connection fails, never falls back to sponsored. Already admitted requests
may finish with their selected connection after deletion. Supported presets are Meta,
OpenAI, Fireworks and OpenRouter; custom connections require public HTTPS on port 443.

`POST /v1/account/first-run {issue_key?,meta_api_key?}` (LAB-1455, signed-in Google session
only; a guard key gets `401`) provisions the owner's default endpoint once and describes it:
`{project_id,endpoint,state,created,active_keys,key,sponsored_enabled,gateway_url}`. When the
default project has no endpoint it creates `Default endpoint` on the sponsored route with the
first allow-listed model and the default policy version; otherwise it creates nothing and
describes the oldest enabled endpoint. `state` is `ready`, `needs_key` (sponsored while
sponsorship is unavailable) or `disabled`. `issue_key: true` issues one endpoint key, returned
raw only in that response, while the endpoint has no active key. `meta_api_key` converts a
`needs_key` sponsored default endpoint, in place, to an own-key `meta` endpoint on
`https://api.meta.ai/v1` (same id, model and policy); any other endpoint gets `422`. The key is
checked for shape first (LAB-1463): surrounding whitespace is dropped, and anything that is not
one token of 20 to 4096 printable ASCII characters without spaces, quotes or `://` is refused
with `422 invalid_provider_key` before anything is saved, so the endpoint stays `needs_key` and
never falls back to sponsored inference. The message names the expected shape, never the value.
This is a format check only; no provider call verifies the key on save. The
operation is one atomic store update (a single conditional write on the Blob store, re-read and
retried up to three times after a conflict), so repeat sign-ins and concurrent first requests never create a second
endpoint. It spends no daily request or token budget and takes no runtime.

### Projects, policies and endpoints

The project store persists configuration in local SQLite or hosted authenticated encrypted
Azure Blob snapshots (see [projects.md](projects.md#hosted-encrypted-blob-snapshots)). Blob
operations use fresh bounded in-memory SQLite state and conditional ETag commits; storage
failures and conflicts return sanitized 503 without automatic replay or local fallback. Hosted
management requires the authenticated Google owner. Self-hosted management uses the single
`local-owner`, protected by the configured API token or trusted loopback access. The first
listing/request for an owner atomically creates a default project with the deployment's default
policy. `X-PII-Guard-Project` selects a project for owner-scoped data routes; on vault, session,
unmask and traffic inspection routes, `X-PII-Guard-Endpoint` may further select an endpoint
namespace. Duplicate selection headers fail closed. Without a selection, existing local
single-owner routes keep their default namespace.

| Method and path | Request | Response / behavior |
|---|---|---|
| `GET /v1/projects` | — | `{projects:[...],default_project_id}`; creates the default if needed |
| `POST /v1/projects` | `{name}` | 201 project metadata; maximum 32 projects per owner |
| `GET /v1/projects/{project_id}` | — | Owned project metadata, including `default_policy_version_id` (the default policy's latest version) |
| `GET /v1/projects/{project_id}/policies` | — | `{policies:[...]}`; every immutable version |
| `POST /v1/projects/{project_id}/policies` | `{name,entity_policies?,language?,mode?,detection_profile?,visual_detection?}` | 201 first version in a new policy family |
| `PUT /v1/projects/{project_id}/policies/{policy_id}` | Same policy fields | 201 next immutable version; existing endpoints remain pinned |
| `GET /v1/projects/{project_id}/policies/versions/{version_id}` | — | Exact policy-version snapshot |
| `GET /v1/projects/{project_id}/endpoints` | — | `{endpoints:[...]}`; credentials are never returned |
| `POST /v1/projects/{project_id}/endpoints` | `{name,provider,policy_version_id,model?,base_url?,api_key?,enabled?}` | 201 endpoint metadata; maximum 128 per project. `model` is `null` for a pass-through endpoint |
| `POST /v1/projects/{project_id}/endpoints/models` | `{provider,base_url?,api_key?,endpoint_id?}` | `{models:[id,...]}` for the endpoint form: the provider's `GET /models` asked with `api_key` (never stored) or, without it, `endpoint_id`'s stored key (same provider and base URL only, else 422); `sponsored` returns the hosted allow-list. No key is 422; a provider 401/403 is `502 upstream_credential_rejected` ("check the API key"); any other provider failure is a generic `502 upstream_unavailable` |
| `PUT /v1/projects/{project_id}/endpoints/{endpoint_id}` | Complete endpoint fields; `api_key` may be omitted to keep current credential | Updated metadata; explicit `policy_version_id` required. `enabled:false` atomically revokes active keys; re-enabling does not restore them |
| `DELETE /v1/projects/{project_id}/endpoints/{endpoint_id}` | — | 204; permanently deletes endpoint and all its key records |
| `GET /v1/projects/{project_id}/endpoints/{endpoint_id}/keys` | — | `{keys:[id,name,created_at,revoked_at]}`; no raw keys |
| `POST /v1/projects/{project_id}/endpoints/{endpoint_id}/keys` | `{name}` | 201 key metadata plus raw `key`, returned once; maximum 32 active and 128 retained records per endpoint |
| `DELETE /v1/projects/{project_id}/endpoints/{endpoint_id}/keys/{key_id}` | — | 204; revokes future admissions |

Policy versions capture a complete text- and visual-entity action map, language, detection mode
and image detection. Omitted entity actions use deployment defaults. Text entities accept
`mask`, `keep` or `block`; visual entities (`FACE`, `ID_PHOTO`, `SIGNATURE`, `STAMP`) accept
`mask` or `keep` (LAB-1444). Unknown entities and extra fields are rejected with sanitized
validation messages. Hosted policies require `fast`; self-hosted policies must use the
deployment's detection profile, and `local-only` refuses `audit`. A policy revision appends a
version and never mutates a prior version or silently changes endpoint pins. A project can
contain up to 256 policy versions.

`visual_detection` chooses who finds visual regions for a selected project policy's images:

- `local` (default): on the CPU only. YuNet finds faces and ID photos, and the pinned YOLOS-tiny
  signature detector (`mdefrance/yolos-tiny-signature-detection` at a fixed revision,
  Apache-2.0, safetensors, every file SHA-256 checked; `python -m pii_guard.visual.segmenters
  fetch`) finds signatures, on the whole image and 2x2 overlapping tiles. No SAM request is
  made. Stamps cannot be found locally: a `local` policy that masks `STAMP` refuses images.
  `analysis.sam.model` is `yunet-2023mar+yolos-tiny-signature` once signatures were asked for.
- `sam`: the server's segmenter (`PII_GUARD_SEGMENTER`, `hybrid` by default: SAM 3.1 on the Meta
  API for signatures and stamps, so the original image leaves the machine). A server set to
  `local` or `off` is stricter and wins. `local-only` deployments and the hosted service accept
  `local` only (`422 invalid_project_config`).

Versions saved before LAB-1444 have no visual actions and no `visual_detection`: they read as
`local` with the server's visual actions. For visual types, an explicit
`PII_GUARD_POLICY_OVERRIDES` entry wins over the policy when it is stricter (`keep` < `mask` <
`block`). Requests without a selected project use the server's policies and segmenter, as
before.

An endpoint pins one policy version and one provider/upstream/credential tuple, and optionally
one model (LAB-1451). Providers
are `meta`, `openai`, `fireworks`, `openrouter`, `custom`, and hosted-only `sponsored` Meta.
Preset providers use their fixed base URL. `custom` requires a base URL. Hosted destinations
must pass the public HTTPS port-443 and DNS validation; local/self-hosted destinations accept
HTTP or HTTPS, including loopback, and reject embedded URL credentials, queries and fragments.
New BYOK endpoints require an API key; on edit, omitting `api_key` preserves the current key.
Provider credentials are encrypted in SQLite and omitted from all endpoint metadata. Sponsored
endpoints store no credential and require an allowlisted hosted model: an empty or
non-allowlisted `model` is `422 invalid_project_config`.

**Endpoint model: pinned or pass-through.** With a `model`, the endpoint is pinned: gateway
requests get that model injected and any other `model` fails closed with `403`. BYOK endpoints
(`meta`, `openai`, `fireworks`, `openrouter`, `custom`) may omit `model` (or send `null` or
`""`): the endpoint is pass-through, metadata reports `model: null`, and the client's own
`model` is forwarded unchanged, so agent harnesses (Codex, Muse Code, OpenCode, Claude Code)
can choose theirs. A pass-through request without a non-empty string `model` (at most 256
characters, no control characters) is `400 invalid_request`, before anything is sent. Storage:
pass-through is `''` in the existing `model TEXT NOT NULL` column, so the SQLite schema and
every existing local store or blob snapshot are unchanged and load as is; existing rows keep
their pinned model. A build from before LAB-1451 reading a pass-through row fails closed (it
refuses every client `model`).

Endpoint gateway URLs are `/e/{endpoint_id}/v1/chat/completions`,
`/e/{endpoint_id}/v1/responses`, and `/e/{endpoint_id}/v1/models`. Send the endpoint key as a
Bearer credential. `/models` lists only the pinned model for a pinned endpoint (the provider is
not asked) and, for pass-through, the provider's own catalog asked with the endpoint's stored
credential (`id`, `object`, `created`, `owned_by` only; a provider failure is a generic
`502 upstream_unavailable`; hosted, through the public-HTTPS egress client). These routes accept
only that endpoint's configured model (when pinned), language, mode,
upstream and policy version; caller overrides fail closed. Endpoint keys cannot call owner,
account, management, traffic or vault routes. A revoked key or disabled endpoint rejects new
admission; an already admitted call uses its captured endpoint/policy/credential snapshot and
may finish. Disabling an endpoint atomically revokes all active keys while preserving its
configuration; re-enabling it leaves those keys revoked. Deleting an endpoint permanently
removes its configuration and key records. At most 32 keys remain active per
endpoint; the store can retain at most 128 records and prunes the oldest revoked records to
enforce that bound. A global 65,536-record cap also applies. Hosted vault/session capacity is
shared across all of an account's project and endpoint namespaces (20 sessions by default).
Hosted request, token, concurrency and sponsored accounting remains account/global and does
not multiply with project count.

### Curated demo

`POST /v1/demo {sample_id,language?}` accepts `hu-support` or `en-support`; an optional
language must match the sample. Extra properties, caller text/model, connection selection
and session/mode overrides are refused. Only server-owned fictional scenarios reach detection
and the upstream. The result is `{sample_id,language,original,masked,answer,restored,entities,
model,session_id,request_id}`, where `answer` is the masked upstream response and `entities`
is an array of `{start,end,type}` referring to the original. No partial result is returned on
failure or an empty model answer. The static UI walkthrough remains available without budget.

### Admission, cost and egress

Every signed-in mutation and data request (any method but `GET`, `HEAD` and `OPTIONS`) and a
guest's `POST /v1/demo` require atomic admission before detector/provider work. Reads (`GET`,
`HEAD`, including the console's polling of `/v1/traffic` and `/v1/status`) spend no daily
request or token budget and hold no inference concurrency; the per-owner read bucket above
bounds them. `/v1/account` is never admitted. Defaults are five guest or 100 standard
requests per UTC day, 100,000 guest or 1,000,000 standard reserved tokens, two active requests
per owner, eight globally, 10,000 requests and 10,000,000 tokens globally per day. Ingress
slots cover slow clients before parsed admission. A request takes one only after identity,
path, origin and abuse checks have passed, so a request refused by any of them never holds
one: 32 slots for signed-in principals (at most eight per principal, a guard key counting
as its owner) and a separate eight for guests (at most two per guest), `429 hosted_capacity`
beyond, never a queue. The slot is held from the body read to the end of the response. One
ten-second deadline from taking the slot bounds the whole body read, however it is
trickled (`504 hosted_timeout`, no quota charged). Endpoint-key lookup, the only wait
before identity is known, has its own pool of eight and reads no body. `GET
/v1/traffic/stream` gives its ingress slot back once admitted and holds a
stream slot instead: two per owner, sixteen in all (`429 hosted_capacity` beyond). Bodies are capped at 32 KiB; hosted
requests have a 180-second deadline, fast text detection, one completion and at most 8192
output/reasoning tokens. Sponsored models are an explicit server allowlist, initially
`muse-spark-1.3`; model selection cannot change the sponsored destination.

Reservations are sized from the request before work. The input charge is the upstream
payload bound `2 × body bytes + 4096` (in tokens: a byte-level tokenizer never emits more
tokens than bytes), and the gateway refuses with `413 payload_too_large`, before any upstream
call, a masked payload larger than that bound. The output charge is the request's own output
token limit (at most 8192; the default when it sets none), and 4096 for the curated demo.
`muse-spark-1.3` reasons before it answers and reasoning counts against that limit: measured
on 2026-10-28 (`eval/results/2026-10-28-lab-1372-meta-reasoning`), every demo-sized call at 512
tokens or fewer came back with empty content, and at 4096 every call answered (at most 2,994
completion tokens used). `PII_GUARD_HOSTED_MAX_OUTPUT_TOKENS` therefore cannot be set below
4096. A client may still ask for less and then gets an empty answer it is charged for. With
the defaults a guest gets its five demos (about 8,250 reserved tokens and $0.14 each) and a
fresh signed-in user can send a chat close to the 32 KiB body limit. Sponsored requests may not
ask for provider-side tools (`web_search_options`, or a `tools` entry other than `function` or
`custom`): Meta bills web search grounding per query, outside the token usage a reservation
bounds, so they are refused with `403 hosted_request_denied` before any work. Completion, cancellation, invalid provider responses and client retries never refund
requests, tokens or money. Concurrency releases only after the response stream and cleanup.
There are no automatic upstream retries. Monetary units are integer microdollars, and configured
per-token rates must upper-bound every permitted model and all reasoning charges. The rate
defaults have one source (`hosted/quotas.py`): 5 input and 30 output microdollars per token
(`HOSTED_INPUT_MICRODOLLARS_PER_TOKEN`, `HOSTED_OUTPUT_MICRODOLLARS_PER_TOKEN`). Reconciled on
2026-10-28 with Meta's published Standard price for `muse-spark-1.3` (USD 1.25 input and 4.25
output per million tokens, <https://dev.meta.ai/docs/pricing-rate-limits>; reasoning tokens are
reported inside `completion_tokens`, so they are charged at the output rate): the defaults are
4× and about 7× that, and also cover Muse Wonder (4.00 / 20.00). Re-check the page before
raising an allocation or adding a model to the allowlist. The global
daily ceiling is $10 and a finite allocation adds a stricter process-lifetime cap.

Sponsored calls default to disabled. Enabling them requires a positive reconciled allocation,
an expiry timestamp, unique allocation ID and an existing durable allocation directory.
Startup uses an atomic exclusive file claim, fsyncs it, and forfeits the entire allocation on
restart. Reusing an ID, missing storage, expiry or accounting failure disables sponsored work.
A new process/day cannot silently replenish spend authority. The operator must reconcile
provider spend before issuing another allocation; claims must never be removed or stored on
an ephemeral container filesystem. The kill switch is a file: with
`PII_GUARD_HOSTED_SPONSORED_KILL_SWITCH_PATH` set (an absolute path), creating that file
disables sponsored admission for the rest of the process. It is checked before every
sponsored admission and on each cleanup tick; any error other than a missing file also
disables it, and removing the file does not re-enable it. Restarting with the same allocation
also fails closed. No billing persistence or
cross-replica accounting is claimed.

All hosted upstream paths (chat, Responses and catalogs) share the secure transport: no URL
credentials, query, fragment, IP literal, local domain, non-HTTPS or non-443 endpoint; every
resolved A/AAAA address must be globally routable (NAT64 `64:ff9b::/96` and
`64:ff9b:1::/48` are refused, as are IPv4-mapped, 6to4 and Teredo addresses). At each new TCP connection DNS is checked
again and the connection uses a checked numeric address, preserving original Host and TLS
SNI/certificate verification. Redirects and environment proxies are disabled. A preflight DNS
check alone is not considered sufficient. Sponsored credentials only go to the fixed Meta
endpoint and never to a custom origin.
Successful upstream responses and complete SSE streams are limited to 2 MiB before buffering
or event parsing. Hosted requests explicitly ask for identity encoding and refuse compressed
responses, so a compressed payload cannot bypass the memory bound during decompression.
An over-limit stream ends with a sanitized stream failure and releases its admission permit.

### Durable sponsored allowance (opt-in)

The default `PII_GUARD_HOSTED_SPEND_STORE=marker` retains the one-use allocation claim above.
`azure_blob` selects a separate monetary-only allowance; it does not persist vault mappings,
owners, keys, connections or local request/token/concurrency quotas. Install the
`hosted-azure` extra. The configured storage account must use its public Azure Blob HTTPS
hostname, without SAS, URL credentials, paths, queries or fragments. Authentication uses
`ManagedIdentityCredential` only, optionally with
`PII_GUARD_HOSTED_SPEND_MANAGED_IDENTITY_CLIENT_ID`; no developer-login fallback exists.
`HOSTED_SPEND_ACCOUNT_URL`, `HOSTED_SPEND_CONTAINER` and `HOSTED_SPEND_ENVIRONMENT=dev|prod`
(all with the `PII_GUARD_` prefix) select one fixed `<environment>.json` blob. Dev/prod
resources and identities must be separate. The app never creates a blob or issues funds.

The operator pre-creates a private block blob of at most 4096 bytes with exactly these keys:

```json
{"version":1,"environment":"dev","allocation_id":"synthetic-approved","ceiling_microdollars":1000000,"expires_at":1900000000,"charged_total":0,"day":"2026-10-28","daily_charged":0,"enabled":false}
```

Integers are exact, not booleans or floats; unknown/duplicate keys, malformed dates, future
UTC days and values outside `0 <= daily_charged <= charged_total <= ceiling_microdollars`
deny sponsorship. Environment, allocation ID, ceiling and expiry must equal the approved
deployment configuration on **every read**. The existing
`HOSTED_SPONSORED_ALLOCATION_ID`, `HOSTED_SPONSORED_MICRODOLLARS` and
`HOSTED_ALLOCATION_EXPIRES_AT` pin that authority; the last must be an integral Unix expiry.
The ceiling is finite, at most 10^15 microdollars. Configuration alone never funds the blob.

Startup reads remaining authority without writes, claims, new IDs or expiry extensions.
Each sponsored call first holds local admission, then reads and atomically charges the full
conservative input/output cost to both lifetime and UTC-day totals using the GET's ETag as
`If-Match`. Detector/provider work starts only after a confirmed write and an expiry/day
recheck. The daily ceiling remains the configured quota limit ($10 by default); daily
rollover changes only the daily counter, never the lifetime total. Completion, cancellation,
retry, missing usage and duplicate completion never refund or perform a monetary update.

Only a known HTTP 412 precondition conflict may retry, at most three attempts. SDK retries
are disabled. Connection/read timeouts and a ten-second admission deadline bound I/O; a
dedicated two-worker pool keeps slots occupied until underlying synchronous work finishes.
Timeouts, unknown commits, cancellation, denied permissions, missing/malformed state and all
accounting errors return sanitized `503 sponsored_unavailable` without outbound work.
An ambiguous/late write may consume credit; it is never retried or refunded. Account/health
and permitted BYOK remain available. The process kill switch and blob `enabled=false` deny
future sponsored admission; account availability is a conservative cached hint, not an
authorization check. The hosted cleanup loop refreshes that hint using bounded, single-flight,
read-only I/O from the 30-second cleanup loop, allowing recovery after an outage or daily rollover.
Every admission still rereads and charges independently of the hint.

ETags protect competing app writes, not malicious or mistaken authorized storage writers.
The app's managed identity and operators with write permission are trusted budget owners.
They must never restore/reset the same allocation, even across cold starts. Local high-water
marks detect rollback only within a process. An explicit operator funding change must keep
the cumulative charged total and current UTC day's daily charge, then approve a new finite
cumulative ceiling/ID/expiry in both blob and deployment configuration. Neither CI, scaling
nor startup may do this. No automatic refill or tamper-proof accounting is claimed.
See [operations.md](operations.md#durable-sponsored-allowance) for release checks.
