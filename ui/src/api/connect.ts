import { createProjectFetch, projectHeaders } from "./project";
// `GET /v1/connect/snippets`: the Connect quickstart's copy-paste blocks
// (src/pii_guard/api/routes/connect.py). `pii-guard connect <tool> --print` prints the same
// text, so the UI never builds a block itself. Keys appear only as variable names.

import type { TrafficEvent } from "./traffic";

export type ToolId = "muse-code" | "pi" | "codex" | "opencode" | "curl" | "python" | "claude-code";

export interface ToolSnippet {
  id: ToolId | string;
  label: string;
  api: "responses" | "chat" | "messages" | string;
  /** `launch`: env/flags only; `connect`: writes the tool's config file first; `request`: one call by hand. */
  kind: "launch" | "connect" | "request" | "unsupported" | string;
  supported: boolean;
  code: string;
  note: string;
  tested_version: string | null;
  docs: string | null;
  /** Further blocks under the main one (cURL: the same request through the Responses API). */
  more?: { title: string; code: string }[];
}

export interface UpstreamPreset {
  id: string;
  label: string;
  base_url: string;
  key_env: string;
  default_model: string | null;
  command: string;
}

export interface Snippets {
  gateway_url: string;
  /** Null for an endpoint's blocks (`?endpoint=`): the endpoint pins its URL and model. */
  session: string | null;
  session_url: string | null;
  endpoint?: { id: string; name: string; model: string | null };
  models: string[];
  model: string | null;
  auth: { token_required: boolean; token_env: string };
  upstream: { connected: boolean; mock: boolean; origin: string | null; preset: string | null; label: string | null };
  presets: UpstreamPreset[];
  tools: ToolSnippet[];
  traffic_log: string;
  /** The session's handle in the traffic log (null while the log is off). */
  session_ref: string | null;
}

export type SnippetsResult = { state: "ok"; snippets: Snippets } | { state: "missing" } | { state: "offline" };

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

export function parseSnippets(raw: unknown): Snippets | null {
  if (!isRecord(raw) || !(typeof raw.session_url === "string" || (isRecord(raw.endpoint) && raw.session_url === null)) || !Array.isArray(raw.tools) || !isRecord(raw.upstream) || !Array.isArray(raw.presets)) return null;
  const tools = raw.tools.filter((t): t is ToolSnippet => isRecord(t) && typeof t.id === "string" && typeof t.code === "string" && typeof t.label === "string");
  return {
    ...(raw as unknown as Snippets),
    models: Array.isArray(raw.models) ? raw.models.filter((m): m is string => typeof m === "string") : [],
    tools,
    session_ref: typeof raw.session_ref === "string" ? raw.session_ref : null,
  };
}

export interface SnippetsQuery { session: string; model?: string | null }

export async function fetchSnippets(
  query: SnippetsQuery | { endpoint: string },
  doFetch: typeof fetch = (...a) => fetch(...a),
  baseUrl = "",
  signal?: AbortSignal,
): Promise<SnippetsResult> {
  // An endpoint pins its URL and model, so `endpoint` goes alone (hosted requires it).
  const params = new URLSearchParams("endpoint" in query ? { endpoint: query.endpoint } : { session: query.session });
  if (!("endpoint" in query) && query.model) params.set("model", query.model);
  let res: Response;
  try {
    res = await createProjectFetch(doFetch)(`${baseUrl.replace(/\/$/, "")}/v1/connect/snippets?${params}`, { headers: projectHeaders({ Accept: "application/json" }), signal });
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
  const snippets = parseSnippets(body);
  return snippets ? { state: "ok", snippets } : { state: "missing" };
}

export type SnippetsLoader = (query: SnippetsQuery, signal?: AbortSignal) => Promise<SnippetsResult>;

export const loadSnippets: SnippetsLoader = (query, signal) => fetchSnippets(query, undefined, "", signal);

/** One project endpoint's blocks, whatever session the quickstart asks for. */
export const endpointSnippets = (endpoint: string): SnippetsLoader => (_query, signal) => fetchSnippets({ endpoint }, undefined, "", signal);

/** A new vault session id for one tool's block: `c_` + 32 hex, as `pii-guard connect` makes. */
export function newSessionId(random: (n: number) => Uint8Array = (n) => crypto.getRandomValues(new Uint8Array(n))): string {
  return "c_" + Array.from(random(16), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** The tool's first call: the oldest traffic event in its session. */
export function firstRequest(events: readonly TrafficEvent[], sessionRef: string | null): TrafficEvent | null {
  if (!sessionRef) return null;
  let first: TrafficEvent | null = null;
  for (const e of events) if (e.session_ref === sessionRef && (first === null || e.seq < first.seq)) first = e;
  return first;
}
