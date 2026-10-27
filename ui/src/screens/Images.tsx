import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { effectiveEngine, type EngineKind, type EngineState, type RoutingClient } from "../api/engine";
import { DemoImageUnavailableError, IMAGE_RECORDINGS } from "../api/imageMock";
import type { ServerStatus } from "../api/status";
import type { ImageMaskRequest, ImageMaskResponse, ImageRegion } from "../api/types";
import { Boundary } from "../components/Boundary";
import { Pane } from "../components/Pane";
import { BlockedNotice, Button, EmptyState, Stat } from "../components/ui";
import { DEFAULT_IMAGE_SAMPLE, IMAGE_SAMPLES, MAX_UPLOAD_BYTES, UPLOAD_TYPES, type ImageSample } from "../content/imageSamples";
import { metaFor, modelLabel } from "../lib/entities";
import {
  MASK_PADDING,
  regionColor,
  tint,
  coverageGaps,
  legendRows,
  percentBox,
  policyLabel,
  regionLabel,
  samTargets,
  segmenterLabel,
  sourceLabel,
  summarizeRegions,
  tagPlacements,
  type TagPlacement,
} from "../lib/imageRegions";
import { toRunError, type RunError } from "../lib/run";

type Selection =
  | { kind: "sample"; key: string; sample: ImageSample }
  | { kind: "upload"; key: string; name: string; blob: Blob; url: string };

interface ImageResult {
  key: string;
  data: ImageMaskResponse;
  engine: EngineKind;
  ms: number;
}

type ImageError = RunError | { code: "demo_upload"; message: string };

interface Props {
  client: RoutingClient;
  /** For honest copy about uploads in demo mode. */
  engineState?: EngineState;
  /** Fetches a sample's bytes. Injectable for tests (jsdom has no static server). */
  loadImage?: (src: string) => Promise<Blob>;
  /**
   * Replays a sample's recorded regions (the demo engine's image call), without switching the
   * app's engine: the way out when the live pipeline refuses (LAB-1265).
   */
  replayRecorded?: (req: ImageMaskRequest) => Promise<ImageMaskResponse>;
  /** What the server's image pipeline can do (`/v1/status`), for honest copy (LAB-1294). */
  serverImages?: ServerStatus["images"] | null;
}

async function fetchImage(src: string): Promise<Blob> {
  const res = await fetch(src);
  if (!res.ok) throw new Error(`could not load ${src}`);
  return res.blob();
}

async function timed<T>(fn: () => Promise<T>): Promise<{ value: T; ms: number }> {
  const started = performance.now();
  const value = await fn();
  return { value, ms: Math.round(performance.now() - started) };
}

const sampleSelection = (sample: ImageSample): Selection => ({ kind: "sample", key: `sample:${sample.id}`, sample });

