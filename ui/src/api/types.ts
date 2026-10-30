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
  "PAYMENT_CARD",
  "COMPANY_ID_HU",
  "ORGANIZATION",
  "PARCEL_NUMBER_HU",
  "VEHICLE_PLATE",
  "SECRET",
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
  /** The type's effective policy (`/v1/analyze`); absent from older APIs and the demo engine. */
  policy?: "mask" | "keep" | "block";
  /** Refines a type that covers several shapes: a `SECRET` span says `github_token`, `jwt` … (LAB-1257). */
  subtype?: string;
}

export interface AnalyzeRequest {
  text: string;
  language?: string;
  /** Previews the session's known values (spans with `detector: "known"`). */
  session_id?: string | null;
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
  /** Detected but left in place by a `keep` policy: type and count only. */
  kept?: TypeCount[];
}

/** A value the application already knows is sensitive (`POST /v1/sessions`). */
export interface KnownValue {
  value: string;
  entity_type: TextEntityType;
}

export interface KnownValuesResponse {
  session_id: string;
  added: number;
  total: number;
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

/** `sam`: SAM 3.1 (Meta API); `local`: the on-device face detector (YuNet); `ocr`: OCR + a text detector. */
export type RegionSource = "sam" | "local" | "ocr";
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
  /** `models`: model id per model-backed detector (`{"llm": "muse-spark-1.3"}`). */
  ocr: { ran: boolean; engine: string | null; detectors: string[]; models?: Record<string, string>; reason: string | null };
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
  /** `POST /v1/sessions` with pre-loaded known values. */
  createSession?(known_values: KnownValue[]): Promise<KnownValuesResponse>;
  /** `POST /v1/sessions/{id}/known-values`. */
  addKnownValues?(session_id: string, known_values: KnownValue[]): Promise<KnownValuesResponse>;
}
