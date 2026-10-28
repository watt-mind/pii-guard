// `GET /v1/status`: what the pii-guard server runs (src/pii_guard/api/routes/status.py).
// Configuration only, never a key or a value. Older servers answer 404: the screens then say
// what they can't know instead of guessing.

import { createProjectFetch } from "./project";
import type { EntityType } from "./types";
import type { Policy } from "../lib/entities";

export interface ModeStatus {
  detectors: string[];
  available: boolean;
  reason: string | null;
  model?: string | null;
}

export interface ServerStatus {
  version: string;
  gateway: {
    /** This server's gateway base URL, as the browser reached it (`…/v1`). */
    url: string;
    default_mode: string;
    modes: { fast: ModeStatus; audit: ModeStatus };
  };
  rest: { detectors: string[] };
  ner: { available: boolean; model: string | null };
  upstream: { configured: boolean; mock: boolean; origin: string | null };
  images: { segmenter: string; sam: boolean; ocr_required: boolean; gaps: string[]; available: boolean };
  policies: Partial<Record<EntityType, Policy>>;
  /** What this server offers the console (LAB-1431); older servers leave it out. */
  capabilities?: Partial<Record<string, boolean>>;
  auth: { token_required: boolean };
  default_language: string;
  traffic_log: "off" | "masked" | "full" | string;
  /** `PII_GUARD_VAULT_INSPECT`; absent on servers that predate the vault inspector. */
  vault_inspect?: "off" | "masked" | "full";
  metrics: boolean;
}

export type StatusResult =
  | { state: "ok"; status: ServerStatus }
  /** The server answers but predates `/v1/status`. */
  | { state: "missing" }
  | { state: "offline" };

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/** A status body from the wire, or null when it lacks what the screens read. */
export function parseStatus(raw: unknown): ServerStatus | null {
  if (!isRecord(raw) || !isRecord(raw.gateway) || !isRecord(raw.gateway.modes) || typeof raw.gateway.url !== "string") return null;
  const modes = raw.gateway.modes;
  if (!isRecord(modes.fast) || !isRecord(modes.audit) || !Array.isArray(modes.fast.detectors)) return null;
  if (!isRecord(raw.ner) || !isRecord(raw.upstream) || !isRecord(raw.images) || !isRecord(raw.policies)) return null;
  return raw as unknown as ServerStatus;
}

export async function fetchStatus(doFetch: typeof fetch = (...a) => fetch(...a), baseUrl = "", signal?: AbortSignal): Promise<StatusResult> {
  let res: Response;
  try {
    res = await createProjectFetch(doFetch)(`${baseUrl.replace(/\/$/, "")}/v1/status`, { headers: { Accept: "application/json" }, signal });
  } catch {
    return { state: "offline" };
  }
  if (res.status === 404 || res.status === 405) return { state: "missing" };
  if (!res.ok) return { state: "offline" };
  let body: unknown;
  try {
    body = JSON.parse(await res.text());
  } catch {
    return { state: "offline" };
  }
  const status = parseStatus(body);
  return status ? { state: "ok", status } : { state: "missing" };
}