export function Images({ client, engineState, loadImage = fetchImage, replayRecorded, serverImages = null }: Props) {
  const [selection, setSelection] = useState<Selection>(() => sampleSelection(DEFAULT_IMAGE_SAMPLE));
  const [result, setResult] = useState<ImageResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<ImageError | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [active, setActive] = useState<number | null>(null);
  const [showRegions, setShowRegions] = useState(true);
  // Samples carry their language; an upload defaults to English and can be switched (LAB-1242).
  const [language, setLanguage] = useState<"hu" | "en">(DEFAULT_IMAGE_SAMPLE.language);
  const runId = useRef(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const uploadSeq = useRef(0);

  // Revoke the object URL of an upload once it is replaced.
  const uploadUrl = selection.kind === "upload" ? selection.url : null;
  useEffect(() => () => {
    if (uploadUrl) URL.revokeObjectURL(uploadUrl);
  }, [uploadUrl]);

  const fresh = result !== null && result.key === selection.key;
  const demo = engineState ? effectiveEngine(engineState) === "mock" : false;
  const manualDemoWithApiUp = engineState?.preference === "mock" && engineState.status.state === "online";
  const src = selection.kind === "sample" ? selection.sample.src : selection.url;
  const alt = selection.kind === "sample" ? selection.sample.alt : `Your upload: ${selection.name}`;

  const select = (next: Selection) => {
    runId.current++; // a pending run for the previous image is ignored
    setRunning(false);
    setSelection(next);
    setLanguage(next.kind === "sample" ? next.sample.language : "en");
    setError(null);
    setActive(null);
  };

  const onFile = (file: File | undefined) => {
    setUploadError(null);
    if (!file) return;
    if (!(UPLOAD_TYPES as readonly string[]).includes(file.type)) {
      setUploadError("Only PNG and JPEG images can be masked.");
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setUploadError(`That image is over ${MAX_UPLOAD_BYTES / 1024 / 1024} MB, the API's limit.`);
      return;
    }
    select({ kind: "upload", key: `upload:${++uploadSeq.current}`, name: file.name, blob: file, url: URL.createObjectURL(file) });
  };

  const run = async (target: Selection = selection, lang: "hu" | "en" = language) => {
    const id = ++runId.current;
    setRunning(true);
    setError(null);
    setActive(null);
    try {
      const { value: routed, ms } = await timed(async () => {
        const blob = target.kind === "sample" ? await loadImage(target.sample.src) : target.blob;
        return client.maskImage({
          image: blob,
          sampleId: target.kind === "sample" ? target.sample.id : null,
          language: lang,
        });
      });
      if (id !== runId.current) return;
      setResult({ key: target.key, data: routed.data, engine: routed.engine, ms });
    } catch (err) {
      if (id !== runId.current) return;
      setResult(null); // fail closed: never leave an older masked image on screen as current
      setError(err instanceof DemoImageUnavailableError ? { code: "demo_upload", message: err.message } : toRunError(err));
    } finally {
      if (id === runId.current) setRunning(false);
    }
  };

  // "Replay the recorded run instead": this sample only, from the bundled recording. The app's
  // engine stays as it is, so Text and Chat keep using the live API.
  const replay = async () => {
    if (!replayRecorded || selection.kind !== "sample") return;
    const target = selection;
    const id = ++runId.current;
    setRunning(true);
    setError(null);
    try {
      const { value, ms } = await timed(async () => replayRecorded({ image: await loadImage(target.sample.src), sampleId: target.sample.id, language }));
      if (id !== runId.current) return;
      setResult({ key: target.key, data: value, engine: "mock", ms });
    } catch (err) {
      if (id !== runId.current) return;
      setError(toRunError(err));
    } finally {
      if (id === runId.current) setRunning(false);
    }
  };

  const data = fresh ? result.data : null;
  const summary = useMemo(() => (data ? summarizeRegions(data.regions) : null), [data]);

  return (
    <div className="space-y-6">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight text-balance text-ink sm:text-3xl">Faces, signatures and ID numbers, covered before the image leaves.</h1>
        <p className="mt-2 text-sm text-pretty text-muted sm:text-base">
          {serverImages && !demo
            ? serverImages.sam
              ? "SAM 3.1 segments signatures and stamps, an on-device detector finds faces and ID photos; OCR plus the text detectors find identifiers printed in the image."
              : "An on-device detector finds faces and ID photos; OCR plus the text detectors find identifiers printed in the image. Signatures and stamps need SAM 3.1 (META_API_KEY on the server)."
            : "Faces, ID photos, signatures and stamps are segmented on the pii-guard server; OCR plus the text detectors find identifiers printed in the image."}{" "}
          Every masked region is filled solid, and the image is rebuilt from pixels, so no metadata leaves either.
        </p>
      </div>

      {serverImages && !serverImages.available && !demo && (
        <p role="note" className="rounded-xl border border-warn/40 bg-warn-soft px-4 py-3 text-sm text-ink">
          <strong className="font-semibold text-warn">This server refuses images right now (fail closed).</strong> {imageNeeds(serverImages.gaps)} The samples can still replay a
          recorded run.
        </p>
      )}

      <p className="sr-only" aria-live="polite">
        {running ? "Masking the image" : summary ? `Image masked: ${summary.masked} regions covered, ${summary.kept} kept` : ""}
      </p>

      <fieldset className="min-w-0">
        <legend className="mb-2 text-xs font-medium text-muted">Fictional samples, or your own image</legend>
        <div className="relative -mx-4 flex snap-x scroll-px-4 gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:grid sm:grid-cols-3 sm:overflow-visible sm:px-0 sm:pb-0 xl:grid-cols-5">
          {IMAGE_SAMPLES.map((s) => {
            const on = selection.kind === "sample" && selection.sample.id === s.id;
            return (
              <button
                key={s.id}
                type="button"
                aria-pressed={on}
                onClick={(e) => {
                  e.currentTarget.scrollIntoView?.({ block: "nearest", inline: "nearest", behavior: "smooth" });
                  const next = sampleSelection(s);
                  select(next);
                  void run(next, s.language); // one click: pick and mask
                }}
                className={[
                  "flex w-[15rem] shrink-0 snap-start items-center gap-3 rounded-lg border p-2 pr-3 text-left transition-colors sm:w-auto",
                  on ? "border-ink bg-surface" : "border-line hover:border-line-strong hover:bg-surface",
                ].join(" ")}
              >
                <img src={s.src} alt="" aria-hidden="true" className="size-12 shrink-0 rounded-md border border-line bg-surface-2 object-cover" />
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-ink">{s.title}</span>
                  <span className="block text-xs text-muted">{s.subtitle}</span>
                </span>
              </button>
            );
          })}
          <div className="flex w-[15rem] shrink-0 snap-start flex-col justify-center gap-1 sm:w-auto">
            <input
              ref={fileInput}
              id="image-upload"
              type="file"
              accept={UPLOAD_TYPES.join(",")}
              className="sr-only"
              tabIndex={-1}
              aria-hidden="true"
              onChange={(e) => {
                onFile(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
            <Button
              variant={selection.kind === "upload" ? "primary" : "secondary"}
              className="h-auto min-h-16 w-full flex-col !items-start gap-0 rounded-lg border-dashed px-3.5 py-2 text-left"
              aria-describedby="upload-hint"
              onClick={() => fileInput.current?.click()}
            >
              <span className="text-sm font-medium">{selection.kind === "upload" ? "Upload another image" : "Upload an image"}</span>
              <span id="upload-hint" className="max-w-full truncate text-xs font-normal opacity-75">
                {selection.kind === "upload" ? selection.name : demo ? "Needs the live API: masking runs on the server." : "PNG or JPEG, up to 10 MB. Fictional only."}
              </span>
            </Button>
          </div>
        </div>
        {uploadError && (
          <p role="alert" className="mt-2 text-sm text-danger">
            {uploadError}
          </p>
        )}
      </fieldset>

      <div className="flex flex-col lg:flex-row lg:items-stretch">
        <Pane
          id="image-input"
          side="you"
          eyebrow="Inside your network"
          title="Your image"
          className="lg:flex-1"
          actions={
            <>
              <label className="sr-only" htmlFor="image-language">
                Language of the text in the image
              </label>
              <select
                id="image-language"
                value={language}
                onChange={(e) => setLanguage(e.target.value as "hu" | "en")}
                className="h-9 rounded-lg border border-line bg-surface px-2 text-sm text-ink"
                title="Language of the text printed in the image: decides which rules run on its OCR text"
              >
                <option value="hu">Hungarian</option>
                <option value="en">English</option>
              </select>
              {data && data.regions.length > 0 && (
                <label className="inline-flex h-9 cursor-pointer items-center gap-2 rounded-lg px-2 text-sm text-muted hover:text-ink">
                  <input type="checkbox" checked={showRegions} onChange={(e) => setShowRegions(e.target.checked)} className="size-4 accent-[var(--guard)]" />
                  Show regions
                </label>
              )}
              <Button variant="primary" onClick={() => void run()} disabled={running}>
                {running ? "Masking…" : fresh ? "Run again" : "Mask image"}
                <span aria-hidden="true">→</span>
              </Button>
            </>
          }
          footer={
            data && data.regions.length > 0 ? (
              <span>Solid outlines: found by the segmenter. Dashed: text found by OCR and a detector. Hover, tap or tab to a region for its type.</span>
            ) : (
              <span>
                {error ? "Nothing left your network for this image." : src ? "Mask the image to see what the model would get." : "Pick a sample or upload a fictional image, then mask it."}
              </span>
            )
          }
        >
          <Figure src={src} alt={alt}>
            {data &&
              showRegions &&
              data.regions.map((r, i, all) => (
                <RegionBox key={i} region={r} models={data.analysis.ocr.models} index={i} width={data.width} height={data.height} active={active === i} onActive={setActive} tag={tagPlacements(all, data.width, data.height)[i] ?? "top-left"} />
              ))}
          </Figure>
        </Pane>

        <Boundary direction="outbound" label="pii-guard boundary: only the masked image crosses it">
          {summary && (
            <dl className="flex gap-3 text-center lg:flex-col lg:gap-2">
              <Stat label="found" value={summary.found} />
              <Stat label="masked" value={summary.masked} />
              <Stat label="kept" value={summary.kept} />
            </dl>
          )}
        </Boundary>

        <Pane
          id="image-model"
          side="model"
          eyebrow="Sent to the model"
          title="What the model saw"
          className="lg:flex-1"
          footer={
            data && result ? (
              result.engine === "api" ? (
                <span>The masked PNG exactly as the API returned it, re-encoded from pixels with no metadata. {result.ms} ms.</span>
              ) : (
                <span>Demo mode: regions recorded from a real SAM 3.1 + OCR run on this sample; the black boxes are drawn in your browser.</span>
              )
            ) : undefined
          }
        >
          {error ? (
            error.code === "demo_upload" ? (
              <DemoUploadNotice switchEngine={manualDemoWithApiUp} />
            ) : error.code === "invalid_image" || error.code === "unsupported_media_type" ? (
              <UnreadableNotice code={error.code} />
            ) : (
              <div className="space-y-3">
                <BlockedNotice error={error} />
                {serverImages && !serverImages.available && <p className="text-sm text-muted">{imageNeeds(serverImages.gaps)}</p>}
                {replayRecorded && selection.kind === "sample" && !demo && (
                  <Button onClick={() => void replay()} title="Shows the regions recorded from a live run on this sample. The engine stays on the live API.">
                    Replay the recorded run instead
                  </Button>
                )}
              </div>
            )
          ) : running ? (
            <Running />
          ) : data && result ? (
            <div className="space-y-4">
              {result.engine === "api" && data.image ? (
                <Figure src={`data:image/png;base64,${data.image}`} alt={`Masked image: ${summary?.masked ?? 0} regions covered.`} testId="masked-image">
                  {active !== null && data.regions[active] && <Highlight region={data.regions[active]} width={data.width} height={data.height} />}
                </Figure>
              ) : (
                <Figure src={src} alt={`Masked image (drawn in the browser): ${summary?.masked ?? 0} regions covered.`} testId="demo-masked-image">
                  {data.regions.map((r, i) =>
                    r.policy === "mask" ? (
                      <span key={i} aria-hidden="true" data-testid="demo-mask" className="absolute bg-black" style={percentBox(r.box, data.width, data.height, MASK_PADDING)} />
                    ) : null,
                  )}
                  {active !== null && data.regions[active] && <Highlight region={data.regions[active]} width={data.width} height={data.height} />}
                </Figure>
              )}
              <WhatRan data={data} engine={result.engine} />
            </div>
          ) : (
            <EmptyState title="Nothing has been sent yet" body="Mask the image to see exactly what would leave your network." />
          )}
        </Pane>
      </div>

      {data && result && !error && (
        <section aria-labelledby="regions-title" className="grid grid-cols-[minmax(0,1fr)] gap-6 rounded-xl border border-line bg-surface p-4 sm:p-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
          <div className="space-y-4">
            <div>
              <h2 id="regions-title" className="text-base font-semibold tracking-tight text-ink">
                Detected regions
              </h2>
              <p className="mt-1 text-sm text-muted">Blue regions were masked. Dashed grey regions were found but kept visible by policy (company stamps, by default). No region carries the text or pixels it covers.</p>
            </div>
            <ImageLegend regions={data.regions} activeType={active !== null ? (data.regions[active]?.entity_type ?? null) : null} />
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted">
              <dt>Engine</dt>
              <dd className="text-ink">{result.engine === "api" ? "pii-guard API" : "Demo engine (recorded regions)"}</dd>
              <dt>Segmentation</dt>
              <dd className="text-ink">
                {data.analysis.sam.model} · {summary?.sam ?? 0} {summary?.sam === 1 ? "region" : "regions"}
              </dd>
              <dt>Text (OCR)</dt>
              <dd className="text-ink">{data.analysis.ocr.ran ? `${data.analysis.ocr.engine} · ${summary?.ocr ?? 0} regions` : "off"}</dd>
              <dt>Image</dt>
              <dd className="tabular-nums text-ink">
                {data.width} × {data.height} px
              </dd>
            </dl>
          </div>
          <div className="min-w-0">
            <h3 className="mb-2 text-sm font-semibold text-ink">Region list</h3>
            <RegionTable regions={data.regions} models={data.analysis.ocr.models} active={active} onActive={setActive} />
          </div>
        </section>
      )}
    </div>
  );
}

function Figure({ src, alt, testId, children }: { src: string; alt: string; testId?: string; children?: ReactNode }) {
  return (
    <div className="flex justify-center rounded-lg bg-surface-2 p-2 ring-1 ring-line">
      <div className="relative w-full max-w-[44rem]" data-testid={testId}>
        <img src={src} alt={alt} className="block h-auto w-full rounded-sm" />
        {children}
      </div>
    </div>
  );
}

function RegionBox({
  region,
  models,
  index,
  width,
  height,
  active,
  onActive,
  tag,
}: {
  region: ImageRegion;
  models?: Record<string, string>;
  index: number;
  width: number;
  height: number;
  active: boolean;
  onActive: (i: number | null) => void;
  tag: TagPlacement;
}) {
  const meta = metaFor(region.entity_type);
  const color = regionColor(region);
  const kept = region.policy !== "mask";
  return (
    <button
      type="button"
      data-testid="region-box"
      aria-label={regionLabel(region, models)}
      aria-pressed={active}
      onMouseEnter={() => onActive(index)}
      onMouseLeave={() => onActive(null)}
      onFocus={() => onActive(index)}
      onBlur={() => onActive(null)}
      onClick={() => onActive(active ? null : index)}
      className="absolute rounded-sm transition-[box-shadow,background-color] focus-visible:outline-offset-1"
      style={{
        ...percentBox(region.box, width, height, MASK_PADDING),
        border: `2px ${region.source === "ocr" ? "dashed" : "solid"} ${color}`,
        backgroundColor: active ? tint(color, 20) : kept ? "transparent" : tint(color, 8),
        boxShadow: active ? `0 0 0 3px ${tint(color, 40)}` : undefined,
      }}
    >
      <span
        aria-hidden="true"
        className={[
          "absolute px-1 font-mono",
          tag.startsWith("top") ? "-top-[1.15rem] rounded-t" : "-bottom-[1.15rem] rounded-b",
          tag.endsWith("left") ? "left-[-2px]" : "right-[-2px]",
          " text-2xs leading-[1.1rem] font-semibold whitespace-nowrap text-white",
          // Text regions sit between lines of text: their tag would hide the line above.
          region.source === "ocr" && !active ? "hidden" : "",
        ].join(" ")}
        style={{ backgroundColor: color }}
      >
        {meta.label}
        {kept ? " · kept" : ""}
      </span>
    </button>
  );
}

function Highlight({ region, width, height }: { region: ImageRegion; width: number; height: number }) {
  const color = regionColor(region);
  return (
    <span
      aria-hidden="true"
      className="pointer-events-none absolute rounded-sm"
      style={{ ...percentBox(region.box, width, height, MASK_PADDING + 2), boxShadow: `0 0 0 3px ${color}` }}
    />
  );
}

function ImageLegend({ regions, activeType }: { regions: ImageRegion[]; activeType: string | null }) {
  const rows = legendRows(regions);
  if (rows.length === 0) return <p className="text-sm text-muted">No regions were found in this image.</p>;
  return (
    <ul aria-label="Region legend" className="flex flex-wrap gap-1.5">
      {rows.map((row) => (
        <li
          key={row.type}
          className={[
            "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition-colors",
            activeType === row.type ? "border-ink text-ink" : "border-line text-muted",
          ].join(" ")}
        >
          <span aria-hidden="true" className={["size-2 rounded-full", row.kept ? "border border-dashed border-kept" : "bg-masked"].join(" ")} />
          <span className="font-medium text-ink">{metaFor(row.type).label}</span>
          <span className="tabular-nums">{row.count}</span>
          {row.sources.map((s) => (
            <span key={s} className="rounded-sm bg-surface-2 px-1 font-mono text-2xs text-muted">
              {s === "sam" ? "SAM" : s === "local" ? "On-device" : "OCR"}
            </span>
          ))}
          {row.kept && <span className="font-mono text-2xs text-muted">kept</span>}
        </li>
      ))}
    </ul>
  );
}

function RegionTable({
  regions,
  models,
  active,
  onActive,
}: {
  regions: ImageRegion[];
  models?: Record<string, string>;
  active: number | null;
  onActive: (i: number | null) => void;
}) {
  if (regions.length === 0) {
    return <p className="py-4 text-sm text-muted">Nothing to list: the image went out re-encoded but otherwise unchanged.</p>;
  }
  return (
    <div role="region" aria-label="Region list (scrolls sideways)" tabIndex={0} className="overflow-x-auto rounded-lg border border-line focus-visible:outline-2 focus-visible:outline-ink">
      <table className="w-full min-w-[30rem] text-left text-sm">
        <thead className="bg-surface-2 text-xs text-muted">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">Type</th>
            <th scope="col" className="px-3 py-2 font-medium">Found by</th>
            <th scope="col" className="px-3 py-2 font-medium">Policy</th>
            <th scope="col" className="px-3 py-2 font-medium">Box (px)</th>
          </tr>
        </thead>
        <tbody>
          {regions.map((r, i) => (
            <tr
              key={i}
              tabIndex={0}
              aria-label={regionLabel(r, models)}
              data-active={active === i || undefined}
              onMouseEnter={() => onActive(i)}
              onMouseLeave={() => onActive(null)}
              onFocus={() => onActive(i)}
              onBlur={() => onActive(null)}
              className={["border-t border-line outline-none focus-visible:bg-surface-2", active === i ? "bg-surface-2" : ""].join(" ")}
            >
              <td className="px-3 py-2">
                <span className="inline-flex items-center gap-2 font-medium text-ink">
                  <span aria-hidden="true" className={["size-2 rounded-full", r.policy === "mask" ? "bg-masked" : "border border-dashed border-kept"].join(" ")} />
                  {metaFor(r.entity_type).label}
                </span>
              </td>
              <td className="px-3 py-2 text-muted">{sourceLabel(r, models)}</td>
              <td className="px-3 py-2">
                <span className={r.policy === "mask" ? "text-masked" : "text-muted"}>{policyLabel(r.policy)}</span>
              </td>
              <td className="px-3 py-2 font-mono text-xs text-muted tabular-nums">{r.box.join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Say exactly what ran, and what did not, so gaps read as known scope. */
function WhatRan({ data, engine }: { data: ImageMaskResponse; engine: EngineKind }) {
  const gaps = coverageGaps(data.analysis);
  const ocr = data.analysis.ocr;
  return (
    <div className="space-y-2" data-testid="image-scope-note">
      <div className="text-sm text-ink">
        <p>
          <span className="font-semibold">{segmenterLabel(data.analysis.sam.model)}</span> looked for {samTargets(data.analysis)}
          {ocr.ran ? (
            <>
              ; <span className="font-semibold">OCR</span> ({ocr.engine}) read the text for the detectors
            </>
          ) : null}
          .
          {ocr.ran && ocr.models?.llm ? (
            <>
              {" "}
              The OCR text also went to <span className="font-semibold">{modelLabel(ocr.models.llm)}</span>, an LLM detector that the pii-guard server calls.
            </>
          ) : null}
        </p>
        {engine === "mock" && (
          <p className="mt-0.5 text-muted">
            Recorded {IMAGE_RECORDINGS.recorded} from the live pipeline on this fictional sample. Nothing was sent anywhere just now.
          </p>
        )}
      </div>
      {gaps.map((g) => (
        <p key={g} role="note" className="rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-sm text-ink">
          <span className="font-semibold text-warn">Not covered · </span>
          {g}
        </p>
      ))}
    </div>
  );
}

function DemoUploadNotice({ switchEngine }: { switchEngine: boolean }) {
  return (
    <div role="alert" className="rounded-xl border border-warn/40 bg-warn-soft p-4 text-sm">
      <p className="font-semibold text-warn">Uploads need the live API.</p>
      <p className="mt-1 text-ink">Image masking runs on the pii-guard server, not in your browser. Your image was not sent anywhere.</p>
      <p className="mt-2 text-muted">
        {switchEngine ? (
          <>The API is up: switch <strong className="font-semibold text-ink">Engine</strong> in the header to <strong className="font-semibold text-ink">Live API</strong>, then mask the image again.</>
        ) : (
          <>
            Start it with <code className="rounded bg-surface px-1 font-mono text-xs">pii-guard up</code>, or try one of the samples, which replay a recorded run.
          </>
        )}
      </p>
    </div>
  );
}

function UnreadableNotice({ code }: { code: string }) {
  return (
    <div role="alert" className="rounded-xl border border-danger/40 bg-danger-soft p-4 text-sm">
      <p className="font-semibold text-danger">{code === "invalid_image" ? "This image couldn't be decoded." : "This file isn't a PNG or JPEG image."}</p>
      <p className="mt-1 text-ink">The guard rejected it before any detection ran, so nothing was sent to the model.</p>
      <p className="mt-2 text-muted">Try another PNG or JPEG file.</p>
    </div>
  );
}

function Running() {
  return (
    <div className="space-y-3" role="status">
      <div aria-hidden="true" className="aspect-[16/10] w-full rounded-lg bg-line motion-safe:animate-pulse" />
      <p className="text-sm text-muted">Segmenting the image and reading its text. This can take a few seconds.</p>
    </div>
  );
}

/** What the server's image pipeline is missing, phrased for a checkout and for `uvx` alike. */
function imageNeeds(gaps: readonly string[]): string {
  const parts: string[] = [];
  if (gaps.includes("ocr")) parts.push("the ocr extra");
  if (gaps.includes("tesseract")) parts.push("Tesseract (brew install tesseract, apt install tesseract-ocr)");
  if (gaps.includes("segmenter")) parts.push("a face detector (the local-vision extra, or META_API_KEY for SAM 3.1)");
  if (!parts.length) return "";
  return `It needs ${parts.join(", ")}. Restart with those extras; the pii-guard up banner prints the exact command.`;
}
