// The landing's labels-mode recording of the fictional specimen ID card (LAB-1484), made by
// scripts/record_image_labels.py with the real API configured like the hosted preview: the
// on-device segmenter (YuNet), Tesseract and the rules, signatures and stamps kept (ADR 0014),
// `render: "labels"`, in the vault session that masked the message below. Value-free: only
// placeholders, regions, the masked transcript and summary, and the masked answer.

import recording from "./imageLabelsRecording.json";
import type { ImageAnalysis, TypeCount } from "../api/types";
import type { LabelledRegion } from "../lib/imageRegions";

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
  answer: { masked: string; by: string };
}

export const IMAGE_LABELS = recording as unknown as ImageLabelsRecording;

/**
 * The user's message as typed. It names the fictional holder printed on the card (already in
 * the sample's alt text); keep it in step with MESSAGE in scripts/record_image_labels.py.
 */
export const IMAGE_LABELS_MESSAGE = "Fiktív Mária is the seller. Is her ID card attached, and is it still valid?";
