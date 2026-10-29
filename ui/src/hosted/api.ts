import { ApiError } from "../api/http";

export interface Connection { id: string; provider: string; origin: string; expires_at: string }
export interface GuardKey { id: string; name: string; prefix: string; created_at: string }
export interface Account {
  mode: "hosted"; authenticated: boolean;
  /** The signed-in owner: an opaque id today; a display name or email only if the server adds one. */
  principal?: { id: string; provider: string; name?: string; email?: string } | null;
  login_url: string; logout_url: string; tier: "anonymous" | "standard";
  providers: unknown[];
  /** The model the free (included) runs answer with, e.g. "muse-spark-1.3"; absent on an older server. */
  included_model?: string | null;
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
  const fallback = site ? " The recorded run is still shown." : "";
  if (error instanceof ApiError) {
    // Free runs on the included model are off (zero until the provider authorises them, docs/hosted.md).
    if (error.code === "sponsored_unavailable") return site ? "Free runs are paused right now. The recorded run is still shown below. Sign in to run your own text with your own model key." : "Free runs are paused right now. Connect your own model key, or try again later.";
    if (error.status === 401 || error.status === 403) return "Your session has ended. Sign in again, then retry.";
    if (error.status === 429) return site ? "Today’s free runs are used up, or requests are coming in too fast. The recorded run is still shown." : "The allowance is used up or requests are arriving too quickly. Check the reset time on Overview and retry later.";
    if (error.status === 410 || /expired|session|connection/.test(error.code)) return "This session or connection has expired. Reconnect your provider or start a fresh request.";
    if (error.status === 404) return `This hosted API feature is unavailable. Retry after the service is restored.${fallback}`;
    if (error.status === 400 || error.status === 422) return "The request was refused. Check the input and provider settings, then retry.";
    if (error.status === 502 || error.status === 503 || error.status === 504) return site ? "The guard or the model provider isn’t responding. Try again in a moment; the recorded run is still shown." : "The guard or model provider is unavailable. Retry later.";
  }
  return `The request didn’t complete. Check your connection and retry.${fallback}`;
}
