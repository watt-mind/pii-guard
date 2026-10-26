import type { EntityType, ImageAnalysis, ImageRegion } from "../api/types";
import { DETECTOR_LABEL, metaFor } from "./entities";

/** Outline colour per type, matching the swatches in ENTITY_META (Tailwind 500/400). */
export const REGION_COLOR: Record<EntityType, string> = {
  PERSON: "#8b5cf6",
  ADDRESS: "#f59e0b",
  EMAIL: "#0ea5e9",
  PHONE: "#14b8a6",
  DATE_OF_BIRTH: "#f43f5e",
  NATIONAL_ID_HU_TAX: "#6366f1",
  NATIONAL_ID_HU_TAJ: "#d946ef",
  ID_DOCUMENT: "#f97316",
  BANK_ACCOUNT: "#10b981",
  COMPANY_ID_HU: "#94a3b8",
  ORGANIZATION: "#a8a29e",
  PARCEL_NUMBER_HU: "#84cc16",
  VEHICLE_PLATE: "#06b6d4",
  FACE: "#ec4899",
  SIGNATURE: "#a855f7",
  ID_PHOTO: "#ef4444",
  STAMP: "#a1a1aa",
};

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

export function sourceLabel(region: Pick<ImageRegion, "source" | "detector">): string {
  if (region.source === "sam") return "SAM 3.1";
  return `OCR + ${DETECTOR_LABEL[region.detector] ?? region.detector}`;
}

export function policyLabel(policy: ImageRegion["policy"]): string {
  return policy === "mask" ? "masked" : policy === "keep" ? "kept by policy" : "blocked";
}

/** What a screen reader hears for one region; never a value (the API sends none). */
export function regionLabel(region: ImageRegion): string {
  return `${metaFor(region.entity_type).label}, found by ${sourceLabel(region)}, ${policyLabel(region.policy)}`;
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
    sam: regions.filter((r) => r.source === "sam").length,
    ocr: regions.filter((r) => r.source === "ocr").length,
  };
}

export interface LegendRow {
  type: EntityType;
  count: number;
  sources: ("sam" | "ocr")[];
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

const NAME_DETECTORS = ["llm", "ner"];

/** Plain-language gaps in what ran, so a missing region reads as known scope, not a promise. */
export function coverageGaps(analysis: ImageAnalysis): string[] {
  const gaps: string[] = [];
  if (!analysis.ocr.ran) {
    gaps.push(
      "Text in this image was not checked: OCR (Tesseract) is not installed on the API host, so only SAM 3.1 ran.",
    );
  } else if (!analysis.ocr.detectors.some((d) => NAME_DETECTORS.includes(d))) {
    gaps.push(
      "Names in the image were not looked for: they need the Llama or NER detector, and this run used " +
        `${analysis.ocr.detectors.map((d) => DETECTOR_LABEL[d] ?? d).join(", ") || "no text detector"} only.`,
    );
  }
  return gaps;
}

const VISUAL_LABEL: Partial<Record<EntityType, string>> = {
  FACE: "faces",
  SIGNATURE: "signatures",
  ID_PHOTO: "ID photos",
  STAMP: "stamps",
};

export function samTargets(analysis: ImageAnalysis): string {
  const names = analysis.sam.entity_types.map((t) => VISUAL_LABEL[t] ?? metaFor(t).label.toLowerCase());
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}
