import type { EntityType, ImageAnalysis, ImageRegion } from "../api/types";
import { DETECTOR_TYPES, detectorLabel, metaFor } from "./entities";

/**
 * Outline colour of a region box, by what happened to it (not by type: the type is written on
 * the box). Drawn over the image itself, which is a light document in either theme, so these
 * tokens are the same in both themes.
 */
export function regionColor(region: Pick<ImageRegion, "policy">): string {
  return region.policy === "mask" ? "var(--region-mask)" : "var(--region-kept)";
}

export const tint = (color: string, pct: number) => `color-mix(in srgb, ${color} ${pct}%, transparent)`;

/** The server grows every filled box by this many pixels; the demo drawing does the same. */
export const MASK_PADDING = 2;

export interface PercentBox {
  left: string;
  top: string;
  width: string;
  height: string;
}

/** A region's inclusive pixel box as CSS percentages of the image, optionally padded and clipped. */
export function percentBox(box: ImageRegion["box"], width: number, height: number, pad = 0): PercentBox {
  const x1 = Math.max(0, box[0] - pad);
  const y1 = Math.max(0, box[1] - pad);
  const x2 = Math.min(width - 1, box[2] + pad);
  const y2 = Math.min(height - 1, box[3] + pad);
  const pct = (v: number, of: number) => `${((v / of) * 100).toFixed(3)}%`;
  return {
    left: pct(x1, width),
    top: pct(y1, height),
    width: pct(x2 - x1 + 1, width),
    height: pct(y2 - y1 + 1, height),
  };
}

/** Model ids per detector, as `analysis.ocr.models` reports them. */
export type DetectorModels = Readonly<Record<string, string>>;

export function sourceLabel(region: Pick<ImageRegion, "source" | "detector" | "entity_type">, models: DetectorModels = {}): string {
  if (region.source === "sam") return "SAM 3.1";
  if (region.source === "local") return "YuNet (on-device)";
  return `OCR + ${detectorLabel(region.detector, { types: [region.entity_type], model: models[region.detector] })}`;
}

export function policyLabel(policy: ImageRegion["policy"]): string {
  return policy === "mask" ? "masked" : policy === "keep" ? "kept by policy" : "blocked";
}

/** What a screen reader hears for one region; never a value (the API sends none). */
export function regionLabel(region: ImageRegion, models: DetectorModels = {}): string {
  return `${metaFor(region.entity_type).label}, found by ${sourceLabel(region, models)}, ${policyLabel(region.policy)}`;
}

export interface RegionSummary {
  found: number;
  masked: number;
  kept: number;
  sam: number;
  ocr: number;
}

export function summarizeRegions(regions: readonly ImageRegion[]): RegionSummary {
  return {
    found: regions.length,
    masked: regions.filter((r) => r.policy === "mask").length,
    kept: regions.filter((r) => r.policy === "keep").length,
    // Every segmenter region (SAM 3.1 or the on-device face detector), as opposed to OCR.
    sam: regions.filter((r) => r.source !== "ocr").length,
    ocr: regions.filter((r) => r.source === "ocr").length,
  };
}

export interface LegendRow {
  type: EntityType;
  count: number;
  sources: ImageRegion["source"][];
  kept: boolean;
}

/** One row per type, in order of first appearance, with where it came from. */
export function legendRows(regions: readonly ImageRegion[]): LegendRow[] {
  const rows = new Map<EntityType, LegendRow>();
  for (const r of regions) {
    const row = rows.get(r.entity_type) ?? { type: r.entity_type, count: 0, sources: [], kept: true };
    row.count += 1;
    if (!row.sources.includes(r.source)) row.sources.push(r.source);
    row.kept = row.kept && r.policy === "keep";
    rows.set(r.entity_type, row);
  }
  return [...rows.values()];
}

/** Plural nouns for coverage notes. */
export const TEXT_TYPE_NOUN: Partial<Record<EntityType, string>> = {
  PERSON: "names",
  ADDRESS: "addresses",
  EMAIL: "email addresses",
  PHONE: "phone numbers",
  DATE_OF_BIRTH: "dates of birth",
  NATIONAL_ID_HU_TAX: "tax IDs",
  NATIONAL_ID_HU_TAJ: "TAJ numbers",
  ID_DOCUMENT: "ID document numbers",
  BANK_ACCOUNT: "bank accounts",
  COMPANY_ID_HU: "company IDs",
  ORGANIZATION: "organization names",
  PARCEL_NUMBER_HU: "parcel numbers",
  VEHICLE_PLATE: "vehicle plates",
  SECRET: "secrets (API keys, tokens, passwords)",
};

