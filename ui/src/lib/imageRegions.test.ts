import { describe, expect, it } from "vitest";
import type { ImageAnalysis, ImageRegion } from "../api/types";
import { coverageGaps, legendRows, percentBox, regionLabel, samTargets, sourceLabel, summarizeRegions } from "./imageRegions";

const face: ImageRegion = { entity_type: "FACE", box: [10, 20, 59, 69], source: "sam", detector: "sam", score: null, policy: "mask" };
const taj: ImageRegion = { entity_type: "NATIONAL_ID_HU_TAJ", box: [0, 0, 9, 9], source: "ocr", detector: "rules", score: 1, policy: "mask" };
const stamp: ImageRegion = { entity_type: "STAMP", box: [60, 60, 99, 99], source: "sam", detector: "sam", score: null, policy: "keep" };

const analysis = (ocr: Partial<ImageAnalysis["ocr"]>): ImageAnalysis => ({
  sam: { model: "sam-3.1", entity_types: ["FACE", "SIGNATURE", "ID_PHOTO", "STAMP"] },
  ocr: { ran: true, engine: "tesseract", detectors: ["rules"], reason: null, ...ocr },
});

describe("image regions", () => {
  it("turns inclusive pixel boxes into percentages, padded and clipped", () => {
    expect(percentBox([10, 20, 59, 69], 100, 100)).toEqual({ left: "10.000%", top: "20.000%", width: "50.000%", height: "50.000%" });
    expect(percentBox([0, 0, 99, 99], 100, 100, 2)).toEqual({ left: "0.000%", top: "0.000%", width: "100.000%", height: "100.000%" });
  });

  it("labels regions without values", () => {
    expect(sourceLabel(face)).toBe("SAM 3.1");
    expect(sourceLabel(taj)).toBe("OCR + Rules + checksum");
    expect(regionLabel(stamp)).toBe("Stamp, found by SAM 3.1, kept by policy");
  });

  it("summarizes and builds legend rows", () => {
    expect(summarizeRegions([face, taj, stamp])).toEqual({ found: 3, masked: 2, kept: 1, sam: 2, ocr: 1 });
    expect(legendRows([face, taj, stamp, face])).toEqual([
      { type: "FACE", count: 2, sources: ["sam"], kept: false },
      { type: "NATIONAL_ID_HU_TAJ", count: 1, sources: ["ocr"], kept: false },
      { type: "STAMP", count: 1, sources: ["sam"], kept: true },
    ]);
  });

  it("states what was not covered", () => {
    expect(coverageGaps(analysis({ ran: false, engine: null, detectors: [], reason: "tesseract_unavailable" }))[0]).toMatch(/Text in this image was not checked/);
    expect(coverageGaps(analysis({}))[0]).toMatch(/Names in the image were not looked for.*Rules \+ checksum only/);
    expect(coverageGaps(analysis({ detectors: ["rules", "llm"] }))).toEqual([]);
    expect(samTargets(analysis({}))).toBe("faces, signatures, ID photos and stamps");
  });
});
