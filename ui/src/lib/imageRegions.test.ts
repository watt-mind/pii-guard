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
    expect(sourceLabel({ ...taj, entity_type: "EMAIL" })).toBe("OCR + Rules");
    expect(sourceLabel({ ...taj, entity_type: "PERSON", detector: "llm" }, { llm: "muse-spark-1.3" })).toBe("OCR + Muse Spark 1.3 (Meta API)");
    expect(sourceLabel({ ...taj, entity_type: "PERSON", detector: "llm" })).toBe("OCR + LLM detector");
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
    expect(coverageGaps(analysis({ ran: false, engine: null, detectors: [], reason: "tesseract_unavailable" }))).toEqual([
      expect.stringMatching(/Text in this image was not checked at all/),
    ]);
    const rulesOnly = coverageGaps(analysis({}));
    expect(rulesOnly[0]).toMatch(/\(Rules \+ checksum\) do not look for names, dates of birth, organization names and parcel numbers/);
    expect(rulesOnly[1]).toMatch(/^Addresses are found only by pattern/);
    expect(coverageGaps(analysis({ detectors: ["rules", "llm"], models: { llm: "muse-spark-1.3" } }))).toEqual([]);
    expect(coverageGaps(analysis({ detectors: ["rules", "ner"] }))[0]).toMatch(/do not look for dates of birth and parcel numbers/);
    expect(samTargets(analysis({}))).toBe("faces, signatures, ID photos and stamps");
  });
});
