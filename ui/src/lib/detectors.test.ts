import { describe, expect, it } from "vitest";
import { detectorLabel } from "./entities";

describe("detectorLabel", () => {
  it("labels caption and MRZ region sources", () => {
    expect(detectorLabel("captions")).toBe("Field captions");
    expect(detectorLabel("mrz")).toBe("Machine-readable zone");
  });

  it("keeps the existing labels and the raw fallthrough", () => {
    expect(detectorLabel("rules")).toBe("Rules");
    expect(detectorLabel("unknown-detector")).toBe("unknown-detector");
  });
});
