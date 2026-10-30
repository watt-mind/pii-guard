// Demo engine for images. Segmentation runs on the server, so the browser cannot segment
// anything itself: for the built-in fictional samples it replays the regions a real run
// returned (src/content/imageRecordings.json), and it refuses uploads rather than
// pretending. The masked image is drawn by the UI from those regions (`image` is empty).

import englishRecording from "../content/imageLabelsRecording.en.json";
import hungarianRecording from "../content/imageLabelsRecording.json";
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

// Reuse each specimen's real local-detector run (LAB-1260, LAB-1488), retaining only the
// region response. Labels-mode placeholders and transcript belong to the landing showcase,
// not this replay. The bundled SAM-era entry for the Hungarian card left the surname
// without a region box; the fresh local-detector recording covers both name lines.
const stripToRegions = (recording: typeof englishRecording | typeof hungarianRecording) => ({
  media_type: recording.image.media_type,
  width: recording.image.width,
  height: recording.image.height,
  masked: recording.image.masked,
  kept: recording.image.kept,
  analysis: recording.image.analysis,
  regions: recording.image.regions.map(({ entity_type, box, source, detector, score, policy }) =>
    ({ entity_type, box, source, detector, score, policy })),
});
export const IMAGE_RECORDINGS: ImageRecordings = {
  ...recordings as unknown as ImageRecordings,
  samples: {
    ...recordings.samples as unknown as ImageRecordings["samples"],
    "id-card-en": stripToRegions(englishRecording) as unknown as Omit<ImageMaskResponse, "image">,
    "id-card": stripToRegions(hungarianRecording) as unknown as Omit<ImageMaskResponse, "image">,
  },
};

export const imageRecordedOn = (sampleId: string | null) =>
  sampleId === "id-card-en"
    ? englishRecording.recorded
    : sampleId === "id-card"
      ? hungarianRecording.recorded
      : IMAGE_RECORDINGS.recorded;

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
