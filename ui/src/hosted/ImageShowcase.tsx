import { useState, type ReactNode } from "react";
import { Boundary } from "../components/Boundary";
import { MaskedText } from "../components/MaskedText";
import { Pane } from "../components/Pane";
import { RestoredText } from "../components/RestoredText";
import { Metric, SegmentedControl } from "../components/ui";
import { SHOWCASE, type ShowcaseCard } from "../content/imageLabels";
import { metaFor } from "../lib/entities";
import { legendRows, MASK_PADDING, percentBox, regionColor, tint, zoomBox } from "../lib/imageRegions";
import { alignLoose, placeholderRegex } from "../lib/placeholders";
import { YourText } from "./Highlight";
import { LabelledCovers } from "./LabelledCovers";
import { restoredSegments } from "./landing";

// Annotated visual example with separately recorded OCR and text-only model answer.

/** The answer with each placeholder put back, from the message's own values (as /v1/unmask does). */
function restore(text: string, masked: string, message: string): string {
  const values = new Map<string, string>();
  for (const s of alignLoose(masked, message) ?? []) if (s.kind === "restored") values.set(s.placeholder, s.text);
  return text.replace(placeholderRegex(), (p) => values.get(p) ?? p);
}

function Figure({ card, alt, compact = false, children }: { card: ShowcaseCard; alt: string; compact?: boolean; children?: ReactNode }) {
  const { image } = card.recording;
  return (
    <div className="flex justify-center rounded-lg bg-surface-2 p-2 ring-1 ring-line">
      <div className={["@container relative w-full max-w-[44rem]", compact ? "max-sm:max-w-[15rem]" : ""].join(" ")}>
        <img src={card.sample.src} alt={alt} width={image.width} height={image.height} loading="lazy" decoding="async" className="block h-auto w-full rounded-sm" />
        {children}
      </div>
    </div>
  );
}

/**
 * The text column, enlarged: as printed on your side, and with the covers the model reads on its
 * side, so the two panes line up and the placeholders on the card can be read. The crop starts
 * right of a photo cover that ends before the text, and a photo cover reaching into the text
 * column is drawn without its label, so no stray tail of it shows at the left (L2 carryover 2).
 */

function Zoom({ card, masked: covered, className = "" }: { card: ShowcaseCard; masked: boolean; className?: string }) {
  const { image } = card.recording;
  const crop = zoomBox(image.regions, image.width, image.height);
  if (!crop) return null;
  const [x1, y1, x2, y2] = crop;
  const w = x2 - x1;
  const h = y2 - y1;
  return (
    <figure className={["space-y-1.5", className].join(" ")}>
      <figcaption><Caption>{covered ? "Enlarged: the details as the model reads them" : "Enlarged: the details as printed"}</Caption></figcaption>
      <div aria-hidden="true" className="relative mx-auto w-full max-w-[13rem] overflow-hidden rounded-md ring-1 ring-line" style={{ aspectRatio: `${w} / ${h}` }}>
        <div className="@container absolute" style={{ width: `${(image.width / w) * 100}%`, left: `${(-x1 / w) * 100}%`, top: `${(-y1 / h) * 100}%` }}>
          <img src={card.sample.src} alt="" width={image.width} height={image.height} loading="lazy" decoding="async" className="block h-auto w-full" />
          {covered && <LabelledCovers regions={image.regions} width={image.width} height={image.height} textLabelsOnly />}
        </div>
      </div>
    </figure>
  );
}

function Caption({ children }: { children: ReactNode }) {
  return <p className="font-mono text-2xs text-muted">{children}</p>;
}

const SPECIMENS = SHOWCASE.map((card, i) => ({ value: String(i), label: card.sample.language === "en" ? "English ID card" : "Hungarian ID card" }));

export default function ImageShowcase() {
  const [picked, setPicked] = useState("0");
  const card = SHOWCASE[Number(picked)]!;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p aria-hidden="true" className="text-sm font-medium text-ink">Specimen</p>
        <SegmentedControl label="Specimen" options={SPECIMENS} value={picked} onChange={setPicked} />
        <p className="text-xs text-muted">Annotated illustration · fictional, AI-generated and overprinted SPECIMEN.</p>
      </div>
      <Showcase key={card.sample.id} card={card} />
    </div>
  );
}

