# pii-guard demo UI

A small web app that makes the guard visible: **what the model saw** next to **what you got
back**. It talks only to the pii-guard REST API (`/healthz`, `/v1/analyze`, `/v1/mask`,
`/v1/unmask`, `/v1/mask/image`, see [docs/contracts.md](../docs/contracts.md)). It never calls a
model provider and holds no secrets (SAM 3.1 is called by the pii-guard server).

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
uv run pii-guard serve        # http://127.0.0.1:8787
```

Point the proxy somewhere else with `PII_GUARD_API_URL=http://host:port pnpm dev`.

## Demo mode

The UI works without the API. A built-in **demo engine** (a few checksum-validated rules and a
gazetteer of the fictional names in the samples, all in the browser) stands in when:

- the engine selector in the header is set to **Demo engine**, or
- it is set to **Auto** (the default) and `/healthz` doesn't answer, or the `/v1` routes return
  404 because they haven't landed yet.

A **Demo mode** badge and banner are shown whenever the demo engine is in use; the dot next to
it shows the API status from `/healthz` (checked every 15 s, click to re-check). Set the
default at build time with `VITE_PII_GUARD_MODE=auto|api|mock`; a choice made in the header is
remembered per browser.

A contract error from a live endpoint (for example `503 detection_failed`) is **not** a reason
to fall back: the guard failed closed, and the UI says that nothing was sent.

## Screens

1. **Playground.** Load a fictional sample (property sale contract, insurance claim email,
   medical referral) or paste text, then mask it. Your document is shown with every detected
   entity highlighted by type; *What the model saw* shows the masked text with typed
   placeholders. Hover or tab to any highlight to see its type, detector and confidence; the
   matching placeholder lights up on the other side. Below: the entity legend and the
   placeholder map (placeholder ↔ type ↔ count). Original values appear only in the input pane.
2. **Round trip.** A simulated model answer that refers to people only by placeholders (edit
   it freely, or add a placeholder the model "invented"). **Restore** unmasks it in one go;
   **Stream** feeds it in small chunks and shows placeholders split across chunks being held
   back, then restored, as they arrive. Unknown placeholders are left visible and flagged.
3. **Images.** Pick a fictional sample image (ID card, signed letter with a company stamp,
   visitor badge) or upload a PNG/JPEG, then mask it. *Your image* shows every region the API
   found, outlined in its type's colour (solid: SAM 3.1 segmentation, dashed: OCR text found by
   a detector; a tag on each SAM box, OCR tags on hover/focus); *What the model saw* shows the
   masked PNG exactly as `/v1/mask/image` returned it. Below: a legend (type, count, SAM/OCR,
   kept) and the region list (type, source, policy, box). Hover, tap or tab to a region to link
   both sides. A note says what ran, and what did not: OCR off on the API host, or names not
   looked for because only the rules detector runs.

   In demo mode the samples replay regions **recorded from a real run** (SAM 3.1 on the Meta
   API + Tesseract + rules, `src/content/imageRecordings.json`) and the black boxes are drawn
   in the browser; uploads are refused, because SAM runs on the server.

   For the live pipeline the API needs `META_API_KEY` (SAM 3.1) and, for text in images,
   `uv sync --extra ocr` plus the `tesseract` binary with `hun` and `eng` data.

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

CI runs the same commands (`.github/workflows/ui.yml`) on changes under `ui/`:

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
| `src/screens/` | Playground and Round trip |
| `src/content/samples.ts` | Fictional Hungarian sample documents and answers |
| `src/content/imageSamples.ts` | The fictional sample images (`public/samples/*.png`) |
| `src/content/imageRecordings.json` | Recorded `/v1/mask/image` regions for the demo engine |
| `src/api/imageMock.ts` | Demo image engine: replays recordings, refuses uploads |
| `src/lib/imageRegions.ts` | Region geometry, labels, legend rows, coverage notes |
| `src/screens/Images.tsx` | The Images screen |
| `scripts/render_samples.py` | Draws the sample images with Pillow |

### Sample images

The PNGs in `public/samples/` are drawn by `scripts/render_samples.py` (ellipse faces, pen
scribbles, a two-circle stamp, fictional names and checksum-valid fictional IDs). After changing
a drawing, re-render and re-record the demo regions against a live API:

```bash
uv run python ui/scripts/render_samples.py
# API running with META_API_KEY and Tesseract; then for each sample:
curl -s --data-binary @ui/public/samples/id-card.png -H 'Content-Type: image/png' \
  http://127.0.0.1:8787/v1/mask/image   # copy the response, minus "image", into imageRecordings.json
```

Offsets from the API are code-point indices (Python `str`); the UI converts them to UTF-16
before slicing, so emoji and other non-BMP characters don't shift highlights.
