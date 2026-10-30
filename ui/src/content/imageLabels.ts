// The landing's labels-mode recording of the fictional specimen ID card (LAB-1484), made by
// scripts/record_image_labels.py with the real API configured like the hosted preview: the
// on-device segmenter (YuNet), Tesseract and the rules, signatures and stamps kept (ADR 0014),
// `render: "labels"`, in the vault session that masked the message below. Value-free: only
// placeholders, regions, the masked transcript and summary, and the masked answer.

import recording from "./imageLabelsRecording.json";
import recordingEn from "./imageLabelsRecording.en.json";
import type { ImageAnalysis, TypeCount } from "../api/types";
import type { LabelledRegion } from "../lib/imageRegions";
import { LANDING_IMAGE_SAMPLES, type ImageSample } from "./imageSamples";

export interface ImageLabelsRecording {
  recorded: string;
  message: { masked: string };
  image: {
    media_type: string;
    width: number;
    height: number;
    regions: LabelledRegion[];
    masked: TypeCount[];
    kept: TypeCount[];
    analysis: ImageAnalysis;
    transcript: string;
    summary: Record<string, unknown>;
    matches: Record<string, number>;
  };
  /** The model's masked answer; `model` names it (Muse Spark since LAB-1524). */
  answer: { masked: string; by: string; model?: string };
}

export const IMAGE_LABELS = recording as unknown as ImageLabelsRecording;

/**
 * The user's message as typed. It names the fictional holder printed on the card (already in
 * the sample's alt text); keep it in step with MESSAGE in scripts/record_image_labels.py.
 */
export const IMAGE_LABELS_MESSAGE = "Fiktív Mária is the seller. Is her ID card attached, and is it still valid?";

/** The English specimen's recording (LAB-1509), the landing's default; same script, `--sample en`. */
export const IMAGE_LABELS_EN = recordingEn as unknown as ImageLabelsRecording;
/** Its message; keep in step with SAMPLES["en"] in scripts/record_image_labels.py. */
export const IMAGE_LABELS_MESSAGE_EN = "Jane Placeholder is the seller. Is her ID card attached, and is it still valid?";

/** One card of the landing's image showcase: the sample, its recording and the message. */
export interface ShowcaseCard {
  sample: ImageSample;
  recording: ImageLabelsRecording;
  message: string;
  /** What the masked card's alt text adds about this recording's covers. */
  maskedNote?: string;
}

/** The landing's showcase cards, in `LANDING_IMAGE_SAMPLES` order: English first, the default. */
export const SHOWCASE: readonly ShowcaseCard[] = LANDING_IMAGE_SAMPLES.map((sample) =>
  sample.language === "en"
    ? { sample, recording: IMAGE_LABELS_EN, message: IMAGE_LABELS_MESSAGE_EN }
    : { sample, recording: IMAGE_LABELS, message: IMAGE_LABELS_MESSAGE, maskedNote: " The photo cover clips the expiry's first digit and also covers the signature." },
);
