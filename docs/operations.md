# Operations: demo stack, traffic log and timing

How to run pii-guard end to end on one machine, watch what the gateway does to each LLM call,
and measure the latency it adds. Everything here works offline and free: a mock upstream
stands in for the model unless you configure a real one.

- [Modes](#modes): `fast` (the default) and `audit`
- [One command](#one-command-pii-guard-up): `uvx ... pii-guard up`, the release wheel, `make wheel`
- [The demo stack](#the-demo-stack): `make demo`, `make demo-traffic`, `make smoke`, Docker
- [Traffic log](#traffic-log): `GET /v1/traffic`, the live stream, the privacy model
- [Timing](#timing): per-stage spans, overhead, `Server-Timing`, `/metrics`
- [Latency benchmark](#latency-benchmark): `pii-guard bench latency`

## Modes

- **`fast`** is the default and the production path: rules + the in-process NER, local, about
  36 ms of detection, $0, and nothing leaves the machine. It needs no model key.
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
  strip and the banner list the active detectors, and the banner prints the exact
  `uvx --from 'wattmind-pii-guard[ner] @ <same source>' pii-guard up` line to add NER.
  `PII_GUARD_GATEWAY_MODE` overrides the mode.
- **Images.** They need OCR (the `ocr` extra plus the Tesseract binary) and face detection (the
  `local-vision` extra with its model, or `META_API_KEY` for SAM 3.1; see
  [Segmenter](#segmenter-faces-on-the-device-signatures-on-sam-31)). Whatever is missing, image
  parts are refused (fail closed), the strip says `images: refused (no OCR, face detection)`,
  and the banner names the missing pieces with the commands to add them. Text works regardless.
- **Traffic log** `masked` by default (the dashboard needs it); `--traffic-log full` only on a
  loopback bind, as everywhere. A fresh tenant key per run unless `PII_GUARD_TENANT_KEY` is set.
- It opens the browser (`--no-browser` to skip) and prints the gateway base URL and the
  `pii-guard connect pi` lines, written with the same `uvx --from` prefix when run through uvx.
  A port in use is refused up front (`--port`). Ctrl-C stops everything within about a second,
  open live-traffic streams included.

**Building the wheel.** `make wheel` builds the UI (`pnpm build`, API mode), copies `ui/dist`
to `src/pii_guard/_ui/` (git-ignored, shipped as a hatch artifact) and runs `uv build --wheel`;
it fails above 5 MiB or without the UI. `make wheel-smoke` (`scripts/ci/wheel_smoke.sh`)
installs `dist/*.whl` with `uv tool run --isolated`, starts `pii-guard up` on port 18999
(`PII_GUARD_SMOKE_PORT`), checks `/healthz`, `/`, a client-side route, one chat call on the
mock (restored) and the masked traffic log, then stops it. CI runs both (job `wheel`); the
release workflow runs them on `v*` tags and attaches the wheel and sdist to the release.

**PyPI.** `release.yml` has a `pypi` job that publishes the release's files with trusted
publishing (OIDC, no stored token). It is off until the repository variable `PYPI_PUBLISH` is
`true`, and skips pre-releases (`v1.2.3-rc1`). Setup, once: on PyPI, a pending trusted
publisher for project `wattmind-pii-guard` with owner `watt-mind`, repository `pii-guard`,
workflow `release.yml` and environment `pypi`; on GitHub, an environment named `pypi`.

## The demo stack

Prerequisites: [uv](https://docs.astral.sh/uv/) and, for the UI, Node 22+ with
[pnpm](https://pnpm.io) (the first run installs the UI dependencies, which needs the network
once). No key and no model download are needed.

```bash
make demo           # mock upstream + API/gateway + UI, prints where to go
make demo-traffic   # in a second terminal: scripted fictional requests through the gateway
make smoke          # start, send the traffic, assert, stop (what CI runs)
```

`make demo` starts, all bound to 127.0.0.1:

| Process | Address | Notes |
|---|---|---|
| Mock upstream | `http://127.0.0.1:8790/v1` | OpenAI-compatible; answers `Echo: <last user message>`, or calls the first tool with it. No model, no network. |
| pii-guard API + gateway | `http://127.0.0.1:8787` | Gateway in `fast` mode by default, traffic log `masked`, `Server-Timing` and `/metrics` on, a fresh tenant key per run (unless `.env` sets one). |
| UI | `http://localhost:5173` | The Vite dev server, proxying `/v1` to the API. Skipped when pnpm is missing (`--no-ui`). |

It prints a banner with the URLs and what it found:

- **Upstream.** The mock, unless `PII_GUARD_UPSTREAM_BASE_URL` (environment or `.env`) names a
  real OpenAI-compatible upstream, or `BASETEN_API_KEY` is set (then Baseten Model APIs with
  Muse Spark Open). `uv run python scripts/demo.py --mock` forces the mock. `make demo-traffic`
  sends `model: pii-guard-mock`; set `PII_GUARD_DEMO_MODEL` for a real upstream. The demo
  traffic is fictional, so it may go to a hosted model.
- **Fast mode** uses rules + the distilled NER when `PII_GUARD_NER_MODEL` points to a checkpoint
  and the `ner` extra is installed (`uv sync --extra ner`), else rules only.
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
the model except in the one labelled scenario:

- **Names** are pre-loaded as session **known values** (`POST /v1/sessions`), the way an
  application that knows its parties would (a CRM record, a case file). The `known` detector
  then masks them in any inflected form, and the answer is restored in that form:
  `Teszt Eleknek`, `Teszt Elekkel`, `Minta Máriának` (a changed stem), `Placeholder Kft.-vel`.
  The `hu-known-values` scenario shows this round trip: `make demo-traffic` prints
  `restored exactly`, and the Live traffic tab shows the restored answer next to the masked
  one when the stack runs `uv run python scripts/demo.py --traffic-log full` (localhost only;
  the recorded replay is `masked`, so it shows the placeholders and their count).
- **Numbers** are checksum-valid fictional identifiers the rules find on their own: TAJ,
  adóazonosító jel, HU / GB / DE IBANs, a Luhn test card, phone numbers, e-mail addresses and
  a postal address.
- **`hu-needs-ner`, labelled "needs fast mode (NER)"**: a free-text name with no known value
  and no rule cue (`Tegnap Gipsz Jakab telefonált…`). In rules-only mode it reaches the mock
  model as written: an **expected miss**, kept on purpose to show what the NER adds.
  `make demo-traffic` prints it as such, and the Live traffic tab marks the call
  "needs fast mode (NER) · expected miss" with the reason.

**In fast mode with the NER** (`PII_GUARD_NER_MODEL` set, `uv sync --extra ner`) the labelled
name is masked too, and the tab says the NER ran.

### Smoke test

`make smoke` (`scripts/smoke.py`) starts the mock upstream and the API on ports 18790 / 18787
(the UI is not needed), sends the demo traffic and fails unless:

1. every answer comes back restored **exactly** (`Echo: <the original message>`, or tool
   arguments equal to `{"text": <the original message>}`);
2. no gold value of any scenario reached the upstream, raw, JSON-escaped or without spaces
   (the mock keeps what it received, `GET /_mock/received`). In rules-only mode that covers
   every scenario except the one labelled "needs fast mode (NER)": its name is printed as an
   expected miss, not a failure. With `PII_GUARD_NER_MODEL` set, its name must be masked too;
3. every call has a traffic event with a timing breakdown, and the log holds no raw session
   id and no credentials.

It runs in CI on every pull request. The same checks run in-process in
`tests/bench/test_bench.py`.

### Docker

```bash
docker compose --profile demo up --build
```

starts the same stack in containers: `mock-upstream`, `demo-api` on
`http://127.0.0.1:8788` (traffic log `masked`, `fast` mode) and `ui` on
`http://localhost:5173`, next to the plain `api` service on 8787. A real upstream:
`PII_GUARD_DEMO_UPSTREAM_URL` and `PII_GUARD_DEMO_UPSTREAM_API_KEY`. Inside a container the
server binds `0.0.0.0`, so the traffic log can only be `masked` there (see below). Send the demo
traffic with `uv run python scripts/demo_traffic.py --url http://127.0.0.1:8788`.

**OCR.** The image installs Tesseract with the Hungarian, English and German data
(`tesseract-ocr-hun`/`-eng`/`-deu`/`-osd`) and the `ocr` extra (`pytesseract`), so the text in
inline images (a TAJ, a name) is read and masked. That adds about 115 MB (the apt layer; the
image grew from about 269 MB to 429 MB in `docker image ls` on arm64). Without an OCR engine,
image parts are refused with `503 ocr_unavailable` (fail closed, ADR 0006): set
`PII_GUARD_IMAGE_REQUIRE_OCR=false` only if SAM-only masking is acceptable, which leaves text in
images unchecked (`X-PII-Guard-Image-OCR: off`). The container healthcheck checks `/healthz`
and OCR availability, and prints `ocr on|off` (`docker inspect --format
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
model 0.23 MB. The CI size budget (`scripts/ci/docker_smoke.sh`) went from 375 to 525 MB. `make demo` fetches it too. Elsewhere: `uv sync --extra local-vision`, then
`uv run python -m pii_guard.visual.segment fetch` (into `PII_GUARD_MODEL_DIR`, default
`~/.cache/pii-guard/models`). Model files are never committed.

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
  make the browser talk to a local pii-guard; its requests still carry that host name. Any other
  `Host` gets `400 Invalid host header`. The UI's Vite proxy sends `127.0.0.1:<port>`; behind a
  proxy or a compose service name (`demo-api`), add that name to `PII_GUARD_ALLOWED_HOSTS`.
- **The token is never forwarded upstream.** The gateway sends `PII_GUARD_UPSTREAM_API_KEY`
  upstream, never the client's token. Without an upstream key the client's own `Authorization`
  is passed through (bring your own key); a pii-guard token sent as the bearer is removed first,
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

Image values are registered in the vault session only when the whole request succeeded: the
work masks into a private fork of the session, committed afterwards. A refused or timed-out
image leaves nothing in the session, even while its thread is still finishing.

## Traffic log

Every call to `POST /v1/chat/completions` produces one event, kept **in memory only**, when the
traffic log is on:

| Setting | Values | Default |
|---|---|---|
| `PII_GUARD_TRAFFIC_LOG` | `off`, `masked`, `full` | `off` (`masked` in the demo) |
| `PII_GUARD_TRAFFIC_LOG_SIZE` | events kept (ring buffer) | `200` |

| Endpoint | What it returns |
|---|---|
| `GET /v1/traffic?limit=50&after=<seq>` | `{"level", "size", "events": [...]}`, oldest first |
| `GET /v1/traffic/stream?replay=10` | Server-sent events: one `traffic` event per call (`id:` = `seq`), a keep-alive comment every 15 s |

Both answer `404 traffic_log_disabled` while the log is off.

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
| `level` | `masked` or `full` |
| `outcome` | `ok`, `blocked` (a `block` policy), `refused` (any other error before or at the upstream), `upstream_error` (upstream HTTP >= 400), `stream_error`, `client_disconnected` (the client went away mid-stream; the partial answer does not seed the detection cache), `error` |
| `error` | `{"code", "status"}` and, for `blocked`, `entity_types` (counts) |
| `mode`, `language`, `stream`, `model` | As requested |
| `session_ref`, `session_new`, `session_source` | Hashed session (see above); whether the call started the conversation; which step chose it: `header`, `path`, `prompt_cache_key` or `default` ([architecture-gateway.md](architecture-gateway.md#sessions)) |
| `detectors` | Detectors that ran (`rules`, `ner`, `llm`, `known`, `visual`) |
| `entities` | `detected` and `masked` counts per entity type, number of texts; `images` (count, regions masked / kept, OCR) |
| `cache` | Detection cache `hits`, `misses`, `seeded` |
| `upstream` | HTTP status, the model it reported, `unresolved_placeholders` (placeholders the model invented) |
| `usage` | Token usage as the upstream reported it (streams: when `stream_options.include_usage` is set) |
| `timing` | See [Timing](#timing) |
| `request` | `masked` (the body sent upstream); `original` at level `full` |
| `response` | `masked` (the upstream's answer; streams: content per choice and the chunk count); `unmasked` at level `full` |

## Timing

The gateway times every request on the monotonic clock, from the moment the body has been
received until the answer is built (non-streamed) or the stream has ended:

| Stage (`timing.stages_ms`) | What it covers |
|---|---|
| `parse` | JSON, collecting the texts and images, request checks |
| `detect` | Every detector on every text (concurrent), then the session's known values; wall time |
| `image` | The visual pipeline (SAM, OCR) for inline images |
| `mask` | Vault masking of every text |
| `forward` | Serialising the masked body and opening the upstream client |
| `upstream_ttfb` | Send until the upstream's response headers |
| `upstream` | All time spent waiting on the upstream: headers, body or each stream read |
| `unmask` | Restoring a stream, summed over its chunks |
| `response` | Restoring a non-streamed answer and building the response |
| `client` | Streams: time spent handing each event to the client (its read speed, network backpressure); neither pii-guard's work nor the upstream's |

Derived fields:

- `total_ms`, `upstream_ms` and **`overhead_ms = total_ms - upstream_ms - client`**: what
  pii-guard added to the call. A slow-reading client makes a stream's `total_ms` longer, not
  its overhead.
- Streams: `ttft_ms` (to the first event sent to the client), `upstream_ttft_ms` (the
  upstream's own time from send to its first data event) and **`added_ttft_ms = ttft_ms -
  upstream_ttft_ms`**: the delay pii-guard added before the first token.
- `detectors_ms`: each detector's own time summed over the texts of the request. Texts run
  concurrently, so these can add up to more than the `detect` stage.

The client-side wall time is a little higher than `total_ms`: reading the request body and the
HTTP framing happen outside the timer.

**`Server-Timing` header** (`PII_GUARD_SERVER_TIMING=true`, off by default): the stages known
when the headers are sent, plus `upstream`, `overhead` and `total`, e.g.
`parse;dur=0.101, detect;dur=0.447, mask;dur=0.118, forward;dur=4.359, upstream_ttfb;dur=53.166, response;dur=0.114, upstream;dur=53.480, overhead;dur=5.246, total;dur=58.726`.
On a stream the header is sent before the answer, so it only covers the work up to the
upstream's response headers.

**Prometheus metrics** (`PII_GUARD_METRICS=true`, off by default) at `GET /metrics`:
`pii_guard_gateway_requests_total{mode,outcome}` and histograms (ms) of
`pii_guard_gateway_overhead_ms`, `_total_ms`, `_upstream_ms`, `_added_ttft_ms` per `mode`, and
`pii_guard_gateway_stage_ms{mode,stage}`. Labels are modes, stages and outcome codes only.

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
