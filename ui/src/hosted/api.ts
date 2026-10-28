import { ApiError } from "../api/http";

export interface Connection { id: string; provider: string; origin: string; expires_at: string }
export interface GuardKey { id: string; name: string; prefix: string; created_at: string }
export interface Account {
  mode: "hosted"; authenticated: boolean;
  /** The signed-in owner: an opaque id today; a display name or email only if the server adds one. */
  principal?: { id: string; provider: string; name?: string; email?: string } | null;
  login_url: string; logout_url: string; tier: "anonymous" | "standard";
  providers: unknown[];
  limits: Record<string, number | string | boolean | null>;
  usage: { requests_today: number; resets_at: string };
  state: { persistence: "ephemeral"; restart_loses_sessions: boolean };
  connections: Connection[];
}
export interface DemoResult {
  sample_id: string; language: "hu" | "en"; original: string; masked: string;
  answer: string; restored: string; entities: { start: number; end: number; type: string }[];
  model: string; session_id: string; request_id: string;
}
export type Requester = <T>(path: string, body?: unknown, method?: "GET" | "POST" | "PUT" | "DELETE") => Promise<T>;

/** Same-origin only. Never expose server messages which could echo sensitive input. */
export const createRequester = (doFetch: typeof fetch): Requester => async <T>(path: string, body?: unknown, method?: "GET" | "POST" | "PUT" | "DELETE"): Promise<T> => {
  const response = await doFetch(path, {
    method: method ?? (body === undefined ? "GET" : "POST"),
    credentials: "same-origin",
    headers: { Accept: "application/json", ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(180_000),
  });
  if (!response.ok) {
    let code = "unavailable";
    try { const payload = await response.json(); if (typeof payload?.error?.code === "string") code = payload.error.code; } catch { /* A proxy error isn't a successful API response. */ }
    throw new ApiError(response.status, code, "The request could not complete.");
  }
  if (response.status === 204) return undefined as T;
  try { return await response.json() as T; } catch { throw new Error("unavailable"); }
};

export const request = createRequester((...args) => fetch(...args));

/**
 * What to do after a failed hosted request, by status only (never server text). The console's
 * screens get the default copy; the public page passes `"site"`, which also points to its static
 * walkthrough, because only that page has one.
 */
export function recovery(error: unknown, context: "console" | "site" = "console"): string {
  const site = context === "site";
  const fallback = site ? " The static example remains available." : "";
  if (error instanceof ApiError) {
    if (error.status === 401 || error.status === 403) return "Your session is no longer authorized. Sign in again, then retry.";
    if (error.status === 429) return site ? "The live allowance is used up or requests are arriving too quickly. Check the reset time below and retry later; the static example remains available." : "The allowance is used up or requests are arriving too quickly. Check the reset time on Overview and retry later.";
    if (error.status === 410 || /expired|session|connection/.test(error.code)) return "This session or connection has expired. Reconnect your provider or start a fresh request.";
    if (error.status === 404) return `This hosted API feature is unavailable. Retry after the service is restored.${fallback}`;
    if (error.status === 400 || error.status === 422) return "The request was refused. Check the input and provider settings, then retry.";
    if (error.status === 502 || error.status === 503 || error.status === 504) return site ? "The guard or model provider is unavailable. No completed live result is available. Retry later or inspect the static example." : "The guard or model provider is unavailable. Retry later.";
  }
  return `The hosted API could not complete this request. Check your connection and retry.${fallback}`;
}