function joinNouns(items: readonly string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/**
 * Plain-language gaps in what ran, derived from the detectors the API reports, so a missing
 * region reads as known scope, not a promise.
 */
export function coverageGaps(analysis: ImageAnalysis): string[] {
  if (!analysis.ocr.ran) {
    return [`Text in this image was not checked at all: OCR (Tesseract) is not installed on the API host, so only ${segmenterLabel(analysis.sam.model).replace(/^The /, "the ")} ran.`];
  }
  const full = new Set<EntityType>();
  const partly = new Set<EntityType>();
  for (const d of analysis.ocr.detectors) {
    DETECTOR_TYPES[d]?.types.forEach((t) => full.add(t));
    DETECTOR_TYPES[d]?.partly?.forEach((t) => partly.add(t));
  }
  const nouns = Object.entries(TEXT_TYPE_NOUN) as [EntityType, string][];
  const missing = nouns.filter(([t]) => !full.has(t) && !partly.has(t)).map(([, n]) => n);
  const someOnly = nouns.filter(([t]) => !full.has(t) && partly.has(t)).map(([, n]) => n);
  const models = analysis.ocr.models ?? {};
  const ran = analysis.ocr.detectors.map((d) => detectorLabel(d, { types: DETECTOR_TYPES[d]?.types, model: models[d] }));
  const gaps: string[] = [];
  if (missing.length) {
    gaps.push(`Text detectors on this run (${joinNouns(ran) || "none"}) do not look for ${joinNouns(missing)}, so any in the image were sent as they are.`);
  }
  if (someOnly.length) gaps.push(`${joinNouns(someOnly).replace(/^./, (c) => c.toUpperCase())} are found only by pattern (postcodes, street names).`);
  return gaps;
}

const VISUAL_LABEL: Partial<Record<EntityType, string>> = {
  FACE: "faces",
  SIGNATURE: "signatures",
  ID_PHOTO: "ID photos",
  STAMP: "stamps",
};

/** The segmenter that ran, from `analysis.sam.model` ("yunet-2023mar+sam-3.1"), never assumed. */
export function segmenterLabel(model: string | null | undefined): string {
  if (!model || model === "off") return "No segmenter";
  const parts = model.split("+").map((p) => (p.startsWith("sam-") ? `SAM ${p.slice(4)}` : p.startsWith("yunet") ? "the on-device face detector (YuNet)" : p));
  const text = joinNouns(parts);
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function samTargets(analysis: ImageAnalysis): string {
  const names = analysis.sam.entity_types.map((t) => VISUAL_LABEL[t] ?? metaFor(t).label.toLowerCase());
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

export type TagPlacement = "top-left" | "top-right" | "bottom-left" | "bottom-right";

/**
 * Where to put each SAM region's type tag so overlapping regions (a face inside an ID photo)
 * don't stack their tags on one corner. Greedy, in region order; OCR tags show on hover only.
 * `tagWidth`/`tagHeight` are the tag's rough size as a share of the image.
 */
export function tagPlacements(
  regions: readonly ImageRegion[],
  width: number,
  height: number,
  tagWidth = 0.16,
  tagHeight = 0.06,
): TagPlacement[] {
  const used: { x: number; y: number }[] = [];
  const near = (x: number, y: number) => used.some((u) => Math.abs(u.x - x) < tagWidth * width && Math.abs(u.y - y) < tagHeight * height);
  return regions.map((r) => {
    if (r.source === "ocr") return "top-left";
    const [x1, y1, x2, y2] = r.box;
    const options: [TagPlacement, number, number][] = [
      ["top-left", x1, y1],
      ["top-right", x2 - tagWidth * width, y1],
      ["bottom-left", x1, y2],
      ["bottom-right", x2 - tagWidth * width, y2],
    ];
    const pick = options.find(([, x, y]) => !near(x, y)) ?? options[0]!;
    used.push({ x: pick[1], y: pick[2] });
    return pick[0];
  });
}
