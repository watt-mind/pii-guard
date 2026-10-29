import type { ReactNode } from "react";
import { Boundary } from "../components/Boundary";
import { MaskedText } from "../components/MaskedText";
import { Pane } from "../components/Pane";
import { RestoredText } from "../components/RestoredText";
import { Metric } from "../components/ui";
import { IMAGE_LABELS, IMAGE_LABELS_MESSAGE } from "../content/imageLabels";
import { DEFAULT_IMAGE_SAMPLE } from "../content/imageSamples";
import { metaFor } from "../lib/entities";
import { legendRows, MASK_PADDING, percentBox, regionColor, tint } from "../lib/imageRegions";
import { alignLoose, placeholderRegex } from "../lib/placeholders";
import { YourText } from "./Highlight";
import { LabelledCovers } from "./LabelledCovers";
import { restoredSegments } from "./landing";

/*
 * The landing's image showcase (LAB-1466, labels render LAB-1484), loaded on demand. The
 * fictional specimen ID card and a message naming its holder, masked in one vault session by
 * the real API with the hosted preview's setup (src/content/imageLabelsRecording.json): each
 * printed value is covered by a box carrying its placeholder, the photo and face are covered
 * solid, and the masked transcript and summary go with the image. The model's answer comes
 * back with the real name. Kept regions are outlined in --region-kept, as on the console's
 * Images screen; signatures and stamps are kept, as on the hosted preview (ADR 0014).
 */

const sample = DEFAULT_IMAGE_SAMPLE;
const { image, message, answer, recorded } = IMAGE_LABELS;
const regions = image.regions;
const masked = regions.filter((r) => r.policy === "mask");
const tokenized = masked.filter((r) => r.source === "ocr" && r.placeholder);
const summary = image.summary as { document_type?: string; holder?: string; document_number?: string; expired?: boolean };

/** The answer with each placeholder put back, from the message's own values (as /v1/unmask does). */
function restore(text: string): string {
  const values = new Map<string, string>();
  for (const s of alignLoose(message.masked, IMAGE_LABELS_MESSAGE) ?? []) if (s.kind === "restored") values.set(s.placeholder, s.text);
  return text.replace(placeholderRegex(), (p) => values.get(p) ?? p);
}

