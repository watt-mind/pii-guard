# PII Guard demo UI

A small web app that makes the guard visible: **what the model saw** next to **what you got
back**. It talks only to the PII Guard REST API (`/healthz`, `/v1/analyze`, `/v1/mask`,
`/v1/unmask`, `/v1/mask/image`, `/v1/traffic`, `/v1/status`, see [docs/contracts.md](../docs/contracts.md)). It never calls a
model provider and holds no secrets (SAM 3.1 is called by the PII Guard server).

## Run it

Requires Node 22+ and [pnpm](https://pnpm.io) (the version is pinned in `package.json`; with
Corepack, `corepack enable` picks it up).

```bash
cd ui
pnpm install
pnpm dev                      # http://127.0.0.1:5173
```

The dev server proxies `/v1` and `/healthz` to `http://127.0.0.1:8787`. To use the real
pipeline, start the API in another terminal from the repository root:

```bash
uv run pii-guard up --no-browser   # http://127.0.0.1:8787, mock upstream by default
```

Point the proxy somewhere else with `PII_GUARD_API_URL=http://host:port pnpm dev`.

## Demo mode

The UI works without the API. A built-in **demo engine** (a few checksum-validated rules and a
gazetteer of the fictional names in the samples, all in the browser) stands in when:

- the **Engine** selector at the bottom of the sidebar is set to **Demo engine**, or
- it is set to **Auto** (the default) and `/healthz` doesn't answer, or the `/v1` routes return
  404 because they haven't landed yet.

A **Demo mode** badge and banner are shown whenever the demo engine is in use; the dot next to
it shows the API status from `/healthz` (checked every 15 s, click to re-check). Set the
default at build time with `VITE_PII_GUARD_MODE=auto|api|mock`; a choice made in the sidebar is
remembered per browser.

A contract error from a live endpoint (for example `503 detection_failed`) is **not** a reason
to fall back: the guard failed closed, and the UI says that nothing was sent.

## Hosted build

`VITE_PII_GUARD_HOSTED=true` builds the hosted page. Anonymous visitors get the public landing
page; a signed-in owner gets this same console, scoped to their own projects, activity and
sessions. Sections are shown or hidden only by the server's capabilities
(`ui/src/lib/capabilities.ts`): `GET /v1/status` `capabilities` when the server reports them,
otherwise the defaults for the mode (hosted: text only, no server Policy, plus the account).
Sign-in returns to `#overview`.

## Screens

