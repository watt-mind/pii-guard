import type { ReactNode } from "react";
import type { ImageRegion } from "../api/types";
import { IMAGE_RECORDINGS } from "../api/imageMock";
import { Boundary } from "../components/Boundary";
import { Pane } from "../components/Pane";
import { Metric } from "../components/ui";
import { DEFAULT_IMAGE_SAMPLE } from "../content/imageSamples";
import { metaFor } from "../lib/entities";
import { legendRows, MASK_PADDING, percentBox, regionColor, tint } from "../lib/imageRegions";

/*
 * The landing's image showcase (LAB-1466), loaded on demand. The fictional specimen ID card
 * and the regions a real run recorded for it (src/content/imageRecordings.json), drawn the way
 * the console's Images screen draws them: masked regions outlined in --region-mask and filled
 * black on the model's side, kept ones outlined in --region-kept. Signatures and stamps are kept,
 * as on the hosted preview (ADR 0014).
 */

const IMAGE_FILL = "var(--image-mask-fill, #000)";
const KEPT_ON_HOSTED = new Set(["SIGNATURE", "STAMP"]);
const sample = DEFAULT_IMAGE_SAMPLE;
const recording = IMAGE_RECORDINGS.samples[sample.id]!;
const regions: ImageRegion[] = recording.regions.map((r) => (KEPT_ON_HOSTED.has(r.entity_type) ? { ...r, policy: "keep" } : r));
const masked = regions.filter((r) => r.policy === "mask");

function Figure({ alt, children }: { alt: string; children?: ReactNode }) {
  return (
    <div className="flex justify-center rounded-lg bg-surface-2 p-2 ring-1 ring-line">
      <div className="relative w-full max-w-[44rem]">
        <img src={sample.src} alt={alt} width={recording.width} height={recording.height} loading="lazy" decoding="async" className="block h-auto w-full rounded-sm" />
        {children}
      </div>
    </div>
  );
}

export default function ImageShowcase() {
  const rows = legendRows(regions);
  const box = (r: ImageRegion) => percentBox(r.box, recording.width, recording.height, MASK_PADDING);
  return (
    <div className="space-y-3">
      <div className="flex flex-col lg:flex-row lg:items-stretch">
        <Pane id="image-original" side="you" eyebrow="Stays with pii-guard" title="Your image" className="lg:flex-1" footer="Solid outlines: found by the segmenter. Dashed: text found by OCR and a detector.">
          <Figure alt={sample.alt}>
            {regions.map((r, i) => (
              <span key={i} aria-hidden="true" className="absolute rounded-sm" style={{ ...box(r), border: r.source === "ocr" ? `1px dashed ${regionColor(r)}` : `2px solid ${regionColor(r)}`, backgroundColor: r.policy === "mask" && r.source !== "ocr" ? tint(regionColor(r), 8) : "transparent" }} />
            ))}
          </Figure>
        </Pane>
        <Boundary direction="outbound" label="pii-guard boundary: only the masked image crosses it">
          <dl className="text-center">
            <Metric label="masked" value={masked.length} className="min-w-12" />
          </dl>
        </Boundary>
        <Pane id="image-sent" side="model" eyebrow="Masked image" title="What the model gets" className="lg:flex-1" footer="Recorded on 27 Oct 2026 from a run on this fictional specimen; the black boxes are drawn in your browser.">
          <Figure alt={`The same specimen with ${masked.length} regions covered in black (${masked.map((r) => metaFor(r.entity_type).label.toLowerCase()).join(", ")}). The signature is still visible.`}>
            {masked.map((r, i) => <span key={i} aria-hidden="true" className="absolute" style={{ ...box(r), backgroundColor: IMAGE_FILL }} />)}
          </Figure>
        </Pane>
      </div>
      <ul aria-label="Region legend" className="flex flex-wrap gap-1.5">
        {rows.map((row) => (
          <li key={row.type} className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-xs text-muted">
            <span aria-hidden="true" className={["size-2 rounded-full", row.kept ? "border border-dashed border-kept" : "bg-masked"].join(" ")} />
            <span className="font-medium text-ink">{metaFor(row.type).label}</span>
            <span className="tabular-nums">{row.count}</span>
            {row.kept && <span className="font-mono text-2xs text-kept-ink">kept</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
