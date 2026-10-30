// `POST /v1/account/first-run` (LAB-1455): the signed-in owner's default endpoint, provisioned
// once by the server, and its first endpoint key, shown once. The raw key lives only in this
// page's memory: never in browser storage, gone on reload (the endpoint keeps only a hash).

import type { Endpoint } from "../projects/api";
import type { Requester } from "./api";

export type FirstRunState = "ready" | "needs_key" | "disabled";

export interface IssuedKey {
  id: string;
  name: string;
  key: string;
  created_at: string;
}

export interface FirstRun {
  project_id: string;
  endpoint: Endpoint;
  state: FirstRunState;
  created: boolean;
  active_keys: number;
  key: IssuedKey | null;
  sponsored_enabled: boolean;
  gateway_url: string;
}

export const FIRST_RUN_PATH = "/v1/account/first-run";
/** Where the snippets read the endpoint key from (`snippets.ENDPOINT_KEY_ENV`). */
export const ENDPOINT_KEY_ENV = "PII_GUARD_ENDPOINT_KEY";
/** Where an owner gets their own Meta Model API key. */
export const META_KEY_URL = "https://dev.meta.ai";

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

export function parseFirstRun(raw: unknown): FirstRun | null {
  if (!isRecord(raw) || !isRecord(raw.endpoint) || typeof raw.endpoint.id !== "string" || typeof raw.project_id !== "string") return null;
  if (raw.state !== "ready" && raw.state !== "needs_key" && raw.state !== "disabled") return null;
  const key = isRecord(raw.key) && typeof raw.key.key === "string" && raw.key.key.startsWith("pg_ep_") ? (raw.key as unknown as IssuedKey) : null;
  return {
    project_id: raw.project_id,
    endpoint: raw.endpoint as unknown as Endpoint,
    state: raw.state,
    created: raw.created === true,
    active_keys: typeof raw.active_keys === "number" ? raw.active_keys : 0,
    key,
    sponsored_enabled: raw.sponsored_enabled === true,
    gateway_url: typeof raw.gateway_url === "string" ? raw.gateway_url : "",
  };
}

async function post(call: Requester, body: Record<string, unknown>): Promise<FirstRun> {
  const parsed = parseFirstRun(await call<unknown>(FIRST_RUN_PATH, body));
  if (!parsed) throw new Error("unavailable");
  return parsed;
}

// One in-flight first run per page: StrictMode's double effects and the console's remounts
// share it, so the key issued at first sign-in is never issued and then dropped unseen.
let pendingRead: { call: Requester; promise: Promise<FirstRun> } | null = null;
let shownKey: (IssuedKey & { endpoint: string }) | null = null;

/** Provision (server-side, once) the default endpoint and its first key, and describe them. */
export function loadFirstRun(call: Requester): Promise<FirstRun> {
  if (pendingRead?.call !== call) {
    const promise = post(call, { issue_key: true }).then((r) => remember(r));
    pendingRead = { call, promise };
    // A failed read is asked again next time.
    promise.catch(() => {
      if (pendingRead?.promise === promise) pendingRead = null;
    });
  }
  return pendingRead.promise;
}

/** The owner's own Meta key for a `needs_key` endpoint, sent once and kept by the server only. */
export async function addMetaKey(call: Requester, metaApiKey: string): Promise<FirstRun> {
  const result = remember(await post(call, { meta_api_key: metaApiKey, issue_key: true }));
  pendingRead = { call, promise: Promise.resolve(result) };
  return result;
}

function remember(result: FirstRun): FirstRun {
  if (result.key) shownKey = { ...result.key, endpoint: result.endpoint.id };
  return result;
}

/** The key this page was shown, until the owner dismisses it or reloads. */
export const getShownKey = (endpoint: string): IssuedKey | null => (shownKey?.endpoint === endpoint ? shownKey : null);
export function rememberKey(endpoint: string, key: IssuedKey) {
  shownKey = { ...key, endpoint };
}
export function forgetShownKey() {
  shownKey = null;
}

/** For tests: start a fresh page. */
export function resetFirstRun() {
  pendingRead = null;
  shownKey = null;
}

/** Whether an endpoint can answer now: sponsored needs the sponsored route, own-key a credential. */
export function endpointState(endpoint: Pick<Endpoint, "enabled" | "provider" | "credential_configured">, sponsoredEnabled: boolean): FirstRunState {
  if (!endpoint.enabled) return "disabled";
  if (endpoint.provider === "sponsored") return sponsoredEnabled ? "ready" : "needs_key";
  return endpoint.credential_configured ? "ready" : "needs_key";
}

/** The fictional prompt the test request sends (ADR 0005), the same one the snippets use. */
export const TEST_PROMPT = "Write a two-line note to jane.placeholder@example.net (phone +44 20 7946 0958) confirming the appointment.";