Dark theme, fast mode (rules + the published NER), mock upstream, fictional English data
(method: [DESIGN.md#screenshots](DESIGN.md#screenshots)). Click a screen for full size.

| | |
|---|---|
| [![Playground, Text tab, dark theme: a fictional English support email with every value highlighted, names included, and what the model saw with typed placeholders in their place](../docs/assets/demo/1-mask.webp)](../docs/assets/demo/1-mask.webp) | [![Playground, Chat tab, dark theme: a message sent through the gateway in fast mode; the model received placeholders for the names, email, phone and IBAN, and the echoed answer came back restored](../docs/assets/demo/2-chat.webp)](../docs/assets/demo/2-chat.webp) |
| [![Playground, Images tab, dark theme: a fictional English ID card masked on-device, the face and ID photo found by YuNet and the name, date of birth and document number found by OCR and the text detectors, each covered with its placeholder](../docs/assets/demo/3-images.webp)](../docs/assets/demo/3-images.webp) | [![Logs, dark theme: calls through the gateway with their entity types, and the latest call's details (fast mode, Multilingual NER and Rules, mock upstream) and timing](../docs/assets/demo/6-traffic.webp)](../docs/assets/demo/6-traffic.webp) |
| [![Overview, dark theme: the live latency charts, overhead per call, overhead by mode, where the time goes and values masked per minute](../docs/assets/demo/7-traffic-charts.webp)](../docs/assets/demo/7-traffic-charts.webp) | [![Evaluation, dark theme: the benchmark headline and every test set at a glance](../docs/assets/demo/4-benchmarks.webp)](../docs/assets/demo/4-benchmarks.webp) |

At phone width: [Text, what the model saw](../docs/assets/demo/5-mask-mobile.webp) ·
[Logs](../docs/assets/demo/8-traffic-mobile.webp). Connect:
[copyable commands per client](../docs/assets/demo/9-connect.webp).

Fresh Text, Chat, Images and public demo views use the existing English synthetic samples.
Language controls and Hungarian samples remain selectable; choosing a sample uses its language.
This presentation default does not change server defaults or saved project policy languages.

A console with a sidebar (a **Menu** button below 1024 px). Every section has its own hash, so
links, new tabs and the back button work; the old tab links (`#mask`, `#chat`, `#images`,
`#benchmarks`, `#traffic`) redirect to their new place.

1. **Overview** (`#overview`). What the guard protected, counted from the gateway's traffic log
   (`GET /v1/traffic` plus the live stream): requests, values masked, requests blocked,
   PII Guard's overhead (p50 and p95), the top entity types, latency per stage, and the live
   latency charts. Next to them, read from `GET /v1/status`: where the gateway forwards (the
   offline mock model or a real upstream, with the last call's HTTP status) and which detectors
   each mode runs (a warning when only the rules run, so free-text names are not masked). With
   no calls yet it says so and points to **Connect**, **Send demo traffic** and the Playground;
   nothing is estimated. **Watch a recorded demo** replays recorded calls in the browser,
   labelled as recorded, without the server's own panels next to them.
2. **Playground** (`#playground/text`, `/chat`, `/images`). Three tabs:
   - **Text**. *Mask a document*: load a fictional sample (Hungarian contract, insurance claim
     email, medical referral, an English support email) or paste text, pick the language, then
     mask it. Your document is shown with every detected entity highlighted by type; *What the
     model saw* shows the masked text with typed placeholders. Hover or tab to a highlight for
     its type, detector, subtype (for example the kind of secret) and confidence. **Known
     values** pre-loads values the application already knows
     (`POST /v1/sessions/{id}/known-values`). **Send it to the model** hands the document to
     Chat in the same session, so the same values keep the same placeholders. *Round trip*: a
     simulated answer, restored in one go or streamed in chunks, with unknown placeholders
     flagged.
   - **Chat**. A live chat through the gateway (`POST /v1/chat/completions` with
     `X-PII-Guard-Echo: masked`): per turn, *You wrote* / *What the model received* and *What
     the model answered* / *What you got back*. It says when the upstream is the offline mock
     (the model name is ignored) and warns when the server runs the rules only. The connection
     details show the session and how the gateway picked it (`X-PII-Guard-Session-Source`).
   - **Images**. Pick a fictional specimen document (ID card, health card, signed letter with
     a company stamp, visitor badge) or upload a PNG/JPEG, then mask it with
     `/v1/mask/image`. *Your image* outlines every region in its type's colour (solid: a
     segmenter, dashed: OCR text found by a detector); *What the model saw* is the masked PNG.
     A note says what ran and what did not (no OCR, no face detector, names not looked for).
     When the server can't mask images, the samples show regions recorded from a
     real SAM 3.1 run on the built-in samples (**Replay the recorded run instead**), without switching the engine.
3. **Logs** (`#logs`). Every call through the gateway as it happens: `GET /v1/traffic` for the
   backlog, then `GET /v1/traffic/stream` (SSE), falling back to polling. Per call: time, mode,
   entity chips, blocked/refused badges and the overhead; pick one for its details (mode,
   model, session and where it came from, detectors, detection cache), a timing waterfall, the
   **original request** (only at `PII_GUARD_TRAFFIC_LOG=full` *and* on localhost), the **masked
   request as sent upstream**, and the **response**, masked and restored. Pause, Clear (the
   server keeps its log), filters by mode, entity type and blocked/failed, and **Send demo
   traffic** (model `pii-guard-mock` by default, `VITE_PII_GUARD_DEMO_MODEL`).
4. **Connect** (`#connect`). The gateway base URL this server reports, and copyable steps per
   client: pi and Muse Code (`pii-guard connect … --gateway <url>`, then `--check`), the OpenAI
   SDK (`OPENAI_BASE_URL`), and curl. Claude Code is listed as not supported yet: it speaks the
   Anthropic Messages API, which the gateway doesn't serve.
5. **Policy** (`#policy`). Read-only, from `GET /v1/status`: the default mode, what fast and
   audit mode run (and why audit is unavailable), images, traffic log level, authentication,
   upstream, and the policy for every entity type (overrides from
   `PII_GUARD_POLICY_OVERRIDES` are marked *changed*). Without `/v1/status` it shows the
   documented defaults and says so.
6. **Evaluation** (`#evaluation`). The published benchmark results: the headline, charts and
   the results table per set and language.

When the API is unreachable (or the engine is set to Demo engine), Overview and Logs replay
calls recorded at level `masked` (`src/content/trafficFixture.json`): no original values, ever.

All sample data is fictional ([ADR 0005](../docs/decisions/0005-synthetic-data-only.md)).
Never paste real personal data into the demo.

## Develop

```bash
pnpm lint          # ESLint
pnpm typecheck     # tsc --noEmit
pnpm test --run    # Vitest + Testing Library (omit --run to watch)
pnpm build         # production build into dist/
pnpm preview       # serve dist/ on :4173 with the same proxy
```

CI runs the same commands (the `ui` job in `.github/workflows/ci.yml`) on changes under `ui/`:

```bash
pnpm install --frozen-lockfile && pnpm lint && pnpm typecheck && pnpm test --run && pnpm build
```

### Layout

| Path | Purpose |
|---|---|
| `src/api/types.ts` | Wire types for the REST contract |
| `src/api/http.ts` | Typed HTTP client; maps contract errors to `ApiError` |
| `src/api/mock.ts` | In-browser demo engine with the same interface |
| `src/api/engine.ts` | Chooses API or demo engine (auto / api / mock) |
| `src/lib/placeholders.ts` | Placeholder parsing, stream hold-back buffer, restore alignment |
| `src/lib/analysis.ts` | Code-point offsets, span ↔ placeholder linking, answer templates |
| `src/lib/stream.ts` | Chunked streaming simulation |
| `src/components/` | Highlighting, placeholders, legend, entity table, panes |
| `src/lib/routes.ts` | Sections, Playground tabs, hash routing and the old-link redirects |
| `src/components/Sidebar.tsx` | The sidebar: sections, engine badge and selector, theme |
| `src/api/status.ts`, `src/hooks/useServerStatus.ts` | `GET /v1/status`: what the server runs |
| `src/screens/Overview.tsx`, `Connect.tsx`, `Policy.tsx` | The Overview, Connect and Policy sections |
| `src/screens/` | Text (`Playground.tsx`), Chat, Round trip, Images, Benchmarks (Evaluation) |
| `src/api/chat.ts` | Gateway chat client (SSE + echo events) and the simulated demo chat |
| `src/components/KnownValues.tsx` | The known-values panel on the Mask screen |
| `src/content/samples.ts` | Fictional Hungarian sample documents and answers |
| `src/content/imageSamples.ts` | The fictional sample images (`public/samples/*.png`) |
| `src/content/imageRecordings.json` | Recorded `/v1/mask/image` regions for the demo engine |
| `src/api/imageMock.ts` | Demo image engine: replays recordings, refuses uploads |
| `src/lib/imageRegions.ts` | Region geometry, labels, legend rows, coverage notes |
| `src/screens/Images.tsx` | The Images screen |
| `src/api/traffic.ts` | Traffic log client: backlog, SSE stream, polling fallback, recorded-traffic replay |
| `src/hooks/useTraffic.ts` | Traffic state shared by Overview and Logs: source (API or recording), pause, clear |
| `src/lib/traffic.ts` | Timing waterfall, rolling percentiles, entity counts, reading event payloads |
| `src/screens/Traffic.tsx`, `TrafficCharts.tsx` | The Logs section, and the latency charts Overview shows |
| `src/api/demoTraffic.ts` | "Send demo traffic": the demo scenarios, sent from the browser |
| `src/content/trafficFixture.json` | Recorded masked-level traffic events for offline mode |

### Sample images

The PNGs in `public/samples/` are four Hungarian documents from the fictional specimen set in
`eval/fixtures/visual/` (Muse Image portraits, signatures and stamp; names and checksum-valid IDs
laid out by `eval/visual/generate_images.py`; overprinted MINTA / SPECIMEN; see its `NOTICE`).
To swap one, copy another document from that set and re-record the demo regions against a live
API:

```bash
cp eval/fixtures/visual/images/hu-id_card-front.png ui/public/samples/id-card.png
# API running with META_API_KEY and Tesseract; then for each sample:
curl -s --data-binary @ui/public/samples/id-card.png -H 'Content-Type: image/png' \
  http://127.0.0.1:8787/v1/mask/image   # copy the response, minus "image", into imageRecordings.json
```

Offsets from the API are code-point indices (Python `str`); the UI converts them to UTF-16
before slicing, so emoji and other non-BMP characters don't shift highlights.

## Public hosted shell

The local console remains the default. Build the public landing and scoped playground with:

```sh
VITE_PII_GUARD_HOSTED=true pnpm build
```

This is a build-time choice, not a query parameter. Serve the output on the same origin as
an API configured for hosted mode and Azure Google authentication (`/.auth/login/google`).
The public shell calls `/v1/account`, `/v1/demo`, scoped account key/connection routes,
and the existing models and streaming chat routes for authenticated custom text. It does
not expose global traffic, vault, operator settings, or a browser mock engine.

The initial walkthrough is an explicitly labelled, hand-written synthetic illustration.
A live run sends a curated `hu-support` or `en-support` id; it never sends editable guest
input and never replaces an API failure with a simulated success. Signed-in visitors can
edit text and select a temporary provider connection. Provider and guard API keys are held
only in component memory; they are never written to local/session storage. A created guard
key is shown once, then only metadata remains in the UI.

For local preview against a hosted API:

```sh
PII_GUARD_API_URL=http://127.0.0.1:8787 VITE_PII_GUARD_HOSTED=true pnpm dev --port 4185
```

The Vite development proxy covers API routes, not Azure's authentication endpoints. Google
sign-in must be verified on the deployed same-origin Azure site. The live guest run and
account controls require the companion hosted API; an unavailable API is shown visibly.
Static illustrations are not benchmark evidence. Source benchmark runs and methodology
are linked with their version/date context instead of copying an undated score.


### Landing narrative and availability

The landing compares two deployment modes. The open-source self-hosted full stack is
available: the customer operates the guard, dashboard and vault, and chooses the upstream.
Keeping every raw-data processing step local also requires local detectors and models;
some detector modes call remote services. The hosted gateway is a preview, not a publicly
live service. It receives raw prompts on the Azure-hosted guard, masks detected values and
then forwards the request upstream. These descriptions do not imply enterprise readiness.

The self-hosted stack supports text and image masking. Detected image text can share
pseudonyms with text in the same session; masked image pixels are not reversibly restored.
Remote detector services, including SAM segmentation, may receive original inputs. The
hosted preview currently exposes text only.

The copy describes privacy risk reduction and support for data minimisation, not automatic
GDPR or EU AI Act compliance. It distinguishes fail-closed processing errors from missed
detections, contextual identification and the limits of reversible pseudonymisation.
