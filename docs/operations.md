# Operations: demo stack, traffic log and timing

How to run pii-guard end to end on one machine, watch what the gateway does to each LLM call,
and measure the latency it adds. Everything here works offline and free: a mock upstream
stands in for the model unless you configure a real one.

- [The demo stack](#the-demo-stack): `make demo`, `make demo-traffic`, `make smoke`, Docker
- [Traffic log](#traffic-log): `GET /v1/traffic`, the live stream, the privacy model
- [Timing](#timing): per-stage spans, overhead, `Server-Timing`, `/metrics`
- [Latency benchmark](#latency-benchmark): `pii-guard bench latency`

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
- **Strict mode** (header `X-PII-Guard-Mode: strict`) is available when an LLM detector key is
  set (`PII_GUARD_LLM_DETECTOR_API_KEY`, or `BASETEN_API_KEY`).

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
  private interface, as for every other endpoint.

### Event fields

| Field | Meaning |
|---|---|
| `id` | Request id, also sent back as `X-PII-Guard-Request-Id` on successful responses |
| `seq`, `time` | Order in this process; UTC timestamp |
| `level` | `masked` or `full` |
| `outcome` | `ok`, `blocked` (a `block` policy), `refused` (any other error before or at the upstream), `upstream_error` (upstream HTTP >= 400), `stream_error`, `error` |
| `error` | `{"code", "status"}` and, for `blocked`, `entity_types` (counts) |
| `mode`, `language`, `stream`, `model` | As requested |
| `session_ref`, `session_new` | Hashed session (see above); whether the call started the conversation |
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

Derived fields:

- `total_ms`, `upstream_ms` and **`overhead_ms = total_ms - upstream_ms`**: what pii-guard
  added to the call.
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
uv run pii-guard bench latency --modes fast,strict --strict-requests 10 --record my-change
```

It starts the mock upstream with a fixed delay (`--upstream-delay-ms`, default 50) and the API
on free loopback ports, and sends a fixed fictional corpus (8 hu / en / de messages, one per
request, each in a new session so the detection cache never helps) through the gateway: N
requests per cell (`--requests`, default 200; `--strict-requests`, default 12, because each one
calls the LLM detector), for every mode, concurrency (`--concurrency 1,8`) and streaming
setting. Per cell it reports p50 / p95 / p99 / mean of the overhead, added time to first token,
every stage and detector, and the client's wall time.

`--record SLUG` writes one run record per mode (`kind: latency`,
`eval/results/runs/<date>-<SLUG>-<mode>.json`, same schema as the evaluation runs);
`uv run pii-guard eval report` then adds them to the **Gateway latency** section and chart of
[benchmarks.md](benchmarks.md). Strict mode uses the configured LLM detector
(`PII_GUARD_LLM_DETECTOR_*`); keep the request count small on a paid endpoint.

Overhead is machine-dependent: compare runs on the same hardware (the record names it).
