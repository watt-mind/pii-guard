# Operations: demo stack, traffic log and timing

How to run PII Guard end to end on one machine, watch what the gateway does to each LLM call,
and measure the latency it adds. Everything here works offline and free: a mock upstream
stands in for the model unless you configure a real one.

## Durable sponsored allowance

The optional `hosted-azure` dependency extra enables
`PII_GUARD_HOSTED_SPEND_STORE=azure_blob`. The default remains `marker`; local/self-hosted
behavior is unchanged. Azure mode reads one existing, private `<environment>.json` block
blob selected by `HOSTED_SPEND_ACCOUNT_URL`, `HOSTED_SPEND_CONTAINER` (default
`sponsored-allowance`) and `HOSTED_SPEND_ENVIRONMENT=dev|prod`, all prefixed `PII_GUARD_`.
Use separate dev/prod resources and managed identities. The SDK accepts managed identity
only; an optional `HOSTED_SPEND_MANAGED_IDENTITY_CLIENT_ID` selects a user-assigned identity.
Never configure a SAS, connection string or shared key.

The [strict monetary document](contracts.md#durable-sponsored-allowance) contains no prompt,
response, mapping, principal, IP or request identifiers. An operator must explicitly approve
and pre-fund it, then pin the exact allocation ID, cumulative ceiling and integral Unix
expiry using the existing hosted allocation settings. Startup never creates, overwrites,
refills or extends this authority, and an unavailable store disables sponsorship while
keeping permitted BYOK and account inspection operational. Keep `enabled=false` and the
configured sponsored amount zero until store validation and provider authorization pass.

Provision a private container with public access disabled and narrowly scoped managed
identity permissions for blob reads/conditional writes. The app has no funding API. Blob
write permissions necessarily let a compromised identity alter the balance: operators and
storage writers are trusted, and restoring/resetting the same allocation is forbidden.
ETags prevent lost updates, not tampering. Do not use lifecycle rules, restore jobs or CI to
replace the allowance document. Fund an additional allowance only by an explicit reviewed
operator change that preserves cumulative `charged_total` and the current UTC day's
`daily_charged`, with a new approved finite cumulative ceiling/ID/expiry. Deployments and
scale-to-zero must reuse the same approved authority without changing those fields.

Before a positive public default, validate real Azure conditional writes and restart with
synthetic accounting operations only: two competing writers cannot exceed the finite
ceiling; a stale ETag receives 412; cold starts/deploys read the same charged totals;
disabled/expired/missing/oversized blobs and revoked RBAC deny sponsorship; and injected
ambiguous PUT outcomes cannot start provider work. Record sanitized verdicts and amounts,
never raw SDK exceptions, tokens or headers. Separate storage diagnostic logging from app
logging, with request/response body logging disabled. Do not issue a refill or call the
provider as part of these checks. Actual cloud behavior remains a release gate until this
validation is recorded; mocked tests alone do not establish it.

The adapter follows Azure's [ETag optimistic concurrency contract](https://learn.microsoft.com/en-us/azure/storage/blobs/concurrency-manage).
It retries only known precondition conflicts (at most three), disables SDK retries and
conservatively consumes the full upper-bound cost. A timeout or cancellation can leave a
late committed charge without provider work; do not compensate automatically. The two
accounting workers remain bounded until synchronous I/O finishes. The finite lifetime
ceiling survives day rollover; the daily ceiling is still $10 by default. Vault/session,
principal quota and abuse state remain ephemeral and require the existing single-process
boundary; this change does not implement general durable tenant state (LAB-1376).
The account's cached availability hint refreshes through single-flight, bounded read-only
I/O in the 30-second cleanup loop, so a recovered store or daily rollover does not require
an app restart. This never grants authority to admission without a fresh successful CAS.

## Hosted secondary abuse admission

Hosted mode has optional network admission in addition to owner/global quotas, concurrent
work bounds and the finite sponsored allocation. Leave
`PII_GUARD_HOSTED_CLIENT_IP_SOURCE=off` until the deployed ingress and logging checks below
pass. The static walkthrough and account/sign-in routes remain available after exhaustion.
Sponsored budgets remain zero until provider authorization and the separate spend/readiness
gates are satisfied; enabling a network signal grants no spending authority.

For **direct Azure Container Apps ingress only**, the optional source is
`aca_xff_rightmost`. Azure documents that ACA appends the rightmost `X-Forwarded-For`
address and that earlier entries are untrusted ([Azure ingress HTTP headers](https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview#http-headers)).
Do not enable it behind a CDN, another reverse proxy or an alternate direct application
path without revisiting that trust contract. There is no fallback to the socket peer,
`Forwarded`, `X-Real-IP` or the first forwarding hop.

Before changing the setting, verify on the real ingress with synthetic requests that
forged prefixes cannot change the selected network; duplicate, oversized and malformed
headers fail closed; absent signals refuse anonymous live demo calls while account and
Google sign-in remain usable; and no alternate application ingress bypasses ACA. Keep
probe output sanitized: record verdicts and counts, never client addresses, raw headers
or tokens. Check server, ingress, platform diagnostics, request tracing and crash-report
logging separately, including whether ACA joins duplicate headers. Disable or redact raw
address/header retention before enabling the source. Application bucket hashing does
not remove addresses already captured by infrastructure. Recheck these gates whenever
the ingress topology or logging configuration changes.

With the source enabled, anonymous demo requests share a 30-request burst refilling
30/minute and 120 requests per fixed hour starting at bucket creation. Signed-in users
have independent 10-request bursts refilling 30/minute even on a shared judge network.
The existing five guest requests/day and other token/cost quotas still apply. New guest
cookies do not reset a network allowance, and sign-in cannot replenish global sponsorship.
429 responses include `Retry-After`; hourly anonymous exhaustion asks for Google sign-in
or the free walkthrough. Missing/untrusted address signals return sanitized 503 errors.

Each anonymous network (IPv4 address, IPv6 /64) also charges its aggregate (IPv4 /24,
IPv6 /48): 120-request burst refilling 60/minute, 480 per hour, at most 64 tracked
networks. A single /48 therefore cannot fill the network table and lock out other clients.

Each in-memory network/aggregate/principal table is limited to 4096 keyed digests with
bounded counters/timestamps, one-hour idle expiry and 24-hour absolute expiry. A full table
evicts its least recently used bucket once it has been idle for five minutes; otherwise it
refuses new entries, and `Retry-After` reports when a slot can free. The HMAC key is random and process-only;
application abuse buckets retain no raw address. State resets on restart, while the
separate durable allocation claim still prevents restart from replenishing sponsored
spend. This is a secondary abuse signal, without an external CAPTCHA or bot-proof claim.

- [Modes](#modes): `fast` (the default) and `audit`
- [Local-only detection](#local-only-detection): enforced raw-processing boundary
- [One command](#one-command-pii-guard-up): `uvx ... pii-guard up`, the release wheel, `make wheel`
- [The demo stack](#the-demo-stack): `make demo`, `make demo-traffic`, `make smoke`, Docker
- [Traffic log](#traffic-log): `GET /v1/traffic`, the live stream, the privacy model
- [Timing](#timing): per-stage spans, overhead, `Server-Timing`, `/metrics`
- [Latency benchmark](#latency-benchmark): `pii-guard bench latency`

## Modes

- **`fast`** is the default and the production path: rules + the in-process NER, local, on
  CPU, $0, and nothing leaves the machine. It needs no model key. What it adds per request is
  measured, not estimated: see [gateway latency](benchmarks.md#gateway-latency) (the README
  quotes one cell of it).
- **`audit`** adds an LLM detector (Muse Spark Open on Baseten by default) to every message: a
  second opinion for sampled or offline quality checks, generating labels and teacher data for
  the NER, and the benchmark upper bound. It is not meant for production traffic: each
  message costs a remote call (about 2 s and $2.5–3 per 1k messages) and its text goes to the
  detector endpoint. Opt in per request (`X-PII-Guard-Mode: audit`) or per server
  (`PII_GUARD_GATEWAY_MODE=audit`).

**Audit mode needs a key.** Without `PII_GUARD_LLM_DETECTOR_API_KEY`, audit mode is
unavailable: every audit request (header, `PII_GUARD_GATEWAY_MODE=audit`, chat or responses,
text or images) gets `503 detection_unavailable` ("audit mode needs
PII_GUARD_LLM_DETECTOR_API_KEY") before anything is detected, segmented or sent, and the
gateway logs one warning at startup. The same holds for `/v1/*` with `PII_GUARD_DETECTORS`
naming `llm`. Before LAB-1290 the text was sent to the default endpoint unauthenticated and the
request failed only on the endpoint's 403. A self-hosted detector on loopback (`localhost`,
`127.0.0.1`, `::1`) may run without a key, since the text stays on the machine; anywhere else,
set a key (any value your endpoint accepts). `make demo` prints "audit mode unavailable (no LLM
detector key)" in this case, and the Chat UI shows the same hint.

**Rename.** Audit mode was called `strict` until LAB-1186, which read as the safer choice and
clashed with policy strictness (block vs mask). `strict` still works everywhere a mode is
accepted, as a deprecated alias of `audit`: the `X-PII-Guard-Mode` header (the response then
carries `Deprecation: true` and a `Warning` header), `PII_GUARD_GATEWAY_MODE` (one log
warning), and the CLI's `--mode` / `--modes` / `--system` values and
`pii-guard bench latency --strict-requests` (a stderr warning). Run records written before the
rename keep their `-strict` IDs; the report shows them as audit.

## Local-only detection

Self-hosting controls who operates the guard; it does not by itself prevent remote detector
calls. Set `PII_GUARD_DETECTION_PROFILE=local-only` to require the supported in-process text
and local image components. This profile is a configuration of the existing product, not a
separate service or a network sandbox for arbitrary Python extensions.

Provision dependencies and a trusted Transformers token-classification checkpoint directory
before serving requests. Model acquisition is an explicit setup operation and may use the
network; it carries no request content. The profile does not automatically fetch missing
weights or fall back to another detector during startup or inference.

```bash
uv sync --extra ner
export PII_GUARD_DETECTION_PROFILE=local-only
export PII_GUARD_NER_MODEL=/absolute/path/to/provisioned/checkpoint
export PII_GUARD_NER_BACKEND=transformers
export PII_GUARD_GATEWAY_MODE=fast
export PII_GUARD_SEGMENTER=local
uv run pii-guard up
```

Supply the usual tenant key and downstream settings as described below. The model directory
must include the checkpoint, tokenizer and configuration files needed by Transformers;
loading uses local files only. A hub model ID, missing directory, missing dependency or broken
checkpoint fails closed. GLiNER and HTTP LLM detectors (even loopback) are outside the supported
profile. `audit`/`strict` requests return `503 detection_profile_denied` before detection or
forwarding. Unused remote URL defaults do not prevent a text-only setup.

For a deliberately limited rules-only installation, set `PII_GUARD_DETECTORS=rules`. Under
local-only this also sets the gateway fast detector stack; no NER dependency or model is
loaded. Rules alone miss much free-form personal data. This is an explicit coverage choice,
never an automatic fallback when NER is broken.

Images require local Tesseract with the necessary language packs and `SEGMENTER=local` or
`off`. Provision the pinned YuNet weights explicitly with
`python -m pii_guard.visual.segment fetch` before using `local`; the local loader does not
download missing weights. YuNet supports faces and estimated ID-photo regions, not signatures
or stamps. The default `SIGNATURE=mask` therefore refuses local images. The guard does not
silently change that policy to `keep`; any operator decision to keep an unsupported entity
leaves it visible. `off` also refuses requested visual masks. See the
[measured local segmentation limits](models.md#local-segmentation) before choosing image policies.

`PII_GUARD_UPSTREAM_BASE_URL` and the downstream model stay independent. Local detection may
send **masked** content to an external LLM; it is not fully local end-to-end inference. For the
latter, operate the downstream model locally too. See the
[privacy boundary](privacy-model.md#local-only-detection-boundary).

## One command: `pii-guard up`

`pii-guard up` runs everything in one process on one port (default 8787, `--port`): the REST
API, the OpenAI-compatible gateway (fast mode) and the built web UI at `/`. It needs only
[uv](https://docs.astral.sh/uv/); uv fetches Python.

```bash
# Today: the wheel attached to a GitHub release (the web UI is bundled in it)
uvx --from https://github.com/watt-mind/pii-guard/releases/download/vX.Y.Z/wattmind_pii_guard-X.Y.Z-py3-none-any.whl pii-guard up
# Once published to PyPI
uvx --from wattmind-pii-guard pii-guard up
# From source: API + gateway only (a git build has no UI; / says how to get it)
uvx --from git+https://github.com/watt-mind/pii-guard pii-guard up
```

The distribution is `wattmind-pii-guard` (the name `pii-guard` on PyPI is an unrelated
project); the command is `pii-guard` and the import package `pii_guard`.

What it does:

- **Upstream.** `--upstream-url` (or `PII_GUARD_UPSTREAM_BASE_URL` in the environment or
  `.env`) names a real OpenAI-compatible upstream; `--api-key-env OPENAI_API_KEY` names the
  variable that holds its key (the value is never printed). Without one, a built-in mock
  upstream (the one below, on a random loopback port) echoes the masked text, and both the
  banner and a strip above the UI say so. `--mock` forces it.
- **Mode.** Fast: rules, plus NER when the `ner` extra is installed (it pulls torch). The
  NER model resolves as in [models.md](models.md#which-ner-model-fast-mode-runs): on the
  first run the published checkpoint or the public fallback is downloaded once (about 1.1 GB).
  The server answers at once and loads (or downloads) it in the background: `/healthz` and
  `/v1/status` say `"ner": "loading"`, and requests that need detection wait for it (up to
  `PII_GUARD_NER_WARMUP_TIMEOUT`, 120 s, then `503 detector_loading` with `Retry-After`;
  LAB-1303). The strip and the banner list the active detectors, the banner
  names the NER model (`NER model  …@… (public fallback, Apache-2.0)`), and without the extra
  it prints the exact `uvx --from 'wattmind-pii-guard[ner] @ <same source>' pii-guard up`
  line to add NER.
  `PII_GUARD_GATEWAY_MODE` overrides the mode.
- **Images.** They need OCR (the `ocr` extra plus the Tesseract binary) and face detection (the
  `local-vision` extra with its model, or `META_API_KEY` for SAM 3.1; see
  [Segmenter](#segmenter-faces-on-the-device-signatures-on-sam-31)). Whatever is missing, image
  parts are refused (fail closed), the strip says `images: refused (no OCR, face detection)`,
  and the banner names the missing pieces with the commands to add them. Text works regardless.
- **Traffic log** `masked` by default (the dashboard needs it); `--traffic-log full` only on a
  loopback bind, as everywhere. A fresh tenant key per run unless `PII_GUARD_TENANT_KEY` is set (in the environment or `.env`).
- It opens the browser (`--no-browser` to skip) and prints the gateway base URL and the
  `pii-guard connect pi` lines, written with the same `uvx --from` prefix when run through uvx.
  A port in use is refused up front (`--port`). Ctrl-C stops everything within about a second,
  open live-traffic streams included.

**Building the wheel.** `make wheel` builds the UI (`pnpm build`, API mode), copies `ui/dist`
to `src/pii_guard/_ui/` (git-ignored, shipped as a hatch artifact) and runs `uv build --wheel`;
the UI build generates the benchmark index (`pii-guard eval report --print-index`), and it fails above 5 MiB or without the UI or the index. `make wheel-smoke` (`scripts/ci/wheel_smoke.sh`)
installs `dist/*.whl` with `uv tool run --isolated`, starts `pii-guard up` on port 18999
(`PII_GUARD_SMOKE_PORT`), checks `/healthz`, `/`, a client-side route, one chat call on the
mock (restored) and the masked traffic log, then stops it. CI runs both (job `wheel`); the
release workflow runs them on `v*` tags and attaches the wheel and sdist to the release.

**PyPI.** `release.yml` has a `pypi` job that publishes the release's files with trusted
publishing (OIDC, no stored token). It is off until the repository variable `PYPI_PUBLISH` is
`true`, and skips pre-releases (`v1.2.3-rc1`). Setup, once: on PyPI, a pending trusted
publisher for project `wattmind-pii-guard` with owner `watt-mind`, repository `pii-guard`,
workflow `release.yml` and environment `pypi`; on GitHub, an environment named `pypi`.
Complete release SOP, tagging, and verification procedures are documented in
[releasing.md](releasing.md), and version history in [CHANGELOG.md](../CHANGELOG.md).

## The demo stack

Prerequisites: [uv](https://docs.astral.sh/uv/) and, for the UI, Node 22+ with
[pnpm](https://pnpm.io) (the first run installs the UI dependencies, which needs the network
once). No key is needed.

```bash
make demo             # mock upstream + API/gateway + UI in fast mode (rules + NER), prints where to go
make demo MODE=rules  # the same, rules only: offline, no NER extra, no model download
make demo-traffic     # in a second terminal: scripted fictional requests through the gateway
make smoke            # start, send the traffic, assert, stop; rules only (what CI runs)
make smoke-fast       # the same in fast mode with the NER (local)
```

**First run of `make demo`.** It installs the `ner` extra (torch, transformers) and, unless
`PII_GUARD_NER_MODEL` is set, downloads the NER model before the API starts, printing
`ner: downloading … (Apache-2.0, about 1110 MB, first run only)`. The model is the published
PII Guard checkpoint, `watt-mind/pii-guard-ner-xlmr-base` release `v2.0` (LAB-1306; see
[models.md](models.md#which-ner-model-fast-mode-runs)), pinned to a hub revision and
checked against its SHA-256, stored in `~/.cache/pii-guard/models/ner/`
(`PII_GUARD_MODELS_DIR`). Later runs load it from there, offline. `PII_GUARD_NER_FALLBACK=cached`
uses it only if it is already there; `off` (what `MODE=rules` sets) never uses it.

`make demo` starts, all bound to 127.0.0.1:

| Process | Address | Notes |
|---|---|---|
| Mock upstream | `http://127.0.0.1:8790/v1` | OpenAI-compatible; answers `Echo: <last user message>`, or calls the first tool with it. No model, no network. |
| PII Guard API + gateway | `http://127.0.0.1:8787` | Gateway in `fast` mode by default, traffic log `masked`, `Server-Timing` and `/metrics` on, a fresh tenant key per run (unless `.env` sets one). |
| UI | `http://localhost:5173` | The Vite dev server, proxying `/v1` to the API. Skipped when pnpm is missing (`--no-ui`). |

It prints a banner with the URLs and what it found:

- **Upstream.** The mock, unless `PII_GUARD_UPSTREAM_BASE_URL` (environment or `.env`) names a
  real OpenAI-compatible upstream, or `BASETEN_API_KEY` is set (then Baseten Model APIs with
  Muse Spark Open). `uv run python scripts/demo.py --mock` forces the mock. `make demo-traffic`
  sends `model: pii-guard-mock`; set `PII_GUARD_DEMO_MODEL` for a real upstream. The demo
  traffic is fictional, so it may go to a hosted model.
- **Fast mode** uses rules + the NER model that resolves (`PII_GUARD_NER_MODEL`, else the
  published PII Guard checkpoint once it is pinned, else the public fallback) and names it,
  for example `fast mode  rules + NER: bardsai/eu-pii-anonimization-multilang@62ca57123687
  (public fallback, Apache-2.0)`. Rules only with `MODE=rules`, or when the `ner` extra is
  missing (the banner says so).
- **Audit mode** (opt in with the header `X-PII-Guard-Mode: audit`) is available when an LLM
  detector key is set (`PII_GUARD_LLM_DETECTOR_API_KEY`, or `BASETEN_API_KEY`).

Other ports: `scripts/demo.py --api-port 9787 --mock-port 9790 --ui-port 6173`.

### Demo traffic

`make demo-traffic` (`scripts/demo_traffic.py --url …`) sends Hungarian, English and German
requests built from fictional values (ADR 0005): a two-turn chat in one session (the second
turn carries the restored answer as history), streamed answers, tool definitions with a tool
call back (plain and streamed) and a message with an inline image. Without SAM configured
the image request is refused (fail closed, nothing forwarded), which shows up in the traffic
log as `refused`. The scenarios live in `src/pii_guard/bench/scenarios.py`; the Live traffic
tab's **Send demo traffic** sends the same ones (`ui/src/content/demoScenarios.json`, written
by `scripts/demo_traffic.py --export-ui` and kept in sync by a test).

**What it shows in rules-only mode** (the default: no `PII_GUARD_NER_MODEL`). Nothing reaches
the model except in the one labeled scenario:

- **Names** are pre-loaded as session **known values** (`POST /v1/sessions`), the way an
  application that knows its parties would (a CRM record, a case file). The `known` detector
  then masks them in any inflected form, and the answer is restored in that form:
  `Teszt Eleknek`, `Teszt Elekkel`, `Minta Máriának` (a changed stem), `Placeholder Kft.-vel`.
  The `hu-known-values` scenario shows this round trip: `make demo-traffic` prints
  `restored exactly`, and the Live traffic tab shows the restored answer next to the masked
  one when the stack runs `uv run python scripts/demo.py --traffic-log full` (localhost only;
  the recorded replay is `masked`, so it shows the placeholders and their count).
- **Numbers** are checksum-valid fictional identifiers the rules find on their own: TAJ,
  adóazonosító jel, HU / GB / DE IBANs, a Luhn test card, phone numbers, email addresses and
  a postal address.
- **`hu-needs-ner`, labeled "needs fast mode (NER)"**: a free-text name with no known value
  and no rule cue (`Tegnap Gipsz Jakab telefonált…`). In rules-only mode it reaches the mock
  model as written: an **expected miss**, kept on purpose to show what the NER adds.
  `make demo-traffic` prints it as such, and the Live traffic tab marks the call
  "needs fast mode (NER) · expected miss" with the reason.

**In fast mode with the NER** (`make demo`, the default) the labeled name is masked too, and
the tab says the NER ran. With `make demo MODE=rules` it is the expected miss described above.

### Smoke test

`make smoke` (`scripts/smoke.py --mode rules`) starts the mock upstream and the API on ports
18790 / 18787 (the UI is not needed), rules only, sends the demo traffic and fails unless:

1. every answer comes back restored **exactly** (`Echo: <the original message>`, or tool
   arguments equal to `{"text": <the original message>}`);
2. no gold value of any scenario reached the upstream, raw, JSON-escaped or without spaces
   (the mock keeps what it received, `GET /_mock/received`). In rules-only mode that covers
   every scenario except the one labeled "needs fast mode (NER)": its name is printed as an
   expected miss, not a failure;
3. every call has a traffic event with a timing breakdown, and the log holds no raw session
   id and no credentials.

It runs in CI on every pull request, rules only to keep CI light (no torch, no model). The
same checks run in-process in `tests/bench/test_bench.py`.

`make smoke-fast` (`scripts/smoke.py --mode fast`, local) runs the same traffic in fast mode
with the resolved NER model (downloaded once on the first run, as for `make demo`). It also
fails unless the NER ran on the call labeled "needs fast mode (NER)" (its traffic event lists
`ner`) and that call's name was masked: no expected misses. A fresh cache
(`PII_GUARD_MODELS_DIR=$(mktemp -d) make smoke-fast`) checks the clean-checkout path.

### Docker

```bash
docker compose --profile demo up --build
```

starts the same stack in containers: `mock-upstream`, `demo-api` on
`http://127.0.0.1:8788` (traffic log `masked`, `fast` mode with the NER) and `ui` on
`http://localhost:5173`, next to the plain `api` service on 8787. The demo services use their
own image, `pii-guard:demo`, built with the `ner` extra (`PII_GUARD_EXTRAS` build argument;
the plain `pii-guard:dev` image stays without torch). On Linux, torch comes from the PyTorch
CPU index (`[tool.uv.sources]` in `pyproject.toml`), so the image has no CUDA libraries
(`nvidia-*`, `triton`): 1.9 GB on arm64 in `docker image ls` (424 MB content, a 1.2 GB
virtualenv), down from 9.6 GB (3.42 GB content, a 5.6 GB virtualenv) with the PyPI wheel
(LAB-1308). `pii-guard:dev` is 654 MB. macOS keeps the PyPI torch wheel, which has MPS. On the first start `demo-api` downloads the NER model into the `pii-guard-models` volume before the server listens (`docker compose
logs -f demo-api` shows `ner: downloading …`); its healthcheck allows 15 minutes for that, and
the UI waits until `demo-api` is healthy. Later starts reuse the volume (`docker compose down
-v` drops it). The UI's Benchmarks view reads an index built from the committed run records;
the Node container has no Python and mounts only `ui/`, so a one-shot `benchmarks-index`
service (the demo image, `eval/` and `docs/` mounted read-only) prints it into the
`pii-guard-benchmarks` volume on every start, and `ui` waits for it and reads it through
`PII_GUARD_BENCHMARKS_INDEX` (LAB-1356). Rules only, offline, no download:
`PII_GUARD_DEMO_NER_FALLBACK=off docker compose --profile demo up --build`. A real upstream:
`PII_GUARD_DEMO_UPSTREAM_URL` and `PII_GUARD_DEMO_UPSTREAM_API_KEY`. Inside a container the
server binds `0.0.0.0`, so the traffic log can only be `masked` there (see below). Send the demo
traffic with `uv run python scripts/demo_traffic.py --url http://127.0.0.1:8788`.

**OCR.** The image installs Tesseract with the Hungarian, English and German data
(`tesseract-ocr-hun`/`-eng`/`-deu`/`-osd`) and the `ocr` extra (`pytesseract`), so the text in
inline images (a TAJ, a name) is read and masked. That adds about 115 MB (the apt layer; the
image grew from about 269 MB to 429 MB in `docker image ls` on arm64). Without an OCR engine,
image parts are refused with `503 ocr_unavailable` (fail closed, ADR 0006): set
`PII_GUARD_IMAGE_REQUIRE_OCR=false` only if SAM-only masking is acceptable, which leaves text in
images unchecked (`X-PII-Guard-Image-OCR: off`). pytesseract hands Tesseract the image through
a temp file, so the read-only `api` and `demo-api` containers mount a `tmpfs` on `/tmp`; a
read-only container without one fails every OCR call (`No usable temporary directory`). The container healthcheck reads `/healthz`
(`"ocr"` plus `"image_require_ocr"`), and prints `ocr on|off` (`docker inspect --format
'{{json .State.Health}}' <container>`). For `make demo` outside Docker: `brew install
tesseract tesseract-lang` or `apt install tesseract-ocr tesseract-ocr-hun`, then
`uv sync --extra ocr`; the banner says whether OCR is on.

### Segmenter: faces on the device, signatures on SAM 3.1

`PII_GUARD_SEGMENTER` picks who finds the visual personal data in images (LAB-1245,
[contracts.md](contracts.md), [models.md](models.md#local-segmentation)):

| Value | Faces, ID photos | Signatures | SAM 3.1 calls per image | Image leaves the machine |
|---|---|---|---:|---|
| `hybrid` (default) | YuNet on the CPU | SAM 3.1 (`signature`, `squiggly line`) | 2 | yes, for the signature prompts |
| `sam-api` (the default before LAB-1245) | SAM 3.1 | SAM 3.1 | 5 (with `stamp`) | yes |
| `local` | YuNet on the CPU | not found: images are refused while `SIGNATURE` is masked | 0 | no |
| `off` | — | — | 0 | no; every image is refused |

`hybrid` is a latency and cost win, not a privacy win: the image still goes to the Meta API for
the signature prompts. YuNet (OpenCV model zoo, 0.23 MB, MIT) runs alongside those calls.
`STAMP` is `keep` by default, so `hybrid` does not ask SAM for stamps; give it another policy
and it does (one more call).

**Fallback (fail closed, ADR 0006).** The segmenter is built on the first image. If OpenCV or
the YuNet model is missing, `hybrid` logs a warning (`on-device face detection unavailable ...;
faces and ID photos go to SAM 3.1 too`) and sends every type to SAM (4 calls): still masked.
With no SAM API key either, every image is `503 detection_failed`. `local` never falls back to
the API, and any SAM or YuNet error while an image is processed refuses the image.

**Getting YuNet.** The Docker image ships it: the `local-vision` extra (OpenCV headless) and the
model, fetched at build time from its pinned OpenCV model zoo URL and checked against its
pinned SHA-256 (the build fails on a mismatch), in `/app/models` (`PII_GUARD_MODEL_DIR`). That
adds about 160 MB unpacked (`du` inside the container, arm64: 317 MB → 478 MB; `docker image
inspect` on Docker Desktop: 430 MB → 653 MB): OpenCV headless about 87 MB, numpy about 68 MB, the
model 0.23 MB. The local-vision change raised the CI size budget from 375 to 525 MB.
LAB-1407 adds `cryptography` for authenticated encryption of stored provider credentials;
the first amd64 CI image with that dependency measured 541 MB unpacked. The budget is now
550 MB, retaining OCR and local vision and allowing 9 MB of headroom. This deliberate
footprint increase supports encrypted configuration without implementing custom cryptography.
`make demo` fetches YuNet too. Elsewhere: `uv sync --extra local-vision`, then
`uv run python -m pii_guard.visual.segment fetch` (into `PII_GUARD_MODEL_DIR`, default
`~/.cache/pii-guard/models`). Model files are never committed.

**SAM 3.1 output parser.** The Docker images install the `sam` extra, Meta's official
`meta-sam-parser` (0.1.0, pure Python, SAM License; see NOTICE). It decodes what SAM 3.1
returns and checks every mask. Elsewhere: `uv sync --extra sam`. Without it, pii-guard's own
decoder reads SAM output (logged once at info level); limits and fail-closed checks are the same.

## Exposure and authentication

**There is no authentication by default.** Anyone who can reach the API can mask and unmask,
read the traffic log and `/metrics`, and use the gateway. With `PII_GUARD_UPSTREAM_API_KEY` set,
the upstream key is shared by every caller: an exposed gateway is an open relay that spends it.
Run the API on loopback (the default `PII_GUARD_HOST=127.0.0.1`) or behind an authenticating
reverse proxy. A container binds `0.0.0.0`; publish its port on `127.0.0.1` only, as
`compose.yaml` does. On a non-loopback bind without a token, startup logs a warning.

| Setting | Effect | Default |
|---|---|---|
| `PII_GUARD_API_TOKEN` | Every route but `/healthz` needs `Authorization: Bearer <token>` (or `X-PII-Guard-Token: <token>`); otherwise `401 unauthorized` | unset: no auth |
| `PII_GUARD_ALLOWED_HOSTS` | Extra `Host` header names the API answers, comma-separated; `*` answers any | `localhost`, `127.0.0.1`, `[::1]` and `PII_GUARD_HOST` |

- **DNS rebinding.** A web page on another site can point its own host name at `127.0.0.1` and
  make the browser talk to a local PII Guard; its requests still carry that host name. Any other
  `Host` gets `400 Invalid host header`. The UI's Vite proxy sends `127.0.0.1:<port>`; behind a
  proxy or a compose service name (`demo-api`), add that name to `PII_GUARD_ALLOWED_HOSTS`.
- **The token is never forwarded upstream.** The gateway sends `PII_GUARD_UPSTREAM_API_KEY`
  upstream, never the client's token. Without an upstream key the client's own `Authorization`
  is passed through (bring your own key); a PII Guard token sent as the bearer is removed first,
  so send the token as `X-PII-Guard-Token` and your provider key as `Authorization`.

## Resource limits

Every limit fails closed with a JSON error and no value in it:

| Limit | Setting (default) | Over it |
|---|---|---|
| Request body | derived from `max_text_chars` (and, for the gateway, `PII_GUARD_GATEWAY_MAX_IMAGES` x `_MAX_IMAGE_BYTES`) | `413 payload_too_large`. A declared `Content-Length` is checked first; a chunked body is counted while it is read and refused as soon as it passes the limit, so it is never buffered whole. |
| Concurrent detections | `PII_GUARD_GATEWAY_CONCURRENCY` (4) threads **per mode** | A detection that times out (`PII_GUARD_GATEWAY_DETECTION_TIMEOUT`) keeps its thread and its slot until it really finishes, so a hung detector holds at most this many threads, and only its own mode's: a stuck audit-mode LLM never starves fast mode. When all slots are stuck, that mode's requests wait inside their timeout, then `503 detection_failed`. |
| Concurrent image work | `PII_GUARD_IMAGE_CONCURRENCY` (2) per app | Shared by `POST /v1/mask/image` and the gateway, held until the thread finishes, like detections. |
| Image time | `PII_GUARD_GATEWAY_IMAGE_TIMEOUT` (120 s, per request) and `PII_GUARD_IMAGE_TIMEOUT` (120 s, `/v1/mask/image`) | `503 detection_failed`. The deadline goes into the work: Tesseract gets the remaining time as its subprocess timeout (killed, not left running) and every stage checks it, so the rest of the request's images are not started. |
| Image size | `PII_GUARD_IMAGE_MAX_PIXELS` (16 000 000) | `413 payload_too_large`, read from the image header before decoding. OCR time and memory grow with pixels: a 221 KB PNG of 7900 x 5000 took 33 to 73 s and about 1 GB, depending on the machine. The decoder's own cap is 40 MP. |
| Vault sessions | `PII_GUARD_VAULT_MAX_SESSIONS` (10 000) | Creating one more **evicts the least recently used session** (the one whose sliding TTL ends first). Eviction rather than `429` keeps the service up under a flood of `/v1/mask` calls without `session_id`; a later use of an evicted session is `404 session_not_found`, and the client starts a new one. |
| Leases per client | `PII_GUARD_VAULT_MAX_LEASES_PER_IDENTITY` (1 000) in-flight gateway requests (streams included) per client identity (`Authorization` hash, or `anonymous`) | `503 vault_capacity_exhausted` for that client only, before any session is created; other clients still get a slot. Without it, one client holding about `PII_GUARD_VAULT_MAX_SESSIONS` long streams (up to 600 s each) pinned every slot and everyone else got the 503 (LAB-1584). |
| Restored characters | `PII_GUARD_UNMASK_MAX_RESTORED_CHARS` (1 000 000, five times the 200 000-character text limit) per `/v1/unmask` call and per gateway response (every choice, field and tool call, streamed or not) | `413 unmask_output_too_large`; a stream ends with an `unmask_output_too_large` error event. Counted before each value is written, so the output never grows past it. Without it, a short text repeating the placeholder of a long secret (a PEM key) expanded about 93 times (LAB-1350). |

Image values are registered in the vault session only when the whole request succeeded: the
work masks into a private fork of the session, committed afterwards. A refused or timed-out
image leaves nothing in the session, even while its thread is still finishing.

### Values held in memory outside the vault

Deleting a session or letting its TTL expire drops its values from the vault. The detectors
keep no copy of their own: the LLM detector builds the patterns that place a reported value in
the text per request and caches none of them (it used to keep every value ever reported, with
no bound; LAB-1353). The one process-wide remnant is Python's `re` compile cache, shared by the
vault and every detector: at most 512 recently compiled patterns (on Python 3.12), the oldest
evicted first, some containing a recent value. A restart clears it; so does
`pii_guard.detect.llm.clear_alignment_caches()` (`re.purge()`) in the API process.

## Traffic log

Every call to `POST /v1/chat/completions`, `POST /v1/responses` or `POST /v1/messages` produces
one event when the traffic log is on or a remote dashboard exporter is configured. The local log
keeps events **in memory only** (none while it is off); the exporter only ships them:

| Setting | Values | Default |
|---|---|---|
| `PII_GUARD_TRAFFIC_LOG` | `off`, `masked`, `full` | `off` (`masked` in the demo) |
| `PII_GUARD_TRAFFIC_LOG_SIZE` | events kept (ring buffer) | `200` |
| `PII_GUARD_REMOTE_URL` | dashboard origin (`https://guard.watt-mind.com`), `/v1` or `/e/<endpoint>/v1`; `https://` only (`http://` for a loopback host), no credentials in the URL. Nothing is exported while it is unset. | unset |
| `PII_GUARD_REMOTE_KEY` | bearer credential (a hosted `pg_...` API key, an endpoint `pg_ep_...` key, or a self-hosted `PII_GUARD_API_TOKEN`) | unset |
| `PII_GUARD_REMOTE_LEVEL` | `masked`: the forwarded (masked) request and response bodies plus stats. That includes any value the policy keeps unmasked. `stats`: counts, entity types, model, usage and timings only. | `masked` |

| Endpoint | What it returns |
|---|---|
| `GET /v1/traffic?limit=50&after=<seq>` | `{"level", "size", "boot", "events": [...]}`, oldest first |
| `POST /v1/traffic` (and `POST /e/<endpoint>/v1/traffic`) | `{"accepted", "boot"}`; ingests 1–50 scrubbed `masked` or `stats` events from a local gateway, `application/json` only (`415 unsupported_media_type` otherwise; `422 invalid_request` if `level="full"`, `request.original` or `response.unmasked` is present). Ingested events carry `"source": "remote"`. |
| `GET /v1/traffic/stream?replay=10` | Server-sent events: one `traffic` event per call (`id:` = `seq`), a keep-alive comment every 15 s |

The exporter is a background thread with a bounded queue: a slow or unreachable dashboard never
blocks or fails a local call. Batches are cut at 24 KiB, under the hosted ingest's 32 KiB body
limit. An event too large for a batch on its own is sent at `stats` level. The first failed
send is logged at warning level; `sent`, `failed` and `dropped` count the rest.

All three answer `404 traffic_log_disabled` while the log is off.

`seq` counts from 1 in each server process. `boot` is a random id (`b_` + 16 hex) chosen at
startup: a poller that sees it change knows the server restarted and its `after` cursor is
stale, and starts again from `after=0`. The Logs screen does this.

Hosted mode keeps one log per owner runtime (the project's own, one per endpoint) but numbers
all of an owner's events from one sequence. With no endpoint selected, `/v1/traffic` and the
stream merge the project's runtime and every one of its endpoint runtimes by `seq`, so a call
through `/e/<endpoint>/v1/...` shows up in the project's Logs; `X-PII-Guard-Endpoint` narrows
the view to that endpoint. Both views share one `boot` and one `seq` space, so `after` is a
plain cursor in either. Another owner's runtimes are never read, and the Vault stays per
runtime.

### Privacy model

- **Nothing is persisted.** Events live in a bounded ring buffer in the API process; they are
  never written to disk or to the application log, and a restart forgets them.
- **`masked`** keeps only what left the machine: the masked request exactly as it was sent
  upstream and the upstream's answer (placeholders, not values), plus entity types and counts.
  This is what the model provider saw anyway.
- **`full`** also keeps the client's original request and the restored answer, side by side,
  for a local demo. It is refused unless the server binds to a loopback address
  (`127.0.0.1`, `::1`, `localhost`): `create_app` and `pii-guard serve` stop at startup with
  `PII_GUARD_TRAFFIC_LOG=full` on any other `PII_GUARD_HOST` / `--host`. Use it with fictional
  data.
- **No credentials.** Events are built from request bodies, never from headers, so
  `Authorization` and the client's key never enter them; every payload is also scrubbed:
  credential-looking fields (`authorization`, `api_key`, `password`, ...) are replaced by
  `[redacted]`, `Bearer …` strings are cut, and the configured upstream key is removed from any
  string. Inline images are replaced by a summary (`[inline image/png, N chars]`); strings over
  20,000 characters are truncated.
- **Masked-image thumbnails, never originals.** Each inline image in the *masked* request
  (regions already blacked out, exactly what the upstream received) also gets a downscaled WebP
  copy in `request.thumbnails`, so the Live traffic tab can show it. Longest side at most
  320 px, each data URL at most 16 KiB (a 240 or 160 px copy is tried before giving up), and at
  most 4 per event; an image that does not fit is listed as `{"index", "omitted"}`. Original
  images are never thumbnailed or kept, at `full` either.
- **Bounded memory.** Thumbnails add at most 64 KiB per event, so the ring buffer holds at most
  `PII_GUARD_TRAFFIC_LOG_SIZE` × 64 KiB of them (12.5 MiB at the default 200), on top of the
  event text (strings capped at 20,000 characters each).
- **No session ids.** The session id is a bearer handle to the vault, so events carry only
  `session_ref`: an HMAC-SHA256 of it under a random key generated when the process starts.
  The ref groups the calls of one conversation, cannot be turned back into the id, and changes
  on restart.
- **Who can read it.** Anyone who can reach the API can read the log; keep the API on a
  private interface, as for every other endpoint ([Exposure and authentication](#exposure-and-authentication)).
  With `full`, every connection that is not loopback on both ends gets `403
  traffic_log_not_local`, whatever launched the server (`uvicorn --host 0.0.0.0` included), and
  `PII_GUARD_ALLOWED_HOSTS` may name loopback hosts only.

### Event fields

| Field | Meaning |
|---|---|
| `id` | Request id, also sent back as `X-PII-Guard-Request-Id` on successful responses |
| `seq`, `time` | Order in this process; UTC timestamp |
| `endpoint` | Hosted only: `{"id", "name"}` of the endpoint the call went through; absent for calls on the project itself |
| `level` | `masked` or `full` |
| `outcome` | `ok`, `blocked` (a `block` policy, or the outbound re-check), `refused` (any other error that stopped the call in the guard, so nothing was forwarded), `upstream_error` (upstream HTTP >= 400), `upstream_failed` (the masked request was forwarded and the upstream failed: unreachable, an unusable answer, or no event stream for a streamed call; `error.code` keeps its `upstream_*` value, such as `upstream_unavailable` or `upstream_did_not_stream`. Before LAB-1629 these calls were `refused`, so a consumer matching `refused` plus an `upstream_*` code still finds older events), `stream_error`, `client_disconnected` (the client went away mid-stream; the partial answer does not seed the detection cache), `error` |
| `error` | `{"code", "status"}` and, for `blocked`, `entity_types` (counts) |
| `outbound_check` | The [outbound re-check](architecture-gateway.md#outbound-re-check) of the masked request: `result` (`passed` or `blocked`), `texts` checked, `hits` (blocking occurrences per entity type), `short` (occurrences too short to block), `ms`; `null` when the call was refused before it |
| `mode`, `language`, `stream`, `model` | As requested; `model` is `"[withheld]"` unless it passed its identifier check (refused, blocked and failed calls), here and in the `full` original (LAB-1358) |
| `session_ref`, `session_new`, `session_source` | Hashed session (see above); whether the call started the conversation; which step chose it: `header`, `path`, `prompt_cache_key` or `default` ([architecture-gateway.md](architecture-gateway.md#sessions)) |
| `detectors` | Detectors that ran (`rules`, `ner`, `llm`, `known`, `visual`) |
| `entities` | `detected` and `masked` counts per entity type, number of texts; `images` (count, regions masked / kept, OCR) |
| `cache` | Detection cache `hits`, `misses`, `seeded` |
| `upstream` | HTTP status, the model it reported (`"[withheld]"` when it is not model-id shaped, for example holds an e-mail address), `unresolved_placeholders` (placeholders the model invented) |
| `usage` | Token usage as the upstream reported it (streams: when `stream_options.include_usage` is set) |
| `timing` | See [Timing](#timing) |
| `request` | `masked` (the body sent upstream); `original` at level `full`; `thumbnails` when the masked body had inline images: `{"index", "width", "height", "data"}` per image (`index` counts the `image_url` parts of `messages` in order, remote URLs included), or `{"index", "omitted"}` with `too_large`, `invalid` or `limit` |
| `response` | `masked` (the upstream's answer; streams: content per choice and the chunk count); `unmasked` at level `full` |

## Vault inspector

The console's **Vault** screen (Inspect group) and `GET /v1/vault/sessions*` show which vault
sessions the server holds and what each one maps, for troubleshooting a value that was or
wasn't restored. Routes, fields and errors: [contracts.md](contracts.md#vault-inspector-v1vaultsessions).

| `PII_GUARD_VAULT_INSPECT` | What you see |
|---|---|
| `off` | Nothing: the routes answer `404 vault_inspect_disabled`. |
| `masked` (default) | Sessions (source, client, created, last used, TTL left, counts) and each placeholder with its type, origin, occurrence count and a redacted hint (`T•••• E•••`). Never an original. |
| `full` | Also a **Reveal values** button per session: the originals, their inflected forms and the session id, fetched on demand and kept only in the page's memory. Loopback only, like the `full` traffic log; every reveal is logged (ref and counts, never a value). |

Troubleshooting with it:

1. **Find the conversation.** On Logs, open the call and use **Open session … in Vault**: the
   traffic log's `session_ref` is the inspector's ref. Or filter the sessions by source.
2. **Check where the session came from.** `Session header`, `URL path`, `Prompt cache key` and
   `Client default` are the gateway's resolution steps
   ([architecture-gateway.md](architecture-gateway.md#sessions)); `REST API` is a session made by
   `/v1/mask` or `/v1/sessions`. Two sessions where you expected one usually mean the client
   changed its `Authorization` value or its `prompt_cache_key` between turns (a different
   client identity or key derives a different session).
3. **Read the placeholders.** A value the model echoed but that came back as a placeholder is
   one this session never issued (the model invented it or copied it from another session):
   it is not in the list. A value that was masked under another type, or not at all, shows in
   the hint and type columns. `Forms` counts inflected forms matched onto a value; `Known value`
   rows were pre-loaded, and a known value no text has matched yet is listed without a
   placeholder.
4. **Start over.** **Drop…** forgets a session now. A client that names it in
   `X-PII-Guard-Session` then gets 404; a derived session (path, prompt cache key, default)
   starts again, empty, on the next request, and earlier placeholders in its history are no
   longer restored.

Reading the inspector never extends a session's TTL. The source, client and created time come
from the gateway's responses and are kept in memory next to the vault; a `REST API` session has
no recorded client or creation time.

## Timing

The gateway times every request on the monotonic clock, from the moment the body has been
received until the answer is built (non-streamed) or the stream has ended:

| Stage (`timing.stages_ms`) | What it covers |
|---|---|
| `parse` | JSON, collecting the texts and images, request checks |
| `detect` | Every detector on every text (concurrent), then the session's known values; wall time |
| `image` | The visual pipeline (SAM, OCR) for inline images |
| `mask` | Vault masking of every text |
| `forward` | Serializing the masked body and opening the upstream client |
| `upstream_ttfb` | Send until the upstream's response headers |
| `upstream` | All time spent waiting on the upstream: headers, body or each stream read |
| `unmask` | Restoring a stream, summed over its chunks |
| `response` | Restoring a non-streamed answer and building the response |
| `client` | Streams: time spent handing each event to the client (its read speed, network backpressure); neither PII Guard's work nor the upstream's |

Derived fields:

- `total_ms`, `upstream_ms` and **`overhead_ms = total_ms - upstream_ms - client`**: what
  PII Guard added to the call. A slow-reading client makes a stream's `total_ms` longer, not
  its overhead.
- Streams: `ttft_ms` (to the first event sent to the client), `upstream_ttft_ms` (the
  upstream's own time from send to its first data event) and **`added_ttft_ms = ttft_ms -
  upstream_ttft_ms`**: the delay PII Guard added before the first token.
- `detectors_ms`: each detector's own time summed over the texts of the request. Texts run
  concurrently, so these can add up to more than the `detect` stage.

The client-side wall time is a little higher than `total_ms`: reading the request body and the
HTTP framing happen outside the timer.

**`Server-Timing` header** (`PII_GUARD_SERVER_TIMING=true`, off by default): the stages known
when the headers are sent, plus `upstream`, `overhead` and `total`, e.g.
`parse;dur=0.101, detect;dur=0.447, mask;dur=0.118, forward;dur=4.359, upstream_ttfb;dur=53.166, response;dur=0.114, upstream;dur=53.480, overhead;dur=5.246, total;dur=58.726`.
On a stream the header is sent before the answer, so it only covers the work up to the
upstream's response headers.

**Prometheus metrics** (`PII_GUARD_METRICS=true`, off by default; `pii-guard up` and `make demo`
enable it by default; disabled in `PII_GUARD_HOSTED=true`) at `GET /metrics`
(`text/plain; version=0.0.4`):

| Metric | Type | Labels | Description |
|---|---|---|---|
| `pii_guard_gateway_requests_total` | `counter` | `mode`, `outcome` | Gateway requests by mode (`fast`, `audit`) and outcome (`ok`, `blocked`, `refused`, `upstream_error`, `upstream_failed`, `stream_error`, `client_disconnected`, `error`) |
| `pii_guard_gateway_overhead_ms` | `histogram` | `mode` | Gateway processing overhead in ms (`total_ms - upstream_ms - client_ms`) |
| `pii_guard_gateway_total_ms` | `histogram` | `mode` | End-to-end gateway turn duration in ms |
| `pii_guard_gateway_upstream_ms` | `histogram` | `mode` | Time spent waiting on the upstream LLM in ms |
| `pii_guard_gateway_added_ttft_ms` | `histogram` | `mode` | Time-to-first-token added by PII Guard on streaming calls in ms |
| `pii_guard_gateway_stage_ms` | `histogram` | `mode`, `stage` | Per-stage gateway timing in ms (`parse`, `detect`, `image`, `mask`, `forward`, `upstream_ttfb`, `upstream`, `unmask`, `response`, `client`) |
| `pii_guard_detector_duration_ms` | `histogram` | `mode`, `detector` | Per-detector runtime in ms (`rules`, `ner`, `llm`, `visual`) |
| `pii_guard_entities_detected_total` | `counter` | `entity_type` | PII entities detected across the gateway and `/v1/analyze` + `/v1/mask` |
| `pii_guard_entities_masked_total` | `counter` | `entity_type` | PII entities replaced with vault placeholders across the gateway and `/v1/mask` |
| `pii_guard_image_regions_total` | `counter` | `entity_type`, `action` | Visual PII regions processed (`action="masked"\|"kept"`) across the gateway and `/v1/mask/image` |
| `pii_guard_blocked_entities_total` | `counter` | `stage`, `entity_type` | Entities that triggered a policy block (`stage="inbound"\|"outbound"`) |
| `pii_guard_outbound_checks_total` | `counter` | `result` | Outbound leak-guard evaluations (`result="passed"\|"blocked"`) |
| `pii_guard_detection_cache_total` | `counter` | `result` | Prefix detection cache lookups (`result="hit"\|"miss"\|"seeded"`) |
| `pii_guard_upstream_tokens_total` | `counter` | `direction` | Upstream LLM tokens (`direction="input"\|"output"`) |
| `pii_guard_unresolved_placeholders_total` | `counter` | — | Unknown or hallucinated `[[TYPE_id]]` placeholders left unresolved |
| `pii_guard_http_requests_total` | `counter` | `method`, `path`, `status` | HTTP requests handled across all API routes (route templates only; `/metrics` excluded) |
| `pii_guard_http_request_duration_ms` | `histogram` | `method`, `path` | HTTP request duration in ms by route template (to response headers on streams) |
| `pii_guard_vault_active_sessions` | `gauge` | — | Live vault sessions in memory across root and project runtimes |
| `pii_guard_ner_state` | `gauge` | `state` | One-hot NER warmup state (`1` for active state among `off`, `loading`, `ready`, `failed`) |

All millisecond histograms use buckets `0.5, 1, 2.5, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, +Inf` (`BUCKETS_MS` in `observability/metrics.py`).
Labels are fixed enums and route templates only—never raw PII, session IDs or client identifiers.
When `PII_GUARD_API_TOKEN` is set, configure Prometheus with `authorization: { credentials: <token> }`
on the scrape job.

## Latency benchmark

```bash
uv run pii-guard bench latency                       # fast mode, concurrency 1 and 8, streamed and not
uv run pii-guard bench latency --modes fast,audit --audit-requests 10 --record my-change
```

It starts the mock upstream with a fixed delay (`--upstream-delay-ms`, default 50) and the API
on free loopback ports, and sends a fixed fictional corpus (8 hu / en / de messages, one per
request, each in a new session so the detection cache never helps) through the gateway: N
requests per cell (`--requests`, default 200; `--audit-requests`, default 12, because each one
calls the LLM detector), for every mode, concurrency (`--concurrency 1,8`) and streaming
setting. Per cell it reports p50 / p95 / p99 / mean of the overhead, added time to first token,
every stage and detector, and the client's wall time.

`--record SLUG` writes one run record per mode (`kind: latency`,
`eval/results/runs/<date>-<SLUG>-<mode>.json`, same schema as the evaluation runs);
`uv run pii-guard eval report` then adds them to the **Gateway latency** section and chart of
[benchmarks.md](benchmarks.md). Audit mode uses the configured LLM detector
(`PII_GUARD_LLM_DETECTOR_*`); keep the request count small on a paid endpoint.

Overhead is machine-dependent: compare runs on the same hardware (the record names it).