export interface TestRoundTrip {
  original: string;
  masked: string;
  maskedAnswer: string;
  restored: string;
  maskedCount: number | null;
  ms: number;
  /** The call's id in Logs (`X-PII-Guard-Request-Id`), when the server sends it. */
  requestId?: string | null;
}

/**
 * One request through the endpoint, as the owner (same-origin session, no endpoint key): the
 * gateway masks it, the endpoint's model answers, and the echo shows what the model saw.
 */
export async function sendTestRequest(endpointId: string, doFetch: typeof fetch = (...a) => fetch(...a), signal?: AbortSignal, policyVersionId?: string): Promise<TestRoundTrip> {
  const started = performance.now();
  const response = await doFetch(`/e/${encodeURIComponent(endpointId)}/v1/chat/completions`, {
    method: "POST",
    credentials: "same-origin",
    headers: { Accept: "application/json", "Content-Type": "application/json", "X-PII-Guard-Echo": "masked" },
    // One vault session per policy version (`prompt_cache_key`, LAB-1629): a value masked in an
    // earlier test stays masked in that session, so a version that keeps it would look unapplied.
    body: JSON.stringify({ messages: [{ role: "user", content: TEST_PROMPT }], stream: false, ...(policyVersionId ? { prompt_cache_key: `pii-guard-connect-test:${policyVersionId}` } : {}) }),
    signal,
  });
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    // a proxy error page
  }
  if (!response.ok) {
    const code = isRecord(payload) && isRecord(payload.error) && typeof payload.error.code === "string" ? payload.error.code : "unavailable";
    throw new TestRequestError(response.status, code);
  }
  const guard = isRecord(payload) && isRecord(payload.pii_guard) ? payload.pii_guard : null;
  const choice = isRecord(payload) && Array.isArray(payload.choices) && isRecord(payload.choices[0]) && isRecord(payload.choices[0].message) ? payload.choices[0].message : null;
  const first = (v: unknown) => (Array.isArray(v) && isRecord(v[0]) && typeof v[0].content === "string" ? v[0].content : "");
  const masked = guard && Array.isArray(guard.masked_messages) ? (guard.masked_messages as unknown[]).filter((m) => isRecord(m) && m.role === "user").map((m) => String((m as { content: unknown }).content)).join("\n") : "";
  const count = Number(response.headers.get("X-PII-Guard-Masked"));
  return {
    original: TEST_PROMPT,
    masked,
    maskedAnswer: guard ? first(guard.masked_answer) : "",
    restored: choice && typeof choice.content === "string" ? choice.content : "",
    maskedCount: response.headers.has("X-PII-Guard-Masked") && Number.isFinite(count) ? count : null,
    ms: Math.round(performance.now() - started),
    requestId: response.headers.get("X-PII-Guard-Request-Id"),
  };
}

export class TestRequestError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
  ) {
    super("The test request could not complete.");
  }
}

/** What to do after a failed test request, by status and error code only (never server text). */
export function testRecovery(error: unknown): string {
  if (error instanceof TestRequestError) {
    if (error.code === "sponsored_unavailable") return "Free runs are paused right now. Add your own Meta API key to this endpoint in Projects, then try again.";
    // The provider's own refusal keeps its status (a wrong key is the provider's 401).
    if (error.code.startsWith("upstream") || error.status === 502 || error.status === 504) return "The model provider refused or didn't answer. If you added your own key, check it is valid for the Meta Model API, then retry.";
    if (error.status === 401 || error.status === 403) return "Your session is no longer authorized. Sign in again, then retry.";
    if (error.status === 429) return "The daily allowance is used up or requests are arriving too quickly. Check the reset time on Overview and retry later.";
    if (error.status === 503) return "The guard or the model provider is unavailable. Retry in a minute.";
    if (error.status === 422 || error.status === 400) return "The endpoint refused the request. Check its settings in Projects, then retry.";
  }
  return "The test request could not complete. Check your connection and retry.";
}

/**
 * A block that works by copy-paste with zero edits: with the endpoint key known, shell blocks
 * start by exporting it and the OpenAI SDK block names it inline. Without it, blocks keep
 * reading `$PII_GUARD_ENDPOINT_KEY`. Keys are `pg_ep_` + URL-safe base64: shell-safe unquoted.
 */
export function withKey(snippet: { id: string; code: string }, key: string | null): string {
  if (!key || !/^pg_ep_[A-Za-z0-9_-]+$/.test(key) || !snippet.code.includes(ENDPOINT_KEY_ENV)) return snippet.code;
  if (snippet.id === "python") {
    const inline = snippet.code.replace(`os.environ["${ENDPOINT_KEY_ENV}"]`, JSON.stringify(key));
    return /\bos\./.test(inline) ? inline : inline.replace(/^import os\n/m, "");
  }
  return `export ${ENDPOINT_KEY_ENV}=${key}\n${snippet.code}`;
}
