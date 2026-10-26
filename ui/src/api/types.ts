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

/** What every engine (live API or the built-in demo engine) offers the screens. */
export interface GuardClient {
  analyze(req: AnalyzeRequest): Promise<AnalyzeResponse>;
  mask(req: MaskRequest): Promise<MaskResponse>;
  unmask(req: UnmaskRequest): Promise<UnmaskResponse>;
}
