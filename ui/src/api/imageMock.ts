// Demo engine for images. Segmentation runs on the server, so the browser cannot segment
// anything itself: for the built-in fictional samples it replays the regions a real run
// returned (src/content/imageRecordings.json), and it refuses uploads rather than
// pretending. The masked image is drawn by the UI from those regions (`image` is empty).

import englishRecording from "../content/imageLabelsRecording.en.json";
import recordings from "../content/imageRecordings.json";
import type { ImageMaskRequest, ImageMaskResponse } from "./types";

/** An upload in demo mode: there is no recording for it, and nothing is sent anywhere. */
export class DemoImageUnavailableError extends Error {
  constructor() {
    super("Uploaded images need the live API: image detection runs on the server.");
    this.name = "DemoImageUnavailableError";
  }
}

export interface ImageRecordings {
  recorded: string;
  samples: Record<string, Omit<ImageMaskResponse, "image">>;
}

// Reuse the English specimen's real local-detector run, retaining only the region response.
// Labels-mode placeholders and transcript belong to the landing showcase, not this replay.
const { media_type, width, height, masked, kept, analysis } = englishRecording.image;
export const IMAGE_RECORDINGS: ImageRecordings = {
  ...recordings as unknown as ImageRecordings,
  samples: {
    ...recordings.samples as unknown as ImageRecordings["samples"],
    "id-card-en": {
      media_type, width, height, masked, kept, analysis,
      regions: englishRecording.image.regions.map(({ entity_type, box, source, detector, score, policy }) =>
        ({ entity_type, box, source, detector, score, policy })),
    } as unknown as Omit<ImageMaskResponse, "image">,
  },
};

export const imageRecordedOn = (sampleId: string | null) =>
  sampleId === "id-card-en" ? englishRecording.recorded : IMAGE_RECORDINGS.recorded;

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
