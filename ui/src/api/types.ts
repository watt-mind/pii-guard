// Wire types for the pii-guard REST API. Source of truth: docs/contracts.md
// ("REST API"). Keep this file in step with that section.

export const TEXT_ENTITY_TYPES = [
  "PERSON",
  "ADDRESS",
  "EMAIL",
  "PHONE",
  "DATE_OF_BIRTH",
  "NATIONAL_ID_HU_TAX",
  "NATIONAL_ID_HU_TAJ",
  "ID_DOCUMENT",
  "BANK_ACCOUNT",
  "COMPANY_ID_HU",
  "ORGANIZATION",
  "PARCEL_NUMBER_HU",
  "VEHICLE_PLATE",
] as const;

export const VISUAL_ENTITY_TYPES = ["FACE", "SIGNATURE", "ID_PHOTO", "STAMP"] as const;

export type TextEntityType = (typeof TEXT_ENTITY_TYPES)[number];
export type VisualEntityType = (typeof VISUAL_ENTITY_TYPES)[number];
export type EntityType = TextEntityType | VisualEntityType;

/** `Span.to_public_dict()`: offsets are code-point indices into the request text. No raw value. */
export interface PublicSpan {
  start: number;
  end: number;
  entity_type: EntityType;
  score: number;
  detector: string;
}

export interface AnalyzeRequest {
  text: string;
  language?: string;
}

export interface AnalyzeResponse {
  spans: PublicSpan[];
}

export interface MaskRequest {
  text: string;
  language?: string;
  session_id?: string | null;
}

export interface MaskedEntity {
  placeholder: string;
  entity_type: EntityType;
  count: number;
}

export interface MaskResponse {
  masked_text: string;
  session_id: string;
  entities: MaskedEntity[];
}

export interface UnmaskRequest {
  text: string;
  session_id: string;
}

export interface UnmaskResponse {
  text: string;
  unresolved: string[];
}

export interface HealthResponse {
  status: string;
  version: string;
}

export interface ErrorBody {
  error: { code: string; message: string };
}

/** `POST /v1/mask/image`: the image is sent as the raw body (PNG or JPEG). */
export interface ImageMaskRequest {
  image: Blob;
  /** Built-in sample id; lets the demo engine replay its recorded regions. Never sent. */
  sampleId?: string | null;
  language?: string;
}

export type RegionSource = "sam" | "ocr";
export type RegionPolicy = "mask" | "keep" | "block";

/** One region, as the API reports it: inclusive pixel corners, no value. */
export interface ImageRegion {
  entity_type: EntityType;
  box: [number, number, number, number];
  source: RegionSource;
  detector: string;
  score: number | null;
  policy: RegionPolicy;
}

export interface TypeCount {
  entity_type: EntityType;
  count: number;
}

export interface ImageAnalysis {
  sam: { model: string; entity_types: EntityType[] };
  ocr: { ran: boolean; engine: string | null; detectors: string[]; reason: string | null };
}

export interface ImageMaskResponse {
  /** The masked image, base64 PNG. Empty from the demo engine, which only replays regions. */
  image: string;
  media_type: string;
  width: number;
  height: number;
  regions: ImageRegion[];
  masked: TypeCount[];
  kept: TypeCount[];
  analysis: ImageAnalysis;
}

/** What every engine (live API or the built-in demo engine) offers the screens. */
export interface GuardClient {
  analyze(req: AnalyzeRequest): Promise<AnalyzeResponse>;
  mask(req: MaskRequest): Promise<MaskResponse>;
  unmask(req: UnmaskRequest): Promise<UnmaskResponse>;
  /** Optional so text-only engines (and test doubles) still fit. */
  maskImage?(req: ImageMaskRequest): Promise<ImageMaskResponse>;
}