const restored = restore(answer.masked);
const day = new Date(`${recorded}T12:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

function Figure({ alt, children }: { alt: string; children?: ReactNode }) {
  return (
    <div className="flex justify-center rounded-lg bg-surface-2 p-2 ring-1 ring-line">
      <div className="@container relative w-full max-w-[44rem]">
        <img src={sample.src} alt={alt} width={image.width} height={image.height} loading="lazy" decoding="async" className="block h-auto w-full rounded-sm" />
        {children}
      </div>
    </div>
  );
}

/** The text covers' column, enlarged, so the placeholders printed on the card can be read. */
function Zoom() {
  const text = masked.filter((r) => r.source === "ocr" && r.cover_box);
  if (!text.length) return null;
  const pad = 14;
  const x1 = Math.max(0, Math.min(...text.map((r) => r.cover_box![0])) - pad);
  const y1 = Math.max(0, Math.min(...text.map((r) => r.cover_box![1])) - pad);
  const x2 = Math.min(image.width, Math.max(...text.map((r) => r.cover_box![2])) + pad);
  const y2 = Math.min(image.height, Math.max(...text.map((r) => r.cover_box![3])) + pad);
  const w = x2 - x1;
  const h = y2 - y1;
  return (
    <figure className="space-y-1.5">
      <figcaption><Caption>Enlarged: the details as the model reads them</Caption></figcaption>
      <div aria-hidden="true" className="relative mx-auto w-full max-w-[13rem] overflow-hidden rounded-md ring-1 ring-line" style={{ aspectRatio: `${w} / ${h}` }}>
        <div className="@container absolute" style={{ width: `${(image.width / w) * 100}%`, left: `${(-x1 / w) * 100}%`, top: `${(-y1 / h) * 100}%` }}>
          <img src={sample.src} alt="" width={image.width} height={image.height} loading="lazy" decoding="async" className="block h-auto w-full" />
          <LabelledCovers regions={regions} width={image.width} height={image.height} />
        </div>
      </div>
    </figure>
  );
}

function Caption({ children }: { children: ReactNode }) {
  return <p className="font-mono text-2xs text-muted">{children}</p>;
}

export default function ImageShowcase() {
  const rows = legendRows(regions);
  const box = (r: (typeof regions)[number]) => percentBox(r.box, image.width, image.height, MASK_PADDING);
  const types = tokenized.map((r) => metaFor(r.entity_type).label.toLowerCase());
  return (
    <div className="space-y-4">
      <div className="flex flex-col lg:flex-row lg:items-stretch">
        <Pane id="image-original" side="you" eyebrow="Stays with pii-guard" title="Your message and image" className="lg:flex-1" footer="Solid outlines: found by the on-device face detector. Dashed: text found by OCR and the rules.">
          <div className="space-y-3">
            <YourText text={IMAGE_LABELS_MESSAGE} masked={message.masked} />
            <Figure alt={sample.alt}>
              {regions.map((r, i) => (
                <span key={i} aria-hidden="true" className="absolute rounded-sm" style={{ ...box(r), border: r.source === "ocr" ? `1px dashed ${regionColor(r)}` : `2px solid ${regionColor(r)}`, backgroundColor: r.policy === "mask" && r.source !== "ocr" ? tint(regionColor(r), 8) : "transparent" }} />
              ))}
            </Figure>
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
        </Pane>
        <Boundary direction="outbound" label="pii-guard boundary: only placeholders cross it">
          <dl className="space-y-1 text-center">
            <Metric label="regions covered" value={masked.length} className="min-w-12" />
            <Metric label="as placeholders" value={tokenized.length} className="min-w-12" />
          </dl>
        </Boundary>
        <Pane id="image-sent" side="model" eyebrow="Placeholders only" title="What the model gets" className="lg:flex-1" footer={`Recorded ${day} by the real masker with the hosted preview's setup; the covers are drawn in your browser from the recorded boxes.`}>
          <div className="space-y-3">
            <MaskedText text={message.masked} />
            <Figure alt={`The same card as the model gets it: the photo and face covered, labelled PHOTO with the holder's placeholder; the ${[...new Set(types)].join(", ")} each covered by a box printed with its placeholder. The expiry date, sex and nationality are not personal data and stay readable, though the photo cover clips the expiry's first digit and also covers the signature.`}>
              <LabelledCovers regions={regions} width={image.width} height={image.height} />
            </Figure>
            <div className="grid grid-cols-[minmax(0,1fr)] gap-4 sm:grid-cols-[minmax(0,13rem)_minmax(0,1fr)]">
            <Zoom />
            <div className="min-w-0 space-y-1.5">
              <Caption>With the image: its document summary</Caption>
              <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
                <dt className="text-muted">Document</dt>
                <dd className="text-ink">{summary.document_type === "id_card" ? "ID card" : (summary.document_type ?? "unknown")}</dd>
                <dt className="text-muted">Holder</dt>
                <dd className="min-w-0"><MaskedText text={summary.holder ?? "not found"} /></dd>
                <dt className="text-muted">Document no.</dt>
                <dd className="min-w-0"><MaskedText text={summary.document_number ?? "not found"} /></dd>
                <dt className="text-muted">Expired</dt>
                <dd className="text-ink">{summary.expired ? "yes" : "no"}</dd>
              </dl>
              <details className="group rounded-md border border-line bg-surface-2/60 px-3 py-2">
                <summary className="cursor-pointer rounded-sm text-xs font-medium text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink">and its OCR transcript, masked</summary>
                <div className="mt-2 [&_.doc]:text-xs [&_.doc]:leading-relaxed"><MaskedText text={image.transcript} /></div>
              </details>
            </div>
            </div>
          </div>
        </Pane>
      </div>
      <div className="flex flex-col lg:flex-row lg:items-stretch">
        <Pane id="image-answer" side="model" eyebrow="Still placeholders" title="The model’s answer about the card" className="lg:flex-1" footer="A stand-in model, reading only the masked summary.">
          <MaskedText text={answer.masked} />
        </Pane>
        <Boundary direction="inbound" label="pii-guard boundary: placeholders are restored on the way back" />
        <Pane id="image-restored" side="you" eyebrow="Real values put back" title="The answer, with the name back" className="lg:flex-1">
          <RestoredText segments={restoredSegments({ answer: answer.masked, restored, masked: message.masked, original: IMAGE_LABELS_MESSAGE })} />
        </Pane>
      </div>
    </div>
  );
}
