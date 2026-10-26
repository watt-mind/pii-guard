// Demo engine for images. SAM 3.1 runs on the server, so the browser cannot segment
// anything itself: for the built-in fictional samples it replays the regions a real run
// returned (src/content/imageRecordings.json), and it refuses uploads rather than
// pretending. The masked image is drawn by the UI from those regions (`image` is empty).

import recordings from "../content/imageRecordings.json";
import type { ImageMaskRequest, ImageMaskResponse } from "./types";

/** An upload in demo mode: there is no recording for it, and nothing is sent anywhere. */
export class DemoImageUnavailableError extends Error {
  constructor() {
    super("Uploaded images need the live API: SAM 3.1 runs on the server.");
    this.name = "DemoImageUnavailableError";
  }
}

export interface ImageRecordings {
  recorded: string;
  samples: Record<string, Omit<ImageMaskResponse, "image">>;
}

export const IMAGE_RECORDINGS = recordings as unknown as ImageRecordings;

export interface MockImageOptions {
  latencyMs?: number;
  recordings?: ImageRecordings;
}

export function createMockImageEngine(options: MockImageOptions = {}) {
  const latency = options.latencyMs ?? 0;
  const source = options.recordings ?? IMAGE_RECORDINGS;
  return {
    async maskImage(req: ImageMaskRequest): Promise<ImageMaskResponse> {
      const recorded = req.sampleId ? source.samples[req.sampleId] : undefined;
      if (latency > 0) await new Promise((r) => setTimeout(r, latency));
      if (!recorded) throw new DemoImageUnavailableError();
      return { ...structuredClone(recorded), image: "" };
    },
  };
}