function Showcase({ card }: { card: ShowcaseCard }) {
  const { image, message, answer, recorded } = card.recording;
  const regions = image.regions;
  const masked = regions.filter((r) => r.policy === "mask");
  const tokenized = masked.filter((r) => r.source === "ocr" && r.placeholder);
  const summary = image.summary as { document_type?: string; holder?: string; document_number?: string; expired?: boolean };
  const restored = restore(answer.masked, message.masked, card.message);
  const day = new Date(`${recorded}T12:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  const rows = legendRows(regions);
  const box = (r: (typeof regions)[number]) => percentBox(r.box, image.width, image.height, MASK_PADDING);
  const types = tokenized.map((r) => metaFor(r.entity_type).label.toLowerCase());
  return (
    <div className="space-y-4">
      <div className="flex flex-col lg:flex-row lg:items-stretch">
        <Pane headingLevel={3} id="image-original" side="you" eyebrow="Stays with PII Guard" title="Your message and image" className="lg:flex-1" footer="Solid outlines: portrait and signature fixture annotations, not detector output. Dashed: recorded OCR and rules.">
          <div className="space-y-3">
            <YourText text={card.message} masked={message.masked} />
            <Figure card={card} alt={card.sample.alt} compact>
              {regions.map((r, i) => (
                <span key={i} aria-hidden="true" className="absolute rounded-sm" style={{ ...box(r), border: r.source === "ocr" ? `1px dashed ${regionColor(r)}` : `2px solid ${regionColor(r)}`, backgroundColor: r.policy === "mask" && r.source !== "ocr" ? tint(regionColor(r), 8) : "transparent" }} />
              ))}
            </Figure>
            <div className="grid grid-cols-[minmax(0,1fr)] gap-4 sm:grid-cols-[minmax(0,13rem)_minmax(0,1fr)]">
            <Zoom card={card} masked={false} className="max-sm:hidden" />
            <div className="min-w-0 space-y-1.5">
            <Caption>Regions in this illustration</Caption>
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
            </div>
          </div>
        </Pane>
        <Boundary direction="outbound" label="PII Guard boundary: only placeholders cross it">
          <dl className="space-y-1 text-center">
            <Metric label="regions covered" value={masked.length} className="min-w-12" />
            <Metric label="as placeholders" value={tokenized.length} className="min-w-12" />
          </dl>
        </Boundary>
        <Pane headingLevel={3} id="image-sent" side="model" eyebrow="Placeholders only" title="What the model gets" className="lg:flex-1" footer={`Annotated illustration: portrait and signature geometry comes from synthetic fixture annotations, not detector output. OCR and text were recorded ${day}. Live detection may differ.`}>
          <div className="space-y-3">
            <MaskedText text={message.masked} />
            <Figure card={card} alt={`The same card as the model gets it: the annotated portrait and signature covered, portrait labeled PHOTO with the holder's placeholder; the ${[...new Set(types)].join(", ")} each covered by a box printed with its placeholder. The expiry date, sex and nationality are not personal data and stay readable.${card.maskedNote ?? ""}`}>
              <LabelledCovers regions={regions} width={image.width} height={image.height} />
            </Figure>
            <div className="grid grid-cols-[minmax(0,1fr)] gap-4 sm:grid-cols-[minmax(0,13rem)_minmax(0,1fr)]">
            <Zoom card={card} masked />
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
        <Pane headingLevel={3} id="image-answer" side="model" eyebrow="Still placeholders" title="The model’s answer about the card" className="lg:flex-1" footer="Muse Spark’s earlier recorded answer, from the unchanged masked message, summary and transcript only; not a new run on this illustration.">
          <MaskedText text={answer.masked} />
        </Pane>
        <Boundary direction="inbound" label="PII Guard boundary: placeholders are restored on the way back" />
        <Pane headingLevel={3} id="image-restored" side="you" eyebrow="Real values put back" title="The answer, with the name back" className="lg:flex-1">
          <RestoredText segments={restoredSegments({ answer: answer.masked, restored, masked: message.masked, original: card.message })} />
        </Pane>
      </div>
    </div>
  );
}
