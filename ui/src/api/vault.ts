import { createProjectFetch } from "./project";
// The vault inspector, `/v1/vault/sessions*` (src/pii_guard/api/routes/vault.py, LAB-1328).
// Sessions are addressed by their `ref` (the traffic log's `session_ref`), never by the session
// id. Values come back only from a revealed read, which the server allows in `full` mode only;
// nothing here is ever written to storage.

import { ApiError, UnreachableError } from "./http";

export type VaultMode = "off" | "masked" | "full";
export type SessionSource = "header" | "path" | "prompt_cache_key" | "default" | "api";

export interface VaultSessionSummary {
  ref: string;
  source: SessionSource;
  client: string | null;
  created: string | null;
  last_used: string;
  ttl_left_seconds: number;
  generation: number;
  entries: number;
  occurrences: number;
  known_values: number;
  entity_counts: Record<string, number>;
}

export interface VaultSessionList {
  mode: "masked" | "full";
  ttl_seconds: number;
  sessions: VaultSessionSummary[];
}

export interface VaultItem {
  placeholder: string | null;
  entity_type: string;
  origin: "detected" | "known";
  count: number;
  forms: number;
  variant_of: string | null;
  hint: string;
  /** Revealed reads only. */
  original?: string | null;
  known_forms?: string[] | null;
}

export interface VaultSessionDetail extends VaultSessionSummary {
  mode: "masked" | "full";
  revealed: boolean;
  session_id: string | null;
  items: VaultItem[];
}

export interface VaultClient {
  list(): Promise<VaultSessionList>;
  detail(ref: string, reveal?: boolean): Promise<VaultSessionDetail>;
  drop(ref: string): Promise<void>;
}

export const SOURCE_LABEL: Record<SessionSource, string> = {
  header: "Session header",
  path: "URL path",
  prompt_cache_key: "Prompt cache key",
  default: "Client default",
  api: "REST API",
};

export function createVaultClient(options: { baseUrl?: string; fetch?: typeof fetch; timeoutMs?: number } = {}): VaultClient {
  const baseUrl = (options.baseUrl ?? "").replace(/\/$/, "");
  const doFetch = createProjectFetch(options.fetch ?? ((...args: Parameters<typeof fetch>) => fetch(...args)));
  const timeoutMs = options.timeoutMs ?? 15_000;

  async function call(method: "GET" | "DELETE", path: string): Promise<unknown> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let res: Response;
    try {
      // `no-store`: a revealed answer must not sit in the browser's HTTP cache.
      res = await doFetch(`${baseUrl}${path}`, {
        method,
        headers: { Accept: "application/json" },
        cache: "no-store",
        signal: controller.signal,
      });
    } catch {
      throw new UnreachableError();
    } finally {
      clearTimeout(timer);
    }
    if (res.status === 204) return undefined;
    const text = await res.text();
    let body: unknown;
    try {
      body = text ? JSON.parse(text) : undefined;
    } catch {
      body = undefined;
    }
    if (res.ok && body !== undefined) return body;
    const err = (body as { error?: { code?: unknown; message?: unknown } } | undefined)?.error;
    if (err && typeof err.code === "string") throw new ApiError(res.status, err.code, typeof err.message === "string" ? err.message : err.code);
    // A server that predates the inspector answers FastAPI's plain 404.
    if (res.status === 404 || res.status === 405) throw new ApiError(res.status, "not_found", `${method} ${path} is not available`);
    throw new UnreachableError(`PII Guard API answered ${res.status} without a contract error body`);
  }

  const at = (ref: string) => `/v1/vault/sessions/${encodeURIComponent(ref)}`;
  return {
    list: async () => (await call("GET", "/v1/vault/sessions")) as VaultSessionList,
    detail: async (ref, reveal = false) => (await call("GET", reveal ? `${at(ref)}?reveal=true` : at(ref))) as VaultSessionDetail,
    drop: async (ref) => {
      await call("DELETE", at(ref));
    },
  };
}
