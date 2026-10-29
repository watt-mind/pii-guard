import { describe, expect, it } from "vitest";
import type { ImageAnalysis, ImageRegion } from "../api/types";
import { IMAGE_LABELS, IMAGE_LABELS_MESSAGE } from "../content/imageLabels";
import { alignLoose, placeholderRegex } from "./placeholders";
import { coverageGaps, labelCovers, legendRows, percentBox, regionLabel, samTargets, sourceLabel, summarizeRegions, type LabelledRegion } from "./imageRegions";

const face: ImageRegion = { entity_type: "FACE", box: [10, 20, 59, 69], source: "sam", detector: "sam", score: null, policy: "mask" };
const taj: ImageRegion = { entity_type: "NATIONAL_ID_HU_TAJ", box: [0, 0, 9, 9], source: "ocr", detector: "rules", score: 1, policy: "mask" };
const stamp: ImageRegion = { entity_type: "STAMP", box: [60, 60, 99, 99], source: "sam", detector: "sam", score: null, policy: "keep" };

const analysis = (ocr: Partial<ImageAnalysis["ocr"]>): ImageAnalysis => ({
  sam: { model: "sam-3.1", entity_types: ["FACE", "SIGNATURE", "ID_PHOTO", "STAMP"] },
  ocr: { ran: true, engine: "tesseract", detectors: ["rules"], reason: null, ...ocr },
});

describe("image regions", () => {
  it("counts on-device face regions as segmenter regions, not OCR", () => {
    const local: ImageRegion = { ...face, source: "local", detector: "yunet", score: 0.9 };
    expect(summarizeRegions([local, taj])).toMatchObject({ sam: 1, ocr: 1 });
    expect(legendRows([local])[0]?.sources).toEqual(["local"]);
  });

  it("turns inclusive pixel boxes into percentages, padded and clipped", () => {
    expect(percentBox([10, 20, 59, 69], 100, 100)).toEqual({ left: "10.000%", top: "20.000%", width: "50.000%", height: "50.000%" });
    expect(percentBox([0, 0, 99, 99], 100, 100, 2)).toEqual({ left: "0.000%", top: "0.000%", width: "100.000%", height: "100.000%" });
  });

  it("labels regions without values", () => {
    expect(sourceLabel(face)).toBe("SAM 3.1");
    expect(sourceLabel({ ...face, source: "local", detector: "yunet" })).toBe("YuNet (on-device)");
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

describe("tagPlacements", () => {
  it("moves the tag of a region nested in another off the shared corner", async () => {
    const { tagPlacements } = await import("./imageRegions");
    const region = (box: [number, number, number, number]) =>
      ({ entity_type: "FACE", box, source: "sam", detector: "sam", score: 0.9, policy: "mask" }) as const;
    const tags = tagPlacements([region([100, 100, 300, 400]), region([110, 110, 290, 380])], 1000, 600);
    expect(tags[0]).toBe("top-left");
    expect(tags[1]).not.toBe("top-left");
  });
});

describe("labels render (LAB-1484)", () => {
  it("draws labelled covers at the server's size, the nested photo label once", () => {
    const photo: LabelledRegion = { ...face, entity_type: "ID_PHOTO", box: [0, 0, 79, 89], source: "local", label: "PHOTO · [[PERSON_ab12cd]]", cover_box: [0, 0, 81, 91], label_lines: ["PHOTO · [[PERSON_ab12cd]]"], label_px: 20 };
    const inner: LabelledRegion = { ...photo, entity_type: "FACE", box: [10, 10, 49, 59], cover_box: [8, 8, 51, 61], label_px: 10 };
    const name: LabelledRegion = { ...taj, entity_type: "PERSON", label: "[[PERSON_ab12cd]]", cover_box: [0, 0, 39, 9], label_lines: ["PERSON", "ab12cd"], label_px: 5 };
    const covers = labelCovers([photo, inner, name, stamp], 200, 100);
    expect(covers.map((c) => c.lines)).toEqual([["PHOTO · [[PERSON_ab12cd]]"], [], ["PERSON", "ab12cd"]]);
    expect(covers[0]).toMatchObject({ visual: true, fontCqw: 10, box: { left: "0.000%", width: "41.000%" } });
    expect(covers[2]?.visual).toBe(false);
    // The photo's label sits in the strip below the face, not across its border (LAB-1488).
    expect(covers[0]?.labelBox).toEqual(percentBox([0, 62, 81, 91], 200, 100));
    expect(covers[1]?.labelBox).toBeUndefined();
    expect(covers[2]?.labelBox).toBeUndefined();
  });

  it("ships a value-free labels recording whose placeholders tie the image to the text", () => {
    const { image, message, answer } = IMAGE_LABELS;
    const holder = /\[\[PERSON_[0-9a-f]+\]\]/.exec(message.masked)?.[0];
    expect(holder).toBeTruthy();
    expect(image.summary.holder).toBe(holder);
    expect(image.regions.filter((r) => r.source === "ocr" && r.entity_type === "PERSON").every((r) => r.placeholder === holder)).toBe(true);
    expect(image.regions.filter((r) => r.source !== "ocr").every((r) => r.policy === "mask")).toBe(true);
    expect(answer.masked).toContain(holder);
    // The message as typed aligns with its masked form, and its name is nowhere in the recording.
    const aligned = alignLoose(message.masked, IMAGE_LABELS_MESSAGE);
    const names = (aligned ?? []).flatMap((s) => (s.kind === "restored" ? [s.text] : []));
    expect(names).toHaveLength(1);
    const blob = JSON.stringify(IMAGE_LABELS);
    // The surname is also an ordinary word the card prints in its footer ("fiktív minta"), so check the full name and the given name.
    const name = names[0]!;
    expect(blob.toLowerCase()).not.toContain(name.toLowerCase());
    expect(blob.toLowerCase()).not.toContain(name.split(" ").at(-1)!.toLowerCase());
    for (const p of image.transcript.match(placeholderRegex()) ?? []) expect(image.regions.some((r) => r.placeholder === p)).toBe(true);
  });
});

